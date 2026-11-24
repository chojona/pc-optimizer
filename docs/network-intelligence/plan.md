# Issue #10 implementation plan

- Issue: https://github.com/chojona/pc-optimizer/issues/10
- Owner: `codex-20261124-network-01`
- Branch: `codex/issue-10-network-intelligence`
- Worktree: `C:/Users/johnn/Desktop/pc_optimizer/data/task-worktrees/issue-10-network-intelligence`
- Base: current fetched main, `7ceed211eff7ed7459ccb92ff19010fc105fd2da` (PR #9 merged).
- Claims: `optimizer/network_intelligence/`, `optimizer/diagnostics.py`,
  `optimizer/network.py`, `optimizer/wlan.py`, `tests/test_network_intelligence.py`,
  `tests/test_diagnostics.py`, `tests/test_network.py`, `docs/network-intelligence/`.
- #12 has a separate active claim with no path overlap. Old network trees are
  clean and have no base-to-head changes relative to current main. Primary UI
  modifications are preserved. Open PRs #5–#8 change only CI/release workflows.

1. Agree and publish contract.md on #10, then commit it separately before engine
   implementation. Approved, posted on issue #10, and committed as `9c244a5`.
   Consumers can review the agreed issue comment; branch publication is pending.
2. Add bounded validators and a pure existing-event adapter inside the package.
3. Reuse diagnostics statistics and correlation; explain insufficient/stale,
   provider failures, route instability, missing probes and signal uncertainty.
   Preserve legacy entrypoints; do not touch UI, dependencies or manifests.
4. Add synthetic contract and behavior tests with actual unittest TestCase cases
   (existing pytest-style modules discovered by unittest run zero tests, so also
   execute the relevant pytest modules and full suite).
5. Document compatibility, cost, manual checks and integration. Review no-I/O
   boundaries, bounded work and all evidence references. No speed claim planned.
6. Use finish-task with a reviewed fail-propagating validation script. Prepare a
   focused PR body; publication requires authorization. Run existing Windows CI
   after authorized publication. Retain claims and worktree through review.
7. Use learn to explain actual code, algorithms/complexity, three interview
   questions and one implementation-based exercise.

Setup: start-task dry-run and non-dry commands completed. GitHub CLI available
at Program Files; elevated execution accesses its valid credentials. Successful
CLI stderr event hints were separated from JSON stdout using a process-local
wrapper, preserving nonzero errors; shared scripts were not changed. Git safety
exception was process-local only. No dependencies or global config changed.

Implementation adds only the new package, its tests and documentation. Existing
diagnostics/network/WLAN modules remain unchanged: compatibility is achieved by
reusing the statistical entrypoint and existing event format without importing
providers. A new UI task #11 now also has an active nonoverlapping claim.
