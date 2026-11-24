param([string]$Tag = '')

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)

$version = & python -c 'from optimizer import __version__; print(__version__)'
if ($LASTEXITCODE -ne 0 -or $version -notmatch '^\d+\.\d+\.\d+$') {
    throw 'Could not read a valid application version.'
}
if ($Tag -and $Tag -cne "v$version") {
    throw "Release tag '$Tag' must match application version 'v$version'."
}

New-Item -ItemType Directory -Path dist -Force | Out-Null
$name = "PC-Optimizer-v$version-windows-source.zip"
$archive = Join-Path (Get-Location).Path "dist\$name"
# git archive includes only committed files from these runtime/documentation paths.
git archive --format=zip --prefix=PC-Optimizer/ "--output=$archive" HEAD -- main.py optimizer README.md requirements.txt setup.ps1 Launch-PC-Optimizer.cmd docs
if ($LASTEXITCODE -ne 0) { throw 'Source archive creation failed.' }

$digest = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$archive.sha256" -Value "$digest  $name" -Encoding ascii
Write-Host "Built dist\$name and SHA-256 checksum."
