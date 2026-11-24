#Requires -Version 7.0
[CmdletBinding()]
param([string]$TemporaryRoot = [IO.Path]::GetTempPath(), [switch]$KeepArtifacts)

# Integration checks use disposable repositories and a local bare origin only.
# No Pester, GitHub authentication, network, or global Git changes are required.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$scripts = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\scripts'))
$pwsh = (Get-Process -Id $PID).Path
$runRoot = Join-Path ([IO.Path]::GetFullPath($TemporaryRoot)) ('engineering-tests-' + [guid]::NewGuid().ToString('N'))
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

function Assert-True([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function Git([string]$Repo, [string[]]$Arguments) {
    $output = & git.exe -C $Repo @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Fixture Git failed: git -C '$Repo' $($Arguments -join ' ')`n$($output -join "`n")" }
    return ($output -join "`n")
}
function Begin-Call([string]$Name, [hashtable]$Parameters, [string]$PathOverride) {
    $script:callNumber++
    $parameterFile = Join-Path $runRoot "parameters-$script:callNumber.json"
    $Parameters | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $parameterFile -Encoding utf8
    $info = [Diagnostics.ProcessStartInfo]::new($pwsh)
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    foreach ($arg in @('-NoProfile','-NonInteractive','-File',$runner,'-Script',(Join-Path $scripts "$Name.ps1"),'-ParametersFile',$parameterFile)) { $info.ArgumentList.Add($arg) }
    if ($PathOverride) { $info.Environment['PATH'] = $PathOverride }
    $process = [Diagnostics.Process]::Start($info)
    [pscustomobject]@{ Process=$process; Output=$process.StandardOutput.ReadToEndAsync(); Error=$process.StandardError.ReadToEndAsync() }
}
function End-Call($Call) {
    if (-not $Call.Process.WaitForExit(45000)) { $Call.Process.Kill($true); throw 'Workflow fixture process timed out after 45 seconds.' }
    $result = [pscustomobject]@{ Code=$Call.Process.ExitCode; Output=$Call.Output.GetAwaiter().GetResult(); Error=$Call.Error.GetAwaiter().GetResult() }
    $Call.Process.Dispose()
    return $result
}
function Call([string]$Name, [hashtable]$Parameters, [string]$PathOverride) { End-Call (Begin-Call $Name $Parameters $PathOverride) }
function Succeeded($Result) { Assert-True ($Result.Code -eq 0) "Expected success, exit $($Result.Code): $($Result.Error) $($Result.Output)" }
function Failed($Result, [string]$Pattern) {
    Assert-True ($Result.Code -ne 0) "Expected refusal but command succeeded: $($Result.Output)"
    if ($Pattern) { Assert-True (($Result.Error + $Result.Output) -match ('(?s)' + $Pattern)) "Expected diagnostic '$Pattern': $($Result.Error) $($Result.Output)" }
}
function New-Fixture {
    $script:fixtureNumber++
    $root = Join-Path $runRoot "fixture-$script:fixtureNumber"
    $repo = Join-Path $root 'repository'
    $origin = Join-Path $root 'origin.git'
    $worktrees = Join-Path $root 'worktrees'
    [IO.Directory]::CreateDirectory($repo) | Out-Null
    Git $root @('init','--bare','--initial-branch=main',$origin) | Out-Null
    Git $repo @('init','--initial-branch=main') | Out-Null
    Git $repo @('config','user.name','Workflow Fixture') | Out-Null
    Git $repo @('config','user.email','workflow-fixture@example.invalid') | Out-Null
    Git $repo @('config','commit.gpgsign','false') | Out-Null
    $hooks = Join-Path $root 'empty-hooks'
    [IO.Directory]::CreateDirectory($hooks) | Out-Null
    Git $repo @('config','core.hooksPath',$hooks) | Out-Null
    [IO.Directory]::CreateDirectory((Join-Path $repo 'src')) | Out-Null
    'seed-a' | Set-Content -LiteralPath (Join-Path $repo 'src/a.txt')
    'seed-b' | Set-Content -LiteralPath (Join-Path $repo 'src/b.txt')
    'fixture-readme' | Set-Content -LiteralPath (Join-Path $repo 'README.md')
    Git $repo @('add','--','src','README.md') | Out-Null
    Git $repo @('commit','-m','Initial fixture') | Out-Null
    Git $repo @('remote','add','origin',$origin) | Out-Null
    Git $repo @('push','origin','main') | Out-Null
    [pscustomobject]@{ Root=$root; Repo=$repo; Origin=$origin; Worktrees=$worktrees; State=(Join-Path $repo '.git/engineering-workflow') }
}
function Start-Parameters($Fixture, [int]$Issue=1, [string]$Owner='agent-one', [string[]]$Files=@('src/a.txt')) {
    @{ Repository=$Fixture.Repo; Issue=$Issue; Slug="task-$Issue"; Owner=$Owner; Files=$Files; Base='main'; WorktreeRoot=$Fixture.Worktrees; Offline=$true }
}
function Task-Path($Fixture,[int]$Issue=1) { Join-Path $Fixture.Worktrees "issue-$Issue-task-$Issue" }
function Finish-Parameters($Fixture, [string[]]$Files=@('src/a.txt')) {
    @{ Repository=(Task-Path $Fixture); Issue=1; Owner='agent-one'; Files=$Files; TestScript=$passTest; Offline=$true }
}
function Check([string]$Name, [scriptblock]$Body) {
    try { & $Body; $results.Add([pscustomobject]@{ Name=$Name; Result='PASS' }); Write-Host "PASS $Name" }
    catch { $results.Add([pscustomobject]@{ Name=$Name; Result='FAIL'; Error=$_.Exception.Message }); Write-Host "FAIL $Name`: $($_.Exception.Message)" }
}

try {
    Check 'dry-run makes no claim, branch, worktree, or test side effect' {
        $f=New-Fixture; $before=Git $f.Repo @('show-ref')
        $p=Start-Parameters $f; $p.DryRun=$true; Succeeded (Call 'start-task' $p)
        Assert-True (-not (Test-Path -LiteralPath $f.State)) 'Dry-run wrote workflow state.'
        Assert-True (-not (Test-Path -LiteralPath $f.Worktrees)) 'Dry-run created worktree directories.'
        Assert-True ((Git $f.Repo @('show-ref')) -ceq $before) 'Dry-run changed refs.'
    }
    Check 'clean start and stable same-owner reuse preserve worktree' {
        $f=New-Fixture; $p=Start-Parameters $f
        Succeeded (Call 'start-task' $p)
        $task=Task-Path $f; 'in-progress' | Add-Content -LiteralPath (Join-Path $task 'src/a.txt')
        $before=Git $task @('status','--porcelain')
        Succeeded (Call 'start-task' $p)
        Assert-True ((Git $task @('status','--porcelain')) -ceq $before) 'Reuse changed in-progress files.'
        Assert-True ((Git $f.Repo @('status','--porcelain')) -eq '') 'Primary checkout changed.'
    }
    Check 'dirty primary checkout remains byte-for-byte unchanged' {
        $f=New-Fixture; $readme=Join-Path $f.Repo 'README.md'; 'user edit' | Add-Content -LiteralPath $readme
        'untracked-user' | Set-Content -LiteralPath (Join-Path $f.Repo 'notes.txt')
        Git $f.Repo @('add','--','README.md') | Out-Null
        $before=Git $f.Repo @('status','--porcelain'); $content=[IO.File]::ReadAllText($readme)
        Succeeded (Call 'start-task' (Start-Parameters $f))
        Assert-True ((Git $f.Repo @('status','--porcelain')) -ceq $before) 'Primary index/status changed.'
        Assert-True ([IO.File]::ReadAllText($readme) -ceq $content) 'Primary user file changed.'
    }
    Check 'duplicate assignment by another owner is refused' {
        $f=New-Fixture; Succeeded (Call 'start-task' (Start-Parameters $f))
        Failed (Call 'start-task' (Start-Parameters $f 1 'agent-two')) 'owned by'
        $registry=Get-Content -Raw -LiteralPath (Join-Path $f.State 'tasks.json') | ConvertFrom-Json -AsHashtable
        Assert-True ($registry['1'].owner -ceq 'agent-one') 'Ownership was stolen.'
    }
    Check 'file-directory and case-insensitive ownership conflicts are refused' {
        $f=New-Fixture; Succeeded (Call 'start-task' (Start-Parameters $f 1 'agent-one' @('src')))
        Failed (Call 'start-task' (Start-Parameters $f 2 'agent-two' @('SRC/a.txt'))) 'Ownership conflict'
        Assert-True (-not (Test-Path -LiteralPath (Task-Path $f 2))) 'Conflicting worktree was created.'
    }
    Check 'unmanaged existing branch is never reset or adopted' {
        $f=New-Fixture; Git $f.Repo @('branch','codex/issue-1-task-1') | Out-Null
        $before=Git $f.Repo @('rev-parse','codex/issue-1-task-1')
        Failed (Call 'start-task' (Start-Parameters $f)) 'already exists'
        Assert-True ((Git $f.Repo @('rev-parse','codex/issue-1-task-1')) -ceq $before) 'Existing branch changed.'
    }
    Check 'existing unmanaged worktree overlap blocks new implementation' {
        $f=New-Fixture; $other=Join-Path $f.Root 'other'
        Git $f.Repo @('worktree','add','-b','existing-owner',$other,'main') | Out-Null
        'other work' | Add-Content -LiteralPath (Join-Path $other 'src/a.txt')
        Failed (Call 'start-task' (Start-Parameters $f)) 'Existing worktree.*overlaps'
        Assert-True ((Get-Content -Raw -LiteralPath (Join-Path $other 'src/a.txt')) -match 'other work') 'Other worktree edit lost.'
    }
    Check 'simultaneous independent creation waits for shared lock and preserves both claims' {
        $f=New-Fixture; [IO.Directory]::CreateDirectory($f.State) | Out-Null
        $held=[IO.File]::Open((Join-Path $f.State 'workflow.lock'),'OpenOrCreate','ReadWrite','None')
        $one=$null; $two=$null
        try {
            $one=Begin-Call 'start-task' (Start-Parameters $f 1 'agent-one' @('src/a.txt'))
            $two=Begin-Call 'start-task' (Start-Parameters $f 2 'agent-two' @('src/b.txt'))
            Start-Sleep -Milliseconds 750
            Assert-True (-not $one.Process.HasExited -and -not $two.Process.HasExited) 'A concurrent command bypassed the held lock.'
        } finally { $held.Dispose() }
        Succeeded (End-Call $one); Succeeded (End-Call $two)
        $registry=Get-Content -Raw -LiteralPath (Join-Path $f.State 'tasks.json') | ConvertFrom-Json -AsHashtable
        Assert-True ($registry.Count -eq 2) 'Concurrent registry write lost a claim.'
        Assert-True ((Test-Path -LiteralPath (Task-Path $f 1)) -and (Test-Path -LiteralPath (Task-Path $f 2))) 'Concurrent task tree missing.'
    }
    Check 'simultaneous duplicate assignment has exactly one winner' {
        $f=New-Fixture
        $one=Begin-Call 'start-task' (Start-Parameters $f 1 'agent-one')
        $two=Begin-Call 'start-task' (Start-Parameters $f 1 'agent-two')
        $r1=End-Call $one; $r2=End-Call $two
        Assert-True (@(@($r1,$r2) | Where-Object Code -EQ 0).Count -eq 1) "Expected exactly one task owner: $($r1.Error) $($r2.Error)"
        $registry=Get-Content -Raw -LiteralPath (Join-Path $f.State 'tasks.json') | ConvertFrom-Json -AsHashtable
        Assert-True ($registry.Count -eq 1) 'Duplicate assignment damaged registry.'
    }
    Check 'missing GitHub CLI is diagnosed without creating a task' {
        $f=New-Fixture; $tools=Join-Path $f.Root 'only-git'; [IO.Directory]::CreateDirectory($tools) | Out-Null
        $gitExe=(Get-Command git -CommandType Application | Select-Object -First 1).Source
        '@echo off', ('"' + $gitExe + '" %*') | Set-Content -LiteralPath (Join-Path $tools 'git.cmd')
        $p=Start-Parameters $f; $p.Remove('Offline')
        Failed (Call 'start-task' $p $tools) "Missing dependency 'gh'"
        Assert-True (-not (Test-Path -LiteralPath (Task-Path $f))) 'Missing gh created a task tree.'
    }
    Check 'failed GitHub authentication is diagnosed before task creation' {
        $f=New-Fixture; $tools=Join-Path $f.Root 'fake-tools'; [IO.Directory]::CreateDirectory($tools) | Out-Null
        '@echo off','echo Not authenticated to github.com 1>&2','exit /b 4' | Set-Content -LiteralPath (Join-Path $tools 'gh.cmd')
        $p=Start-Parameters $f; $p.Remove('Offline')
        Failed (Call 'start-task' $p ($tools + [IO.Path]::PathSeparator + $env:PATH)) 'Not authenticated|gh failed'
        Assert-True (-not (Test-Path -LiteralPath (Task-Path $f))) 'Failed auth created a task tree.'
    }
    Check 'failed tests block committing and preserve changes' {
        $f=New-Fixture; Succeeded (Call 'start-task' (Start-Parameters $f)); $task=Task-Path $f
        'candidate' | Add-Content -LiteralPath (Join-Path $task 'src/a.txt'); $before=Git $task @('rev-parse','HEAD')
        $p=Finish-Parameters $f; $p.TestScript=$failTest; $p.Commit=$true; $p.Message='Must not commit'
        Failed (Call 'finish-task' $p) 'test|7|failed'
        Assert-True ((Git $task @('rev-parse','HEAD')) -ceq $before) 'Failed tests produced a commit.'
        Assert-True ((Git $task @('status','--porcelain')) -match 'src/a.txt') 'Failed test discarded work.'
    }
    Check 'finish dry-run never executes test script or commits' {
        $f=New-Fixture; Succeeded (Call 'start-task' (Start-Parameters $f)); $task=Task-Path $f
        'candidate' | Add-Content -LiteralPath (Join-Path $task 'src/a.txt')
        $marker=Join-Path $f.Root 'test-ran'; $test=Join-Path $f.Root 'side-effect-test.ps1'
        ('[IO.File]::WriteAllText(''' + $marker.Replace("'","''") + ''', ''executed'')') | Set-Content -LiteralPath $test
        $before=Git $task @('rev-parse','HEAD'); $p=Finish-Parameters $f; $p.DryRun=$true; $p.TestScript=$test; $p.Commit=$true; $p.Message='Dry commit'
        $registryBefore=[IO.File]::ReadAllText((Join-Path $f.State 'tasks.json'))
        Succeeded (Call 'finish-task' $p)
        Assert-True (-not (Test-Path -LiteralPath $marker)) 'Dry finish executed the test script.'
        Assert-True ((Git $task @('rev-parse','HEAD')) -ceq $before) 'Dry finish committed.'
        Assert-True ([IO.File]::ReadAllText((Join-Path $f.State 'tasks.json')) -ceq $registryBefore) 'Dry finish changed task registry.'
    }
    Check 'finish refuses tracked and untracked files outside ownership' {
        foreach($outside in @('src/b.txt','outside-new.txt')) {
            $f=New-Fixture; Succeeded (Call 'start-task' (Start-Parameters $f)); $task=Task-Path $f
            'owned change' | Add-Content -LiteralPath (Join-Path $task 'src/a.txt')
            'unowned change' | Add-Content -LiteralPath (Join-Path $task $outside)
            $p=Finish-Parameters $f; $p.Commit=$true; $p.Message='Must not include unowned file'
            Failed (Call 'finish-task' $p) 'ownership|outside|unowned'
            Assert-True ((Git $task @('status','--porcelain')) -match [regex]::Escape($outside)) 'Unowned change was lost.'
        }
    }
    Check 'validated explicit commit contains intended owned change' {
        $f=New-Fixture; Succeeded (Call 'start-task' (Start-Parameters $f)); $task=Task-Path $f
        'candidate' | Add-Content -LiteralPath (Join-Path $task 'src/a.txt')
        $before=Git $task @('rev-parse','HEAD'); $p=Finish-Parameters $f; $p.Commit=$true; $p.Message='Implement fixture task'
        Succeeded (Call 'finish-task' $p)
        Assert-True ((Git $task @('rev-parse','HEAD')) -cne $before) 'Explicit finish did not commit.'
        Assert-True ((Git $task @('show','--format=','--name-only','HEAD')).Trim() -eq 'src/a.txt') 'Commit included unintended files.'
        Assert-True ((Git $task @('status','--porcelain')) -eq '') 'Finished task is unexpectedly dirty.'
    }
    Check 'canceled staged change outside ownership cannot enter an owned commit' {
        $f=New-Fixture; Succeeded (Call 'start-task' (Start-Parameters $f)); $task=Task-Path $f
        $outside=Join-Path $task 'src/b.txt'; $original=[IO.File]::ReadAllBytes($outside)
        'staged outside change' | Set-Content -LiteralPath $outside
        Git $task @('add','--','src/b.txt') | Out-Null
        [IO.File]::WriteAllBytes($outside,$original)
        'owned change' | Add-Content -LiteralPath (Join-Path $task 'src/a.txt')
        Assert-True ((Git $task @('diff','HEAD','--','src/b.txt')) -eq '') 'Fixture must have no net outside diff against HEAD.'
        Assert-True ((Git $task @('diff','--cached','--name-only')) -match 'src/b.txt') 'Fixture staged outside edit missing.'
        $before=Git $task @('rev-parse','HEAD'); $p=Finish-Parameters $f; $p.Commit=$true; $p.Message='Must not include staged outside work'
        Failed (Call 'finish-task' $p) 'ownership|outside'
        Assert-True ((Git $task @('rev-parse','HEAD')) -ceq $before) 'Canceled outside change entered a commit.'
        Assert-True ((Git $task @('diff','--cached','--name-only')) -match 'src/b.txt') 'Refusal discarded outside staged work.'
    }
    Check 'unmerged cleanup is refused and retains branch and worktree' {
        $f=New-Fixture; Succeeded (Call 'start-task' (Start-Parameters $f)); $task=Task-Path $f
        'unmerged' | Add-Content -LiteralPath (Join-Path $task 'src/a.txt')
        Git $task @('add','--','src/a.txt') | Out-Null; Git $task @('commit','-m','Unmerged task') | Out-Null
        $p=@{Repository=$task; ReleaseIssue=1; Owner='agent-one'; ApproveRelease=$true; Cleanup=$true; ApproveCleanup=$true}
        Failed (Call 'agent-status' $p) 'merged|integrat'
        Assert-True (Test-Path -LiteralPath $task) 'Unmerged worktree deleted.'
        Git $f.Repo @('rev-parse','--verify','refs/heads/codex/issue-1-task-1') | Out-Null
    }
    Check 'release requires approval and retains clean task files and branch' {
        $f=New-Fixture; Succeeded (Call 'start-task' (Start-Parameters $f)); $task=Task-Path $f
        $p=@{Repository=$task; ReleaseIssue=1; Owner='agent-one'}
        Failed (Call 'agent-status' $p) 'ApproveRelease|approval'
        $p.ApproveRelease=$true; Succeeded (Call 'agent-status' $p)
        Assert-True (Test-Path -LiteralPath $task) 'Release deleted task worktree.'
        Git $f.Repo @('rev-parse','--verify','refs/heads/codex/issue-1-task-1') | Out-Null
        $registry=Get-Content -Raw -LiteralPath (Join-Path $f.State 'tasks.json') | ConvertFrom-Json -AsHashtable
        Assert-True ($registry['1'].status -eq 'released') 'Released task remains claimed.'
    }
    Check 'dirty cleanup is refused without losing untracked files' {
        $f=New-Fixture; Succeeded (Call 'start-task' (Start-Parameters $f)); $task=Task-Path $f
        'precious' | Set-Content -LiteralPath (Join-Path $task 'untracked.txt')
        $p=@{Repository=$task; ReleaseIssue=1; Owner='agent-one'; ApproveRelease=$true; Cleanup=$true; ApproveCleanup=$true}
        Failed (Call 'agent-status' $p) 'dirty|clean|changes|untracked'
        Assert-True (Test-Path -LiteralPath (Join-Path $task 'untracked.txt')) 'Cleanup lost an untracked file.'
    }
    Check 'approved clean merged cleanup removes only managed task and branch' {
        $f=New-Fixture; Succeeded (Call 'start-task' (Start-Parameters $f)); $task=Task-Path $f
        'merged' | Add-Content -LiteralPath (Join-Path $task 'src/a.txt')
        Git $task @('add','--','src/a.txt') | Out-Null; Git $task @('commit','-m','Merged task') | Out-Null
        Git $f.Repo @('merge','--ff-only','codex/issue-1-task-1') | Out-Null
        $p=@{Repository=$task; ReleaseIssue=1; Owner='agent-one'; ApproveRelease=$true; Cleanup=$true; ApproveCleanup=$true}
        Succeeded (Call 'agent-status' $p)
        Assert-True (-not (Test-Path -LiteralPath $task)) 'Merged task worktree survived approved cleanup.'
        Assert-True ((Git $f.Repo @('branch','--list','codex/issue-1-task-1')) -eq '') 'Merged task branch survived cleanup.'
        Assert-True (Test-Path -LiteralPath (Join-Path $f.Repo 'README.md')) 'Cleanup damaged primary checkout.'
        Assert-True (Test-Path -LiteralPath $f.Origin) 'Cleanup damaged local origin.'
    }
    Check 'ignored payload blocks cleanup even when Git status is clean' {
        $f=New-Fixture; Succeeded (Call 'start-task' (Start-Parameters $f)); $task=Task-Path $f
        'cache/' | Set-Content -LiteralPath (Join-Path $task '.gitignore')
        Git $task @('add','--','.gitignore') | Out-Null; Git $task @('commit','-m','Ignore fixture cache') | Out-Null
        Git $f.Repo @('merge','--ff-only','codex/issue-1-task-1') | Out-Null
        [IO.Directory]::CreateDirectory((Join-Path $task 'cache')) | Out-Null
        'precious ignored payload' | Set-Content -LiteralPath (Join-Path $task 'cache/payload.txt')
        Assert-True ((Git $task @('status','--porcelain')) -eq '') 'Fixture ignored payload appears in ordinary status.'
        $p=@{Repository=$task; ReleaseIssue=1; Owner='agent-one'; ApproveRelease=$true; Cleanup=$true; ApproveCleanup=$true}
        Failed (Call 'agent-status' $p) 'Ignored files'
        Assert-True (Test-Path -LiteralPath (Join-Path $task 'cache/payload.txt')) 'Cleanup lost ignored data.'
    }
    Check 'status dry-run reports managed task without altering registry' {
        $f=New-Fixture; Succeeded (Call 'start-task' (Start-Parameters $f))
        $before=[IO.File]::ReadAllText((Join-Path $f.State 'tasks.json'))
        $r=Call 'agent-status' @{Repository=$f.Repo; DryRun=$true}; Succeeded $r
        Assert-True ($r.Output -match 'agent-one') 'Status omitted task ownership.'
        Assert-True ([IO.File]::ReadAllText((Join-Path $f.State 'tasks.json')) -ceq $before) 'Read-only status altered ownership.'
    }
    Check 'repository installer fills empty skeleton and safely repeats' {
        $f=New-Fixture; $skeleton=Join-Path $f.Repo 'Engineering/skills/start-task'
        [IO.Directory]::CreateDirectory($skeleton) | Out-Null
        [IO.File]::WriteAllText((Join-Path $skeleton 'SKILL.md'),'')
        $p=@{Destination=$f.Repo; DryRun=$true}; Succeeded (Call 'install-workflow' $p)
        Assert-True ((Get-Item -LiteralPath (Join-Path $skeleton 'SKILL.md')).Length -eq 0) 'Dry installer filled skeleton.'
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $f.Repo 'AGENTS.md'))) 'Dry installer wrote root adapter.'
        $p.Remove('DryRun'); Succeeded (Call 'install-workflow' $p)
        Assert-True ((Get-Item -LiteralPath (Join-Path $skeleton 'SKILL.md')).Length -gt 0) 'Installer did not fill empty skill.'
        $before=(Get-FileHash -LiteralPath (Join-Path $f.Repo 'AGENTS.md')).Hash
        Succeeded (Call 'install-workflow' $p)
        Assert-True ((Get-FileHash -LiteralPath (Join-Path $f.Repo 'AGENTS.md')).Hash -ceq $before) 'Repeat installer changed existing matching content.'
    }
    Check 'repository installer preflights conflicts without overwriting user instructions' {
        $f=New-Fixture; $instruction=Join-Path $f.Repo 'CLAUDE.md'
        'Existing user-specific instructions' | Set-Content -LiteralPath $instruction
        $before=[IO.File]::ReadAllText($instruction)
        Failed (Call 'install-workflow' @{Destination=$f.Repo}) 'manual merge|nonempty'
        Assert-True ([IO.File]::ReadAllText($instruction) -ceq $before) 'Installer overwrote user instructions.'
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $f.Repo 'AGENTS.md'))) 'Conflict preflight allowed partial installation.'
    }
    $summary=[ordered]@{ Passed=@($results | Where-Object Result -EQ 'PASS').Count; Failed=@($results | Where-Object Result -EQ 'FAIL').Count; Artifacts=$runRoot; Tests=$results }
    $summary | ConvertTo-Json -Depth 8
    if ($summary.Failed -gt 0) { $KeepArtifacts=$true; exit 1 }
} finally {
    if (-not $KeepArtifacts) {
        # This is only the uniquely created disposable test root, never a caller's repository.
        $resolved=[IO.Path]::GetFullPath($runRoot)
        $parent=[IO.Path]::GetFullPath($TemporaryRoot).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
        if (-not $resolved.StartsWith($parent,[StringComparison]::OrdinalIgnoreCase) -or (Split-Path $resolved -Leaf) -notmatch '^engineering-tests-[0-9a-f]{32}$') { throw "Refusing unsafe fixture cleanup: $resolved" }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    } else { Write-Host "Preserved fixture artifacts: $runRoot" }
}
