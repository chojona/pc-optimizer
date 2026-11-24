# Environment and agent discovery

Inspected on 2026-11-24. This report describes the observed Windows environment; it is not an installer or a guarantee about another machine.

## Repository observations

The source checkout is `C:\Users\johnn\Desktop\pc_optimizer`, with origin `https://github.com/chojona/pc-optimizer.git`. Its active branch was `codex/network-optimization-center`. It contained modified application files and untracked application assets before this work began. Those changes were preserved.

Three pre-existing linked worktrees were found under `data/`: `clean-ui-pr`, `network-diagnostics`, and `plain-english-pr`. They were not adopted or changed. Infrastructure implementation used the additional isolated worktree `data/engineering-workflow` on branch `codex/engineering-workflow`.

The original checkout also contained untracked, empty `Engineering/AGENTS.md` and five empty skill entrypoints under `Engineering/skills/`. Infrastructure was developed in isolation first. The repository installer can populate these zero-byte placeholders only after temporary-repository validation, while preserving nonempty user content. The installation destination is `C:\Users\johnn\Desktop\pc_optimizer`; its isolated development source remains `data/engineering-workflow`.

Git user name and email were configured. The system Git configuration uses `core.autocrlf=true` and Git Credential Manager. No global Git settings were changed. Creating the implementation worktree required a command-scoped `safe.directory` override because the checkout and execution account had different owners; no persistent trust exception was installed.

## Installed tools and instructions

| Item | Observation |
| --- | --- |
| Git | Available at `C:\Program Files\Git\cmd\git.exe` |
| Codex | CLI reports `0.171.0-alpha.13.2`; desktop-bundled executable on PATH |
| Cursor | CLI reports `3.32.4`, Windows x64 |
| Claude Code | Not found on PATH or checked standard user installation paths; Claude account/app availability was not inferred |
| GitHub CLI | `gh` not found on PATH or checked standard installation paths |
| GitHub authentication | Unverified because CLI is unavailable; Git credential setup does not establish GitHub CLI or Projects permissions |
| PowerShell | `pwsh` available from the Codex runtime; scripts require PowerShell 7 |
| Existing global instructions | No `AGENTS.md` in checked ancestor directories, no user `~/.codex/AGENTS.md`, and no user `~/.claude/CLAUDE.md` found |
| Existing skill roots | `C:\Users\johnn\.codex\skills\.system` exists; checked user `.agents/skills`, `.cursor/skills`, `.cursor/rules`, and `.claude/skills` roots were absent |

No authentication tokens, credential files, agent chat histories, unrelated repositories, editor settings, PATH settings, or system policies were changed. Status inspection reports an inaccessible worktree with `dirty: null` and an `inspectionError`; it never interprets a Git trust error as a clean worktree or modifies global Git trust automatically.

## Verified discovery mechanisms

These mechanisms were checked against official documentation on the inspection date. The wrappers deliberately use each tool's supported mechanism rather than assuming that a file named `SKILL.md` anywhere in a repository is discoverable.

| Agent | Instruction mechanism used here | Skill mechanism used here | Explicit invocation |
| --- | --- | --- | --- |
| Codex | Root `AGENTS.md` directs the agent to read `Engineering/ENGINEERING.md`; nested repository instructions remain applicable | `.agents/skills/<name>/SKILL.md` | `$start-task`, `$review-pr`, `$benchmark`, `$finish-task`, `$learn`; `/skills` opens selection in CLI/IDE |
| Cursor | Root `AGENTS.md` plus an always-applied `.cursor/rules/engineering.mdc` reference | `.agents/skills/<name>/SKILL.md`; also discovers Claude compatibility wrappers | `/start-task`, `/review-pr`, `/benchmark`, `/finish-task`, `/learn` in Agent chat |
| Claude Code | Root `CLAUDE.md` imports `@Engineering/ENGINEERING.md` using native import syntax | `.claude/skills/<name>/SKILL.md` | `/start-task`, `/review-pr`, `/benchmark`, `/finish-task`, `/learn` |

Codex uses `~/.codex/AGENTS.md` (or its configured Codex home) for global guidance. Its documented repository skill root is `.agents/skills`, and the current user skill root is `~/.agents/skills`. Existing bundled skills under `.codex` are preserved. Sources: [Codex instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md), [Codex skills](https://learn.chatgpt.com/docs/build-skills).

Cursor supports both `AGENTS.md` and `.cursor/rules/*.mdc`. User Rules are managed through Cursor settings. Its documented skill roots include `.agents/skills`, `.cursor/skills`, and their user-level equivalents, with compatibility discovery under `.claude/skills` and `.codex/skills`. Sources: [Cursor rules](https://cursor.com/docs/rules), [Cursor skills](https://cursor.com/docs/skills).

Claude Code documents `CLAUDE.md` imports and `.claude/skills` for project/user skills. Recent versions can read `AGENTS.md` directly, but that behavior depends on version and the presence of `CLAUDE.md` files. This bundle uses explicit imports for predictable behavior across installations. Sources: [Claude instructions](https://code.claude.com/docs/en/memory), [Claude skills](https://code.claude.com/docs/en/skills).

Documentation verification does not prove that a particular installed desktop session has reloaded the files. Open a fresh session in the task worktree and inspect its skill menu. In Claude Code, `/memory` shows loaded instructions. Ask each agent to identify its shared rules file and task owner before implementation.

## Proposed global locations — not installed

Repository-level validation comes first. A later global installation requires explicit user approval and a review of existing files at installation time.

| Purpose | Proposed Windows location | Preservation strategy |
| --- | --- | --- |
| Versioned personal bundle | `C:\Users\johnn\EngineeringWorkflow` | Create a separate user-owned bundle; retain a pinned revision |
| Codex user instruction reference | `C:\Users\johnn\.codex\AGENTS.md` | Append one reviewed instruction to read the shared bundle; preserve all existing content and any configured `CODEX_HOME` |
| Codex/Cursor user skill wrappers | `C:\Users\johnn\.agents\skills\<name>\SKILL.md` | Create missing wrappers only; inspect name collisions before installation |
| Claude user instruction import | `C:\Users\johnn\.claude\CLAUDE.md` | Append a reviewed `@` import, preserving all existing instructions |
| Claude user skill wrappers | `C:\Users\johnn\.claude\skills\<name>\SKILL.md` | Create missing wrappers only; inspect name collisions before installation |
| Cursor user instructions | Cursor Settings → Rules → User Rules | Add a reviewed shared-file reference through the UI; do not edit undocumented settings files |

Do not install same-named global and repository wrappers indiscriminately. Prefer repository discovery for projects containing this bundle; use distinct names or explicitly resolve global collisions. Global wrappers must reference the absolute global bundle location, not the repository-relative paths used here. Machine-local global skills are not automatically available in every cloud/remote agent environment.

## Verification limits

The bundled Codex manual fetch helper failed with Windows TLS credential error `SEC_E_NO_CREDENTIALS`; official documentation was read through the web tool instead. Live GitHub issue, pull request, and Projects access was not established. The workflow must therefore distinguish local validation from authenticated integration testing. Installation, authentication, scope changes, account changes, and system configuration changes remain explicit user actions.
