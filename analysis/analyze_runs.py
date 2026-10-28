"""Reproducibly summarize ClockPressure raw run artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from pathlib import Path
from typing import Any, Iterable


def _quantiles(values: Iterable[float]) -> dict[str, float | int | None]:
    ordered = sorted(values)
    if not ordered:
        return {"n": 0, "min": None, "median": None, "p95": None, "p99": None, "max": None}

    def nearest_rank(p: float) -> float:
        return ordered[max(0, math.ceil(p * len(ordered)) - 1)]

    return {
        "n": len(ordered),
        "min": ordered[0],
        "median": statistics.median(ordered),
        "p95": nearest_rank(0.95),
        "p99": nearest_rank(0.99),
        "max": ordered[-1],
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
    return records


def _rate_comparison(start: dict[str, Any], end: dict[str, Any], clock: str) -> dict[str, float] | None:
    raw_start = start.get("monotonic_raw_ns")
    raw_end = end.get("monotonic_raw_ns")
    other_start = start.get(clock)
    other_end = end.get(clock)
    if None in (raw_start, raw_end, other_start, other_end):
        return None
    raw_interval = raw_end - raw_start
    other_interval = other_end - other_start
    if raw_interval <= 0:
        return None
    # The bracket spans sequential reads at both boundaries; it bounds their
    # unknown alignment conservatively but is not a calibration uncertainty.
    boundary_bracket = start.get("read_bracket_ns", 0) + end.get("read_bracket_ns", 0)
    return {
        "raw_interval_ns": raw_interval,
        "clock_interval_ns": other_interval,
        "difference_ppm_vs_raw": (other_interval - raw_interval) / raw_interval * 1_000_000,
        "endpoint_read_bracket_bound_ppm": boundary_bracket / raw_interval * 1_000_000,
    }


def _paired_crossstamp_rate(start: dict[str, Any], end: dict[str, Any]) -> dict[str, Any] | None:
    device_start = start.get("ptp_precise_ns")
    device_end = end.get("ptp_precise_ns")
    system_start = start.get("ptp_precise_sys_monoraw_ns")
    system_end = end.get("ptp_precise_sys_monoraw_ns")
    if None in (device_start, device_end, system_start, system_end):
        return None
    system_interval = system_end - system_start
    device_interval = device_end - device_start
    if system_interval <= 0:
        return None
    result = {
        "paired_sys_monoraw_interval_ns": system_interval,
        "device_interval_ns": device_interval,
        "difference_ppm_vs_paired_sys_monoraw": (
            (device_interval - system_interval) / system_interval * 1_000_000
        ),
        "capture_method": "PTP_SYS_OFFSET_PRECISE",
        "capture_uncertainty": "not quantified; crossstamp is internal and is not an external calibration",
    }
    realtime_start = start.get("ptp_precise_sys_realtime_ns")
    realtime_end = end.get("ptp_precise_sys_realtime_ns")
    if realtime_start is not None and realtime_end is not None:
        realtime_interval = realtime_end - realtime_start
        result["paired_sys_realtime_interval_ns"] = realtime_interval
        result["sys_realtime_minus_paired_sys_monoraw_ppm"] = (
            (realtime_interval - system_interval) / system_interval * 1_000_000
        )
    return result


def _paired_crossstamp_dynamics(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    pairs = [
        (record["ptp_precise_sys_monoraw_ns"], record["ptp_precise_ns"])
        for record in records
        if record.get("kind") in ("start", "sample", "end")
        and record.get("ptp_precise_sys_monoraw_ns") is not None
        and record.get("ptp_precise_ns") is not None
    ]
    pairs.sort(key=lambda pair: pair[0])
    if len(pairs) < 3:
        return None
    origin_system, origin_device = pairs[0]
    elapsed = [system - origin_system for system, _ in pairs]
    offset = [device - system - (origin_device - origin_system) for system, device in pairs]
    if elapsed[-1] <= elapsed[0]:
        return None
    mean_elapsed = statistics.mean(elapsed)
    mean_offset = statistics.mean(offset)
    variance = sum((value - mean_elapsed) ** 2 for value in elapsed)
    if variance <= 0:
        return None
    slope = sum(
        (x - mean_elapsed) * (y - mean_offset) for x, y in zip(elapsed, offset)
    ) / variance
    residuals = [
        abs(y - (mean_offset + slope * (x - mean_elapsed)))
        for x, y in zip(elapsed, offset)
    ]
    return {
        "paired_sample_count": len(pairs),
        "elapsed_ns": elapsed[-1] - elapsed[0],
        "offset_span_ns": max(offset) - min(offset),
        "least_squares_rate_difference_ppm": slope * 1_000_000,
        "absolute_fit_residual_ns": _quantiles(residuals),
        "uncertainty": "descriptive fit only; serial correlation and cross-timestamp capture uncertainty are not modeled",
    }


def _period_errors(samples: list[dict[str, Any]], period_ns: int, clock: str) -> list[float]:
    ordered = sorted(samples, key=lambda sample: sample["seq"])
    errors = []
    for earlier, later in zip(ordered, ordered[1:]):
        sequence_delta = later["seq"] - earlier["seq"]
        if sequence_delta <= 0 or earlier.get(clock) is None or later.get(clock) is None:
            continue
        expected = sequence_delta * period_ns
        observed = later[clock] - earlier[clock]
        if expected > 0:
            errors.append((observed - expected) / expected * 1_000_000)
    return errors


def _robust_outlier_count(values: list[float]) -> int:
    if len(values) < 5:
        return 0
    median = statistics.median(values)
    mad = statistics.median(abs(value - median) for value in values)
    threshold = median + 6 * mad if mad else median + 1_000
    return sum(value > threshold for value in values)


def _bootstrap_mean_interval(values: list[float], seed: int) -> dict[str, float] | None:
    """A descriptive CI across independent run-pair summaries, never samples."""
    if len(values) < 3:
        return None
    rng = random.Random(seed)
    estimates = []
    for _ in range(10000):
        resample = [values[rng.randrange(len(values))] for _ in values]
        estimates.append(statistics.mean(resample))
    estimates.sort()
    return {
        "lower_2_5_percent": estimates[249],
        "upper_97_5_percent": estimates[9749],
    }


def _read_scheduler(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.exists():
        return {"event_count": 0, "runnable_latency_ns": _quantiles([])}, None
    latencies = []
    malformed = 0
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if event.get("kind") == "sched_runnable_to_run":
            latencies.append(event["runnable_latency_ns"])
    return (
        {
            "event_count": len(latencies),
            "malformed_line_count": malformed,
            "runnable_latency_ns": _quantiles(latencies),
        },
        None,
    )


def _telemetry_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"sample_count": 0}
    records = _load_jsonl(path)
    temperatures: dict[str, list[float]] = {}
    package_temperatures: list[float] = []
    frequencies: dict[str, list[float]] = {}
    pressure: dict[str, dict[str, list[float]]] = {}
    brackets: list[float] = []
    service_usage: list[float] = []
    service_memory: list[float] = []
    idle_counters: dict[tuple[str, str, str], dict[str, list[int]]] = {}
    idle_cpu_sets: list[set[str]] = []

    for record in records:
        bracket = record.get("snapshot_bracket_ns")
        if isinstance(bracket, (int, float)):
            brackets.append(float(bracket))

        for sensor, reading in record.get("temperatures", {}).items():
            value = reading.get("temp_millidegree_c")
            try:
                celsius = float(value) / 1000
            except (TypeError, ValueError):
                continue
            temperatures.setdefault(sensor, []).append(celsius)
            if reading.get("type") == "x86_pkg_temp":
                package_temperatures.append(celsius)

        for policy, readings in record.get("frequencies_khz", {}).items():
            value = readings.get("cpuinfo_avg_freq") or readings.get("scaling_cur_freq")
            try:
                frequency = float(value)
            except (TypeError, ValueError):
                continue
            frequencies.setdefault(policy, []).append(frequency)

        for cpu, states in record.get("cpuidle_states", {}).items():
            for state_id, state in states.items():
                name = state.get("name") or state_id
                counters = idle_counters.setdefault(
                    (cpu, state_id, name), {"time_usec": [], "usage": []}
                )
                for counter in ("time_usec", "usage"):
                    value = state.get(counter)
                    if isinstance(value, int) and value >= 0:
                        counters[counter].append(value)
        idle_cpu_sets.append(set(record.get("cpuidle_states", {})))

        for resource, text in record.get("pressure_stall_information", {}).items():
            if not isinstance(text, str):
                continue
            for line in text.splitlines():
                fields = line.split()
                if not fields or fields[0] not in ("some", "full"):
                    continue
                value = next(
                    (field.partition("=")[2] for field in fields if field.startswith("avg10=")),
                    None,
                )
                try:
                    pressure.setdefault(resource, {}).setdefault(fields[0], []).append(float(value))
                except (TypeError, ValueError):
                    continue

        service = record.get("sensetrace_service_cgroup", {})
        usage = service.get("cpu_stat", {}).get("usage_usec")
        memory = service.get("memory_current_bytes")
        try:
            service_usage.append(float(usage))
        except (TypeError, ValueError):
            pass
        try:
            service_memory.append(float(memory))
        except (TypeError, ValueError):
            pass

    def delta(values: list[float]) -> float | None:
        if len(values) < 2 or values[-1] < values[0]:
            return None
        return values[-1] - values[0]

    elapsed_ns = None
    if len(records) >= 2:
        first = records[0].get("monotonic_raw_ns_before")
        last = records[-1].get("monotonic_raw_ns_before")
        if isinstance(first, int) and isinstance(last, int) and last > first:
            elapsed_ns = last - first
    one_cpu_capacity_usec = elapsed_ns / 1000 if elapsed_ns else None
    idle_cpus = set.intersection(*idle_cpu_sets) if idle_cpu_sets else set()

    idle_by_cpu_state = {}
    idle_time_by_name: dict[str, int] = {}
    idle_usage_by_name: dict[str, int] = {}
    for (cpu, state_id, name), counters in sorted(idle_counters.items()):
        if cpu not in idle_cpus:
            continue
        time_delta = delta(counters["time_usec"])
        usage_delta = delta(counters["usage"])
        idle_by_cpu_state[f"{cpu}/{state_id}"] = {
            "name": name,
            "time_delta_usec": time_delta,
            "usage_delta": usage_delta,
        }
        if time_delta is not None:
            idle_time_by_name[name] = idle_time_by_name.get(name, 0) + int(time_delta)
        if usage_delta is not None:
            idle_usage_by_name[name] = idle_usage_by_name.get(name, 0) + int(usage_delta)

    idle_pct_by_cpu_state_name: dict[str, dict[str, float]] = {}
    if one_cpu_capacity_usec:
        for key, state in idle_by_cpu_state.items():
            time_delta = state.get("time_delta_usec")
            if time_delta is None:
                continue
            cpu, _state_id = key.split("/", 1)
            name = state["name"]
            by_name = idle_pct_by_cpu_state_name.setdefault(cpu, {})
            by_name[name] = by_name.get(name, 0.0) + time_delta / one_cpu_capacity_usec * 100
    cpu_capacity_usec = elapsed_ns / 1000 * len(idle_cpus) if elapsed_ns and idle_cpus else None
    idle_pct_by_name = {
        name: (time_delta / cpu_capacity_usec * 100)
        for name, time_delta in idle_time_by_name.items()
    } if cpu_capacity_usec else {}

    return {
        "sample_count": len(records),
        "snapshot_read_bracket_ns": _quantiles(brackets),
        "package_temperature_c": _quantiles(package_temperatures),
        "temperature_c_by_sensor": {
            sensor: _quantiles(values) for sensor, values in sorted(temperatures.items())
        },
        "frequency_khz_by_policy": {
            policy: _quantiles(values) for policy, values in sorted(frequencies.items())
        },
        "pressure_stall_avg10_pct": {
            resource: {
                category: _quantiles(values) for category, values in sorted(categories.items())
            }
            for resource, categories in sorted(pressure.items())
        },
        "sensetrace_service_cpu_usage_delta_usec": delta(service_usage),
        "sensetrace_service_memory_current_bytes": _quantiles(service_memory),
        "cpu_idle_cpus_observed": len(idle_cpus),
        "cpu_idle_elapsed_ns": elapsed_ns,
        "cpu_idle_residency_delta_usec_by_cpu_state": idle_by_cpu_state,
        "cpu_idle_residency_delta_usec_by_state_name": idle_time_by_name,
        "cpu_idle_usage_delta_by_state_name": idle_usage_by_name,
        "cpu_idle_residency_pct_by_cpu_state_name": idle_pct_by_cpu_state_name,
        "cpu_idle_residency_pct_of_cpu_capacity_by_state_name": idle_pct_by_name,
    }


def _environment_group_summaries(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for run in runs:
        grouped.setdefault((run["condition"], run["observer"]), []).append(run)
    summaries = []
    for (condition, observer), members in sorted(grouped.items()):
        environments = [run.get("environment_telemetry", {}) for run in members]
        summaries.append(
            {
                "condition": condition,
                "observer": observer,
                "run_count": len(members),
                "run_package_temperature_max_c": _quantiles(
                    [
                        value["package_temperature_c"]["max"]
                        for value in environments
                        if value.get("package_temperature_c", {}).get("max") is not None
                    ]
                ),
                "run_cpu_psi_some_avg10_max_pct": _quantiles(
                    [
                        value["pressure_stall_avg10_pct"]["cpu"]["some"]["max"]
                        for value in environments
                        if value.get("pressure_stall_avg10_pct", {}).get("cpu", {}).get("some", {}).get("max") is not None
                    ]
                ),
                "run_sensetrace_cpu_usage_delta_usec": _quantiles(
                    [
                        value["sensetrace_service_cpu_usage_delta_usec"]
                        for value in environments
                        if value.get("sensetrace_service_cpu_usage_delta_usec") is not None
                    ]
                ),
                "run_c10_cpu_idle_residency_pct": _quantiles(
                    [
                        value["cpu_idle_residency_pct_of_cpu_capacity_by_state_name"]["C10"]
                        for value in environments
                        if value.get("cpu_idle_residency_pct_of_cpu_capacity_by_state_name", {}).get("C10") is not None
                    ]
                ),
            }
        )
    return summaries


def _checksum_status(run_dir: Path, manifest: dict[str, Any]) -> dict[str, str]:
    status = {}
    for filename, expected in manifest.get("artifacts", {}).items():
        path = run_dir / filename
        if not path.is_file():
            status[filename] = "missing"
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        status[filename] = "ok" if digest == expected.get("sha256") else "mismatch"
    return status


def summarize_run(run_dir: Path) -> dict[str, Any]:
    manifest = json.loads((run_dir / "manifest.json").read_text())
    records = _load_jsonl(run_dir / "probe.jsonl")
    start = next((record for record in records if record.get("kind") == "start"), None)
    end = next((record for record in reversed(records) if record.get("kind") == "end"), None)
    samples = [record for record in records if record.get("kind") == "sample"]
    if start is None or end is None:
        raise ValueError(f"{run_dir}: missing start/end markers")

    lateness = [sample["wakeup_lateness_ns"] for sample in samples]
    cpu_ids = [sample.get("cpu_after") for sample in samples]
    migrations = sum(a != b for a, b in zip(cpu_ids, cpu_ids[1:]) if None not in (a, b))
    tsc_aux = [sample.get("tsc_aux") for sample in samples]
    tsc_aux_migrations = sum(a != b for a, b in zip(tsc_aux, tsc_aux[1:]) if None not in (a, b))
    period_ns = int(manifest["workload"]["period_us"]) * 1_000
    mono_period_error = _period_errors(samples, period_ns, "monotonic_ns")
    raw_period_error = _period_errors(samples, period_ns, "monotonic_raw_ns")
    scheduler, _ = _read_scheduler(run_dir / "scheduler.jsonl")
    integrity = _checksum_status(run_dir, manifest)
    environment = _telemetry_summary(run_dir / "telemetry.jsonl")

    return {
        "run_id": manifest["run_id"],
        "status": manifest["status"],
        "campaign_id": manifest.get("campaign_id"),
        "condition": manifest["condition"],
        "observer": manifest["workload"]["observer"],
        "replicate": manifest.get("replicate"),
        "campaign_role": manifest.get("campaign_role"),
        "code_revision": manifest.get("code_revision"),
        "host_alias": manifest["host"].get("host_alias"),
        "duration_sec_requested": manifest["workload"]["duration_sec"],
        "samples": len(samples),
        "endpoint_intervals_ns": {
            clock: end.get(clock) - start.get(clock)
            for clock in ("monotonic_ns", "monotonic_raw_ns", "boottime_ns", "ptp_ns")
            if end.get(clock) is not None and start.get(clock) is not None
        },
        "internal_rate_comparisons": {
            label: _rate_comparison(start, end, clock)
            for label, clock in (
                ("monotonic_vs_raw", "monotonic_ns"),
                ("boottime_vs_raw", "boottime_ns"),
                ("realtime_vs_raw", "realtime_ns"),
                ("tai_vs_raw", "tai_ns"),
                ("ptp_vs_raw", "ptp_ns"),
            )
        },
        "paired_crossstamp_rate": _paired_crossstamp_rate(start, end),
        "paired_crossstamp_dynamics": _paired_crossstamp_dynamics(records),
        "wakeup_lateness_ns": _quantiles(lateness),
        "wakeup_lateness_exploratory_outliers": _robust_outlier_count(lateness),
        "sample_period_error_ppm_vs_requested_period": {
            "monotonic": _quantiles(mono_period_error),
            "monotonic_raw": _quantiles(raw_period_error),
        },
        "sample_cpu_distribution": {
            str(cpu): cpu_ids.count(cpu) for cpu in sorted({cpu for cpu in cpu_ids if cpu is not None})
        },
        "sample_cpu_migrations_between_adjacent_samples": migrations,
        "tsc_aux_changes_between_adjacent_samples": tsc_aux_migrations,
        "scheduler_witness": scheduler,
        "timestamp_overhead": json.loads((run_dir / "overhead.json").read_text())
        if (run_dir / "overhead.json").exists()
        else None,
        "telemetry_sample_count": environment["sample_count"],
        "environment_telemetry": environment,
        "integrity": integrity,
        "evidence_scope": manifest["measurement_semantics"]["evidence_scope"],
        "reference_status": "no independent external elapsed-time reference was acquired",
    }


def _group_summaries(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for run in runs:
        grouped.setdefault((run["condition"], run["observer"]), []).append(run)
    summaries = []
    for (condition, observer), members in sorted(grouped.items()):
        wake_p99 = [run["wakeup_lateness_ns"].get("p99") for run in members]
        mono_rates = [
            run["internal_rate_comparisons"]["monotonic_vs_raw"]["difference_ppm_vs_raw"]
            for run in members
            if run["internal_rate_comparisons"].get("monotonic_vs_raw")
        ]
        ptp_rates = [
            run["internal_rate_comparisons"]["ptp_vs_raw"]["difference_ppm_vs_raw"]
            for run in members
            if run["internal_rate_comparisons"].get("ptp_vs_raw")
        ]
        crossstamp_rates = [
            run["paired_crossstamp_rate"]["difference_ppm_vs_paired_sys_monoraw"]
            for run in members
            if run.get("paired_crossstamp_rate")
        ]
        crossstamp_fits = [
            run["paired_crossstamp_dynamics"]["least_squares_rate_difference_ppm"]
            for run in members
            if run.get("paired_crossstamp_dynamics")
        ]
        summaries.append(
            {
                "condition": condition,
                "observer": observer,
                "run_count": len(members),
                "run_p99_wakeup_lateness_ns": _quantiles(
                    [value for value in wake_p99 if value is not None]
                ),
                "run_monotonic_minus_raw_ppm": _quantiles(mono_rates),
                "run_ptp_minus_raw_ppm": _quantiles(ptp_rates),
                "run_ptp_precise_minus_paired_sys_monoraw_ppm": _quantiles(crossstamp_rates),
                "run_ptp_precise_time_series_fit_ppm": _quantiles(crossstamp_fits),
            }
        )
    return summaries


def _paired_contrasts(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compare run-level outcomes by campaign replicate; never resample events."""
    indexed = {}
    for run in runs:
        if run.get("campaign_id") is None or run.get("replicate") is None:
            continue
        key = (run["campaign_id"], run["replicate"], run["condition"], run["observer"])
        indexed[key] = run

    campaigns = sorted({run["campaign_id"] for run in runs if run.get("campaign_id")})
    contrasts = []
    for campaign_id in campaigns:
        differences: dict[tuple[str, str, str], list[float]] = {}
        observer_differences: dict[str, list[float]] = {
            "baseline": [], "cpu_pressure": [], "recovery": []
        }
        replicates = sorted({
            run.get("replicate")
            for run in runs
            if run.get("campaign_id") == campaign_id and run.get("replicate") is not None
        })
        for replicate in replicates:
            for observer in ("none", "sched_bpf"):
                baseline = indexed.get((campaign_id, replicate, "baseline", observer))
                for condition, contrast_name in (
                    ("cpu_pressure", "cpu_pressure_minus_baseline"),
                    ("recovery", "recovery_minus_baseline"),
                ):
                    treatment = indexed.get((campaign_id, replicate, condition, observer))
                    if not baseline or not treatment:
                        continue
                    for metric, unit, extract in (
                        (
                            "run_p99_wakeup_lateness",
                            "ns",
                            lambda run: run.get("wakeup_lateness_ns", {}).get("p99"),
                        ),
                        (
                            "adjacent_sample_cpu_migrations",
                            "count",
                            lambda run: run.get("sample_cpu_migrations_between_adjacent_samples"),
                        ),
                        (
                            "paired_crossstamp_time_series_rate_difference",
                            "ppm",
                            lambda run: (run.get("paired_crossstamp_dynamics") or {}).get(
                                "least_squares_rate_difference_ppm"
                            ),
                        ),
                        (
                            "cpu_c10_idle_residency",
                            "percentage_points",
                            lambda run: run.get("environment_telemetry", {})
                            .get("cpu_idle_residency_pct_of_cpu_capacity_by_state_name", {})
                            .get("C10"),
                        ),
                    ):
                        before = extract(baseline)
                        after = extract(treatment)
                        if before is not None and after is not None:
                            differences.setdefault(
                                (contrast_name, observer, metric), []
                            ).append(after - before)
                    baseline_idle = baseline.get("environment_telemetry", {}).get(
                        "cpu_idle_residency_pct_by_cpu_state_name", {}
                    )
                    treatment_idle = treatment.get("environment_telemetry", {}).get(
                        "cpu_idle_residency_pct_by_cpu_state_name", {}
                    )
                    for cpu in sorted(set(baseline_idle) & set(treatment_idle)):
                        before = baseline_idle[cpu].get("C10")
                        after = treatment_idle[cpu].get("C10")
                        if before is not None and after is not None:
                            differences.setdefault(
                                (contrast_name, observer, f"cpu_c10_idle_residency_{cpu}"), []
                            ).append(after - before)
            for condition in ("baseline", "cpu_pressure", "recovery"):
                unobserved = indexed.get((campaign_id, replicate, condition, "none"))
                observed = indexed.get((campaign_id, replicate, condition, "sched_bpf"))
                if unobserved and observed:
                    before = unobserved["wakeup_lateness_ns"].get("p99")
                    after = observed["wakeup_lateness_ns"].get("p99")
                    if before is not None and after is not None:
                        observer_differences[condition].append(after - before)
        seed_base = int(hashlib.sha256(campaign_id.encode()).hexdigest()[:8], 16)
        for index, ((contrast_name, observer, metric), values) in enumerate(sorted(differences.items())):
            unit = {
                "run_p99_wakeup_lateness": "ns",
                "adjacent_sample_cpu_migrations": "count",
                "paired_crossstamp_time_series_rate_difference": "ppm",
                "cpu_c10_idle_residency": "percentage_points",
            }.get(metric, "percentage_points")
            interval = _bootstrap_mean_interval(values, seed_base + index)
            result = {
                "campaign_id": campaign_id,
                "contrast": contrast_name,
                "stratum": f"observer={observer}",
                "metric": metric,
                "unit": unit,
                "paired_difference_n": len(values),
                "paired_difference": _quantiles(values),
                "paired_mean_difference_bootstrap_95_percent_interval": interval,
                "interval_note": "descriptive paired-run resampling only; unavailable below three run pairs",
            }
            # Preserve the original nanosecond keys for consumers of analysis.v1.
            if unit == "ns":
                result["paired_difference_ns"] = result["paired_difference"]
                result["paired_mean_difference_bootstrap_95_percent_interval_ns"] = interval
            contrasts.append(result)
        for condition, differences in observer_differences.items():
            if differences:
                interval = _bootstrap_mean_interval(
                    differences, seed_base + 100 + len(contrasts)
                )
                quantiles = _quantiles(differences)
                contrasts.append(
                    {
                        "campaign_id": campaign_id,
                        "contrast": "sched_bpf_minus_no_observer",
                        "stratum": f"condition={condition}",
                        "metric": "run_p99_wakeup_lateness_ns",
                        "unit": "ns",
                        "paired_difference_n": len(differences),
                        "paired_difference": quantiles,
                        "paired_mean_difference_bootstrap_95_percent_interval": interval,
                        "paired_difference_ns": quantiles,
                        "paired_mean_difference_bootstrap_95_percent_interval_ns": interval,
                        "interval_note": "descriptive paired-run resampling only; unavailable below three run pairs",
                    }
                )
    return contrasts


def _markdown(report: dict[str, Any]) -> str:
    rows = []
    for run in report["runs"]:
        raw = run.get("internal_rate_comparisons", {}).get("monotonic_vs_raw") or {}
        ptp = run.get("internal_rate_comparisons", {}).get("ptp_vs_raw") or {}
        paired_ptp = run.get("paired_crossstamp_rate") or {}
        crossstamp_fit = run.get("paired_crossstamp_dynamics") or {}
        latency = run["wakeup_lateness_ns"]
        sched = run["scheduler_witness"]["runnable_latency_ns"]
        mono = "{rate} / ±{bound}".format(
            rate=_fmt(raw.get("difference_ppm_vs_raw")),
            bound=_fmt(raw.get("endpoint_read_bracket_bound_ppm")),
        )
        nic = "{rate} / ±{bound}".format(
            rate=_fmt(ptp.get("difference_ppm_vs_raw")),
            bound=_fmt(ptp.get("endpoint_read_bracket_bound_ppm")),
        )
        rows.append(
            "| {id} | {condition} | {observer} | {n} | {wake_p99} | {mono} | {nic} | {paired_ptp} | {crossstamp_fit} | {sched_p99} |".format(
                id=run["run_id"],
                condition=run["condition"],
                observer=run["observer"],
                n=run["samples"],
                wake_p99=_fmt(latency.get("p99")),
                mono=mono,
                nic=nic,
                paired_ptp=_fmt(paired_ptp.get("difference_ppm_vs_paired_sys_monoraw")),
                crossstamp_fit=_fmt(crossstamp_fit.get("least_squares_rate_difference_ppm")),
                sched_p99=_fmt(sched.get("p99")),
            )
        )
    environment_rows = [
        "| {condition} | {observer} | {n} | {temperature} | {cpu_psi} | {c10} | {sensetrace} |".format(
            condition=summary["condition"],
            observer=summary["observer"],
            n=summary["run_count"],
            temperature=_fmt(summary["run_package_temperature_max_c"].get("median")),
            cpu_psi=_fmt(summary["run_cpu_psi_some_avg10_max_pct"].get("median")),
            c10=_fmt(summary["run_c10_cpu_idle_residency_pct"].get("median")),
            sensetrace=_fmt(summary["run_sensetrace_cpu_usage_delta_usec"].get("median")),
        )
        for summary in report["environment_group_summaries"]
    ]
    return "\n".join(
        [
            "# ClockPressure initial pilot analysis",
            "",
            f"Runs analyzed: {len(report['runs'])}",
            "",
            "| Run | Condition | eBPF | Samples | Wake late p99 (ns) | MONOTONIC–RAW ppm / endpoint bound | NIC PHC–RAW ppm / endpoint bound | PHC vs paired MONORAW endpoints (ppm) | PHC/MONORAW offset fit (ppm) | eBPF runnable latency p99 (ns) |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            *rows,
            "",
            "## Paired within-campaign contrasts",
            "",
            "| Campaign | Contrast | Stratum | Matched replicates | Metric | Median difference | Descriptive 95% interval |",
            "| --- | --- | --- | ---: | --- | ---: | ---: |",
            *[
                "| {campaign} | {contrast} | {stratum} | {n} | {metric} ({unit}) | {median} | {ci} |".format(
                    campaign=contrast["campaign_id"],
                    contrast=contrast["contrast"],
                    stratum=contrast["stratum"],
                    n=contrast["paired_difference_n"],
                    metric=contrast["metric"],
                    unit=contrast.get("unit", "ns"),
                    median=_fmt(
                        (contrast.get("paired_difference") or contrast.get("paired_difference_ns", {})).get(
                            "median"
                        )
                    ),
                    ci=(
                        "{lo} to {hi} {unit}".format(
                            lo=_fmt(
                                (contrast.get("paired_mean_difference_bootstrap_95_percent_interval") or contrast.get("paired_mean_difference_bootstrap_95_percent_interval_ns", {})).get(
                                    "lower_2_5_percent"
                                )
                            ),
                            hi=_fmt(
                                (contrast.get("paired_mean_difference_bootstrap_95_percent_interval") or contrast.get("paired_mean_difference_bootstrap_95_percent_interval_ns", {})).get(
                                    "upper_97_5_percent"
                                )
                            ),
                            unit=contrast.get("unit", "ns"),
                        )
                        if contrast.get("paired_mean_difference_bootstrap_95_percent_interval") or contrast.get("paired_mean_difference_bootstrap_95_percent_interval_ns")
                        else "not estimable (<3 pairs)"
                    ),
                )
                for contrast in report["paired_contrasts"]
            ],
            "",
            "## Environmental telemetry by condition",
            "",
            "Values show the median of per-run maxima (package temperature and CPU PSI), or per-run SenseTrace cgroup CPU-usage increments. Detailed per-run distributions remain in `analysis.json`.",
            "",
            "| Condition | eBPF | Runs | Package max (°C) | CPU PSI some avg10 max (%) | Per-CPU C10 residency (%) | SenseTrace CPU delta (µs) |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
            *environment_rows,
            "",
            "## Interpretation limits",
            "",
            "- Wakeup lateness is event-delivery delay measured against `CLOCK_MONOTONIC`; it does not establish clock-rate error.",
            "- `CLOCK_MONOTONIC`, `CLOCK_MONOTONIC_RAW`, `CLOCK_BOOTTIME`, and eBPF `bpf_ktime_get_ns()` share the kernel timekeeping path or related hardware. Their differences are internal diagnostics.",
            "- The Intel e1000e PHC is a candidate separate hardware clock. This pilot does not establish oscillator independence, calibration uncertainty, or independent capture of the exact endpoints.",
            "- When available, `PTP_SYS_OFFSET_PRECISE` returns a driver-supported PHC/system cross-timestamp. Its paired rate result reduces userspace read-order ambiguity but remains an internal comparison with unquantified cross-timestamp accuracy; it is not an external standard.",
            "- The paired PHC/MONORAW offset fit uses all retained cross-timestamps. Its residual spread is descriptive; no confidence interval is reported because samples are serially correlated and driver cross-timestamp accuracy is unquantified.",
            "- Per-CPU C10 residency is each CPU's fraction of elapsed time in the named cpuidle state; the aggregate is across per-CPU capacity. Neither exposes package C-state residency or proves the cause of timer wakeup changes.",
            "- Endpoint read brackets are reported as conservative acquisition bounds; they are not calibration certificates or a complete uncertainty budget.",
            "- No external elapsed-time reference was acquired, so these data cannot establish physical clock drift or a hardware-caused false pass.",
            "- Raw JSONL, the per-run manifests, source revision and checksums are retained beside this analysis.",
            "",
        ]
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    return f"{value:.6g}" if isinstance(value, (float, int)) else str(value)


def analyze(data_dir: Path) -> dict[str, Any]:
    run_root = data_dir / "runs" if (data_dir / "runs").exists() else data_dir
    runs = []
    for run_dir in sorted(run_root.iterdir()):
        if not run_dir.is_dir() or run_dir.name.endswith(".in-progress"):
            continue
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("status") == "complete":
            runs.append(summarize_run(run_dir))
    return {
        "schema": "clockpressure.analysis.v1",
        "analysis_code": "analysis/analyze_runs.py",
        "runs": runs,
        "group_summaries": _group_summaries(runs),
        "environment_group_summaries": _environment_group_summaries(runs),
        "paired_contrasts": _paired_contrasts(runs),
        "limits": {
            "external_reference": False,
            "physical_clock_drift_claim_allowed": False,
            "bpf_clock_independent": False,
            "ptp_independence_verified": False,
            "ptp_precise_crossstamp_is_external": False,
            "bootstrap_unit": "run-level paired summaries; timer samples are not treated as independent replicates",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path)
    args = parser.parse_args()
    report = analyze(args.data_dir.expanduser().resolve())
    out_dir = args.data_dir.expanduser().resolve()
    (out_dir / "analysis.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (out_dir / "analysis.md").write_text(_markdown(report))
    print(f"analyzed {len(report['runs'])} runs in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
