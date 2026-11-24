---
name: finish-task
description: Validate an owned issue implementation, inspect and commit intended changes, publish an authorized focused PR, and produce an engineering handoff.
---

# Finish a task

Read `Engineering/ENGINEERING.md` and applicable project instructions. Verify the repository, issue, unique owner, claimed files, task worktree/branch, intended base, current index, status, and remote. Inspect all changes, including new files, staged changes, and relevant ignored outputs. Do not stage unrelated work or use a different owner to bypass a claim.

Check each acceptance criterion against implementation evidence. Run relevant tests, static checks, security checks, and benchmark comparisons where performance claims are made. Investigate failures; do not call a skipped or failing check a pass. Review the actual final diff for regressions, secrets, compatibility, documentation, dependency/interface changes, and scope. Identify new file ownership conflicts before publication.

Use `Engineering/scripts/finish-task.ps1` with `-Repository <task-worktree> -Issue <number> -Owner <session-owner> -TestScript <reviewed-test-script> -Files <explicit-changed-paths>` for validation. Add `-Commit -Message <reviewed-message>` only when committing is authorized. Inspect a `-DryRun` first. Execute a test script only after reviewing what it does; include meaningful project checks and propagate their failures. The finish command is a deterministic safeguard, not proof that acceptance criteria are met. If the task already has commits, inspect the complete base-to-head diff as well as the current index.

Push and PR creation require publication authorization; supply `-Publish -Title <focused-title> -BodyFile <reviewed-body-file>` only when authorized. Prepare an exact multiline PR body file with resulting behavior, issue linkage, validation evidence, decisions, and limitations. Use `Closes #<issue>` only for a complete resolution. Inspect existing PRs for the branch before creating another. Never force-push, approve, merge, enable auto-merge, or claim success for a failed remote step.

Update GitHub Project status only if authorized, with verified Project/item/status field and option IDs and adequate token permissions. A local finish or successful push does not imply that Project status changed. Retain claims through review and integration; safe cleanup/release is a separate coordinated action.

Produce a concise handoff: issue/PR URL, owner and branch/worktree, behavior changed, key files/functions, acceptance evidence, exact check results, performance evidence if relevant, decisions/trade-offs, learning concept, remaining risks, and next steps. State partial completion and recovery steps if commit, push, PR creation, or status update failed.
