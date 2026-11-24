# Shared engineering guidance

@Engineering/ENGINEERING.md

Read applicable repository-specific instructions too. The `.claude/skills/` entries route to the canonical procedures under `Engineering/skills/`.

## Mandatory end-of-session protocol

Every session that changes this repository must complete all seven steps of the end-of-session protocol in the imported rules before it stops, and report each result:

1. Review the complete diff for correctness, unrelated changes, and exposed secrets.
2. Run the relevant tests and report their actual results; never present a failing or skipped check as a pass.
3. Commit the reviewed, claimed changes with a descriptive message.
4. Push the task's own feature branch.
5. Create or update exactly one pull request for that branch — ready for review when complete and passing, otherwise a draft documenting the blockers under a `## Blockers` heading.
6. Update the associated GitHub issue and Project board status, or report the exact blocked operation.
7. Hand off completed work, remaining work, test results, blockers, the pull request URL, and the engineering concepts involved.

A session with no repository changes performs step 7 only and creates no pull request. Work in an isolated worktree created before the first edit, keep one task to one branch, one worktree, and one pull request, preserve unfinished work as commits plus a draft pull request, and never merge your own pull request, force-push, discard changes, bypass failing checks, or touch another agent's worktree.

Run `/finish-task` to carry this out and `pwsh -File Engineering/scripts/end-session.ps1 -Repository <task-worktree>` to verify it. Claude Code applies this protocol from these instructions; it is not enforced by a hook, so state in the handoff anything the scripts could not verify. `/ship` and similar built-in commands do not replace the protocol, and nothing here authorizes merging.
