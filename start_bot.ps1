$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$pythonExe = Join-Path -Path $PSScriptRoot -ChildPath "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    $pythonExe = "python.exe"
}
Start-Process -FilePath $pythonExe -ArgumentList "multi_store_bot.py" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
