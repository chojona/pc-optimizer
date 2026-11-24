# Validation record

Validated on 2026-11-24 using Git for Windows 2.56.0 and PowerShell 7.6.9. Tests ran against newly created disposable repositories and local bare origins before installing the bundle into the existing project. No live GitHub issues, Projects, PRs, or unrelated repositories were changed.

## Repository automation

```powershell
pwsh -NoProfile -File .\Engineering\tests\workflow.tests.ps1
```

Result: **24 passed, 0 failed**, exit code 0.

Coverage includes clean and dirty repositories; preservation of unrelated changes; same-owner dirty worktree reuse; duplicate owners; file/directory and case-insensitive ownership conflicts; unmanaged branches/worktrees; actual concurrent independent and duplicate starts; exclusive-lock contention; missing CLI/authentication; failed tests preventing commits; dry runs without execution or workflow state; tracked/untracked ownership; explicit commits; staged changes canceled in the working copy; unmerged, dirty, and ignored-file cleanup refusals; approved release and merged cleanup; status snapshots; empty-skeleton installation, idempotence, and preserving nonempty instructions.

The successful run removed its own disposable fixtures. Diagnosed failed-run fixtures were also removed after validating their exact GUID-named paths beneath the temporary directory. Real development worktrees were preserved.

## End-of-session protocol

```powershell
pwsh -NoProfile -File .\Engineering\tests\session-protocol.tests.ps1
```

Result on 2026-11-24 with PowerShell 7.7.0: **11 passed, 0 failed**, exit code 0.

Coverage includes a completed session reporting every step satisfied; a failed session refusing to commit and refusing a ready-for-review publication while preserving in-progress work; a failed session committing with the real failure output retained as evidence and reaching `documented-failure` only once a draft pull request exists; an incomplete session with uncommitted work naming the uncommitted file; an interrupted session keeping its commit and reporting the unpushed branch and missing pull request; later edits invalidating an earlier review and test attestation; a session with no repository changes requiring no pull request; refusal to validate under another owner or from another worktree; an unmanaged worktree reported as unverified rather than complete, with `-ReportOnly` keeping the pending list; coordinator status surfacing each claimed task's pending steps; and a discovery check that `AGENTS.md`, `CLAUDE.md`, `.cursor/rules/engineering.mdc`, the canonical rules, and all six start/finish skill files still expose the protocol.

The first two suites now also run in CI as the `Engineering workflow and session protocol` job. Publication itself is not exercised offline: the draft pull request, pull request reuse, issue comment, and empty-session cases are in the GitHub contract suite below.

## Instructions and skills

All 15 canonical/discovery `SKILL.md` files passed checks for frontmatter delimiters, matching names, descriptions, bodies, and relative reference targets. PowerShell source files passed parser checks. The bundled skill validator was attempted but could not execute because its Python environment lacks PyYAML; no dependency was installed to change the machine. Official agent documentation links and observed tool availability are recorded in [DISCOVERY.md](DISCOVERY.md).

## GitHub-facing contract checks

```powershell
pwsh -NoProfile -File .\Engineering\tests\github-contract.tests.ps1
```

Result on 2026-11-24: **10 passed, 0 failed**, exit code 0. The suite verified online dry-run reads without mutations; paginated PR ownership conflicts including renamed paths; authentication refusal; actual commit and push to a local bare origin with a simulated PR URL and retained review claim; refusal to reuse a PR that does not reference this repository's issue; denied Project permission reported as pending without losing successful publication or leaking the failed API exit code; failing checks published only as a draft pull request, refused without `-Draft`, refused without a `## Blockers` section, refused with a closing keyword, and then pushed and recorded as `testStatus: failed` with preserved evidence; an existing pull request updated and marked ready for review instead of duplicated, with the issue commented; a denied issue comment reported as pending without claiming an update; and a session with no commits touching no pull request, branch, or review status.

Only this optional suite needs the existing Windows .NET Framework compiler at `%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe` to build a temporary native CLI stub. Its missing-compiler diagnostic was also checked: it fails before creating fixtures. No compiler or package was installed. Successful and diagnosed failed contract fixtures were cleaned safely. GitHub responses were simulated; Git transport was rewritten only in each disposable repository's configuration.

## Independent review

An independent review reproduced and led to regression coverage for canceled staged changes bypassing ownership, scalar path concatenation in PowerShell, and Windows slash normalization during worktree reuse. PR validation also now checks the exact repository/issue and the actual body of an existing PR. Contract tests found and verified fixes for remote URL transport rewrites and leaking an optional API failure's exit code. No unresolved finding from that review remains knowingly accepted.

## Limits

Live GitHub authentication, repository permissions, Projects permissions, and installed agent UI discovery remain to be checked in fresh authenticated sessions. Local simulated responses cannot establish server-side permissions. No performance improvement is claimed or inferred from these functional checks.

No agent product exposes a reliable session-end hook, so the end-of-session protocol is not automatically enforced at session end for Codex, Cursor, or Claude Code. It is carried by the instruction adapters each agent loads, performed by `finish-task.ps1`, and validated on demand by `end-session.ps1`. The automated discovery check confirms the rules are present and consistent in every adapter and skill file; that each agent actually loads and follows them was confirmed for Claude Code in this session and still needs a live session check for Codex and Cursor. Review, test, publication, issue, and handoff steps are recorded attestations, so the validator reports what a session claimed and when, not independent proof that a diff was read carefully.
