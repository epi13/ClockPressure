# Safety, scope and research ethics

ClockPressure is intended for **authorized**, reproducible measurements on systems under the experimenter's control. The research is about trustworthy timing and evaluation, not about stealthily falsifying results on third-party systems.

## Default boundaries

- Run only on hosts where the owner has granted permission and understands load / tracing impact.
- Favor read-only introspection and bounded, low-overhead tracing before any stress experiment.
- Do not modify host-wide timekeeping, firmware, BIOS/UEFI, boot parameters, hypervisor configuration, or clocksource settings in the default study.
- Do not attempt voltage / clock manipulation, overheating, physical interference, persistent hardware changes, or bypasses of system safety mechanisms.
- No covert persistence, privileged evasion, production-clock tampering, or third-party timing-evaluator attacks.
- Avoid collecting unrelated process content, personal data, credentials, secrets, network payloads or user workloads.
- Treat eBPF access as privileged even when it is intended for observation. Apply least privilege.

## Risk management

Agree on ceilings and a stop / rollback plan before each workload: CPU %, memory pressure, I/O volume, disk wear, duration, temperature and acceptable observer overhead. Abort on instability, thermal alarms, resource exhaustion, runaway event volume, anomalous service interruption, or unclear system ownership.

Do not disrupt concurrent SenseTrace or other research. If worker-03 is unavailable or busy, postpone rather than escalating load.

## Scientific integrity

- Never present a synthetic slow clock as natural hardware drift.
- Never call two interfaces independent merely because they have different names.
- Never conflate wakeup latency or CPU execution time with elapsed wall-clock time.
- Report negative and inconclusive findings, uncertainty, environmental changes, and data-loss events.
- Record whether an agent *observably* changed an evaluator, instead of assuming intent.
- Keep the independent verifier and original intended contract visible in demonstrations.

## Responsible disclosure

If a real timing weakness affects a third-party operating system, hardware component, cloud environment or security control, limit reproduction to owned systems and coordinate with the relevant maintainer before publicizing weaponizable specifics. Publish minimal, non-invasive educational proofs when appropriate.

## License / provenance

This repository retains its existing Apache-2.0 license. Contributors must identify the source and compatible license of imported work, preserve notices where required, and distinguish machine-generated material, hypotheses, and measured results.
