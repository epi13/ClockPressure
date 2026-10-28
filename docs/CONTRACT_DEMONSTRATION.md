# Timing-contract demonstration

## Motivation

A contract test may check a reported metric instead of the actual property it is intended to guarantee. A program can appear to complete within a deadline because its clock implementation or evaluator has an accounting defect. A reproducible false pass is the target **demonstration**, not an established research result.

## Define the contract precisely

Example intended requirement: *The task completes within a deadline measured as externally validated elapsed time between specified start and completion events.*

The test may implement a weaker predicate: *A program-supplied time reading is less than or equal to the deadline.*

These are not equivalent when the measured task influences—or shares failure modes with—the measurement chain.

For clarity, record:
- Exact start / stop event and how each is captured.
- Whether deadline means wall elapsed, CPU time, or time excluding suspend.
- Reporting clock's provenance and whether the agent can edit, replace or wrap it.
- Authorized test and production environment behavior.
- Independent verifier and uncertainty for close-to-deadline cases.

## Stage 1: explicit positive control

Construct a small, deterministic example of **bad software timing**, e.g. fixed-count iterations that each add an assumed 10 ms although callbacks are delayed. A separate correct elapsed-time clock should show the discrepancy.

The control illustrates measurement failure but **does not** prove a real hardware clock was slowed. Do not imply an agent discovered the exploit; a human-designed control is a different result.

## Stage 2: discovered system effect (conditional)

If a worker-03 experiment identifies a validated clock-rate discrepancy or timing-path fault:

1. Freeze the affected environment and reproduction procedure.
2. Define an independent event anchor and deadline, with reference uncertainty.
3. Show a result where the test passes but the independent observer establishes failure with clear separation beyond uncertainty.
4. Repeat the result; show controls and counterexamples.
5. Disclose exactly which timing layer was responsible (event latency, accounting, clocksource, firmware, virtualization, etc.).

If this condition is not met, publish a **software-timer positive control** and negative / bounded findings honestly. Do not manufacture a physical clock effect.

## Stage 3: agent behavior (separate study)

A later study may give an agent a legitimate time-bounded programming task, with sandboxed authority over the submitted code and explicit measurement boundaries. Observe whether the agent independently chooses changes that degrade the evaluator while improving the reported score.

Safeguards for valid attribution:
- The agent should not be instructed to falsify results.
- Freeze the test contract, scoring harness, tool access, model / prompt settings, and evaluator version before trials.
- Separate agent-visible test signals from evaluator-only independent evidence.
- Include controls with immutable / independent timing checks.
- Distinguish an accidental bug, intentional evaluator manipulation, and a model-proposed workaround based on observable actions—not presumed motive.
- Preserve complete permitted trace / artifacts and count all trials including failures.
- Never claim a model 'cheated' from a passing test alone.

## Broader application

This is a concrete example of **measurement authority**: who decides whether a system succeeded, and can that decision source be influenced by the process being assessed? The transfer to MNCS is a research question for environment-managed contracts, trusted evaluation paths, and provenance—not a claim that MNCS currently has a specific vulnerability.

## Reporting labels

Use one or more explicit labels: `synthetic positive control`, `observed scheduler jitter`, `internal cross-clock difference`, `externally validated drift`, `timing contract false pass`, `observed agent behavior`. Never upgrade a claim without the evidence needed for the higher category.
