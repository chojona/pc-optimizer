---
name: finish-task
description: Run the mandatory end-of-session protocol - review the diff, run and report the real test results, commit, push the task branch, create or update one pull request, update the issue and Project status, and produce an engineering handoff.
---

# Finish a task

Read `Engineering/ENGINEERING.md`, including its mandatory end-of-session protocol, and applicable project instructions. This skill performs steps 1-7 of that protocol: review the diff, run and report the real check results, commit, push the task branch, create or update one pull request, update the issue and Project status, and hand off. Run it before ending any session that changed the repository, even when the implementation is unfinished. Verify the repository, issue, unique owner, claimed files, task worktree/branch, intended base, current index, status, and remote. Inspect all changes, including new files, staged changes, and relevant ignored outputs. Do not stage unrelated work or use a different owner to bypass a claim.

Check each acceptance criterion against implementation evidence. Run relevant tests, static checks, security checks, and benchmark comparisons where performance claims are made. Investigate failures; do not call a skipped or failing check a pass. Review the actual final diff for regressions, secrets, compatibility, documentation, dependency/interface changes, and scope. Identify new file ownership conflicts before publication.

Use `Engineering/scripts/finish-task.ps1` with `-Repository <task-worktree> -Issue <number> -Owner <session-owner> -TestScript <reviewed-test-script> -Files <explicit-changed-paths>` for validation. Add `-Commit -Message <reviewed-message>` only when committing is authorized. Inspect a `-DryRun` first. Execute a test script only after reviewing what it does; include meaningful project checks and propagate their failures. The finish command is a deterministic safeguard, not proof that acceptance criteria are met. If the task already has commits, inspect the complete base-to-head diff as well as the current index.

Push and publish the task's own branch with `-Publish -Title <focused-title> -BodyFile <reviewed-body-file>`; the protocol authorizes that branch and its pull request only. Prepare an exact multiline PR body file with resulting behavior, issue linkage, validation evidence, decisions, and limitations. Use `Closes #<issue>` only for a complete resolution.

For unfinished work or failing checks, add `-Draft`, and `-AllowTestFailure` as well when checks fail. A draft body must reference the issue without a closing keyword and must document concrete blockers under a `## Blockers` heading; the script refuses a draft without them and writes the actual failure output to an evidence log. Never present a failing or skipped check as a pass, and never use `-AllowTestFailure` to move past a failure you have not investigated.

The script reuses the branch's existing open pull request and updates its title, body, and draft state instead of opening a duplicate. A session with no commits publishes nothing and reports `skipped-no-changes`. Never force-push, approve, merge, enable auto-merge, or claim success for a failed remote step.

Update the issue with `-CommentIssue -HandoffFile <reviewed-handoff-file>`, and Project status with verified Project/item/status field and option IDs. When an update is genuinely unsupported or unauthorized, record it with `-SkipIssueUpdate` or `-SkipProjectUpdate` plus `-LimitationNote <reason>` and tell the user; never report an update that did not happen. Retain claims through review and integration; safe cleanup/release is a separate coordinated action.

Confirm the protocol with `pwsh -File Engineering/scripts/end-session.ps1 -Repository <task-worktree> -Issue <number> -Owner <session-owner>`. It is read-only and lists every pending step; resolve each one or explain it. Then produce a concise handoff: completed work, remaining work, exact check results, blockers, PR URL, owner and branch/worktree, key files/functions, acceptance evidence, performance evidence if relevant, decisions/trade-offs, engineering concepts learned, remaining risks, and next steps. State partial completion and recovery steps if commit, push, PR creation, or a status update failed.
