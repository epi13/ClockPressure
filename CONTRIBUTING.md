# Contributing to ClockPressure

Contributions are welcome, including null results, corrections to timing semantics, measurement designs, instrumentation plans, reproducible probes, and independent reviews.

## Before proposing an experiment

- Read the [research hypotheses](docs/RESEARCH_QUESTIONS.md), [clock independence model](docs/CLOCKS_AND_INDEPENDENCE.md), [protocol](docs/EXPERIMENT_PROTOCOL.md), and [safety policy](docs/SAFETY_AND_ETHICS.md).
- Define a falsifiable claim and the exact time interval / clock being measured.
- State how your reference is independent, or explicitly mark it an internal diagnostic.
- Include a baseline, negative control, resource ceilings, potential observer effects and stop conditions.
- Describe expected artifacts, recording format, reproducibility and platform compatibility.

## Documentation and pull requests

Prefer small PRs with a clear rationale. For each change provide: what is new, why it is needed, what was verified, and what remains untested. Do not claim worker-03 or eBPF execution without observed logs. Record command / kernel versions for platform-specific examples.

## Code and research outputs

- Keep experiments bounded and opt-in. No unexpected privileged configuration changes.
- Separate instrumentation, workload generation, independent verification, and analysis.
- Include unit or fixture tests for calculations and parsers, and integration tests only where supported.
- Include synthetic examples with explicit labels, not as evidence of hardware behavior.
- Keep generated binaries, large traces, private host identifiers and access tokens out of Git.
- Respect the repository's Apache-2.0 license and document third-party provenance.

## Evidence labels

Use: `hypothesis`, `simulation / synthetic control`, `observed (internal only)`, `externally validated`, `replicated`, or `inconclusive`. The label must match the highest level actually supported by the supplied artifacts.
