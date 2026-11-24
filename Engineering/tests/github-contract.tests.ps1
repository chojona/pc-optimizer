#Requires -Version 7.0
[CmdletBinding()]
param([string]$TemporaryRoot = [IO.Path]::GetTempPath(), [switch]$KeepArtifacts)

# Exercise GitHub-facing paths without network, real credentials, or global configuration.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$scripts = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\scripts'))
$pwsh = (Get-Process -Id $PID).Path
$compiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'Contract fixtures require %WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe. No fixtures or system changes were created.' }
$runRoot = Join-Path ([IO.Path]::GetFullPath($TemporaryRoot)) ('github-contract-tests-' + [guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($runRoot) | Out-Null
$results = [Collections.Generic.List[object]]::new()
$script:fixtureNumber = 0
$script:callNumber = 0
$runner = Join-Path $runRoot 'invoke.ps1'
@'
param([string]$Script, [string]$ParametersFile)
$parameters = Get-Content -Raw -LiteralPath $ParametersFile | ConvertFrom-Json -AsHashtable
try { & $Script @parameters; exit $LASTEXITCODE }
catch { Write-Error $_ -ErrorAction Continue; exit 1 }
'@ | Set-Content -LiteralPath $runner
$stub = Join-Path $runRoot 'GhFixture.cs'
@'
using System;
class GhFixture {
  static int Fail(string message, int code) { Console.Error.WriteLine(message); return code; }
  static int Main(string[] args) {
    string scenario = Environment.GetEnvironmentVariable("WORKFLOW_GITHUB_FIXTURE");
    string verb = args.Length > 0 ? args[0] : "";
    string sub = args.Length > 1 ? args[1] : "";
    string endpoint = args.Length > 0 ? args[args.Length - 1] : "";
    if (verb == "auth") return scenario == "auth-failure" ? Fail("Fixture: GitHub authentication missing",4) : 0;
    if (verb == "issue" && sub == "view") {
      Console.WriteLine("{\"number\":1,\"title\":\"Fixture task\",\"body\":\"Implement owned file; no dependencies.\",\"url\":\"https://github.com/example/fixture/issues/1\",\"state\":\"OPEN\",\"assignees\":[]}"); return 0;
    }
    if (verb == "api" && endpoint.Contains("/pulls?")) {
      if (scenario == "renamed-overlap") Console.WriteLine("[[{\"number\":2,\"head\":{\"ref\":\"first\",\"repo\":{\"full_name\":\"example/fixture\"}}}],[{\"number\":3,\"head\":{\"ref\":\"second\",\"repo\":{\"full_name\":\"example/fixture\"}}}]]");
      else if (scenario == "wrong-existing-body") Console.WriteLine("[[{\"number\":7,\"head\":{\"ref\":\"codex/issue-1-fixture\",\"repo\":{\"full_name\":\"example/fixture\"}},\"base\":{\"ref\":\"main\"},\"body\":\"Closes unrelated/project#1\",\"html_url\":\"https://github.com/example/fixture/pull/7\"}]]");
      else Console.WriteLine("[[]]"); return 0;
    }
    if (verb == "api" && endpoint.Contains("/pulls/2/files?")) { Console.WriteLine("[[{\"filename\":\"unrelated.txt\"}]]"); return 0; }
    if (verb == "api" && endpoint.Contains("/pulls/3/files?")) { Console.WriteLine("[[{\"filename\":\"renamed.txt\",\"previous_filename\":\"owned.txt\"}]]"); return 0; }
    if (verb == "pr" && sub == "create") { Console.WriteLine("https://github.com/example/fixture/pull/7"); return 0; }
    if (verb == "project" && sub == "item-edit") return scenario == "project-denied" ? Fail("Fixture: missing project write permission",5) : 0;
    return Fail("Unexpected fixture gh call: " + String.Join(" ",args),9);
  }
}
'@ | Set-Content -LiteralPath $stub
$tools = Join-Path $runRoot 'tools'
[IO.Directory]::CreateDirectory($tools) | Out-Null
# Use a native executable so Windows cmd metacharacters never reinterpret API arguments.
# Windows supplies this .NET Framework compiler; no package or system installation occurs.
& $compiler /nologo /target:exe ("/out:" + (Join-Path $tools 'gh.exe')) $stub
if ($LASTEXITCODE -ne 0) { throw 'Could not build the temporary native GitHub CLI fixture.' }
$testScript = Join-Path $runRoot 'pass.ps1'
'exit 0' | Set-Content -LiteralPath $testScript
$bodyFile = Join-Path $runRoot 'pr-body.md'
'Implement the fixture acceptance criteria. Closes #1' | Set-Content -LiteralPath $bodyFile

function Assert-True([bool]$Value, [string]$Message) { if (-not $Value) { throw $Message } }
function Git([string]$Repository, [string[]]$Arguments) {
    $output = & git.exe -C $Repository @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Fixture git failed: $($Arguments -join ' ')`n$($output -join "`n")" }
    $output -join "`n"
}
function Call([string]$Name, [hashtable]$Parameters, [string]$Scenario = 'happy') {
    $script:callNumber++
    $parameterFile = Join-Path $runRoot "parameters-$script:callNumber.json"
    $Parameters | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $parameterFile
    $info = [Diagnostics.ProcessStartInfo]::new($pwsh)
    $info.UseShellExecute = $false; $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true; $info.RedirectStandardError = $true
    $info.Environment['PATH'] = $tools + [IO.Path]::PathSeparator + $env:PATH
    $info.Environment['WORKFLOW_GITHUB_FIXTURE'] = $Scenario
    foreach ($argument in @('-NoProfile','-NonInteractive','-File',$runner,'-Script',(Join-Path $scripts "$Name.ps1"),'-ParametersFile',$parameterFile)) { $info.ArgumentList.Add($argument) }
    $process = [Diagnostics.Process]::Start($info)
    $output = $process.StandardOutput.ReadToEndAsync(); $errorOutput = $process.StandardError.ReadToEndAsync()
    try {
        if (-not $process.WaitForExit(45000)) { $process.Kill($true); throw 'Fixture process timed out.' }
        [pscustomobject]@{ Code=$process.ExitCode; Output=$output.GetAwaiter().GetResult(); Error=$errorOutput.GetAwaiter().GetResult() }
    } finally { $process.Dispose() }
}
function Succeeded($Result) { Assert-True ($Result.Code -eq 0) "Expected success: $($Result.Error) $($Result.Output)" }
function Failed($Result, [string]$Pattern) {
    Assert-True ($Result.Code -ne 0) "Expected refusal: $($Result.Output)"
    Assert-True (($Result.Error + $Result.Output) -match ('(?s)' + $Pattern)) "Missing diagnostic '$Pattern': $($Result.Error) $($Result.Output)"
}
function New-Fixture {
    $script:fixtureNumber++
    $root = Join-Path $runRoot "fixture-$script:fixtureNumber"
    $repository = Join-Path $root 'repository'; $origin = Join-Path $root 'origin.git'
    [IO.Directory]::CreateDirectory($repository) | Out-Null
    Git $root @('init','--bare','--initial-branch=main',$origin) | Out-Null
    Git $repository @('init','--initial-branch=main') | Out-Null
    Git $repository @('config','user.name','Workflow Fixture') | Out-Null
    Git $repository @('config','user.email','fixture@example.invalid') | Out-Null
    Git $repository @('config','commit.gpgsign','false') | Out-Null
    $hooks = Join-Path $root 'empty-hooks'; [IO.Directory]::CreateDirectory($hooks) | Out-Null
    Git $repository @('config','core.hooksPath',$hooks) | Out-Null
    'baseline' | Set-Content -LiteralPath (Join-Path $repository 'owned.txt')
    Git $repository @('add','owned.txt') | Out-Null
    Git $repository @('commit','-m','Fixture baseline') | Out-Null
    Git $repository @('remote','add','origin','https://github.com/example/fixture.git') | Out-Null
    # Git expands this rewrite only for transport; the workflow still sees a GitHub origin.
    $localUrl = $origin.Replace('\','/')
    Git $repository @('config',"url.$localUrl.insteadOf",'https://github.com/example/fixture.git') | Out-Null
    Git $repository @('push','origin','main') | Out-Null
    [pscustomobject]@{ Root=$root; Repository=$repository; Origin=$origin; Worktrees=(Join-Path $root 'worktrees'); State=(Join-Path $repository '.git/engineering-workflow') }
}
function Start-Parameters($Fixture) {
    @{ Repository=$Fixture.Repository; Issue=1; Slug='fixture'; Owner='fixture-agent'; Files=@('owned.txt'); WorktreeRoot=$Fixture.Worktrees }
}
function Task-Path($Fixture) { Join-Path $Fixture.Worktrees 'issue-1-fixture' }
function Finish-Parameters($Fixture) {
    @{ Repository=(Task-Path $Fixture); Issue=1; Owner='fixture-agent'; Files=@('owned.txt'); TestScript=$testScript; Commit=$true; Message='Implement fixture'; Publish=$true; Title='Implement fixture'; BodyFile=$bodyFile }
}
function Registry($Fixture) { Get-Content -Raw -LiteralPath (Join-Path $Fixture.State 'tasks.json') | ConvertFrom-Json -AsHashtable }
function Check([string]$Name, [scriptblock]$Body) {
    try { & $Body; $results.Add([pscustomobject]@{ Name=$Name; Result='PASS' }); Write-Host "PASS $Name" }
    catch { $results.Add([pscustomobject]@{ Name=$Name; Result='FAIL'; Error=$_.Exception.Message }); Write-Host "FAIL $Name`: $($_.Exception.Message)" }
}

try {
    Check 'online dry-run reads empty PR pages without mutations' {
        $f=New-Fixture; $p=Start-Parameters $f; $p.DryRun=$true
        $before=Git $f.Repository @('show-ref'); $r=Call 'start-task' $p; Succeeded $r
        Assert-True ($r.Output -match 'Fixture task') 'Issue details missing.'
        Assert-True (-not (Test-Path -LiteralPath $f.State)) 'Dry-run wrote ownership metadata.'
        Assert-True ((Git $f.Repository @('show-ref')) -ceq $before) 'Dry-run changed refs.'
    }
    Check 'second PR page renamed-file ownership overlap is refused' {
        $f=New-Fixture; $p=Start-Parameters $f; $p.DryRun=$true
        Failed (Call 'start-task' $p 'renamed-overlap') 'Open PR #3 overlaps'
        Assert-True (-not (Test-Path -LiteralPath $f.State)) 'Refused dry-run wrote metadata.'
    }
    Check 'native GitHub authentication failure blocks online start' {
        $f=New-Fixture
        Failed (Call 'start-task' (Start-Parameters $f) 'auth-failure') 'authentication missing'
        Assert-True (-not (Test-Path -LiteralPath (Task-Path $f))) 'Authentication failure created a task worktree.'
    }
    Check 'publish commits pushes locally and records focused PR for review' {
        $f=New-Fixture; Succeeded (Call 'start-task' (Start-Parameters $f))
        $task=Task-Path $f; 'implementation' | Add-Content -LiteralPath (Join-Path $task 'owned.txt')
        $r=Call 'finish-task' (Finish-Parameters $f); Succeeded $r
        Assert-True ($r.Output -match 'https://github.com/example/fixture/pull/7') 'PR URL missing.'
        $registry=Registry $f
        Assert-True ($registry['1'].status -eq 'review') 'Publication failed to reserve review ownership.'
        Assert-True ($registry['1'].owner -eq 'fixture-agent') 'Publication changed ownership.'
        Assert-True ((Git $f.Origin @('rev-parse','refs/heads/codex/issue-1-fixture')) -ceq (Git $task @('rev-parse','HEAD'))) 'Local bare origin did not receive task commit.'
        Assert-True ((Git $f.Origin @('show','refs/heads/codex/issue-1-fixture:owned.txt')) -match 'implementation') 'Published content differs from implementation.'
    }
    Check 'existing PR with wrong issue body blocks push' {
        $f=New-Fixture; Succeeded (Call 'start-task' (Start-Parameters $f))
        'candidate' | Add-Content -LiteralPath (Join-Path (Task-Path $f) 'owned.txt')
        Failed (Call 'finish-task' (Finish-Parameters $f) 'wrong-existing-body') "PR body must resolve"
        Assert-True ((Git $f.Origin @('for-each-ref','--format=%(refname)','refs/heads/codex/issue-1-fixture')) -eq '') 'Wrong-issue PR allowed remote push.'
        Assert-True ((Registry $f)['1'].status -eq 'active') 'Wrong-issue PR changed task status.'
    }
    Check 'Project permission failure reports pending and preserves published task' {
        $f=New-Fixture; Succeeded (Call 'start-task' (Start-Parameters $f))
        'candidate' | Add-Content -LiteralPath (Join-Path (Task-Path $f) 'owned.txt')
        $p=Finish-Parameters $f
        $p.UpdateProject=$true; $p.ProjectId='PVT_fixture'; $p.ProjectItemId='PVTI_fixture'; $p.StatusFieldId='PVTSSF_fixture'; $p.StatusOptionId='review-option'
        $r=Call 'finish-task' $p 'project-denied'; Succeeded $r
        Assert-True ($r.Output -match 'pending' -and ($r.Output + $r.Error) -match 'permission') 'Missing Project write permission did not produce actionable pending status.'
        Assert-True ((Registry $f)['1'].status -eq 'review') 'Project failure lost published task status.'
        Git $f.Origin @('rev-parse','refs/heads/codex/issue-1-fixture') | Out-Null
    }
    $summary=[ordered]@{ Passed=@($results | Where-Object Result -EQ 'PASS').Count; Failed=@($results | Where-Object Result -EQ 'FAIL').Count; Tests=$results }
    $summary | ConvertTo-Json -Depth 8
    if ($summary.Failed) { $KeepArtifacts=$true; exit 1 }
} finally {
    if ($KeepArtifacts) { Write-Host "Preserved fixture artifacts: $runRoot" }
    else {
        $resolved=[IO.Path]::GetFullPath($runRoot)
        $parent=[IO.Path]::GetFullPath($TemporaryRoot).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
        if (-not $resolved.StartsWith($parent,[StringComparison]::OrdinalIgnoreCase) -or (Split-Path $resolved -Leaf) -notmatch '^github-contract-tests-[0-9a-f]{32}$') { throw "Unsafe fixture cleanup target: $resolved" }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
