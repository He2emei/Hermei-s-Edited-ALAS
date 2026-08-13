[CmdletBinding()]
param(
    [ValidateRange(0, 600)]
    [int]$StartupDelaySeconds = 20,

    [ValidateRange(10, 600)]
    [int]$EmulatorTimeoutSeconds = 180,

    [ValidateRange(10, 600)]
    [int]$AlasTimeoutSeconds = 180,

    [switch]$EnvironmentCheckOnly,

    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$AlasRoot = Split-Path -Parent $PSScriptRoot
$AlasExecutable = Join-Path $AlasRoot 'webapp\dist\win-unpacked\alas.exe'
$DeployConfig = Join-Path $AlasRoot 'config\deploy.yaml'
$MumuIndexes = @('0', '1')
$SchedulerConfigs = @('alas', 'alas2')
$LogDirectory = Join-Path $PSScriptRoot 'logs'
$LogFile = Join-Path $LogDirectory 'startup.log'
$MumuRoot = $null
$MumuManager = $null
$MumuCli = $null
$AlasProcessStartedByScript = $null

function Write-StartupLog {
    param([Parameter(Mandatory = $true)][string]$Message)

    $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Write-Host $line
    if (-not $DryRun) {
        if (-not (Test-Path -LiteralPath $LogDirectory)) {
            New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
        }
        Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
    }
}

function Assert-RequiredFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required file not found: $Path"
    }
}

function Get-DeployScalar {
    param([Parameter(Mandatory = $true)][string]$Name)

    $line = Get-Content -LiteralPath $DeployConfig |
        Where-Object { $_ -match ('^\s*{0}\s*:' -f [regex]::Escape($Name)) } |
        Select-Object -First 1
    if ($null -eq $line) {
        throw "$Name is missing from: $DeployConfig"
    }
    return ($line -split ':', 2)[1].Trim().Trim("'").Trim('"')
}

function Initialize-AlasPythonEnvironment {
    Assert-RequiredFile $DeployConfig

    $pythonExecutable = [Environment]::ExpandEnvironmentVariables((Get-DeployScalar 'PythonExecutable'))
    if (-not [IO.Path]::IsPathRooted($pythonExecutable)) {
        $pythonExecutable = Join-Path $AlasRoot $pythonExecutable
    }
    $pythonExecutable = [IO.Path]::GetFullPath($pythonExecutable)
    Assert-RequiredFile $pythonExecutable

    $pythonRoot = Split-Path -Parent $pythonExecutable
    $requiredPaths = @(
        $pythonRoot
        (Join-Path $pythonRoot 'Scripts')
        (Join-Path $pythonRoot 'Library\bin')
    ) | Where-Object { Test-Path -LiteralPath $_ -PathType Container }

    $currentPaths = @($env:PATH -split ';' | Where-Object { $_ })
    $prependPaths = @($requiredPaths | Where-Object { $candidate = $_; -not ($currentPaths | Where-Object { $_ -ieq $candidate }) })
    $env:PATH = (@($prependPaths) + $currentPaths) -join ';'

    return $pythonExecutable
}

function Assert-AlasPythonEnvironment {
    param([Parameter(Mandatory = $true)][string]$PythonExecutable)

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $PythonExecutable
    $startInfo.WorkingDirectory = $AlasRoot
    $startInfo.Arguments = '-c "import ssl; import uvicorn; import pywebio"'
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true

    $process = [System.Diagnostics.Process]::Start($startInfo)
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) {
        throw "ALAS Python environment check failed with exit code $($process.ExitCode): $stdout $stderr"
    }
}

function Stop-StartedAlasProcess {
    param([Parameter(Mandatory = $true)]$Process)

    try {
        Write-StartupLog "Stopping ALAS process tree started by this run (PID $($Process.Id))."
        $taskkill = Join-Path $env:SystemRoot 'System32\taskkill.exe'
        $cleanup = Start-Process -FilePath $taskkill `
            -ArgumentList @('/PID', $Process.Id, '/T', '/F') `
            -Wait -PassThru -WindowStyle Hidden
        if ($cleanup.ExitCode -ne 0) {
            Write-StartupLog "WARNING: taskkill exited with code $($cleanup.ExitCode) for ALAS PID $($Process.Id)."
        }
    }
    catch {
        Write-StartupLog "WARNING: Failed to stop ALAS PID $($Process.Id): $($_.Exception.Message)"
    }
}

function Resolve-MumuInstallation {
    $programsDirectory = [Environment]::GetFolderPath('Programs')
    $shortcutFiles = Get-ChildItem -LiteralPath $programsDirectory -Filter 'MuMu*.lnk' -Recurse -ErrorAction SilentlyContinue
    $shell = New-Object -ComObject WScript.Shell

    foreach ($shortcutFile in $shortcutFiles) {
        $target = $shell.CreateShortcut($shortcutFile.FullName).TargetPath
        if ([IO.Path]::GetFileName($target) -ieq 'MuMuNxMain.exe' -and (Test-Path -LiteralPath $target -PathType Leaf)) {
            return [pscustomobject]@{
                Root = Split-Path -Parent $target
                Manager = $target
                Shortcut = $shortcutFile.FullName
            }
        }
    }
    throw "No Start Menu shortcut targeting MuMuNxMain.exe was found under: $programsDirectory"
}

function Assert-SchedulerConfiguration {
    Assert-RequiredFile $DeployConfig
    $runLine = Get-Content -LiteralPath $DeployConfig | Where-Object { $_ -match '^\s*Run\s*:' } | Select-Object -First 1
    if ($null -eq $runLine) {
        throw "Webui.Run is missing from: $DeployConfig"
    }

    $runValue = ($runLine -split ':', 2)[1].Trim().Trim("'").Trim('"').Trim('[', ']')
    $configured = @($runValue -split ',' | ForEach-Object { $_.Trim().Trim("'").Trim('"') })
    if (($configured -join ',') -ne ($SchedulerConfigs -join ',')) {
        throw "Webui.Run must be $($SchedulerConfigs -join ','); current value is $($configured -join ',')."
    }
}

function Get-MumuInfo {
    $raw = & $MumuCli info --vmindex ($MumuIndexes -join ',') 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "mumu-cli info failed with exit code $LASTEXITCODE`: $($raw -join ' ')"
    }
    return ($raw -join [Environment]::NewLine) | ConvertFrom-Json
}

function Get-MumuInfoWithRetry {
    $deadline = (Get-Date).AddSeconds($EmulatorTimeoutSeconds)
    do {
        try {
            return Get-MumuInfo
        }
        catch {
            if ((Get-Date) -ge $deadline) {
                throw
            }
            Write-StartupLog "MuMu CLI is not ready yet: $($_.Exception.Message)"
            Start-Sleep -Seconds 5
        }
    } while ($true)
}

function Get-MumuInstance {
    param(
        [Parameter(Mandatory = $true)]$Info,
        [Parameter(Mandatory = $true)][string]$Index
    )

    $property = $Info.PSObject.Properties[$Index]
    if ($null -eq $property) {
        throw "MuMu instance $Index does not exist."
    }
    return $property.Value
}

function Get-StoppedMumuIndexes {
    param([Parameter(Mandatory = $true)]$Info)

    $stopped = @()
    foreach ($index in $MumuIndexes) {
        $instance = Get-MumuInstance -Info $Info -Index $index
        if (-not $instance.is_process_started -or $instance.player_state -ne 'start_finished') {
            $stopped += $index
        }
    }
    return $stopped
}

function Get-ProcessAtPath {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $expectedPath = [IO.Path]::GetFullPath($Path)
    return Get-Process -Name $Name -ErrorAction SilentlyContinue | Where-Object {
        try { [IO.Path]::GetFullPath($_.Path) -ieq $expectedPath } catch { $false }
    } | Select-Object -First 1
}

function Test-TcpPort {
    param(
        [Parameter(Mandatory = $true)][string]$HostName,
        [Parameter(Mandatory = $true)][int]$Port
    )

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $result = $client.BeginConnect($HostName, $Port, $null, $null)
        return $result.AsyncWaitHandle.WaitOne(500) -and $client.Connected
    }
    finally {
        $client.Close()
    }
}

function Get-WebuiPort {
    $portLine = Get-Content -LiteralPath $DeployConfig | Where-Object { $_ -match '^\s*WebuiPort\s*:' } | Select-Object -First 1
    if ($null -eq $portLine) {
        throw "WebuiPort is missing from: $DeployConfig"
    }
    return [int](($portLine -split ':', 2)[1].Trim())
}

function Test-SchedulerStartupLogs {
    param([Parameter(Mandatory = $true)][datetime]$StartedAfter)

    foreach ($configName in $SchedulerConfigs) {
        $logFiles = Get-ChildItem -LiteralPath (Join-Path $AlasRoot 'log') -Filter "*_$configName.txt" -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -ge $StartedAfter }
        $found = $false
        foreach ($logFile in $logFiles) {
            $matches = Select-String -LiteralPath $logFile.FullName -SimpleMatch "Start scheduler loop: $configName"
            foreach ($match in $matches) {
                if ($match.Line -match '^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})') {
                    $timestamp = [datetime]::ParseExact(
                        $Matches[1],
                        'yyyy-MM-dd HH:mm:ss.fff',
                        [Globalization.CultureInfo]::InvariantCulture
                    )
                    if ($timestamp -ge $StartedAfter) {
                        $found = $true
                        break
                    }
                }
            }
            if ($found) {
                break
            }
        }
        if (-not $found) {
            return $false
        }
    }
    return $true
}

function Wait-AlasReady {
    param([Parameter(Mandatory = $true)][datetime]$StartedAfter)

    $webuiPort = Get-WebuiPort
    $deadline = (Get-Date).AddSeconds($AlasTimeoutSeconds)
    do {
        $processReady = $null -ne (Get-ProcessAtPath -Name 'alas' -Path $AlasExecutable)
        $webuiReady = Test-TcpPort -HostName '127.0.0.1' -Port $webuiPort
        $schedulersReady = Test-SchedulerStartupLogs -StartedAfter $StartedAfter
        if ($processReady -and $webuiReady -and $schedulersReady) {
            return
        }
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $deadline)

    throw "ALAS, WebUI port $webuiPort, and schedulers $($SchedulerConfigs -join ',') did not all become ready within $AlasTimeoutSeconds seconds."
}

try {
    Write-StartupLog "Startup sequence begins. DryRun=$DryRun"
    Assert-RequiredFile $AlasExecutable
    $pythonExecutable = Initialize-AlasPythonEnvironment
    Assert-AlasPythonEnvironment -PythonExecutable $pythonExecutable
    Write-StartupLog "ALAS Python environment check passed: $pythonExecutable"

    if ($EnvironmentCheckOnly) {
        exit 0
    }

    Assert-SchedulerConfiguration

    $mumu = Resolve-MumuInstallation
    $MumuRoot = $mumu.Root
    $MumuManager = $mumu.Manager
    $MumuCli = Join-Path $MumuRoot 'mumu-cli.exe'
    Assert-RequiredFile $MumuCli
    Write-StartupLog "Resolved MuMu from Start Menu shortcut: $($mumu.Shortcut)"

    if ($StartupDelaySeconds -gt 0) {
        Write-StartupLog "Waiting $StartupDelaySeconds seconds for the desktop session."
        if (-not $DryRun) {
            Start-Sleep -Seconds $StartupDelaySeconds
        }
    }

    if (-not (Get-ProcessAtPath -Name 'MuMuNxMain' -Path $MumuManager)) {
        Write-StartupLog 'Starting MuMu manager.'
        if (-not $DryRun) {
            Start-Process -FilePath $MumuManager -WorkingDirectory $MumuRoot
        }
    }
    else {
        Write-StartupLog 'The expected MuMu manager is already running.'
    }

    $info = if ($DryRun) { Get-MumuInfo } else { Get-MumuInfoWithRetry }
    $stoppedIndexes = @(Get-StoppedMumuIndexes -Info $info)
    if ($stoppedIndexes.Count -gt 0) {
        if ($DryRun) {
            Write-StartupLog "Would launch MuMu instances: $($stoppedIndexes -join ','). Readiness was not claimed in dry-run mode."
        }
        else {
            Write-StartupLog "Launching MuMu instances: $($stoppedIndexes -join ',')"
            $output = & $MumuCli control --vmindex ($stoppedIndexes -join ',') launch 2>&1
            if ($LASTEXITCODE -ne 0) {
                throw "mumu-cli launch failed with exit code $LASTEXITCODE`: $($output -join ' ')"
            }
        }
    }
    else {
        Write-StartupLog "MuMu instances $($MumuIndexes -join ',') are already running."
    }

    if (-not $DryRun) {
        $deadline = (Get-Date).AddSeconds($EmulatorTimeoutSeconds)
        do {
            $info = Get-MumuInfoWithRetry
            if (@(Get-StoppedMumuIndexes -Info $info).Count -eq 0) {
                break
            }
            Start-Sleep -Seconds 5
        } while ((Get-Date) -lt $deadline)

        if (@(Get-StoppedMumuIndexes -Info $info).Count -gt 0) {
            throw "MuMu instances $($MumuIndexes -join ',') did not become ready within $EmulatorTimeoutSeconds seconds."
        }
        Write-StartupLog "MuMu instances $($MumuIndexes -join ',') are ready."
    }

    $existingAlas = Get-ProcessAtPath -Name 'alas' -Path $AlasExecutable
    if ($existingAlas) {
        Write-StartupLog 'The expected ALAS executable is already running; verifying WebUI and schedulers.'
        if (-not $DryRun) {
            Wait-AlasReady -StartedAfter $existingAlas.StartTime.AddSeconds(-2)
            Write-StartupLog "ALAS WebUI and schedulers $($SchedulerConfigs -join ',') are ready."
        }
    }
    elseif ($DryRun) {
        Write-StartupLog "Would start ALAS with configured schedulers: $($SchedulerConfigs -join ',')."
    }
    else {
        Write-StartupLog "Starting ALAS with configured schedulers: $($SchedulerConfigs -join ',')."
        $alasStartedAt = (Get-Date).AddSeconds(-2)
        $AlasProcessStartedByScript = Start-Process -FilePath $AlasExecutable -WorkingDirectory $AlasRoot -PassThru
        Write-StartupLog "Started ALAS process with PID $($AlasProcessStartedByScript.Id)."
        Wait-AlasReady -StartedAfter $alasStartedAt
        Write-StartupLog "ALAS WebUI and schedulers $($SchedulerConfigs -join ',') are ready."
    }

    Write-StartupLog 'Startup sequence completed successfully.'
    exit 0
}
catch {
    Write-StartupLog "ERROR: $($_.Exception.Message)"
    if ($null -ne $AlasProcessStartedByScript) {
        Stop-StartedAlasProcess -Process $AlasProcessStartedByScript
    }
    exit 1
}
