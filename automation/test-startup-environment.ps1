[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$AutomationRoot = $PSScriptRoot
$AlasRoot = Split-Path -Parent $AutomationRoot
$StartupScript = Join-Path $AutomationRoot 'start-alas-at-logon.ps1'
$CleanPath = @(
    [Environment]::GetEnvironmentVariable('Path', 'Machine')
    [Environment]::GetEnvironmentVariable('Path', 'User')
) -join ';'

$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$arguments = @(
    '-NoLogo'
    '-NoProfile'
    '-NonInteractive'
    '-ExecutionPolicy', 'Bypass'
    '-File', ('"{0}"' -f $StartupScript)
    '-EnvironmentCheckOnly'
) -join ' '

$startInfo = New-Object System.Diagnostics.ProcessStartInfo
$startInfo.FileName = $powershell
$startInfo.WorkingDirectory = $AlasRoot
$startInfo.Arguments = $arguments
$startInfo.UseShellExecute = $false
$startInfo.RedirectStandardOutput = $true
$startInfo.RedirectStandardError = $true
$startInfo.EnvironmentVariables['PATH'] = $CleanPath

$process = [System.Diagnostics.Process]::Start($startInfo)
$stdout = $process.StandardOutput.ReadToEnd()
$stderr = $process.StandardError.ReadToEnd()
$process.WaitForExit()

if ($process.ExitCode -ne 0) {
    throw "Startup environment check failed with exit code $($process.ExitCode):`n$stdout`n$stderr"
}
if ($stdout -notmatch 'ALAS Python environment check passed') {
    throw "Startup environment check did not report success:`n$stdout`n$stderr"
}

Write-Host 'PASS: logon startup environment can load the ALAS Python runtime.'
