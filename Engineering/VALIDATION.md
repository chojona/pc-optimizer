# Validation record

Validated on 2026-11-24 using Git for Windows 2.56.0 and PowerShell 7.6.9. Tests ran against newly created disposable repositories and local bare origins before installing the bundle into the existing project. No live GitHub issues, Projects, PRs, or unrelated repositories were changed.

## Repository automation

```powershell
pwsh -NoProfile -File .\Engineering\tests\workflow.tests.ps1
```

Result: **24 passed, 0 failed**, exit code 0.

Coverage includes clean and dirty repositories; preservation of unrelated changes; same-owner dirty worktree reuse; duplicate owners; file/directory and case-insensitive ownership conflicts; unmanaged branches/worktrees; actual concurrent independent and duplicate starts; exclusive-lock contention; missing CLI/authentication; failed tests preventing commits; dry runs without execution or workflow state; tracked/untracked ownership; explicit commits; staged changes canceled in the working copy; unmerged, dirty, and ignored-file cleanup refusals; approved release and merged cleanup; status snapshots; empty-skeleton installation, idempotence, and preserving nonempty instructions.

The successful run removed its own disposable fixtures. Diagnosed failed-run fixtures were also removed after validating their exact GUID-named paths beneath the temporary directory. Real development worktrees were preserved.

## Instructions and skills

All 15 canonical/discovery `SKILL.md` files passed checks for frontmatter delimiters, matching names, descriptions, bodies, and relative reference targets. PowerShell source files passed parser checks. The bundled skill validator was attempted but could not execute because its Python environment lacks PyYAML; no dependency was installed to change the machine. Official agent documentation links and observed tool availability are recorded in [DISCOVERY.md](DISCOVERY.md).

## GitHub-facing contract checks

```powershell
pwsh -NoProfile -File .\Engineering\tests\github-contract.tests.ps1
```

Result: **6 passed, 0 failed**, exit code 0. The suite verified online dry-run reads without mutations; paginated PR ownership conflicts including renamed paths; authentication refusal; actual commit and push to a local bare origin with a simulated PR URL and retained review claim; refusal to reuse a PR closing another repository's issue; and denied Project permission reported as pending without losing successful publication or leaking the failed API exit code.

Only this optional suite needs the existing Windows .NET Framework compiler at `%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe` to build a temporary native CLI stub. Its missing-compiler diagnostic was also checked: it fails before creating fixtures. No compiler or package was installed. Successful and diagnosed failed contract fixtures were cleaned safely. GitHub responses were simulated; Git transport was rewritten only in each disposable repository's configuration.

## Independent review

An independent review reproduced and led to regression coverage for canceled staged changes bypassing ownership, scalar path concatenation in PowerShell, and Windows slash normalization during worktree reuse. PR validation also now checks the exact repository/issue and the actual body of an existing PR. Contract tests found and verified fixes for remote URL transport rewrites and leaking an optional API failure's exit code. No unresolved finding from that review remains knowingly accepted.

## Limits

Live GitHub authentication, repository permissions, Projects permissions, and installed agent UI discovery remain to be checked in fresh authenticated sessions. Local simulated responses cannot establish server-side permissions. No performance improvement is claimed or inferred from these functional checks.
