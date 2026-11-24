# Personal engineering workflow for Windows

Use GitHub Issues to define work, one isolated Git worktree per implementation task, and focused pull requests to integrate changes. Codex, Cursor, and Claude Code share the engineering rules and skill procedures in this bundle. No global configuration changes are needed for repository use.

Read [the shared engineering rules](ENGINEERING.md), [the architecture](ARCHITECTURE.md), and [the discovery report](DISCOVERY.md). The discovery report includes proposed global locations; none was installed.

## Mandatory end-of-session protocol

Every session that changes a repository must finish seven steps before it stops: review the complete diff, run the relevant checks and report their actual results, commit, push the task's own branch, create or update exactly one pull request, update the issue and Project board status, and hand off. Completed work whose checks pass is ready for review; unfinished work or failing checks publish a draft pull request documenting the blockers under a `## Blockers` heading. A session with no repository changes hands off and creates no pull request. The canonical definition, including the standing authorization it rests on and what it still does not authorize, is in [the shared engineering rules](ENGINEERING.md#end-every-session-with-the-mandatory-protocol).

`finish-task.ps1` performs the protocol and records what it did. `end-session.ps1` validates it read-only and exits nonzero while any step is unrecorded:

```powershell
& "$scripts\end-session.ps1" -Repository $task -Issue 42 -Owner codex-parser-a
```

Git establishes the change, commit, and push facts. Review, test, publication, issue, and handoff steps are attestations recorded by `finish-task.ps1`, so a `pending` step means "not recorded here", not proof that the step was skipped — and never a reason to claim it was done. Editing the worktree after validation invalidates the review and test attestations for the new head, which the validator reports. No agent enforces the protocol automatically at session end; each one follows it from its instruction adapter, and anything the scripts could not verify belongs in the handoff. `-ReportOnly` prints the same report with exit code 0 for coordination use, and `agent-status.ps1` summarizes each claimed task's pending steps.

## Requirements and first use

Use PowerShell 7 (`pwsh`) and Git for Windows. GitHub operations additionally require GitHub CLI (`gh`), an authenticated account, and the repository/project permissions needed for the requested operation. The workflow does not install dependencies, authenticate accounts, grant scopes, alter execution policy, or change Windows settings.

From the repository root, inspect prerequisites without printing tokens:

```powershell
Get-Command git, pwsh, gh -ErrorAction SilentlyContinue
git --version
pwsh --version
git status --short
git worktree list --porcelain
git remote -v
gh auth status
```

If a command is missing, install it separately after approving the installation. If `gh auth status` fails, complete `gh auth login` yourself. A Git credential helper and a connected agent GitHub account do not establish CLI authentication. Do not run `gh auth token` for diagnostics. Check the actual repository and project before requesting additional permission; a fine-grained token may have different permissions from a classic OAuth scope.

Commit the reviewed infrastructure into a project's base branch before opening task worktrees from that branch, so new worktrees contain the instructions and scripts. Until integration, inspect and test this isolated infrastructure worktree directly; creating a task from an older base will not copy uncommitted infrastructure into it.

Open an agent session in the task worktree itself. Never point several implementation agents at the main checkout. Review-only agents may inspect an existing task read-only without becoming its implementation owner.

## Repository instruction and skill locations

All paths below are relative to the repository root. The repository installation destination is `C:\Users\johnn\Desktop\pc_optimizer`; the isolated development and validation worktree is `C:\Users\johnn\Desktop\pc_optimizer\data\engineering-workflow`. This same directory layout travels with future projects.

| Path | Meaning |
| --- | --- |
| `Engineering/ENGINEERING.md` | Canonical reusable rules |
| `AGENTS.md` | Codex/Cursor entrypoint; keep project-specific content here or in more specific instruction files |
| `CLAUDE.md` | Claude-specific native import and project guidance |
| `.cursor/rules/engineering.mdc` | Always-applied Cursor reference |
| `Engineering/AGENTS.md` | Infrastructure-specific instructions |
| `Engineering/skills/<skill>/SKILL.md` | Canonical skill procedure |
| `.agents/skills/<skill>/SKILL.md` | Codex/Cursor discovery wrappers |
| `.claude/skills/<skill>/SKILL.md` | Claude discovery wrappers |
| `Engineering/scripts/` | PowerShell automation, including `end-session.ps1` protocol validation |

Global instruction and skill locations differ by agent. See the exact paths and preservation plan in [DISCOVERY.md](DISCOVERY.md#proposed-global-locations--not-installed). There is no assumed shared global `AGENTS.md` or `SKILL.md` convention.

## Invoke the skills

Type these in the agent chat, not in PowerShell:

| Task | Codex | Cursor Agent | Claude Code |
| --- | --- | --- | --- |
| Start an issue | `$start-task` | `/start-task` | `/start-task` |
| Review a pull request | `$review-pr` | `/review-pr` | `/review-pr` |
| Measure performance | `$benchmark` | `/benchmark` | `/benchmark` |
| Validate and publish | `$finish-task` | `/finish-task` | `/finish-task` |
| Explain the implementation | `$learn` | `/learn` | `/learn` |

Invoke the finish skill at the end of every session that changed the repository, including an unfinished one.

Include issue/repository, a unique owner session, scope, and constraints with the request. For example: “`$start-task` for issue 42 in this repository; owner `codex-parser-a`; own `src/parser` and `tests/parser`; use `main` as base.” The skill still checks the issue's acceptance criteria and overlaps before implementation. Explicit invocation syntax and discovery sources are recorded in [DISCOVERY.md](DISCOVERY.md#verified-discovery-mechanisms).

Start a fresh agent session if skills do not appear. Verify the selected skill's path when multiple same-named skills are installed. Cursor can see both the shared and Claude compatibility wrappers; both route to the same canonical procedure. Do not create another `.cursor/skills` copy just to duplicate them.

## Parallel development example

Define three small GitHub issues with acceptance criteria. Let issue 41 own a shared data contract, issue 42 depend on that contract and own parser code, and issue 43 depend on it and own UI code. The contract owner first documents/lands the API or supplies an explicitly agreed dependency branch. A dependency is never assumed to be available just because it appears in another worktree.

After the contract is available on the intended base, start independent tasks from the coordinator checkout. Use a distinct owner per running agent session:

```powershell
$repo = 'C:\Projects\MyApp'
$scripts = Join-Path $repo 'Engineering\scripts'
& "$scripts\start-task.ps1" -Repository $repo -Issue 42 -Slug parser `
  -Owner codex-parser-a -Files @('src/parser', 'tests/parser') -Base main -DryRun
& "$scripts\start-task.ps1" -Repository $repo -Issue 42 -Slug parser `
  -Owner codex-parser-a -Files @('src/parser', 'tests/parser') -Base main
& "$scripts\start-task.ps1" -Repository $repo -Issue 43 -Slug results-ui `
  -Owner cursor-ui-b -Files @('src/ui', 'tests/ui') -Base main
& "$scripts\agent-status.ps1" -Repository $repo
```

Use the returned worktree paths to open Codex and Cursor. A third agent can review the actual PR diff read-only. A reviewer must not stage, commit, or take ownership of another agent's worktree. Run `$learn` or `/learn` after implementation to explain the files, architecture, trade-offs, three interview questions, and a practical exercise.

Default branches are `codex/issue-<number>-<slug>`, regardless of the agent product. The default worktree root is a sibling of the main checkout named `.<repository-name>-worktrees`; use `-WorktreeRoot` to choose another approved location. Script output includes the exact branch, path, base commit, owner, and plan. Never assume the output path is writable by the current agent sandbox: present a concrete location and obtain permission if the tool requires it.

Claim directory prefixes or explicit files, not vague labels such as “backend.” If both tasks need the same dependency manifest, lockfile, migration, generated file, or interface, stop and assign that change to one owner. Expand scope only after updating coordination and checking overlaps.

Reuse requires the same issue, slug, base, owner, location, and claims. A different owner cannot adopt a worktree, and an unregistered existing branch is not reset or adopted automatically. Ownership claims remain active through review; they do not expire with time or a missing process. A changed scope or ownership transfer needs explicit coordination and a reviewed registry update under the same lock. There is no automatic takeover or claim-expansion command.

## Offline planning and authorization

`start-task.ps1 -Offline` supports deliberate local preparation when GitHub is unavailable. It uses a local base rather than claiming a fresh remote base or verified issue. The agent must record that issue/dependency/PR checks were skipped and complete them before publication. Offline mode does not silently replace a failed online check.

`-DryRun` previews intended operations without creating a task, updating ownership, fetching refs, staging, committing, pushing, creating a PR, or changing a Project. Read-only inspections may still require dependencies and permissions. It is not a substitute for executing the real checks later.

The finish skill verifies acceptance criteria and reviews the final diff. A repository test script must return a nonzero exit code on failure. Prefer a checked-in script that runs the repository's established test/lint/typecheck commands; do not pass untrusted issue text as executable code. Local completion and publication are separate choices. Publication requires explicit authorization for commit/push/PR actions; merging always requires separate approval.

## Finish and hand off

Review the trusted project test script before running it. It executes in a separate PowerShell 7 process with the task worktree as its working directory. For a repository using Python's unittest runner, a minimal test script is:

```powershell
$ErrorActionPreference = 'Stop'
& python -m unittest discover -s tests
exit $LASTEXITCODE
```

Adapt the command to the project's actual runner. If there are multiple native commands, check each exit code and stop on the first failure; a later successful command must not mask an earlier failed test. Keep temporary output ignored and inspect generated files after the checks.

Use the exact path returned by start-task. The default finish operation validates without staging or committing. `-Files` must cover all changed paths, and every changed or already-committed task path must fit the task's ownership claims:

```powershell
$task = 'C:\Projects\.MyApp-worktrees\issue-42-parser'
$checks = Join-Path $task 'tests\run-checks.ps1' # Reviewed project-owned script
& "$scripts\finish-task.ps1" -Repository $task -Issue 42 -Owner codex-parser-a `
  -Files @('src/parser', 'tests/parser') -TestScript $checks -Offline -DryRun
& "$scripts\finish-task.ps1" -Repository $task -Issue 42 -Owner codex-parser-a `
  -Files @('src/parser', 'tests/parser') -TestScript $checks -Offline
```

After reviewing the actual unstaged/staged diff and acceptance evidence, commit with `-Commit -Message 'Implement parser acceptance criteria'`. To publish, remove `-Offline` and supply `-Publish -Title 'Implement parser validation' -BodyFile 'C:\Temp\issue-42-pr.md'` together with `-Commit -Message ...`. The reviewed body file should describe behavior, acceptance criteria, exact checks, limitations, and `Closes #42`. Add `-CommentIssue -HandoffFile 'C:\Temp\issue-42-handoff.md'` to update the issue, and `-UpdateProject` with verified IDs for the board. Record a genuinely unsupported update with `-SkipIssueUpdate` or `-SkipProjectUpdate` plus `-LimitationNote '<reason>'` instead of implying it happened.

For unfinished work, add `-Draft`; for failing checks add `-AllowTestFailure` as well. A draft body must reference the issue without a closing keyword and list concrete blockers under a `## Blockers` heading, or the script refuses it. `-AllowTestFailure` records the real failure output as an evidence log and reports `testStatus: failed`; it never turns a failure into a pass. Without `-Publish` the failing work is still committed and the failure recorded, so an offline or unauthenticated session preserves it. The script updates the branch's existing open pull request, including its draft state, instead of creating a duplicate, publishes nothing for a session with no commits, and never merges. Failed pushes/PR creation preserve the local branch and commits for a safe retry.

The skill's handoff includes the issue/PR, key files and functions, tests/results, interface changes, evidence for performance claims, educational notes, remaining risks, and the next reviewer action. The script's JSON output is an operation record, not a substitute for engineering review.

## Status, release, and cleanup

`agent-status.ps1 -Repository $repo` reports linked worktrees, dirty state, task claims, branches, and CLI availability. Its snapshot does not establish GitHub authentication or semantic conflict freedom. `-DryRun` avoids state changes; an ordinary status read takes the existing coordination lock for a consistent snapshot. If Git cannot inspect a listed worktree, its `dirty` value is `null` and `inspectionError` explains the failure; unknown state must not be treated as clean. A Git ownership/trust failure does not cause the script to add a global `safe.directory` setting.

Only after human approval, release a clean task claim with the exact owner. Release without cleanup preserves its worktree and branch, even when unmerged:

```powershell
& "$scripts\agent-status.ps1" -Repository $repo -ReleaseIssue 42 `
  -Owner codex-parser-a -ApproveRelease -DryRun
& "$scripts\agent-status.ps1" -Repository $repo -ReleaseIssue 42 `
  -Owner codex-parser-a -ApproveRelease
```

For separately approved cleanup, add `-Cleanup -ApproveCleanup`. That mode removes the registered worktree and uses `git branch -d` to delete its branch only after checking that the branch is an ancestor of the local base. It refuses dirty or unmerged work and never uses force. Fetching `origin/main` does not advance the local `main` branch; update/integrate the local base deliberately before cleanup. Do not switch or merge it underneath another task. Squash/rebase integration may fail this conservative ancestry check; inspect and preserve those branches for manual handling.

Inspect ignored files and the absolute target path before approving deletion. The approval flags record an approval already given by the user; agents must not invent approval by setting them. See [the recovery rules](ARCHITECTURE.md#recovery-and-safe-cleanup).

## Run the workflow validation

From the infrastructure worktree, use:

```powershell
pwsh -NoProfile -File .\Engineering\tests\workflow.tests.ps1
pwsh -NoProfile -File .\Engineering\tests\session-protocol.tests.ps1
pwsh -NoProfile -File .\Engineering\tests\github-contract.tests.ps1
```

The session-protocol suite covers completed, incomplete, interrupted, failed, and no-change sessions, stale review and test attestations, unmanaged worktrees, coordinator reporting, and whether every agent adapter and skill still exposes the protocol. The first two suites also run in this repository's CI; the contract suite stays local because it needs the Windows .NET Framework compiler.

The suite uses temporary repositories to exercise isolation, ownership, failures, concurrent callers, dry runs, and cleanup. It does not require a live GitHub account or modify another project's repository. CLI simulations establish local error/coordination behavior; authenticated GitHub permissions and actual remote publication still need a deliberate integration check after `gh` is installed and authenticated. Preserve a failed test fixture for diagnosis when the suite reports its path.

The GitHub contract suite simulates CLI responses and rewrites Git transport to a disposable local bare origin. It verifies pagination, authentication failures, local push/PR coordination, issue linkage, and denied Project updates without contacting GitHub. See [the validation record](VALIDATION.md) for observed results and limits.

That optional suite builds a temporary native CLI fixture with `%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe`; it reports a missing compiler before creating fixtures. The workflow scripts and main 24-case suite do not require this compiler. Nothing is installed automatically.

## GitHub Projects coordination

Keep issue dependencies and ownership visible in GitHub. Updating Projects is optional and authorized separately; project IDs and status values are never guessed. Identify the exact project, issue item, status field, and status option, then inspect CLI support:

```powershell
gh project list --owner OWNER --format json
gh project field-list PROJECT_NUMBER --owner OWNER --format json
gh project item-list PROJECT_NUMBER --owner OWNER --format json
gh project item-edit --help
```

For an authorized update, the stable machine-oriented form uses the verified IDs:

```powershell
gh project item-edit --id ITEM_ID --project-id PROJECT_ID `
  --field-id STATUS_FIELD_ID --single-select-option-id STATUS_OPTION_ID
```

The scripts expose the same operation through `-UpdateProject -ProjectId PROJECT_ID -ProjectItemId ITEM_ID -StatusFieldId STATUS_FIELD_ID -StatusOptionId STATUS_OPTION_ID`. Supplying these switches is an explicit request to update that item; inspect IDs first. A rejected Project update is reported as pending without discarding a successfully created local task.

Use an “in progress” option after a successful start and a “review” option after a PR is open. Do not mark a task done merely because a PR exists. Report a missing `gh`, authentication failure, unsupported Projects command, or missing permission with the exact blocked operation. Do not grant scopes or alter tokens automatically. See [GitHub CLI Projects documentation](https://cli.github.com/manual/gh_project_item-edit).

## Install into another repository

For a future user-approved installation, first run the integration tests in this bundle. Then create a dedicated worktree in the target project, inspect its instruction hierarchy and existing skills, and install only reviewed infrastructure. The installer accepts an explicit target Git root, so it does not search for or modify other projects.

Use the installer from the reviewed source bundle. The destination must be the exact Git repository/worktree root, not a child folder. Preview first:

```powershell
$bundleRoot = 'C:\Users\johnn\Desktop\pc_optimizer\data\engineering-workflow'
$targetRoot = 'C:\Projects\MyApp'
& "$bundleRoot\Engineering\scripts\install-workflow.ps1" -Destination $targetRoot -DryRun
& "$bundleRoot\Engineering\scripts\install-workflow.ps1" -Destination $targetRoot
```

The installer copies `Engineering`, `.agents/skills`, `.claude/skills`, and the root instruction adapters. Missing files and empty placeholders may be populated; identical files are left alone. Any differing nonempty destination file aborts the entire preflight before copying. Target file links and directory junctions/reparse points are refused. Run installation without concurrent edits to these destination paths. A failure during copying may leave partial new files; inspect the reported paths and rerun rather than deleting existing content. No global configuration is installed, and installation does not commit the result.

For repositories with existing instructions or skill names, merge the changes manually in the reviewed target worktree. Preserve root `AGENTS.md` and add a direction to read `Engineering/ENGINEERING.md`; preserve `CLAUDE.md` and add `@Engineering/ENGINEERING.md`; manually merge the supplied `.cursor/rules/engineering.mdc`. Retain all repository-specific build, test, architectural, and safety instructions. Inspect nested instruction files before modifying their scope. Resolve same-named existing skills deliberately rather than overwriting them. The strict installer is intentionally not an automatic configuration merger.

Keep the bundle in version control. Port upgrades through focused changes with the workflow's integration tests; do not auto-sync a global directory into active projects. Before approving a global setup, review [the proposed installation locations](DISCOVERY.md#proposed-global-locations--not-installed) and adapt wrappers to absolute global paths.

## Operational limits

Ownership protects cooperating scripts in one clone. Cross-machine coordination requires GitHub, and semantic interface conflicts require engineering judgment. Dirty unrelated worktrees are preserved; tests/builds in a task may need their own dependencies, ports, secrets, and data. No credentials are copied into worktrees. Git hooks and test scripts are project code and should be reviewed before execution. Project permissions, status field names, and GitHub availability can vary.

Cleanup is separately approved and opt-in through the status script. Keep unmerged branches and failed task evidence. Follow the verification steps in [safe cleanup](ARCHITECTURE.md#recovery-and-safe-cleanup); never use forced worktree removal or branch deletion to recover from an ownership conflict.
