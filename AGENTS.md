# Repository engineering guidance

Before engineering work, read and follow [Engineering/ENGINEERING.md](Engineering/ENGINEERING.md), the canonical shared rules. Also read any more specific repository instruction files relevant to the task. This reference is an instruction to open that file; do not assume Markdown links are automatically imported.

Preserve existing repository-specific guidance when adopting this workflow elsewhere. Independent implementation tasks require an owned Git worktree, created or safely reused before the first edit; read-only inspection does not require creating a task worktree.

## Mandatory end-of-session protocol

Every session that changes this repository must complete all seven steps before it stops and report each result. The canonical definition, including the standing authorization it rests on, is in [Engineering/ENGINEERING.md](Engineering/ENGINEERING.md#end-every-session-with-the-mandatory-protocol).

1. Review the complete diff for correctness, unrelated changes, and exposed secrets.
2. Run the relevant tests and report their actual results; a failing or skipped check is never reported as a pass.
3. Commit the reviewed, claimed changes with a descriptive message.
4. Push the task's own feature branch.
5. Create or update exactly one pull request for that branch — ready for review when the work is complete and the checks pass, otherwise a draft documenting the blockers under a `## Blockers` heading.
6. Update the associated GitHub issue and Project board status, or report the exact blocked operation.
7. Hand off completed work, remaining work, test results, blockers, the pull request URL, and the engineering concepts involved.

A session with no repository changes performs step 7 only and creates no pull request. Preserve unfinished work as commits and a draft pull request. Never merge your own pull request, force-push, discard changes, bypass failing checks, or modify another agent's worktree.

Use `$start-task` and `$finish-task`, and verify with `pwsh -File Engineering/scripts/end-session.ps1 -Repository <task-worktree>`. Codex and Cursor cannot enforce this automatically at session end; follow it yourself and state anything the scripts could not verify.
