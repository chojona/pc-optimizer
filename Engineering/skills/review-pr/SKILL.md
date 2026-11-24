---
name: review-pr
description: Review an actual pull request diff and relevant tests for actionable correctness, security, concurrency, regression, and performance findings without approving or merging.
---

# Review a pull request

Read `Engineering/ENGINEERING.md` and the project's relevant review guidance. Obtain the PR description, linked issue and acceptance criteria, exact base/head commit IDs, full actual diff, changed files, checks, and relevant discussion using GitHub CLI or an authorized connector. If remote access is unavailable, review an explicitly identified local base/head diff and label that limitation; do not substitute a remembered or proposed diff.

Inspect surrounding code, callers, data models, tests, and prior behavior where necessary to establish a finding. Focus on correctness, regressions, validation and authorization boundaries, sensitive data, concurrency and cancellation, resource lifetime, error recovery, compatibility, and algorithmic/I/O costs. Trace a concrete failing condition and its consequence. Distinguish measured performance evidence from plausible hypotheses. Avoid speculative findings and stylistic preferences that do not violate project requirements.

Use a separate review worktree when checkout changes or test artifacts could affect another owner's work. Do not switch branches in an actively owned implementation tree. Run relevant tests and checks in the review worktree when permitted; record the commands, base/head tested, outcomes, and unavailable validation. Tests supplied by the PR do not replace investigation of missing failure cases. Review the final diff again if the head changes.

Report actionable findings by severity: P0 critical/blocking, P1 high, P2 medium, P3 low. Give each finding a concise title, the trigger and impact, and the smallest useful actual file/line reference in the current diff. State the PR head reviewed and validation evidence. If no actionable findings remain, say so and state material coverage limits; do not invent issues. Separate findings from optional questions or suggestions.

Return the review to the user. Do not automatically submit a GitHub approval, request-changes review, comment, or merge; posting requires explicit authorization and approval/merge must never be automatic. Do not edit implementation or transfer ownership as part of review unless separately requested.
