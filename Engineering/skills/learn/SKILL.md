---
name: learn
description: Explain a real implementation and its engineering concepts, architecture, algorithms, complexity, trade-offs, three interview questions, and a practical exercise.
---

# Learn from an implementation

Read `Engineering/ENGINEERING.md`, the task's issue/acceptance criteria, actual diff, relevant implementation, and tests. Identify the commit or PR being explained; if unavailable, explain the inspected working tree and state that boundary. Base the teaching on code that exists, and distinguish inference from verified behavior. This skill is read-only unless the user separately requests changes.

Explain the problem, how the resulting behavior works, and the underlying engineering concepts at a level suited to the user's context. Trace a concrete input through the important files and functions; provide accurate file/line references and explain each component's responsibility. Describe the relevant algorithms and data structures, state time/space complexity with the input variables and assumptions, and discuss practical costs such as I/O, allocation, contention, and network latency.

Explain the architecture decisions, reuse and module boundaries, failure handling, concurrency/security implications, alternatives, and trade-offs. Connect tests to the behaviors they demonstrate and name important untested cases. Use actual benchmark evidence when available and clearly label performance predictions or uncertainty. Keep explanations focused on decisions the implementation illustrates rather than generic textbook filler.

Generate exactly three technical interview questions grounded in this implementation, with brief answer guides. Include one practical exercise with a concrete objective, files/functions to inspect or extend, constraints, and observable acceptance criteria. The exercise should reinforce a concept from the implementation and be possible in a new isolated worktree; proposing it does not authorize editing or changing host settings.

End with useful next reading or an experiment only when it follows from a demonstrated knowledge gap. Do not invent APIs, benchmark results, rationale from authors, or code paths that were not inspected.
