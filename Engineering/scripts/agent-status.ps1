#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$Repository = '.',
    [int]$ReleaseIssue,
    [string]$Owner,
    [switch]$ApproveRelease,
    [switch]$Cleanup,
    [switch]$ApproveCleanup,
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Workflow.psm1') -Force -DisableNameChecking
$lock = $null
try {
    $context = Get-Context $Repository
    if ($Cleanup -and -not $ReleaseIssue) { throw '-Cleanup requires -ReleaseIssue and explicit approval.' }
    if ($ReleaseIssue) {
        if (-not $ApproveRelease -or -not $Owner) { throw 'Ownership release requires -Owner and -ApproveRelease after human approval.' }
        if ($Cleanup -and -not $ApproveCleanup) { throw 'Removing a worktree requires explicit -ApproveCleanup after human approval.' }
        if (-not $DryRun) { $lock = Enter-WorkflowLock $context }
        $registry = Read-Registry $context
        $task = $registry["$ReleaseIssue"]
        if (-not $task) { throw 'Unknown issue claim.' }
        Assert-Task $task $Owner $task.path
        if (Invoke-Git $task.path @('status', '--porcelain')) { throw 'Task worktree is dirty. No ownership was released and no files were deleted.' }
        if ($Cleanup) {
            if (Invoke-Git $task.path @('ls-files', '--others', '--ignored', '--exclude-standard')) { throw 'Ignored files are present. Inspect and preserve them before cleanup; nothing was deleted.' }
            $trees = @(Get-Worktrees $context.Root)
            $main = $trees[0].Path
            if (Test-SamePath $main $task.path) { throw 'Never remove the primary worktree.' }
            # Explicitly test ancestry. No --force removal or -D deletion is used.
            $base = "refs/heads/$($task.base)"
            Invoke-Git $main @('rev-parse', '--verify', "$base^{commit}") | Out-Null
            try { Invoke-Git $main @('merge-base', '--is-ancestor', $task.branch, $base) | Out-Null }
            catch { throw "Task branch is unmerged into local '$($task.base)'. Fetch and integrate with human approval before cleanup; everything was preserved." }
            $registered = @($trees | Where-Object { (Test-SamePath $_.Path $task.path) -and $_.Branch -ceq $task.branch })
            if ($registered.Count -ne 1) { throw 'Worktree registration does not match the claim. Refusing cleanup.' }
            if (-not $DryRun) {
                # Git removes only the verified registered worktree and refuses untracked files.
                Invoke-Git $main @('worktree', 'remove', '--', $task.path) | Out-Null
                Invoke-Git $main @('branch', '-d', '--', $task.branch) | Out-Null
            }
        }
        if (-not $DryRun) { $task.status = 'released'; $task['releasedAt'] = [DateTime]::UtcNow.ToString('o'); Write-Registry $context $registry }
        [pscustomobject]@{ issue=$ReleaseIssue; released=(-not $DryRun); cleanup=[bool]$Cleanup; dryRun=[bool]$DryRun } | ConvertTo-Json
        exit 0
    }
    # Snapshot readers also lock when state exists, but a status call never initializes state.
    if ((Test-Path -LiteralPath $context.State) -and -not $DryRun) { $lock = Enter-WorkflowLock $context }
    $registry = Read-Registry $context
    $trees = @(Get-Worktrees $context.Root)
    $status = foreach ($tree in $trees) {
        $claim = @($registry.Values | Where-Object { (Test-SamePath $_.path $tree.Path) -and $_.status -ne 'released' })
        $dirty = $null; $inspectionError = $null
        try { $dirty = [bool](Invoke-Git $tree.Path @('status','--porcelain')) }
        catch { $inspectionError = $_.Exception.Message }
        [pscustomobject]@{ path=$tree.Path; branch=$tree.Branch; head=$tree.Head; dirty=$dirty; inspectionError=$inspectionError; managed=($claim.Count -gt 0); task=$claim }
    }
    $gh = Get-Command gh -ErrorAction SilentlyContinue
    [ordered]@{ repository=$context.Root; state=$context.State; gitVersion=(Invoke-Tool git @('--version')); githubCliAvailable=[bool]$gh; githubAuthentication='Not checked; run gh auth status'; worktrees=@($status); tasks=@($registry.Values); dryRun=[bool]$DryRun } | ConvertTo-Json -Depth 15
    exit 0
} catch { Write-Error $_ -ErrorAction Continue; exit 1 }
finally { if ($lock) { $lock.Dispose() } }
