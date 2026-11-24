---
name: benchmark
description: Design and run reproducible before-and-after performance measurements with controlled conditions, raw evidence, sample sizes, uncertainty, and limitations.
---

# Benchmark a change

Read `Engineering/ENGINEERING.md`, relevant project instructions, and the implementation under study. Define the question and acceptance threshold before measurement. Identify baseline and candidate commit IDs, workload/input data, metrics and units (for example latency distribution, throughput, peak memory, CPU, I/O), correctness checks, and relevant confounders.

Use separate owned worktrees for implementation variants. Establish a reproducible baseline and retain commands, harness version, raw results, runtime/compiler/dependency versions, Windows version, hardware, configuration, input seeds, and timestamps. Control workload size, warmup, cache state, build mode, background load, power/thermal conditions, network variability, and measurement overhead as appropriate. Do not change host power/security/service settings or install tools without explicit approval.

Run comparable before/after trials with repeated samples and documented warmup/exclusion rules; interleave or randomize trial order where drift matters. Verify that both variants produce correct equivalent results. Record failed trials instead of silently dropping inconvenient observations. Choose a sample count proportional to variance and cost, and report the actual independent run count separately from inner-loop iterations.

Report baseline/candidate summaries, units, sample sizes, distributions or spread, relative and absolute differences, uncertainty method and assumptions, and practical significance. Avoid treating correlated operations as independent samples. Preserve raw evidence in the task's agreed artifact location without secrets or unnecessary large files. State limitations such as synthetic workload, noisy machine, shared network, or insufficient samples. If measurements are inconclusive, report that outcome; if execution is unavailable, supply a runnable measurement plan and label results pending.

Never fabricate results or improvement percentages. Keep algorithmic complexity reasoning and performance hypotheses separate from measured results. Explain the observed bottleneck, trade-offs, and what further experiment would resolve uncertainty.
