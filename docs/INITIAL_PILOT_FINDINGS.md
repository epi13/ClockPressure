# Initial worker-03 baseline and CPU-pressure findings

**Observation date:** 2026-10-28 UTC  
**Campaign:** `20261028T033913Z-campaign-d467c6a9` (seed `20261028`)  
**Probe revision:** `53e47bcfd89244dd0be9f60dac8c536829400127`

## Design

The campaign began with one pressure-free, uninstrumented baseline sentinel, then randomized three baseline and three four-core CPU-pressure replicates with the scheduler eBPF observer both off and on. Each trial sampled for 20 seconds at 100 Hz. Four `nice +10` CPU workers were pinned to CPUs 1–4; the probe was unpinned. Every CPU-pressure trial was followed by a five-second wait and a 20-second no-load recovery observation. The campaign completed 19 runs: 13 planned baseline/pressure trials and six recovery runs.

The pressure condition is ordinary CPU-bound load. No clocksource, system time, CPU frequency policy, firmware, kernel configuration or SenseTrace setting was changed. The primary outcome is timer wakeup lateness, which combines timer delivery, scheduler delay and timestamp acquisition. Cross-clock intervals are secondary internal diagnostics.

## Findings

### No resolved clock-rate change under CPU pressure

In the first campaign, the MONOTONIC-minus-RAW rate stayed near −11.58 ppm across all conditions. Chrony subsequently reported the host frequency as `+11.586 ppm fast`, consistent with system frequency discipline. The MONOTONIC/REALTIME family moving relative to RAW is expected from host correction; it is not evidence that elapsed time was mismeasured.

The sequential NIC PHC comparison was much closer to RAW. Its median PHC-minus-RAW rates were:

| Condition | Median rate difference | Runs |
| --- | ---: | ---: |
| Baseline, no BPF observer | −0.547 ppm | 4, including initial sentinel |
| Baseline, scheduler BPF | −0.526 ppm | 3 |
| CPU pressure, no BPF observer | −0.361 ppm | 3 |
| CPU pressure, scheduler BPF | −0.367 ppm | 3 |
| Recovery, no BPF observer | −0.563 ppm | 6 |

Each run's conservative endpoint read-order bound was 1.2–2.3 ppm. The baseline-to-pressure PHC differences were smaller than those per-run bounds, so this experiment did not resolve a PHC rate change. The PHC is a candidate separate counter, not a calibrated external standard.

### CPU pressure changed timer wakeup latency

The uninstrumented run-level median P99 wakeup lateness was 424.7 µs at baseline and 94.5 µs under pressure. With scheduler eBPF enabled, the medians were 441.9 µs and 109.4 µs. Matched pressure-minus-baseline differences in run P99 were:

| Observer | Matched pairs | Median difference | Descriptive bootstrap interval |
| --- | ---: | ---: | ---: |
| None | 3 | −332.471 µs | −345.100 to −322.606 µs |
| Scheduler BPF | 3 | −332.539 µs | −349.807 to −328.586 µs |

After pressure, recovery P99 returned to 426–440 µs. The direction and recovery make this a repeatable timer-delivery observation within this campaign. The three-pair bootstrap ranges are descriptive within-run-set summaries, not population-level confidence or clock calibration intervals.

The scheduler observer added a median 16.877 µs to baseline run P99 (descriptive range 4.502–18.649 µs). Under pressure, its median difference was 8.716 µs (−0.205–20.762 µs). This observer effect is another reason to use uninstrumented runs as the primary latency result.

Reduced idle-exit delay is a plausible explanation for the lower wake latency under load, but this campaign did not record cpuidle counters or package C-state residency. It therefore does not establish the mechanism. Timer delivery becoming earlier is not clock drift.

## Positive control

The worker-03 software-accounting demonstration used a 500 ms deadline. The child reported 400 ms and passed its weak evaluator; the supervising process measured 843.248 ms with `CLOCK_MONOTONIC_RAW` and rejected the requirement. This is a deliberately constructed software accounting error. Both processes used clocks on the same host, and this says nothing about a physical clock anomaly.

## Integrity and limits

- All 19 trials completed; no campaign command failed.
- The native probe retained 38,000 timer samples. All 38,038 ordinary PHC timestamps, including run endpoints, were valid.
- Six scheduler-observed runs retained 12,012 target runnable-to-run events. Raw artifact checksums matched. The initial analyzer counted trailing blank bpftrace lines as malformed; this parser issue is fixed, and the corrected analysis reports zero malformed records.
- Package temperature peaked at 78°C, below the configured 85°C abort ceiling. CPU PSI `some avg10` peaked at 3.71%.
- This was one host, one boot/session, three matched treatment pairs, and 20-second windows. No calibrated external elapsed-time reference was present. The result cannot establish absolute elapsed-time accuracy, firmware effects, or an externally validated contract failure.

Raw worker data and the regenerated run analysis are preserved at `/home/worker-03/clockpressure-data/initial-campaign-20261028`. A local permission-restricted copy is at `/home/epi13/Documents/Projects/.clockpressure-data/worker-03/initial-campaign-20261028`. The analysis includes per-run manifests, source revision, SHA-256 checks and raw JSONL.

## Follow-up

After this campaign, a read-only check confirmed that `/dev/ptp0` supports `PTP_SYS_OFFSET_PRECISE`. The Linux PTP interface returns a paired device/MONORAW/REALTIME timestamp; the e1000e PCH path can obtain a hardware-supported pair using the NIC clock and Intel ART ([PTP interface](https://github.com/torvalds/linux/blob/v6.17/include/uapi/linux/ptp_clock.h), [e1000e implementation](https://github.com/torvalds/linux/blob/v6.17/drivers/net/ethernet/intel/e1000e/ptp.c)). This reduces software read-order ambiguity but does not provide an external calibration and may share dependencies with the host TSC. The updated probe now records this pair and per-CPU cpuidle counters. Those additions pass local tests but await a retained-data worker-03 follow-up.
