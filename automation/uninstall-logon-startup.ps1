[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$StartupDirectory = [Environment]::GetFolderPath('Startup')
$ShortcutPath = Join-Path $StartupDirectory 'AzurLaneAutoScript.lnk'

if (Test-Path -LiteralPath $ShortcutPath -PathType Leaf) {
    Remove-Item -LiteralPath $ShortcutPath -Force
    Write-Host "Removed current-user logon startup shortcut: $ShortcutPath"
}
else {
    Write-Host "Startup shortcut is not installed: $ShortcutPath"
}
