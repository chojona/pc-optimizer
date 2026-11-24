# Engineering workflow

Read [ENGINEERING.md](ENGINEERING.md) before working in this directory. It is the canonical shared policy; preserve repository-specific instructions alongside it. Skills in `skills/` are canonical procedures; discoverable adapters live in the repository's `.agents/skills/` and `.claude/skills/` directories.

Changes here affect every agent and repository that installs this bundle. The mandatory end-of-session protocol is defined once in [ENGINEERING.md](ENGINEERING.md#end-every-session-with-the-mandatory-protocol); the root `AGENTS.md`, `CLAUDE.md`, and `.cursor/rules/engineering.mdc` adapters carry a short summary so each agent can discover it without opening another file. Keep those summaries and the canonical section consistent, and keep the protocol's step names aligned with `scripts/Workflow.psm1`; `tests/session-protocol.tests.ps1` checks both.

Sessions in this directory follow the same protocol as any other: `scripts/finish-task.ps1` performs it and `scripts/end-session.ps1` validates it.
