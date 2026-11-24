# Reviewed, offline checks for finish-task. No dependency installation or probes.
$ErrorActionPreference = 'Stop'
$pythonPath = $env:NETWORK_INTELLIGENCE_PYTHON
if (-not $pythonPath) { $pythonPath = 'python' }
$env:QT_QPA_PLATFORM = 'offscreen'
New-Item -ItemType Directory -Path data -Force | Out-Null
foreach ($pattern in @('test_network_intelligence.py', 'test_diagnostics.py', 'test_network.py')) {
    & $pythonPath -m unittest discover -s tests -p $pattern
    # Python 3.14 uses exit 5 for zero discovered tests. Only the two known
    # pytest-only legacy modules permit this; the full pytest suite runs below.
    if ($LASTEXITCODE -eq 5 -and $pattern -ne 'test_network_intelligence.py') {
        Write-Host "$pattern contains pytest functions; unittest ran no cases. Validating with pytest below."
    } elseif ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
# The legacy diagnostic/network tests use pytest functions: unittest discovers
# zero cases there. Execute them through pytest as part of the full suite too.
$temporaryTests = Join-Path 'data' ('finish-tests-' + [guid]::NewGuid().ToString('N'))
& $pythonPath -m pytest tests -q -p no:cacheprovider --basetemp $temporaryTests --junitxml=data/network-intelligence-tests.xml
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $pythonPath -m compileall -q optimizer main.py scripts
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $pythonPath -m pip check
exit $LASTEXITCODE
