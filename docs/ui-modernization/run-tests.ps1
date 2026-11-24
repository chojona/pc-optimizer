#Requires -Version 7.0
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Set-Location -LiteralPath $root
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONUTF8 = '1'
New-Item -ItemType Directory -Path data -Force | Out-Null
$python = Join-Path $root '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = 'python' }
& $python -m compileall -q optimizer main.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $python -m pytest tests -q -p no:cacheprovider --basetemp data/test-temp
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $python -m unittest discover -s tests -p test_gui.py -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $python -m unittest discover -s tests -p test_ai_ui.py -q
exit $LASTEXITCODE
