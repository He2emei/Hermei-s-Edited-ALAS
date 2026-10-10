"""Best-effort terminal failure event emission for the external repair launcher."""
import json
import os
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


CHINA_TZ = timezone(timedelta(hours=8), name="China Standard Time")
REPAIR_TASK = "ALAS-Repair"


def _in_month_end_pause(now):
    local = now.astimezone(CHINA_TZ)
    next_month = (local.replace(day=28) + timedelta(days=4)).replace(day=1)
    last_day = (next_month - timedelta(days=1)).day
    return (local.day == last_day and local.hour >= 23) or (local.day == 1 and local.hour < 6)


def _is_cross_month_protection(error):
    return "Overdue OpsiCrossMonth cannot confirm" in str(error)


def _is_paused(workspace, profile):
    tmp = workspace / "code_workflow" / "tmp"
    if (tmp / "alas_guard.pause").exists() or (tmp / "alas_guard.repair.pause").exists():
        return True
    if profile in ("alas", "alas2"):
        return (tmp / f"alas_guard.{profile}.pause").exists()
    return any(tmp.glob("alas_guard.*.pause"))


def emit_terminal_failure(profile, task, error, *, root=None, launcher=subprocess.run, now=None, pid=None):
    """Write a minimal event and start ALAS-Repair when explicitly enabled.

    Reporting a failure must never mask ALAS's original terminal error.
    """
    event_id = None
    try:
        root = Path(root or Path(__file__).resolve().parents[2])
        if root.name != "AzurLaneAutoScript-Use":
            return {"event_id": None, "dispatched": False, "reason": "nonproduction"}
        event_id = str(uuid.uuid4())
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        message = str(error).splitlines()[0] if str(error) else ""
        event = {
            "schema": 1, "id": event_id, "profile": str(profile), "task": str(task),
            "error_type": type(error).__name__, "error_line": message[:500],
            "time_utc": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "pid": os.getpid() if pid is None else int(pid),
        }
        event_dir = root / "log" / "repair_events"
        event_dir.mkdir(parents=True, exist_ok=True)
        destination = event_dir / f"{event_id}.json"
        temporary = event_dir / f".{event_id}.tmp"
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(event, stream, ensure_ascii=False, separators=(",", ":"))
                stream.write("\n")
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()

        workspace = root.parent
        if _is_cross_month_protection(error):
            return {"event_id": event_id, "dispatched": False, "reason": "scope_or_protection"}
        settings_path = workspace / "code_workflow" / "tmp" / "alas_repair_settings.json"
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"event_id": event_id, "dispatched": False, "reason": "settings_unavailable"}
        if settings.get("enabled") is not True or settings.get("RepairProvider") not in ("Hapi", "Codex"):
            return {"event_id": event_id, "dispatched": False, "reason": "disabled"}
        if _in_month_end_pause(now) or _is_paused(workspace, str(profile)):
            return {"event_id": event_id, "dispatched": False, "reason": "paused"}
        result = launcher(["schtasks.exe", "/Run", "/TN", REPAIR_TASK], capture_output=True, timeout=3,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        ok = getattr(result, "returncode", 1) == 0
        return {"event_id": event_id, "dispatched": ok,
                "reason": "started" if ok else "launcher_failed"}
    except Exception:
        return {"event_id": event_id, "dispatched": False, "reason": "event_failure"}

