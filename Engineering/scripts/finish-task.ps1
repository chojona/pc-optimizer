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
    [switch]$Draft, [switch]$AllowTestFailure,
    [switch]$CommentIssue, [string]$HandoffFile,
    [switch]$SkipIssueUpdate, [switch]$SkipProjectUpdate, [string]$LimitationNote,
    [switch]$Offline, [switch]$DryRun, [switch]$UpdateProject,
    [string]$ProjectId, [string]$ProjectItemId, [string]$StatusFieldId, [string]$StatusOptionId
)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Workflow.psm1') -Force -DisableNameChecking
$lock = $null
try {
    Assert-ProjectParameters -UpdateProject:$UpdateProject -ProjectId $ProjectId -ProjectItemId $ProjectItemId -StatusFieldId $StatusFieldId -StatusOptionId $StatusOptionId
    if ($Draft -and -not $Publish) { throw '-Draft describes the published pull request; use it with -Publish.' }
    if ($AllowTestFailure -and $Publish -and -not $Draft) { throw 'Failing checks may only be published as a draft pull request with documented blockers. Add -Draft.' }
    if ($Offline -and ($Publish -or $UpdateProject -or $CommentIssue)) { throw 'Publishing, issue comments, and Project updates require GitHub; remove -Offline.' }
    if ($Commit -and [string]::IsNullOrWhiteSpace($Message)) { throw '-Commit requires a reviewed -Message.' }
    if ($Publish -and ([string]::IsNullOrWhiteSpace($Title) -or -not $BodyFile)) { throw '-Publish requires -Title and a reviewed -BodyFile.' }
    if ($CommentIssue -and -not $HandoffFile) { throw '-CommentIssue posts the reviewed -HandoffFile contents; supply that file.' }
    if ($UpdateProject -and $SkipProjectUpdate) { throw 'Choose either -UpdateProject or -SkipProjectUpdate, not both.' }
    if (($SkipIssueUpdate -or $SkipProjectUpdate) -and [string]::IsNullOrWhiteSpace($LimitationNote)) { throw 'Skipping the issue or Project update requires -LimitationNote describing why it is unsupported or unauthorized.' }
    $context = Get-Context $Repository
    if (-not $DryRun) { $lock = Enter-WorkflowLock $context }
    $registry = Read-Registry $context
    $task = $registry["$Issue"]
    Assert-Task $task $Owner $context.Root
    $filesToStage = @(Convert-Claims $Files)
    Assert-OwnedPaths $filesToStage $task.files
    $testPath = (Resolve-Path -LiteralPath $TestScript).Path
    if ([IO.Path]::GetExtension($testPath) -ine '.ps1') { throw '-TestScript must be a trusted PowerShell .ps1 file. No command strings are evaluated.' }
    $handoffPath = $null
    if ($HandoffFile) {
        $handoffPath = (Resolve-Path -LiteralPath $HandoffFile).Path
        if ((Get-Item -LiteralPath $handoffPath).Length -eq 0) { throw '-HandoffFile is empty. Record completed work, remaining work, test results, blockers, the pull request URL, and the engineering concepts involved.' }
    }
    $bodyPath = $null
    $github = $null
    if ($Publish -or $UpdateProject -or $CommentIssue) { Assert-GitHub; $github = Get-GitHubRepository $context.Root }
    if ($Publish -or $CommentIssue) {
        if ($task.github -and $task.github -cne $github) { throw 'origin no longer matches the GitHub repository recorded for this task.' }
        $issueInfo = Invoke-Tool gh @('issue', 'view', "$Issue", '--repo', $github, '--json', 'number,title,url,state') | ConvertFrom-Json
        if ($issueInfo.state -ne 'OPEN') { throw 'The assigned GitHub issue is not open; resolve its status before publication.' }
    }
    if ($Publish) {
        $bodyPath = (Resolve-Path -LiteralPath $BodyFile).Path
        $body = Get-Content -Raw -LiteralPath $bodyPath
        Assert-IssueLink $body $Issue $github -Mode $(if ($Draft) { 'references' } else { 'resolves' })
        if ($Draft) { Assert-Blockers $body }
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
    $plan = [ordered]@{ issue=$Issue; owner=$Owner; branch=$task.branch; path=$task.path; changed=$changed; tests=$testPath; commit=[bool]$Commit; publish=[bool]$Publish; draft=[bool]$Draft; dryRun=[bool]$DryRun }
    if ($DryRun) {
        $plan['sessionProtocol'] = Get-SessionProtocol $context.Root $task $task.branch $task.baseCommit
        $plan | ConvertTo-Json -Depth 10
        exit 0
    }
    $testStatus = 'passed'
    Push-Location $context.Root
    try {
        # A separate process makes native exit failures visible; the script must propagate its test runner's exit code.
        try { $testOutput = Invoke-Tool (Join-Path $PSHOME 'pwsh.exe') @('-NoProfile', '-File', $testPath) }
        catch {
            if (-not $AllowTestFailure) { throw }
            $testStatus = 'failed'
            $testOutput = $_.Exception.Message
        }
        Write-Host $testOutput
    } finally { Pop-Location }
    if ($testStatus -eq 'failed') {
        # Preserve the actual failure text as evidence; a failing run is never reported as a pass.
        $testLog = Join-Path $context.State ("test-failure-$Issue-" + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '.log')
        [IO.File]::WriteAllText($testLog, $testOutput, [Text.UTF8Encoding]::new($false))
        $task['testLog'] = $testLog
        Write-Warning "Checks failed. This session may only publish a draft pull request that documents the blockers. Evidence: $testLog"
    }
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
        if ($count -eq 0) {
            # A session without repository changes must not leave an empty pull request behind.
            $plan['publish'] = 'skipped-no-changes'
            Write-Warning 'This session produced no commits. No pull request was created or updated.'
        } else {
            # Preflight remote PR identity. Never attach a task to another base silently.
            $existing = @(Get-OpenPullRequests $github | Where-Object { $_.head.ref -eq $task.branch -and $_.head.repo -and $_.head.repo.full_name -eq $github })
            if ($existing.Count -gt 1 -or ($existing.Count -eq 1 -and $existing[0].base.ref -ne $task.base)) { throw 'Existing PR base is inconsistent with task ownership; coordinate manually.' }
            if ($existing.Count -eq 1) { Assert-IssueMention $existing[0].body $Issue $github }
            Invoke-Git $context.Root @('push', '--set-upstream', 'origin', "HEAD:refs/heads/$($task.branch)") | Write-Host
            if ($existing.Count -eq 1) {
                # One task, one pull request: update the existing one instead of opening a duplicate.
                $number = [int]$existing[0].number
                Set-PullRequestContent $github $number $Title $bodyPath
                if ([bool]$existing[0].draft -ne [bool]$Draft) { Set-PullRequestDraft $github $number ([bool]$Draft) }
                $plan['pullRequest'] = $existing[0].html_url
                $plan['pullRequestAction'] = 'updated'
            } else {
                $arguments = @('pr', 'create', '--repo', $github, '--head', $task.branch, '--base', $task.base, '--title', $Title, '--body-file', $bodyPath)
                if ($Draft) { $arguments += '--draft' }
                $plan['pullRequest'] = Invoke-Tool gh $arguments
                $plan['pullRequestAction'] = 'created'
            }
            $task.status = 'review'
            $task['pullRequest'] = $plan['pullRequest']
            $task['pullRequestDraft'] = [bool]$Draft
        }
    }
    if ($CommentIssue) { $task['issueUpdate'] = Add-IssueComment $github $Issue $handoffPath }
    elseif ($SkipIssueUpdate) { $task['issueUpdate'] = 'not-supported'; $task['issueUpdateNote'] = $LimitationNote }
    if ($UpdateProject) { $task['projectStatus'] = Update-ProjectStatus $ProjectId $ProjectItemId $StatusFieldId $StatusOptionId }
    elseif ($SkipProjectUpdate) { $task['projectStatus'] = 'not-supported'; $task['projectStatusNote'] = $LimitationNote }
    $task['validatedCommit'] = Invoke-Git $context.Root @('rev-parse', 'HEAD')
    $task['validatedAt'] = [DateTime]::UtcNow.ToString('o')
    $task['tests'] = $testPath
    $task['testStatus'] = $testStatus
    if ($handoffPath) { $task['handoff'] = $handoffPath; $task['handoffAt'] = [DateTime]::UtcNow.ToString('o') }
    Write-Registry $context $registry
    $plan['testStatus'] = $testStatus
    if ($task.Contains('issueUpdate')) { $plan['issueUpdate'] = $task['issueUpdate'] }
    if ($task.Contains('projectStatus')) { $plan['projectStatus'] = $task['projectStatus'] }
    $plan['sessionProtocol'] = Get-SessionProtocol $context.Root $task $task.branch $task.baseCommit
    $plan['handoff'] = 'Report completed work, remaining work, exact test results, blockers, the pull request URL, and the engineering concepts involved. Ownership remains reserved through review. Human approval is required to merge.'
    $plan | ConvertTo-Json -Depth 10
    exit 0
} catch { Write-Error $_ -ErrorAction Continue; exit 1 }
finally { if ($lock) { $lock.Dispose() } }
