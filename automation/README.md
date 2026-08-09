# ALAS logon startup

This automation starts, in order:

1. MuMu Player manager.
2. MuMu instances `0` and `1`.
3. The ALAS desktop app, whose `Webui.Run` setting starts schedulers `alas` and `alas2`.

`frpc` is intentionally not started.

## Files

- `start-alas-at-logon.ps1`: idempotent startup sequence with readiness checks and logging.
- `install-logon-startup.ps1`: installs a shortcut in the current user's Startup folder.
- `uninstall-logon-startup.ps1`: removes that shortcut.

The startup log is written to `automation/logs/startup.log`. The script waits 20 seconds after logon before doing any work. It resolves the MuMu installation from the current user's Start Menu shortcut, waits for instances `0` and `1`, validates `config/deploy.yaml`, and confirms both scheduler startup messages in the ALAS logs. Run it with `-DryRun` to validate paths and inspect the intended actions without launching anything.

The installed shortcut uses Windows PowerShell with `ExecutionPolicy Bypass` for this script only. It does not change the machine or user execution policy. This is needed on systems where unsigned local scripts are otherwise blocked; remove that argument from `install-logon-startup.ps1` if your policy already permits this script.
