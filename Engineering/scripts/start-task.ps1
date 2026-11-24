#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$Repository = '.',
    [Parameter(Mandatory)][ValidateRange(1,2147483647)][int]$Issue,
    [Parameter(Mandatory)][ValidatePattern('^[a-z0-9]+(?:-[a-z0-9]+)*$')][string]$Slug,
    [Parameter(Mandatory)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]{2,99}$')][string]$Owner,
    [Parameter(Mandatory)][string[]]$Files,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9/_.-]*$')][string]$Base = 'main',
    [string]$WorktreeRoot,
    [switch]$Offline, [switch]$DryRun, [switch]$UpdateProject,
    [string]$ProjectId, [string]$ProjectItemId, [string]$StatusFieldId, [string]$StatusOptionId
)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Workflow.psm1') -Force -DisableNameChecking
$lock = $null
try {
    Assert-ProjectParameters -UpdateProject:$UpdateProject -ProjectId $ProjectId -ProjectItemId $ProjectItemId -StatusFieldId $StatusFieldId -StatusOptionId $StatusOptionId
    if ($Offline -and $UpdateProject) { throw 'Cannot update GitHub Projects in offline mode.' }
    $context = Get-Context $Repository
    $claims = @(Convert-Claims $Files)
    Invoke-Git $context.Root @('check-ref-format', '--branch', $Base) | Out-Null
    $branch = "codex/issue-$Issue-$Slug"
    Invoke-Git $context.Root @('check-ref-format', '--branch', $branch) | Out-Null
    $trees = @(Get-Worktrees $context.Root)
    if (-not $WorktreeRoot) {
        $main = $trees[0].Path
        $WorktreeRoot = Join-Path (Split-Path $main -Parent) ('.' + (Split-Path $main -Leaf) + '-worktrees')
    }
    $target = [IO.Path]::GetFullPath((Join-Path $WorktreeRoot "issue-$Issue-$Slug"))
    if (-not $DryRun) { $lock = Enter-WorkflowLock $context }
    $trees = @(Get-Worktrees $context.Root)
    $registry = Read-Registry $context
    $key = "$Issue"
    $task = $registry[$key]
    if ($task -and $task.status -ne 'released') {
        Assert-Task $task $Owner $task.path
        if ($task.branch -cne $branch -or $task.base -cne $Base -or -not (Test-SamePath $task.path $target) -or ($task.files -join "`n") -cne ($claims -join "`n")) { throw 'Existing task parameters differ. Keep ownership stable; coordinate an explicit release before reassignment.' }
        $target = $task.path
    }
    foreach ($otherKey in $registry.Keys) {
        $other = $registry[$otherKey]
        if ($otherKey -ne $key -and $other.status -ne 'released' -and (Test-Overlap $claims $other.files)) { throw "Ownership conflict with issue $otherKey ($($other.owner)): $($other.files -join ', ')" }
    }
    $issueInfo = $null; $prs = @(); $github = $null
    if (-not $Offline) {
        Assert-GitHub
        $github = Get-GitHubRepository $context.Root
        $issueInfo = Invoke-Tool gh @('issue', 'view', "$Issue", '--repo', $github, '--json', 'number,title,body,url,state,assignees') | ConvertFrom-Json
        if ($issueInfo.state -ne 'OPEN') { throw 'The assigned GitHub issue is not open.' }
        $prs = @(Get-OpenPullRequests $github)
        foreach ($pr in $prs) {
            if ($task -and $pr.head.ref -eq $branch -and $pr.head.repo -and $pr.head.repo.full_name -eq $github) { continue }
            $pages = Invoke-Tool gh @('api', '--paginate', '--slurp', "repos/$github/pulls/$($pr.number)/files?per_page=100") | ConvertFrom-Json
            $prPaths = @(foreach ($page in $pages) { foreach ($file in $page) { $file.filename; if ($file.PSObject.Properties['previous_filename']) { $file.previous_filename } } })
            if (Test-Overlap $claims $prPaths) { throw "Open PR #$($pr.number) overlaps declared ownership. Coordinate before starting." }
        }
        if (-not $DryRun) { Invoke-Git $context.Root @('fetch', '--no-tags', 'origin', "+refs/heads/${Base}:refs/remotes/origin/$Base") | Out-Null }
        $baseRef = "refs/remotes/origin/$Base"
    } else { $baseRef = "refs/heads/$Base" }
    # Dry run never fetches: it reports if the cached base is unavailable.
    $baseCommit = Invoke-Git $context.Root @('rev-parse', '--verify', "$baseRef^{commit}")
    foreach ($tree in $trees) {
        if ($task -and $task.status -ne 'released' -and (Test-SamePath $tree.Path $task.path)) { continue }
        $paths = @(Get-ChangedPaths $tree.Path)
        $paths += Get-Lines (Invoke-Git $tree.Path @('-c', 'core.quotePath=false', 'diff', '--name-only', '--no-renames', "$baseCommit...HEAD", '--'))
        if (Test-Overlap $claims $paths) { throw "Existing worktree '$($tree.Path)' overlaps declared ownership. Coordinate committed and uncommitted changes first." }
    }
    $branches = Get-Lines (Invoke-Git $context.Root @('for-each-ref', '--format=%(refname:short)', 'refs/heads/'))
    if (-not $task -or $task.status -eq 'released') {
        if ($branch -in $branches) { throw "Branch '$branch' already exists without this active claim. No branch was reset or adopted." }
        if (Test-Path -LiteralPath $target) { throw "Worktree target already exists: $target. No files were changed." }
    }
    $plan = [ordered]@{
        issue = $Issue; owner = $Owner; branch = $branch; path = $target; base = $Base; baseCommit = $baseCommit
        files = $claims; offline = [bool]$Offline; issueDetails = $issueInfo; localBranches = $branches; worktrees = $trees; openPullRequests = @($prs | ForEach-Object { $_.number })
        plan = @('Read issue acceptance criteria and dependencies; resolve blockers.', 'Inspect repository instructions and existing modules.', 'Agree interface contracts and ownership before implementation.', 'Implement focused changes and meaningful tests.', 'Measure performance claims and prepare educational handoff.')
    }
    if ($DryRun) { $plan['dryRun'] = $true; $plan | ConvertTo-Json -Depth 15; exit 0 }
    if (-not $task -or $task.status -eq 'released') {
        [IO.Directory]::CreateDirectory((Split-Path $target -Parent)) | Out-Null
        Invoke-Git $context.Root @('worktree', 'add', '-b', $branch, $target, $baseCommit) | Out-Null
        $registry[$key] = @{ issue=$Issue; owner=$Owner; branch=$branch; path=$target; base=$Base; baseCommit=$baseCommit; files=$claims; status='active'; created=[DateTime]::UtcNow.ToString('o'); github=$github }
        Write-Registry $context $registry
    }
    if ($UpdateProject) { $plan['projectStatus'] = Update-ProjectStatus $ProjectId $ProjectItemId $StatusFieldId $StatusOptionId }
    $plan | ConvertTo-Json -Depth 15
    exit 0
} catch { Write-Error $_ -ErrorAction Continue; exit 1 }
finally { if ($lock) { $lock.Dispose() } }
