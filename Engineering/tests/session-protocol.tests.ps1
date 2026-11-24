#Requires -Version 7.0
[CmdletBinding()]
param([string]$TemporaryRoot = [IO.Path]::GetTempPath(), [switch]$KeepArtifacts)

# End-of-session protocol checks for completed, incomplete, interrupted, failed, and
# no-change sessions. Disposable repositories and a local bare origin only: no Pester,
# no GitHub authentication, no network, and no global Git or system changes.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$bundle = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$scripts = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\scripts'))
$pwsh = (Get-Process -Id $PID).Path
$runRoot = Join-Path ([IO.Path]::GetFullPath($TemporaryRoot)) ('session-protocol-tests-' + [guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($runRoot) | Out-Null
$results = [Collections.Generic.List[object]]::new()
$script:callNumber = 0
$script:fixtureNumber = 0
$runner = Join-Path $runRoot 'invoke.ps1'
@'
param([string]$Script, [string]$ParametersFile)
$ErrorActionPreference = 'Stop'
$parameters = Get-Content -Raw -LiteralPath $ParametersFile | ConvertFrom-Json -AsHashtable
try { & $Script @parameters; exit $LASTEXITCODE }
catch { Write-Error $_ -ErrorAction Continue; exit 1 }
'@ | Set-Content -LiteralPath $runner -Encoding utf8
$passTest = Join-Path $runRoot 'pass.ps1'
$failTest = Join-Path $runRoot 'fail.ps1'
'exit 0' | Set-Content -LiteralPath $passTest
'Write-Error "Deliberate fixture test failure"; exit 7' | Set-Content -LiteralPath $failTest
$handoffFile = Join-Path $runRoot 'handoff.md'
"Completed: fixture change. Remaining: none. Tests: pass.ps1 exit 0. Blockers: none." | Set-Content -LiteralPath $handoffFile -Encoding utf8

function Assert-True([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function Git([string]$Repository, [string[]]$Arguments) {
    $output = & git.exe -C $Repository @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Fixture Git failed: git -C '$Repository' $($Arguments -join ' ')`n$($output -join "`n")" }
    return ($output -join "`n")
}
function Call([string]$Name, [hashtable]$Parameters) {
    $script:callNumber++
    $parameterFile = Join-Path $runRoot "parameters-$script:callNumber.json"
    $Parameters | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $parameterFile -Encoding utf8
    $info = [Diagnostics.ProcessStartInfo]::new($pwsh)
    $info.UseShellExecute = $false; $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true; $info.RedirectStandardError = $true
    foreach ($argument in @('-NoProfile','-NonInteractive','-File',$runner,'-Script',(Join-Path $scripts "$Name.ps1"),'-ParametersFile',$parameterFile)) { $info.ArgumentList.Add($argument) }
    $process = [Diagnostics.Process]::Start($info)
    $output = $process.StandardOutput.ReadToEndAsync(); $errorOutput = $process.StandardError.ReadToEndAsync()
    try {
        if (-not $process.WaitForExit(45000)) { $process.Kill($true); throw 'Session protocol fixture process timed out after 45 seconds.' }
        [pscustomobject]@{ Code=$process.ExitCode; Output=$output.GetAwaiter().GetResult(); Error=$errorOutput.GetAwaiter().GetResult() }
    } finally { $process.Dispose() }
}
function Succeeded($Result) { Assert-True ($Result.Code -eq 0) "Expected success, exit $($Result.Code): $($Result.Error) $($Result.Output)" }
function Failed($Result, [string]$Pattern) {
    Assert-True ($Result.Code -ne 0) "Expected refusal but the command succeeded: $($Result.Output)"
    if ($Pattern) { Assert-True (($Result.Error + $Result.Output) -match ('(?s)' + $Pattern)) "Expected diagnostic '$Pattern': $($Result.Error) $($Result.Output)" }
}
function Protocol($Result) {
    # The report is the last JSON object on stdout; warnings go to stderr.
    $start = $Result.Output.IndexOf('{')
    Assert-True ($start -ge 0) "No protocol report in output: $($Result.Output) $($Result.Error)"
    return ($Result.Output.Substring($start) | ConvertFrom-Json).protocol
}
function Step($ProtocolReport, [string]$Name) {
    $step = @($ProtocolReport.steps | Where-Object { $_.step -eq $Name })
    Assert-True ($step.Count -eq 1) "Protocol report is missing the '$Name' step."
    return $step[0]
}
function New-Fixture {
    $script:fixtureNumber++
    $root = Join-Path $runRoot "fixture-$script:fixtureNumber"
    $repository = Join-Path $root 'repository'
    $origin = Join-Path $root 'origin.git'
    [IO.Directory]::CreateDirectory($repository) | Out-Null
    Git $root @('init','--bare','--initial-branch=main',$origin) | Out-Null
    Git $repository @('init','--initial-branch=main') | Out-Null
    Git $repository @('config','user.name','Protocol Fixture') | Out-Null
    Git $repository @('config','user.email','protocol-fixture@example.invalid') | Out-Null
    Git $repository @('config','commit.gpgsign','false') | Out-Null
    $hooks = Join-Path $root 'empty-hooks'; [IO.Directory]::CreateDirectory($hooks) | Out-Null
    Git $repository @('config','core.hooksPath',$hooks) | Out-Null
    [IO.Directory]::CreateDirectory((Join-Path $repository 'src')) | Out-Null
    'seed-a' | Set-Content -LiteralPath (Join-Path $repository 'src/a.txt')
    'seed-b' | Set-Content -LiteralPath (Join-Path $repository 'src/b.txt')
    Git $repository @('add','--','src') | Out-Null
    Git $repository @('commit','-m','Initial fixture') | Out-Null
    Git $repository @('remote','add','origin',$origin) | Out-Null
    Git $repository @('push','origin','main') | Out-Null
    [pscustomobject]@{ Root=$root; Repository=$repository; Origin=$origin; Worktrees=(Join-Path $root 'worktrees'); State=(Join-Path $repository '.git/engineering-workflow') }
}
function Start-Parameters($Fixture) { @{ Repository=$Fixture.Repository; Issue=1; Slug='task-1'; Owner='agent-one'; Files=@('src/a.txt'); Base='main'; WorktreeRoot=$Fixture.Worktrees; Offline=$true } }
function Task-Path($Fixture) { Join-Path $Fixture.Worktrees 'issue-1-task-1' }
function Finish-Parameters($Fixture) { @{ Repository=(Task-Path $Fixture); Issue=1; Owner='agent-one'; Files=@('src/a.txt'); TestScript=$passTest; Offline=$true } }
function End-Parameters($Fixture) { @{ Repository=(Task-Path $Fixture); Issue=1; Owner='agent-one' } }
function Registry($Fixture) { Get-Content -Raw -LiteralPath (Join-Path $Fixture.State 'tasks.json') | ConvertFrom-Json -AsHashtable }
function Start-Task($Fixture) { Succeeded (Call 'start-task' (Start-Parameters $Fixture)); return (Task-Path $Fixture) }
function Push-TaskBranch($Fixture) {
    # Stand in for an authorized publication push; the fixture origin is a local bare repository.
    $task = Task-Path $Fixture
    Git $task @('push','--set-upstream','origin','HEAD:refs/heads/codex/issue-1-task-1') | Out-Null
    Git $task @('fetch','--no-tags','origin','+refs/heads/codex/issue-1-task-1:refs/remotes/origin/codex/issue-1-task-1') | Out-Null
}
function Set-RegistryField($Fixture, [hashtable]$Fields) {
    # Simulate the attestations finish-task records during an authorized publication.
    $file = Join-Path $Fixture.State 'tasks.json'
    $registry = Get-Content -Raw -LiteralPath $file | ConvertFrom-Json -AsHashtable
    foreach ($key in $Fields.Keys) { $registry['1'][$key] = $Fields[$key] }
    $registry | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $file -Encoding utf8
}
function Check([string]$Name, [scriptblock]$Body) {
    try { & $Body; $results.Add([pscustomobject]@{ Name=$Name; Result='PASS' }); Write-Host "PASS $Name" }
    catch { $results.Add([pscustomobject]@{ Name=$Name; Result='FAIL'; Error=$_.Exception.Message }); Write-Host "FAIL $Name`: $($_.Exception.Message)" }
}

try {
    Check 'completed session reports every protocol step satisfied' {
        $f=New-Fixture; $task=Start-Task $f
        'candidate' | Add-Content -LiteralPath (Join-Path $task 'src/a.txt')
        $p=Finish-Parameters $f; $p.Commit=$true; $p.Message='Implement fixture task'; $p.HandoffFile=$handoffFile
        $p.SkipIssueUpdate=$true; $p.SkipProjectUpdate=$true; $p.LimitationNote='Offline fixture has no GitHub issue or Project board.'
        Succeeded (Call 'finish-task' $p)
        Push-TaskBranch $f
        # Publication itself needs GitHub; the contract suite covers it. Record its result here.
        Set-RegistryField $f @{ pullRequest='https://github.com/example/fixture/pull/1'; pullRequestDraft=$false }
        $r=Call 'end-session' (End-Parameters $f); Succeeded $r
        $protocol=Protocol $r
        Assert-True ([bool]$protocol.satisfied) "Completed session reported pending steps: $($protocol.pendingSteps -join ', ')"
        Assert-True ((Step $protocol 'tests').status -eq 'complete') 'Passing tests were not recorded as complete.'
        Assert-True ((Step $protocol 'commit').status -eq 'complete') 'Committed clean worktree was not recorded as complete.'
        Assert-True ((Step $protocol 'push').status -eq 'complete') 'Pushed branch was not recorded as complete.'
        Assert-True ((Registry $f)['1'].testStatus -eq 'passed') 'Passing test run was not recorded.'
    }
    Check 'failed session refuses a ready pull request and records the real failure' {
        $f=New-Fixture; $task=Start-Task $f
        'candidate' | Add-Content -LiteralPath (Join-Path $task 'src/a.txt')
        $before=Git $task @('rev-parse','HEAD')
        $p=Finish-Parameters $f; $p.TestScript=$failTest; $p.Commit=$true; $p.Message='Must not pass'
        Failed (Call 'finish-task' $p) 'Deliberate fixture test failure|exit 7'
        Assert-True ((Git $task @('rev-parse','HEAD')) -ceq $before) 'Failing checks produced a commit.'
        $p.AllowTestFailure=$true; $p.Publish=$true; $p.Title='Must not be ready for review'; $p.BodyFile=$handoffFile
        Failed (Call 'finish-task' $p) 'draft'
        Assert-True ((Git $task @('rev-parse','HEAD')) -ceq $before) 'Publishing failing checks as ready for review produced a commit.'
        Assert-True ((Git $task @('status','--porcelain')) -match 'src/a.txt') 'Refusal discarded in-progress work.'
    }
    Check 'failed session commits and reports a documented failure for a draft pull request' {
        $f=New-Fixture; $task=Start-Task $f
        'candidate' | Add-Content -LiteralPath (Join-Path $task 'src/a.txt')
        $p=Finish-Parameters $f; $p.TestScript=$failTest; $p.AllowTestFailure=$true; $p.Commit=$true; $p.Message='Record failing checks'
        $p.HandoffFile=$handoffFile; $p.SkipIssueUpdate=$true; $p.SkipProjectUpdate=$true; $p.LimitationNote='Offline fixture.'
        # Failing work is still committed and preserved; publication needs GitHub and a draft.
        Succeeded (Call 'finish-task' $p)
        Assert-True ((Registry $f)['1'].testStatus -eq 'failed') 'A failing run was not recorded as failed.'
        $log=(Registry $f)['1'].testLog
        Assert-True ((Test-Path -LiteralPath $log) -and ((Get-Content -Raw -LiteralPath $log) -match 'Deliberate fixture test failure')) 'Failure evidence was not preserved.'
        Push-TaskBranch $f
        $r=Call 'end-session' (End-Parameters $f); Failed $r 'tests'
        $protocol=Protocol $r
        Assert-True ((Step $protocol 'tests').status -eq 'pending') 'Failing checks without a draft pull request were treated as acceptable.'
        Set-RegistryField $f @{ pullRequest='https://github.com/example/fixture/pull/1'; pullRequestDraft=$true }
        $r=Call 'end-session' (End-Parameters $f); Succeeded $r
        Assert-True ((Step (Protocol $r) 'tests').status -eq 'documented-failure') 'A draft pull request did not document the failing checks.'
    }
    Check 'incomplete session with uncommitted work reports commit and push pending' {
        $f=New-Fixture; $task=Start-Task $f
        'in progress' | Add-Content -LiteralPath (Join-Path $task 'src/a.txt')
        $r=Call 'end-session' (End-Parameters $f); Failed $r 'incomplete'
        $protocol=Protocol $r
        Assert-True ([bool]$protocol.repositoryChanges) 'Uncommitted work was not detected as a repository change.'
        foreach ($name in @('review-diff','tests','commit','push','pull-request','issue-and-project','handoff')) {
            Assert-True ((Step $protocol $name).status -eq 'pending') "Step '$name' was not pending for an incomplete session."
        }
        Assert-True ((Step $protocol 'commit').detail -match 'src/a.txt') 'The pending commit step did not name the uncommitted file.'
        Assert-True ((Git $task @('status','--porcelain')) -match 'src/a.txt') 'Validation modified the worktree.'
    }
    Check 'interrupted session preserves commits and reports the unpushed branch' {
        $f=New-Fixture; $task=Start-Task $f
        'interrupted work' | Add-Content -LiteralPath (Join-Path $task 'src/a.txt')
        $p=Finish-Parameters $f; $p.Commit=$true; $p.Message='Preserve interrupted work'; $p.HandoffFile=$handoffFile
        $p.SkipIssueUpdate=$true; $p.SkipProjectUpdate=$true; $p.LimitationNote='Offline fixture.'
        Succeeded (Call 'finish-task' $p)
        # The session stops here: work is committed but never pushed or published.
        $r=Call 'end-session' (End-Parameters $f); Failed $r 'push|pull-request'
        $protocol=Protocol $r
        Assert-True ((Step $protocol 'commit').status -eq 'complete') 'Committed interrupted work was not recognized.'
        Assert-True ((Step $protocol 'push').status -eq 'pending') 'An unpushed branch was reported as pushed.'
        Assert-True ((Step $protocol 'pull-request').status -eq 'pending') 'A missing pull request was reported as present.'
        Assert-True ($protocol.commitCount -eq 1) 'Interrupted work lost its commit.'
        Assert-True ((Git $task @('show','--format=','--name-only','HEAD')).Trim() -eq 'src/a.txt') 'Interrupted commit lost its content.'
    }
    Check 'later edits invalidate an earlier review and test attestation' {
        $f=New-Fixture; $task=Start-Task $f
        'candidate' | Add-Content -LiteralPath (Join-Path $task 'src/a.txt')
        $p=Finish-Parameters $f; $p.Commit=$true; $p.Message='Implement fixture task'; $p.HandoffFile=$handoffFile
        $p.SkipIssueUpdate=$true; $p.SkipProjectUpdate=$true; $p.LimitationNote='Offline fixture.'
        Succeeded (Call 'finish-task' $p)
        Push-TaskBranch $f
        'later edit' | Add-Content -LiteralPath (Join-Path $task 'src/a.txt')
        Git $task @('add','--','src/a.txt') | Out-Null
        Git $task @('commit','-m','Later unvalidated edit') | Out-Null
        $r=Call 'end-session' (End-Parameters $f); Failed $r 'review-diff|tests'
        $protocol=Protocol $r
        Assert-True ((Step $protocol 'review-diff').status -eq 'pending') 'A stale review attestation was accepted for a new head.'
        Assert-True ((Step $protocol 'tests').status -eq 'pending') 'A stale test attestation was accepted for a new head.'
        Assert-True ((Step $protocol 'push').status -eq 'pending') 'A superseded push was reported as current.'
    }
    Check 'session without repository changes needs no pull request' {
        $f=New-Fixture; Start-Task $f | Out-Null
        $r=Call 'end-session' (End-Parameters $f); Failed $r 'handoff'
        $protocol=Protocol $r
        Assert-True (-not $protocol.repositoryChanges) 'An unchanged worktree reported repository changes.'
        foreach ($name in @('review-diff','tests','commit','push','pull-request','issue-and-project')) {
            Assert-True ((Step $protocol $name).status -eq 'not-applicable') "Step '$name' was required for a session with no changes."
        }
        Assert-True ((Step $protocol 'pull-request').detail -match 'empty pull request') 'The no-change report did not rule out an empty pull request.'
        Assert-True ((Step $protocol 'handoff').status -eq 'pending') 'A session with no changes skipped the handoff.'
    }
    Check 'validation never reuses another owner or worktree' {
        $f=New-Fixture; Start-Task $f | Out-Null
        $p=End-Parameters $f; $p.Owner='agent-two'
        Failed (Call 'end-session' $p) 'owned by'
        $p=End-Parameters $f; $p.Repository=$f.Repository
        Failed (Call 'end-session' $p) "worktree|branch"
    }
    Check 'unmanaged session is reported as unverified rather than complete' {
        $f=New-Fixture
        $tree=Join-Path $f.Root 'unmanaged'
        Git $f.Repository @('worktree','add','-b','feature/unmanaged',$tree,'main') | Out-Null
        'unmanaged change' | Add-Content -LiteralPath (Join-Path $tree 'src/a.txt')
        $r=Call 'end-session' @{ Repository=$tree; Base='main' }; Failed $r 'incomplete'
        $protocol=Protocol $r
        Assert-True (-not $protocol.managed) 'An unregistered worktree was reported as a managed task.'
        Assert-True ([bool]$protocol.repositoryChanges) 'Unmanaged changes were not detected.'
        $r=Call 'end-session' @{ Repository=$tree; Base='main'; ReportOnly=$true }; Succeeded $r
        Assert-True ((Protocol $r).pendingSteps.Count -gt 0) 'Report-only mode hid the pending steps.'
    }
    Check 'every agent adapter and skill exposes the protocol' {
        $required = @(
            'AGENTS.md', 'CLAUDE.md', '.cursor/rules/engineering.mdc', 'Engineering/ENGINEERING.md',
            'Engineering/skills/start-task/SKILL.md', 'Engineering/skills/finish-task/SKILL.md',
            '.agents/skills/start-task/SKILL.md', '.agents/skills/finish-task/SKILL.md',
            '.claude/skills/start-task/SKILL.md', '.claude/skills/finish-task/SKILL.md'
        )
        foreach ($relative in $required) {
            $path = Join-Path $bundle $relative
            Assert-True (Test-Path -LiteralPath $path) "Missing agent instruction file: $relative"
            $text = Get-Content -Raw -LiteralPath $path
            Assert-True ($text -match '(?i)end-of-session protocol|end every session') "'$relative' does not mention the end-of-session protocol."
        }
        foreach ($relative in @('AGENTS.md', 'CLAUDE.md', '.cursor/rules/engineering.mdc')) {
            $text = Get-Content -Raw -LiteralPath (Join-Path $bundle $relative)
            foreach ($term in @('diff', 'test', 'commit', 'push', 'pull request', 'issue', 'hand off|handoff', 'draft', 'Blockers')) {
                Assert-True ($text -match "(?i)$term") "The '$relative' adapter omits the protocol term '$term'."
            }
        }
        $policy = Get-Content -Raw -LiteralPath (Join-Path $bundle 'Engineering/ENGINEERING.md')
        Assert-True ($policy -match '(?i)end-session\.ps1') 'The canonical rules do not point at the protocol validator.'
        Assert-True ($policy -match '(?i)never create an empty pull request|creates no pull request') 'The canonical rules do not rule out empty pull requests.'
    }
    Check 'coordinator status reports each claimed task protocol state' {
        $f=New-Fixture; $task=Start-Task $f
        'candidate' | Add-Content -LiteralPath (Join-Path $task 'src/a.txt')
        $r=Call 'agent-status' @{ Repository=$f.Repository }; Succeeded $r
        $report=$r.Output | ConvertFrom-Json
        $managed=@($report.worktrees | Where-Object { $_.managed })
        Assert-True ($managed.Count -eq 1) 'Status did not report exactly one managed task worktree.'
        Assert-True ($null -ne $managed[0].sessionProtocol -and -not $managed[0].sessionProtocol.satisfied) 'Status omitted the pending end-of-session protocol.'
        Assert-True (@($managed[0].sessionProtocol.pendingSteps) -contains 'commit') 'Status did not report the pending commit step.'
    }
    $summary=[ordered]@{ Passed=@($results | Where-Object Result -EQ 'PASS').Count; Failed=@($results | Where-Object Result -EQ 'FAIL').Count; Artifacts=$runRoot; Tests=$results }
    $summary | ConvertTo-Json -Depth 8
    if ($summary.Failed -gt 0) { $KeepArtifacts=$true; exit 1 }
} finally {
    if (-not $KeepArtifacts) {
        # Only the uniquely created disposable test root, never a caller's repository.
        $resolved=[IO.Path]::GetFullPath($runRoot)
        $parent=[IO.Path]::GetFullPath($TemporaryRoot).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
        if (-not $resolved.StartsWith($parent,[StringComparison]::OrdinalIgnoreCase) -or (Split-Path $resolved -Leaf) -notmatch '^session-protocol-tests-[0-9a-f]{32}$') { throw "Refusing unsafe fixture cleanup: $resolved" }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    } else { Write-Host "Preserved fixture artifacts: $runRoot" }
}
