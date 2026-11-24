#Requires -Version 7.0
# Copy a reviewed repository bundle. Never writes to global configuration.
[CmdletBinding()]
param([Parameter(Mandatory)][string]$Destination, [switch]$DryRun)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Workflow.psm1') -Force -DisableNameChecking
$lock = $null
try {
    $source = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
    $context = Get-Context $Destination
    $targetRoot = [IO.Path]::GetFullPath($context.Root)
    if (-not (Test-SamePath $Destination $targetRoot)) { throw 'Destination must be the exact root of the reviewed target repository/worktree.' }
    if (Test-SamePath $source $targetRoot) { throw 'Source and destination are identical.' }
    if (-not $DryRun) { $lock = Enter-WorkflowLock $context }
    $paths = @('AGENTS.md', 'CLAUDE.md', '.cursor/rules/engineering.mdc')
    foreach ($dir in @('Engineering', '.agents/skills', '.claude/skills')) {
        $paths += Get-ChildItem -LiteralPath (Join-Path $source $dir) -Recurse -File | ForEach-Object { [IO.Path]::GetRelativePath($source, $_.FullName) }
    }
    $copies = @(); $conflicts = @()
    foreach ($relative in $paths) {
        $from = Join-Path $source $relative
        $to = Join-Path $targetRoot $relative
        # Refuse directory links/junctions so a repository adapter cannot redirect writes globally.
        $ancestor = Split-Path $to -Parent
        while ($ancestor.Length -ge $targetRoot.Length) {
            if ((Test-Path -LiteralPath $ancestor) -and ((Get-Item -Force -LiteralPath $ancestor).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Linked target directory is unsupported: $ancestor" }
            if ($ancestor -ieq $targetRoot) { break }; $ancestor = Split-Path $ancestor -Parent
        }
        if (Test-Path -LiteralPath $to) {
            $item = Get-Item -Force -LiteralPath $to
            if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { $conflicts += $to; continue }
            if ((Get-FileHash -LiteralPath $from).Hash -eq (Get-FileHash -LiteralPath $to).Hash) { continue }
            if ($item.Length -gt 0) { $conflicts += $to; continue }
        }
        $copies += [pscustomobject]@{ source=$from; target=$to }
    }
    if ($conflicts.Count) { throw "Existing nonempty files need a manual merge; no files copied:`n$($conflicts -join "`n")" }
    if (-not $DryRun) {
        foreach ($copy in $copies) {
            [IO.Directory]::CreateDirectory((Split-Path $copy.target -Parent)) | Out-Null
            # Recheck immediately before copying; never overwrite newly-added user content.
            if ((Test-Path -LiteralPath $copy.target) -and (Get-Item -LiteralPath $copy.target).Length -gt 0) { throw "Target changed during installation: $($copy.target). Prior copies remain; inspect and rerun." }
            Copy-Item -LiteralPath $copy.source -Destination $copy.target
        }
    }
    [ordered]@{ destination=$targetRoot; dryRun=[bool]$DryRun; copies=$copies; note='Existing nonempty configurations were preserved; inspect and commit the repository diff explicitly.' } | ConvertTo-Json -Depth 5
    exit 0
} catch { Write-Error $_ -ErrorAction Continue; exit 1 }
finally { if ($lock) { $lock.Dispose() } }
