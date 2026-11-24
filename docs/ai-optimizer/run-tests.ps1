#Requires -Version 7.0
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $root
New-Item -ItemType Directory -Path data -Force | Out-Null
$env:QT_QPA_PLATFORM = 'offscreen'
$candidates = @(
    (Join-Path $root '.venv\Scripts\python.exe'),
    'C:\Users\johnn\Desktop\pc_optimizer\.venv\Scripts\python.exe'
)
$py = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $py) { throw 'Python venv not found for PC Optimizer tests.' }
& $py -m unittest discover -s tests -p test_ai_optimizer_ui.py -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py -m unittest discover -s tests -p test_gui.py -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py -m pytest tests -q -p no:cacheprovider --basetemp data/test-temp
exit $LASTEXITCODE
