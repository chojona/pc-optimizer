#Requires -Version 7.0
<#
  Validate the mandatory end-of-session protocol for one task worktree.

  Read-only: it never stages, commits, pushes, publishes, or contacts GitHub. Commit, push,
  and change facts come from Git; review, test, publication, issue, and handoff steps are
  attestations recorded by finish-task.ps1. A pending step means "not recorded here", which
  is not the same as "not done"; it still has to be completed or explained to the user.
#>
[CmdletBinding()]
param(
    [string]$Repository = '.',
    [ValidateRange(0, 2147483647)][int]$Issue,
    [string]$Owner,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9/_.-]*$')][string]$Base = 'main',
    [string]$BaseCommit,
    [switch]$ReportOnly
)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Workflow.psm1') -Force -DisableNameChecking
$lock = $null
try {
    $context = Get-Context $Repository
    # Snapshot readers lock when coordination state exists; this call never initializes it.
    if (Test-Path -LiteralPath $context.State) { $lock = Enter-WorkflowLock $context }
    $registry = Read-Registry $context
    $branch = Invoke-Git $context.Root @('branch', '--show-current')
    if (-not $branch) { throw 'HEAD is detached. Check out the task branch before validating the session protocol.' }
    $task = $null
    if ($Issue -gt 0) { $task = $registry["$Issue"] }
    else {
        $matched = @($registry.Values | Where-Object { $_.status -ne 'released' -and (Test-SamePath $_.path $context.Root) })
        if ($matched.Count -gt 1) { throw 'Several active claims name this worktree. Pass -Issue to select one; nothing was changed.' }
        if ($matched.Count -eq 1) { $task = $matched[0] }
    }
    if ($task -and $task.status -eq 'released') { $task = $null }
    if ($task -and $Owner) { Assert-Task $task $Owner $context.Root }
    $resolvedBase = if ($task) { $task.baseCommit } elseif ($BaseCommit) { Invoke-Git $context.Root @('rev-parse', '--verify', "$BaseCommit^{commit}") } else { Resolve-BaseCommit $context.Root $Base }
    $taskBranch = if ($task) { $task.branch } else { $branch }
    if ($task -and $branch -cne $task.branch) { throw "Expected the task branch '$($task.branch)', found '$branch'." }
    $protocol = Get-SessionProtocol $context.Root $task $taskBranch $resolvedBase
    $guidance = @(
        'Every session that changed this repository ends with: review the diff, run the relevant tests and report the actual results, commit, push the task branch, create or update one pull request, update the issue and Project status, and hand off.',
        'Failing checks or incomplete work publish a draft pull request that documents the blockers; they are never reported as a pass.',
        'A session with no repository changes creates no pull request.',
        'Unrecorded steps are reported as pending. Record them with finish-task.ps1 or explain the limitation to the user; never claim an unperformed GitHub update.'
    )
    [ordered]@{ protocol = $protocol; guidance = $guidance } | ConvertTo-Json -Depth 15
    if (-not $protocol.satisfied -and -not $ReportOnly) {
        Write-Error "The end-of-session protocol is incomplete: $($protocol.pendingSteps -join ', '). Nothing was changed." -ErrorAction Continue
        exit 1
    }
    exit 0
} catch { Write-Error $_ -ErrorAction Continue; exit 1 }
finally { if ($lock) { $lock.Dispose() } }
