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
    param([string]$Body, [int]$Issue, [string]$GitHubRepository, [ValidateSet('resolves', 'references')][string]$Mode = 'resolves')
    $repo = [regex]::Escape($GitHubRepository)
    $closing = "(?im)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+(?:$repo)?#$Issue\b"
    if ($Mode -eq 'resolves') {
        if ($Body -notmatch $closing) { throw "PR body must resolve this repository's issue using 'Closes #$Issue' or 'Closes $GitHubRepository#$Issue'." }
        return
    }
    # An incomplete implementation links the issue without claiming to resolve it.
    if ($Body -match $closing) { throw "An incomplete or failing session must not claim to close issue #$Issue. Reference it instead, for example 'Refs #$Issue'." }
    if ($Body -notmatch "(?im)(?:$repo)?#$Issue\b") { throw "PR body must reference issue #$Issue, for example 'Refs #$Issue'." }
}
function Assert-IssueMention {
    param([string]$Body, [int]$Issue, [string]$GitHubRepository)
    # The lookbehind keeps 'other/project#1' from passing as this repository's issue reference.
    $repo = [regex]::Escape($GitHubRepository)
    if ($Body -notmatch "(?im)(?<![A-Za-z0-9_./-])(?:$repo)?#$Issue\b") { throw "The existing pull request body does not reference issue #$Issue in this repository. Coordinate manually instead of reusing another task's pull request." }
}
function Set-PullRequestContent {
    param([string]$GitHubRepository, [int]$Number, [string]$Title, [string]$BodyPath)
    Invoke-Tool gh @('pr', 'edit', "$Number", '--repo', $GitHubRepository, '--title', $Title, '--body-file', $BodyPath) | Out-Null
}
function Set-PullRequestDraft {
    param([string]$GitHubRepository, [int]$Number, [bool]$Draft)
    # Converting a ready PR back to draft is a deliberate signal that work is incomplete.
    $arguments = @('pr', 'ready', "$Number", '--repo', $GitHubRepository)
    if ($Draft) { $arguments += '--undo' }
    Invoke-Tool gh $arguments | Out-Null
}
function Add-IssueComment {
    param([string]$GitHubRepository, [int]$Issue, [string]$BodyPath)
    try { Invoke-Tool gh @('issue', 'comment', "$Issue", '--repo', $GitHubRepository, '--body-file', $BodyPath) | Out-Null; return 'commented' }
    catch { Write-Warning "The issue was not commented on. Check issue write permission. $($_.Exception.Message)"; return 'pending' }
}
function Assert-Task {
    param($Task, [string]$Owner, [string]$Repository)
    if (-not $Task -or $Task.status -eq 'released') { throw 'No active managed task found. Run start-task first.' }
    if ($Task.owner -cne $Owner) { throw "Task is owned by '$($Task.owner)'. Never reuse another agent's worktree." }
    if (-not (Test-SamePath $Repository $Task.path)) { throw "Use this task's worktree: $($Task.path)" }
    $branch = Invoke-Git $Repository @('branch', '--show-current')
    if ($branch -cne $Task.branch) { throw "Expected branch '$($Task.branch)', found '$branch'." }
}
function Get-Field {
    param($Object, [string]$Name)
    if ($null -eq $Object) { return $null }
    if ($Object -is [System.Collections.IDictionary]) { if ($Object.Contains($Name)) { return $Object[$Name] }; return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($property) { return $property.Value }
    return $null
}
function Resolve-BaseCommit {
    param([string]$Repository, [string]$Base)
    foreach ($ref in @("refs/remotes/origin/$Base", "refs/heads/$Base")) {
        try { return (Invoke-Git $Repository @('merge-base', 'HEAD', $ref)) } catch { continue }
    }
    throw "Cannot resolve a base commit for '$Base'. Supply -BaseCommit or fetch the base explicitly; nothing was changed."
}
function Get-PushedCommit {
    param([string]$Repository, [string]$Branch)
    # Local read of the remote-tracking ref only. It never contacts the network and can be stale.
    try { return (Invoke-Git $Repository @('rev-parse', '--verify', "refs/remotes/origin/$Branch^{commit}")) } catch { return $null }
}
function Assert-Blockers {
    param([string]$Body)
    $lines = @($Body -split "`r?`n")
    $index = -1
    for ($i = 0; $i -lt $lines.Count; $i++) { if ($lines[$i] -match '(?i)^#{1,6}\s*blockers\b') { $index = $i; break } }
    if ($index -lt 0) { throw 'An incomplete or failing session must document a "## Blockers" section in the reviewed pull request body.' }
    for ($i = $index + 1; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^#{1,6}\s') { break }
        if ($lines[$i] -match '^\s*(?:[-*+]|\d+\.)\s+\S') { return }
    }
    throw 'The "## Blockers" section must list at least one concrete blocker.'
}
function New-ProtocolStep {
    param([string]$Step, [string]$Status, [string]$Detail)
    return [ordered]@{ step = $Step; status = $Status; detail = $Detail }
}
function Get-SessionProtocol {
    <#
      Report the mandatory end-of-session protocol state for one task worktree.
      Commit, push, and change facts come from Git. Review, test, publication, issue, and
      handoff steps are attestations recorded by finish-task.ps1, not independent proof.
      This function is read-only: it never commits, pushes, publishes, or contacts GitHub.
    #>
    param([string]$Repository, $Task, [string]$Branch, [string]$BaseCommit)
    $head = Invoke-Git $Repository @('rev-parse', 'HEAD')
    $pending = @(Get-ChangedPaths $Repository)
    $clean = -not [bool](Invoke-Git $Repository @('status', '--porcelain'))
    $committed = @(Get-Lines (Invoke-Git $Repository @('-c', 'core.quotePath=false', 'diff', '--name-only', '--no-renames', "$BaseCommit...HEAD", '--')))
    $commitCount = [int](Invoke-Git $Repository @('rev-list', '--count', "$BaseCommit..HEAD"))
    $pushed = Get-PushedCommit $Repository $Branch
    $changed = ($commitCount -gt 0) -or ($pending.Count -gt 0)
    $validated = Get-Field $Task 'validatedCommit'
    $validatedHead = [bool]($validated -and $validated -ceq $head)
    $testStatus = Get-Field $Task 'testStatus'
    $pullRequest = Get-Field $Task 'pullRequest'
    $draft = [bool](Get-Field $Task 'pullRequestDraft')
    $issueUpdate = Get-Field $Task 'issueUpdate'
    $projectStatus = Get-Field $Task 'projectStatus'
    $handoff = Get-Field $Task 'handoff'
    $steps = [Collections.Generic.List[object]]::new()
    if (-not $changed) {
        foreach ($name in @('review-diff', 'tests', 'commit', 'push', 'pull-request', 'issue-and-project')) {
            $steps.Add((New-ProtocolStep $name 'not-applicable' 'This session produced no repository changes; no empty pull request is created.'))
        }
    } else {
        $reviewDetail = if ($validatedHead) { "Diff reviewed and validated at $head." }
            elseif ($validated) { "Validation was recorded for $validated, not the current head $head. Review the current diff again." }
            else { 'No recorded diff review. Inspect the full diff for correctness, unrelated changes, and exposed secrets.' }
        $steps.Add((New-ProtocolStep 'review-diff' $(if ($validatedHead) { 'complete' } else { 'pending' }) $reviewDetail))
        $testDetail = switch ($testStatus) {
            'passed' { "Tests recorded as passed at $validated." }
            'failed' { "Tests recorded as failed at $validated. A draft pull request must document the blockers." }
            default { 'No recorded test run. Run the relevant project checks and report their actual results.' }
        }
        $testState = 'pending'
        if ($validatedHead -and $testStatus -eq 'passed') { $testState = 'complete' }
        elseif ($validatedHead -and $testStatus -eq 'failed' -and $pullRequest -and $draft) { $testState = 'documented-failure' }
        $steps.Add((New-ProtocolStep 'tests' $testState $testDetail))
        $commitState = if ($commitCount -gt 0 -and $clean) { 'complete' } else { 'pending' }
        $commitDetail = if ($commitState -eq 'complete') { "$commitCount commit(s) on '$Branch'; the worktree is clean." }
            elseif ($pending.Count) { "Uncommitted work remains: $($pending -join ', '). Commit it or preserve it deliberately." }
            else { "No commits on '$Branch' since $BaseCommit." }
        $steps.Add((New-ProtocolStep 'commit' $commitState $commitDetail))
        $pushState = if ($pushed -and $pushed -ceq $head) { 'complete' } else { 'pending' }
        $pushDetail = if ($pushState -eq 'complete') { "origin/$Branch matches the local head." }
            elseif ($pushed) { "origin/$Branch is at $pushed; the local head is $head. Push the task branch." }
            else { "No remote-tracking ref for origin/$Branch. Push the task branch; a never-fetched ref also looks like this." }
        $steps.Add((New-ProtocolStep 'push' $pushState $pushDetail))
        $prDetail = if ($pullRequest) { "$(if ($draft) { 'Draft' } else { 'Ready-for-review' }) pull request: $pullRequest" }
            else { 'No pull request recorded. Create one, or update the existing pull request for this branch instead of opening a duplicate.' }
        $steps.Add((New-ProtocolStep 'pull-request' $(if ($pullRequest) { 'complete' } else { 'pending' }) $prDetail))
        $issueDone = $issueUpdate -in @('commented', 'not-authorized', 'not-supported')
        $projectDone = $projectStatus -in @('updated', 'not-authorized', 'not-supported')
        $steps.Add((New-ProtocolStep 'issue-and-project' $(if ($issueDone -and $projectDone) { 'complete' } else { 'pending' }) "Issue update: $(if ($issueUpdate) { $issueUpdate } else { 'not recorded' }); Project status: $(if ($projectStatus) { $projectStatus } else { 'not recorded' }). Record an unavailable permission explicitly instead of reporting an update that did not happen."))
    }
    $handoffDetail = if ($handoff) { "Handoff recorded: $handoff" }
        else { 'No handoff recorded. Report completed work, remaining work, test results, blockers, the pull request URL, and the engineering concepts involved.' }
    $steps.Add((New-ProtocolStep 'handoff' $(if ($handoff) { 'complete' } else { 'pending' }) $handoffDetail))
    $pendingSteps = @($steps | Where-Object { $_.status -eq 'pending' } | ForEach-Object { $_.step })
    return [ordered]@{
        repository = $Repository; branch = $Branch; head = $head; baseCommit = $BaseCommit
        managed = [bool]$Task; owner = (Get-Field $Task 'owner'); taskStatus = (Get-Field $Task 'status')
        repositoryChanges = $changed; clean = $clean; commitCount = $commitCount
        pendingPaths = $pending; committedPaths = $committed; pushedCommit = $pushed
        pullRequest = $pullRequest; pullRequestDraft = $draft; testStatus = $testStatus
        steps = @($steps); pendingSteps = $pendingSteps; satisfied = ($pendingSteps.Count -eq 0)
    }
}
Export-ModuleMember -Function *
