# Requires PowerShell 7. No global configuration is changed by this module.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-Tool {
    param([string]$Tool, [string[]]$Arguments)
    if (-not (Get-Command $Tool -ErrorAction SilentlyContinue)) { throw "Missing dependency '$Tool'. Install it explicitly; no system changes were made." }
    $output = & $Tool @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw "$Tool failed (exit $LASTEXITCODE): $($output -join [Environment]::NewLine)" }
    return ($output -join "`n")
}
function Invoke-Git { param([string]$Repository, [string[]]$Arguments) Invoke-Tool git (@('-C', $Repository) + $Arguments) }
function Get-Context {
    param([string]$Repository)
    $root = Invoke-Git $Repository @('rev-parse', '--show-toplevel')
    $common = Invoke-Git $root @('rev-parse', '--path-format=absolute', '--git-common-dir')
    [pscustomobject]@{ Root = $root; Common = $common; State = (Join-Path $common 'engineering-workflow') }
}
function Test-SamePath {
    param([string]$First, [string]$Second)
    $a = [IO.Path]::GetFullPath($First).Replace('\','/').TrimEnd('/')
    $b = [IO.Path]::GetFullPath($Second).Replace('\','/').TrimEnd('/')
    return $a.Equals($b, 'OrdinalIgnoreCase')
}
function Enter-WorkflowLock {
    param($Context, [int]$TimeoutSeconds = 15)
    [IO.Directory]::CreateDirectory($Context.State) | Out-Null
    $timer = [Diagnostics.Stopwatch]::StartNew()
    do {
        try { return [IO.File]::Open((Join-Path $Context.State 'workflow.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
        catch [IO.IOException] {
            if ($timer.Elapsed.TotalSeconds -ge $TimeoutSeconds) { throw 'Workflow is busy in another process. Retry later; never delete a held lock.' }
            Start-Sleep -Milliseconds 100
        }
    } while ($true)
}
function Read-Registry {
    param($Context)
    $file = Join-Path $Context.State 'tasks.json'
    if (-not (Test-Path -LiteralPath $file)) { return @{} }
    try { $data = Get-Content -Raw -LiteralPath $file | ConvertFrom-Json -AsHashtable }
    catch { throw "Unreadable task registry '$file'. Preserve it and repair manually; refusing to replace ownership." }
    if ($data -isnot [System.Collections.IDictionary]) { throw 'Invalid task registry; expected an object.' }
    return $data
}
function Write-Registry {
    param($Context, $Registry)
    $file = Join-Path $Context.State 'tasks.json'
    $temporary = "$file.$([guid]::NewGuid().ToString('N')).tmp"
    try {
        [IO.File]::WriteAllText($temporary, ($Registry | ConvertTo-Json -Depth 20), [Text.UTF8Encoding]::new($false))
        [IO.File]::Move($temporary, $file, $true)
    } finally { if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary } }
}
function Get-Worktrees {
    param([string]$Repository)
    $result = @(); $entry = $null
    foreach ($line in ((Invoke-Git $Repository @('-c', 'core.quotePath=false', 'worktree', 'list', '--porcelain')) -split "`n")) {
        if ($line.StartsWith('worktree ')) { if ($entry) { $result += [pscustomobject]$entry }; $entry = @{ Path = $line.Substring(9); Branch = ''; Head = '' } }
        elseif ($entry -and $line.StartsWith('branch refs/heads/')) { $entry.Branch = $line.Substring(18) }
        elseif ($entry -and $line.StartsWith('HEAD ')) { $entry.Head = $line.Substring(5) }
    }
    if ($entry) { $result += [pscustomobject]$entry }; return $result
}
function Convert-Claims {
    param([string[]]$Files)
    if (-not $Files.Count) { throw 'Declare at least one file or directory ownership path with -Files.' }
    $result = foreach ($file in $Files) {
        $path = $file.Replace('\', '/').TrimEnd('/')
        if ([string]::IsNullOrWhiteSpace($path) -or $path -match '(^/|//|:|[\x00-\x1f*?\[\]]|(^|/)\.\.?(/|$)|^\.git(/|$))') {
            throw "Invalid ownership path '$file'. Use literal repository-relative files or directories; no globs or traversal."
        }
        $path
    }
    return @($result | Sort-Object -Unique)
}
function Test-Overlap {
    param([string[]]$First, [string[]]$Second)
    foreach ($a in $First) { foreach ($b in $Second) {
        if ($a.Equals($b, 'OrdinalIgnoreCase') -or $a.StartsWith("$b/", 'OrdinalIgnoreCase') -or $b.StartsWith("$a/", 'OrdinalIgnoreCase')) { return $true }
    } }; return $false
}
function Assert-OwnedPaths {
    param([string[]]$Paths, [string[]]$Claims)
    foreach ($path in $Paths) {
        $allowed = $false
        foreach ($claim in $Claims) { if ($path.Equals($claim, 'OrdinalIgnoreCase') -or $path.StartsWith("$claim/", 'OrdinalIgnoreCase')) { $allowed = $true; break } }
        if (-not $allowed) { throw "File '$path' is outside this task's declared ownership. Coordinate before changing shared files." }
    }
}
function Get-Lines { param([string]$Value) return @($Value -split "`n" | Where-Object { $_ -ne '' }) }
function Get-ChangedPaths {
    param([string]$Repository)
    $paths = @()
    $paths += Get-Lines (Invoke-Git $Repository @('-c', 'core.quotePath=false', 'diff', '--cached', '--name-only', '--no-renames', '--'))
    $paths += Get-Lines (Invoke-Git $Repository @('-c', 'core.quotePath=false', 'diff', '--name-only', '--no-renames', '--'))
    $paths += Get-Lines (Invoke-Git $Repository @('-c', 'core.quotePath=false', 'ls-files', '--others', '--exclude-standard'))
    $paths | Sort-Object -Unique
}
function Get-GitHubRepository {
    param([string]$Repository)
    # Read identity before transport rewrites (e.g. SSH aliases or a test's local origin).
    $url = Invoke-Git $Repository @('config', '--get', 'remote.origin.url')
    if ($url -notmatch '^(?:https://github\.com/|git@github\.com:)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?$') { throw 'origin must identify a github.com OWNER/REPO. Enterprise remotes need a reviewed adapter.' }
    return $Matches[1]
}
function Assert-GitHub {
    Invoke-Tool gh @('auth', 'status', '--hostname', 'github.com') | Out-Null
}
function Get-OpenPullRequests {
    param([string]$GitHubRepository)
    $pages = Invoke-Tool gh @('api', '--paginate', '--slurp', "repos/$GitHubRepository/pulls?state=open&per_page=100") | ConvertFrom-Json
    foreach ($page in $pages) { foreach ($pr in $page) { $pr } }
}
function Update-ProjectStatus {
    param([string]$ProjectId, [string]$ProjectItemId, [string]$StatusFieldId, [string]$StatusOptionId)
    try {
        Invoke-Tool gh @('project', 'item-edit', '--id', $ProjectItemId, '--project-id', $ProjectId, '--field-id', $StatusFieldId, '--single-select-option-id', $StatusOptionId) | Out-Null
        return 'updated'
    } catch { Write-Warning "Project status was not updated. Check project write permission and the exact item/field/option IDs. $($_.Exception.Message)"; return 'pending' }
}
function Assert-ProjectParameters {
    param([switch]$UpdateProject, [string]$ProjectId, [string]$ProjectItemId, [string]$StatusFieldId, [string]$StatusOptionId)
    if ($UpdateProject -and (-not $ProjectId -or -not $ProjectItemId -or -not $StatusFieldId -or -not $StatusOptionId)) { throw '-UpdateProject requires -ProjectId, -ProjectItemId, -StatusFieldId and -StatusOptionId. IDs are never guessed.' }
}
function Assert-IssueLink {
    param([string]$Body, [int]$Issue, [string]$GitHubRepository)
    $repo = [regex]::Escape($GitHubRepository)
    $pattern = "(?im)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+(?:$repo)?#$Issue\b"
    if ($Body -notmatch $pattern) { throw "PR body must resolve this repository's issue using 'Closes #$Issue' or 'Closes $GitHubRepository#$Issue'." }
}
function Assert-Task {
    param($Task, [string]$Owner, [string]$Repository)
    if (-not $Task -or $Task.status -eq 'released') { throw 'No active managed task found. Run start-task first.' }
    if ($Task.owner -cne $Owner) { throw "Task is owned by '$($Task.owner)'. Never reuse another agent's worktree." }
    if (-not (Test-SamePath $Repository $Task.path)) { throw "Use this task's worktree: $($Task.path)" }
    $branch = Invoke-Git $Repository @('branch', '--show-current')
    if ($branch -cne $Task.branch) { throw "Expected branch '$($Task.branch)', found '$branch'." }
}
Export-ModuleMember -Function *
