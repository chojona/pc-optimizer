#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$Repository = '.',
    [Parameter(Mandatory)][int]$Issue,
    [Parameter(Mandatory)][string]$Owner,
    [Parameter(Mandatory)][string[]]$Files,
    [Parameter(Mandatory)][string]$TestScript,
    [switch]$Commit, [string]$Message,
    [switch]$Publish, [string]$Title, [string]$BodyFile,
    [switch]$Offline, [switch]$DryRun, [switch]$UpdateProject,
    [string]$ProjectId, [string]$ProjectItemId, [string]$StatusFieldId, [string]$StatusOptionId
)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Workflow.psm1') -Force -DisableNameChecking
$lock = $null
try {
    Assert-ProjectParameters -UpdateProject:$UpdateProject -ProjectId $ProjectId -ProjectItemId $ProjectItemId -StatusFieldId $StatusFieldId -StatusOptionId $StatusOptionId
    if ($Offline -and ($Publish -or $UpdateProject)) { throw 'Publishing and Project updates require GitHub; remove -Offline.' }
    if ($Commit -and [string]::IsNullOrWhiteSpace($Message)) { throw '-Commit requires a reviewed -Message.' }
    if ($Publish -and ([string]::IsNullOrWhiteSpace($Title) -or -not $BodyFile)) { throw '-Publish requires -Title and a reviewed -BodyFile.' }
    $context = Get-Context $Repository
    if (-not $DryRun) { $lock = Enter-WorkflowLock $context }
    $registry = Read-Registry $context
    $task = $registry["$Issue"]
    Assert-Task $task $Owner $context.Root
    $filesToStage = @(Convert-Claims $Files)
    Assert-OwnedPaths $filesToStage $task.files
    $testPath = (Resolve-Path -LiteralPath $TestScript).Path
    if ([IO.Path]::GetExtension($testPath) -ine '.ps1') { throw '-TestScript must be a trusted PowerShell .ps1 file. No command strings are evaluated.' }
    $bodyPath = $null
    $github = $null
    if ($Publish -or $UpdateProject) { Assert-GitHub; $github = Get-GitHubRepository $context.Root }
    if ($Publish) {
        if ($task.github -and $task.github -cne $github) { throw 'origin no longer matches the GitHub repository recorded for this task.' }
        $issueInfo = Invoke-Tool gh @('issue', 'view', "$Issue", '--repo', $github, '--json', 'number,title,url,state') | ConvertFrom-Json
        if ($issueInfo.state -ne 'OPEN') { throw 'The assigned GitHub issue is not open; resolve its status before publication.' }
        $bodyPath = (Resolve-Path -LiteralPath $BodyFile).Path
        $body = Get-Content -Raw -LiteralPath $bodyPath
        Assert-IssueLink $body $Issue $github
    }
    function Assert-FinalDiff {
        $changed = @(Get-ChangedPaths $context.Root)
        Assert-OwnedPaths $changed $task.files
        Assert-OwnedPaths $changed $filesToStage
        $committed = Get-Lines (Invoke-Git $context.Root @('-c', 'core.quotePath=false', 'diff', '--name-only', '--no-renames', "$($task.baseCommit)...HEAD", '--'))
        Assert-OwnedPaths $committed $task.files
        Invoke-Git $context.Root @('diff', '--check', 'HEAD', '--') | Out-Null
        return $changed
    }
    $changed = @(Assert-FinalDiff)
    $plan = [ordered]@{ issue=$Issue; owner=$Owner; branch=$task.branch; path=$task.path; changed=$changed; tests=$testPath; commit=[bool]$Commit; publish=[bool]$Publish; dryRun=[bool]$DryRun }
    if ($DryRun) { $plan | ConvertTo-Json -Depth 10; exit 0 }
    Push-Location $context.Root
    try {
        # A separate process makes native exit failures visible; the script must propagate its test runner's exit code.
        $testOutput = Invoke-Tool (Join-Path $PSHOME 'pwsh.exe') @('-NoProfile', '-File', $testPath)
        Write-Host $testOutput
    } finally { Pop-Location }
    # Tests may generate files or switch branches: recheck all invariants before mutation.
    Assert-Task $task $Owner $context.Root
    $changed = @(Assert-FinalDiff)
    Write-Host (Invoke-Git $context.Root @('diff', '--stat', 'HEAD', '--'))
    Write-Host (Invoke-Git $context.Root @('diff', '--stat', "$($task.baseCommit)...HEAD", '--'))
    if ($Commit -and $changed.Count) {
        # Literal pathspecs avoid treating filenames as Git pathspec expressions.
        Invoke-Git $context.Root (@('--literal-pathspecs', 'add', '--') + $filesToStage) | Out-Null
        Invoke-Git $context.Root @('diff', '--cached', '--check') | Out-Null
        Invoke-Git $context.Root @('commit', '-m', $Message) | Write-Host
    }
    $remaining = Invoke-Git $context.Root @('status', '--porcelain')
    if ($Publish -and $remaining) { throw 'Publishing requires a clean worktree. Review changes and use -Commit or commit explicitly.' }
    if ($Publish) {
        $count = [int](Invoke-Git $context.Root @('rev-list', '--count', "$($task.baseCommit)..HEAD"))
        if ($count -eq 0) { throw 'No task commits to publish.' }
        # Preflight remote PR identity. Never attach a task to another base silently.
        $existing = @(Get-OpenPullRequests $github | Where-Object { $_.head.ref -eq $task.branch -and $_.head.repo -and $_.head.repo.full_name -eq $github })
        if ($existing.Count -gt 1 -or ($existing.Count -eq 1 -and $existing[0].base.ref -ne $task.base)) { throw 'Existing PR base is inconsistent with task ownership; coordinate manually.' }
        if ($existing.Count -eq 1) { Assert-IssueLink $existing[0].body $Issue $github }
        Invoke-Git $context.Root @('push', '--set-upstream', 'origin', "HEAD:refs/heads/$($task.branch)") | Write-Host
        if ($existing.Count -eq 1) { $plan['pullRequest'] = $existing[0].html_url }
        else {
            $plan['pullRequest'] = Invoke-Tool gh @('pr', 'create', '--repo', $github, '--head', $task.branch, '--base', $task.base, '--title', $Title, '--body-file', $bodyPath)
        }
        $task.status = 'review'
        $task['pullRequest'] = $plan['pullRequest']
    }
    $task['validatedCommit'] = Invoke-Git $context.Root @('rev-parse', 'HEAD')
    $task['validatedAt'] = [DateTime]::UtcNow.ToString('o')
    $task['tests'] = $testPath
    Write-Registry $context $registry
    if ($UpdateProject) { $plan['projectStatus'] = Update-ProjectStatus $ProjectId $ProjectItemId $StatusFieldId $StatusOptionId }
    $plan['handoff'] = 'Report acceptance criteria, exact tests/results, remaining risks, interface changes, measurements, and learning notes. Ownership remains reserved through review. Human approval is required to merge.'
    $plan | ConvertTo-Json -Depth 10
    exit 0
} catch { Write-Error $_ -ErrorAction Continue; exit 1 }
finally { if ($lock) { $lock.Dispose() } }
