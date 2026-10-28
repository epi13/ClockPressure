"""Analyze one timerlat-enabled/disabled controlled ClockPressure campaign."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

from analysis.analyze_runs import _bootstrap_mean_interval, _quantiles, analyze
from analysis.analyze_idle_transitions import analyze_idle_transitions
from analysis.analyze_timerlat import analyze_trace

_PROBE_METRICS = {
    "clockpressure_wakeup_p99": "ns",
    "clockpressure_crossstamp_fit_rate": "ppm",
    "clockpressure_monotonic_vs_raw_rate": "ppm",
    "cpu_c9_aggregate_residency": "percentage_points",
    "cpu_c10_aggregate_residency": "percentage_points",
    "probe_cpu_c9_residency": "percentage_points",
    "probe_cpu_c10_residency": "percentage_points",
    "timerlat_cpu_c9_residency": "percentage_points",
    "timerlat_cpu_c10_residency": "percentage_points",
    "probe_adjacent_sample_migrations": "count",
}
_TIMERLAT_KINDS = ("irq", "thread", "user_return")


def _metric_record(values: list[float], seed: int, unit: str) -> dict[str, Any]:
    return {
        "paired_difference_n": len(values),
        "paired_difference": _quantiles(values),
        "unit": unit,
        "mean_bootstrap_95_percent_interval": _bootstrap_mean_interval(values, seed),
        "interval_note": "descriptive paired-run resampling; samples within a run are not independent replicates",
    }


def _resolve_artifact(root: Path, value: str) -> Path | None:
    recorded = Path(value)
    if not recorded.is_absolute():
        candidate = root / recorded
        return candidate if candidate.is_file() else None
    if recorded.is_file():
        return recorded
    parts = recorded.parts
    if "timerlat" in parts:
        candidate = root.joinpath(*parts[parts.index("timerlat") :])
        if candidate.is_file():
            return candidate
    matches = list(root.rglob(recorded.name))
    return matches[0] if len(matches) == 1 else None


def _parse_trace_buffer_stats(value: str | None) -> dict[str, int]:
    stats: dict[str, int] = {}
    for line in (value or "").splitlines():
        key, separator, raw = line.partition(":")
        if not separator:
            continue
        try:
            number = int(raw.strip())
        except ValueError:
            continue
        stats[key.strip().lower().replace(" ", "_")] = number
    return stats


_TURBOSTAT_METRICS = (
    "Busy%",
    "Bzy_MHz",
    "C10%",
    "Pkg%pc6",
    "Pk%pc10",
    "PkgWatt",
    "PkgTmp",
)
_TURBOSTAT_UNITS = {
    "Busy%": "percentage_points",
    "Bzy_MHz": "MHz",
    "C10%": "percentage_points",
    "Pkg%pc6": "percentage_points",
    "Pk%pc10": "percentage_points",
    "PkgWatt": "W",
    "PkgTmp": "degC",
}
_TURBOSTAT_CONTRAST_METRICS = tuple(
    (f"turbostat_cpu_{metric}_median", unit)
    for metric, unit in _TURBOSTAT_UNITS.items()
)


def _turbostat_median(
    summaries: dict[tuple[str, int, str], dict[str, Any]],
    key: tuple[str, int, str],
    metric_name: str,
) -> Any:
    metric = metric_name.removeprefix("turbostat_cpu_").removesuffix("_median")
    return (summaries.get(key, {}).get("metrics", {}).get(metric) or {}).get("median")


def _read_probe_realtime_window(root: Path, trial: dict[str, Any]) -> tuple[float, float] | None:
    """Return the probe's host CLOCK_REALTIME measurement window in epoch seconds."""
    run_dir = trial.get("run_dir")
    if not run_dir:
        return None
    recorded_run_path = Path(str(run_dir))
    if recorded_run_path.is_absolute():
        run_path = recorded_run_path if recorded_run_path.is_dir() else None
    else:
        candidate = root / recorded_run_path
        run_path = candidate if candidate.is_dir() else None
    if run_path is None or not run_path.is_dir():
        return None
    probe_path = run_path / "probe.jsonl"
    if not probe_path.is_file():
        return None
    start_ns = end_ns = None
    try:
        with probe_path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("kind") == "start":
                    start_ns = record.get("realtime_ns")
                elif record.get("kind") == "end":
                    end_ns = record.get("realtime_ns")
    except OSError:
        return None
    if not isinstance(start_ns, int) or not isinstance(end_ns, int) or end_ns < start_ns:
        return None
    return start_ns / 1e9, end_ns / 1e9


def _parse_turbostat_rows(path: Path, cpu: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Read CPU rows from turbostat TSV, accepting its repeated table headers."""
    samples: list[dict[str, Any]] = []
    diagnostics = {"header_rows": 0, "malformed_rows": 0, "cpu_rows": 0}
    if not path.is_file():
        return samples, diagnostics
    header: list[str] | None = None
    try:
        with path.open(encoding="utf-8", errors="replace", newline="") as stream:
            for row in csv.reader(stream, delimiter="\t"):
                if not row or not any(cell.strip() for cell in row):
                    continue
                normalized = [cell.strip() for cell in row]
                if normalized[0] == "Time_Of_Day_Seconds" and "CPU" in normalized:
                    header = normalized
                    diagnostics["header_rows"] += 1
                    continue
                if header is None or len(normalized) != len(header):
                    diagnostics["malformed_rows"] += 1
                    continue
                item = dict(zip(header, normalized, strict=True))
                if item.get("CPU") != str(cpu):
                    continue
                diagnostics["cpu_rows"] += 1
                try:
                    timestamp = float(item["Time_Of_Day_Seconds"])
                except (KeyError, ValueError):
                    diagnostics["malformed_rows"] += 1
                    continue
                if not math.isfinite(timestamp):
                    diagnostics["malformed_rows"] += 1
                    continue
                numeric: dict[str, float] = {}
                for metric in _TURBOSTAT_METRICS:
                    value = item.get(metric)
                    if value in (None, "", "-"):
                        continue
                    try:
                        parsed = float(value)
                    except ValueError:
                        continue
                    if math.isfinite(parsed):
                        numeric[metric] = parsed
                samples.append({"timestamp_epoch_seconds": timestamp, "metrics": numeric})
    except OSError:
        return [], diagnostics
    samples.sort(key=lambda sample: sample["timestamp_epoch_seconds"])
    return samples, diagnostics


def _iso_epoch(epoch_seconds: float | None) -> str | None:
    if epoch_seconds is None:
        return None
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _summarize_turbostat_window(
    samples: list[dict[str, Any]], window: tuple[float, float] | None, cpu: int
) -> dict[str, Any]:
    if window is None:
        return {
            "status": "unavailable",
            "cpu": cpu,
            "sample_count": 0,
            "reason": "probe CLOCK_REALTIME start/end markers are unavailable",
        }
    start, end = window
    selected = [
        sample
        for sample in samples
        if start <= sample["timestamp_epoch_seconds"] <= end
    ]
    result: dict[str, Any] = {
        "status": "aligned" if selected else "no_samples_in_window",
        "cpu": cpu,
        "sample_count": len(selected),
        "probe_window_start_host_realtime_utc": _iso_epoch(start),
        "probe_window_end_host_realtime_utc": _iso_epoch(end),
        "sample_first_host_realtime_utc": _iso_epoch(
            selected[0]["timestamp_epoch_seconds"] if selected else None
        ),
        "sample_last_host_realtime_utc": _iso_epoch(
            selected[-1]["timestamp_epoch_seconds"] if selected else None
        ),
        "sample_label_span_seconds": (
            selected[-1]["timestamp_epoch_seconds"] - selected[0]["timestamp_epoch_seconds"]
            if len(selected) > 1
            else 0.0 if selected else None
        ),
        "metrics": {},
        "join_clock": "worker CLOCK_REALTIME probe markers matched to turbostat Time_Of_Day_Seconds",
        "join_limit": (
            "same-host wall-clock alignment at turbostat sampling resolution; this join is not an "
            "independent elapsed-time reference and can be affected by CLOCK_REALTIME adjustments"
        ),
    }
    for metric in _TURBOSTAT_METRICS:
        values = [sample["metrics"][metric] for sample in selected if metric in sample["metrics"]]
        if values:
            result["metrics"][metric] = _quantiles(values)
    return result


def analyze_turbostat_capture(
    root: Path, campaign: dict[str, Any]
) -> tuple[dict[str, Any] | None, dict[tuple[str, int, str], dict[str, Any]]]:
    capture = campaign.get("turbostat_capture")
    if not isinstance(capture, dict):
        return None, {}
    raw_path = _resolve_artifact(root, str(capture.get("output", "")))
    cpu = int(capture.get("cpu", campaign.get("design", {}).get("timerlat_cpu", 7)))
    samples, diagnostics = _parse_turbostat_rows(raw_path, cpu) if raw_path else ([], {
        "header_rows": 0,
        "malformed_rows": 0,
        "cpu_rows": 0,
    })
    try:
        raw_output_label = raw_path.relative_to(root).as_posix() if raw_path else capture.get("output")
    except ValueError:
        raw_output_label = str(raw_path)
    result: dict[str, Any] = {
        "capture_status": capture.get("status"),
        "cpu": cpu,
        "observer_process_state": capture.get("observer_process_state"),
        "observer_process_state_at_stop": capture.get("observer_process_state_at_stop"),
        "interval_seconds": capture.get("interval_seconds"),
        "raw_output": raw_output_label,
        "raw_output_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest() if raw_path else None,
        "raw_output_bytes": raw_path.stat().st_size if raw_path else None,
        "parsed_cpu_sample_count": len(samples),
        "parser_diagnostics": diagnostics,
        "time_semantics": (
            "Time_Of_Day_Seconds is a host wall-clock label used only to join CPU telemetry "
            "to the probe's CLOCK_REALTIME start/end markers"
        ),
    }
    summaries: dict[tuple[str, int, str], dict[str, Any]] = {}
    for trial in campaign.get("trials", []):
        window = _read_probe_realtime_window(root, trial)
        summary = _summarize_turbostat_window(samples, window, cpu)
        key = (str(trial.get("arm")), int(trial.get("replicate", 0)), str(trial.get("condition")))
        summaries[key] = summary
    return result, summaries


def _probe_value(
    run: dict[str, Any], metric: str, probe_cpu: int, timerlat_cpu: int
) -> float | None:
    if metric == "clockpressure_wakeup_p99":
        return run.get("wakeup_lateness_ns", {}).get("p99")
    if metric == "clockpressure_crossstamp_fit_rate":
        return (run.get("paired_crossstamp_dynamics") or {}).get("least_squares_rate_difference_ppm")
    if metric == "clockpressure_monotonic_vs_raw_rate":
        return (run.get("internal_rate_comparisons", {}).get("monotonic_vs_raw") or {}).get(
            "difference_ppm_vs_raw"
        )
    if metric in ("cpu_c9_aggregate_residency", "cpu_c10_aggregate_residency"):
        state = "C9" if metric == "cpu_c9_aggregate_residency" else "C10"
        return (
            run.get("environment_telemetry", {})
            .get("cpu_idle_residency_pct_of_cpu_capacity_by_state_name", {})
            .get(state)
        )
    if metric in (
        "probe_cpu_c9_residency",
        "probe_cpu_c10_residency",
        "timerlat_cpu_c9_residency",
        "timerlat_cpu_c10_residency",
    ):
        cpu = probe_cpu if metric.startswith("probe_") else timerlat_cpu
        state = "C9" if "_c9_" in metric else "C10"
        return (
            run.get("environment_telemetry", {})
            .get("cpu_idle_residency_pct_by_cpu_state_name", {})
            .get(f"cpu{cpu}", {})
            .get(state)
        )
    if metric == "probe_adjacent_sample_migrations":
        return run.get("sample_cpu_migrations_between_adjacent_samples")
    return None


def build_report(
    campaign: dict[str, Any],
    probe_summaries: dict[tuple[str, int, str], dict[str, Any]],
    timerlat_summaries: dict[tuple[str, int, str], dict[str, Any]],
    turbostat_summary: dict[str, Any] | None = None,
    turbostat_trial_summaries: dict[tuple[str, int, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    campaign_id = campaign["campaign_id"]
    design = campaign.get("design", {})
    probe_cpu = int(design.get("probe_cpu", 6))
    timerlat_cpu = int(design.get("timerlat_cpu", 7))
    turbostat_trial_summaries = turbostat_trial_summaries or {}
    probe_values: dict[str, dict[tuple[str, int, str], float]] = {
        metric: {} for metric in _PROBE_METRICS
    }
    for key, run in probe_summaries.items():
        for metric in _PROBE_METRICS:
            value = _probe_value(run, metric, probe_cpu, timerlat_cpu)
            if value is not None:
                probe_values[metric][key] = float(value)

    contrasts: list[dict[str, Any]] = []
    contrast_specs = (
        ("cpu_pressure", "pressure_minus_baseline"),
        ("recovery", "recovery_minus_baseline"),
    )
    probe_map = probe_values["clockpressure_wakeup_p99"]
    all_replicates = sorted(
        {replicate for _, replicate, _ in probe_map}
        | {replicate for _, replicate, _ in timerlat_summaries}
        | {replicate for _, replicate, _ in turbostat_trial_summaries}
    )
    design = campaign.get("design", {})
    arms = tuple(design.get("arms") or ("timerlat_disabled", "timerlat_user"))
    configured_timerlat_arms = design.get("timerlat_arms")
    if not configured_timerlat_arms or "timerlat_disabled" in configured_timerlat_arms:
        timerlat_arms = {arm for arm in arms if arm.startswith("timerlat_user")}
    else:
        timerlat_arms = set(configured_timerlat_arms)
    seed_base = sum(campaign_id.encode())

    for arm_index, arm in enumerate(arms):
        for condition, label in contrast_specs:
            metric_specs = [*list(_PROBE_METRICS.items()), *_TURBOSTAT_CONTRAST_METRICS]
            if arm in timerlat_arms:
                metric_specs.extend((f"timerlat_{kind}_p99", "ns") for kind in _TIMERLAT_KINDS)
            for metric_name, unit in metric_specs:
                values: list[float] = []
                if metric_name.startswith("timerlat_") and metric_name.endswith("_p99"):
                    kind = metric_name.removeprefix("timerlat_").removesuffix("_p99")
                    for replicate in all_replicates:
                        base_summary = timerlat_summaries.get((arm, replicate, "baseline"), {})
                        after_summary = timerlat_summaries.get((arm, replicate, condition), {})
                        base = base_summary.get(kind, {}).get("p99")
                        after = after_summary.get(kind, {}).get("p99")
                        if base is not None and after is not None:
                            values.append(float(after) - float(base))
                elif metric_name.startswith("turbostat_cpu_"):
                    for replicate in all_replicates:
                        base = _turbostat_median(
                            turbostat_trial_summaries, (arm, replicate, "baseline"), metric_name
                        )
                        after = _turbostat_median(
                            turbostat_trial_summaries, (arm, replicate, condition), metric_name
                        )
                        if base is not None and after is not None:
                            values.append(float(after) - float(base))
                else:
                    value_map = probe_values[metric_name]
                    for replicate in all_replicates:
                        base = value_map.get((arm, replicate, "baseline"))
                        after = value_map.get((arm, replicate, condition))
                        if base is not None and after is not None:
                            values.append(float(after) - float(base))
                if values:
                    contrasts.append(
                        {
                            "arm": arm,
                            "contrast": label,
                            "metric": metric_name,
                            **_metric_record(values, seed_base + arm_index * 31 + len(contrasts), unit),
                        }
                    )

    observer_effects = []
    if "timerlat_disabled" in arms and "timerlat_user" in arms:
        for condition in ("baseline", "cpu_pressure", "recovery"):
            differences = []
            for replicate in all_replicates:
                disabled = probe_map.get(("timerlat_disabled", replicate, condition))
                enabled = probe_map.get(("timerlat_user", replicate, condition))
                if disabled is not None and enabled is not None:
                    differences.append(enabled - disabled)
            if differences:
                observer_effects.append(
                    {
                        "condition": condition,
                        "contrast": "timerlat_user_minus_tracer_disabled",
                        "metric": "clockpressure_wakeup_p99",
                        **_metric_record(differences, seed_base + 500 + len(observer_effects), "ns"),
                    }
                )

    intervention_effects = []
    interaction_effects = []
    intervention = design.get("cpu_dma_latency_intervention")
    if intervention:
        default_arm = str(intervention.get("control_arm", "timerlat_user_default"))
        intervention_arm = str(intervention.get("arm", "timerlat_user_pm_qos"))
        metric_specs = (
            *list(_PROBE_METRICS.items()),
            *_TURBOSTAT_CONTRAST_METRICS,
            *((f"timerlat_{kind}_p99", "ns") for kind in _TIMERLAT_KINDS),
        )
        for condition in ("baseline", "cpu_pressure", "recovery"):
            for metric_name, unit in metric_specs:
                values = []
                for replicate in all_replicates:
                    if metric_name.startswith("timerlat_") and metric_name.endswith("_p99"):
                        kind = metric_name.removeprefix("timerlat_").removesuffix("_p99")
                        default = timerlat_summaries.get((default_arm, replicate, condition), {}).get(
                            kind, {}
                        ).get("p99")
                        treated = timerlat_summaries.get((intervention_arm, replicate, condition), {}).get(
                            kind, {}
                        ).get("p99")
                    elif metric_name.startswith("turbostat_cpu_"):
                        default = _turbostat_median(
                            turbostat_trial_summaries,
                            (default_arm, replicate, condition),
                            metric_name,
                        )
                        treated = _turbostat_median(
                            turbostat_trial_summaries,
                            (intervention_arm, replicate, condition),
                            metric_name,
                        )
                    else:
                        default = probe_values[metric_name].get((default_arm, replicate, condition))
                        treated = probe_values[metric_name].get((intervention_arm, replicate, condition))
                    if default is not None and treated is not None:
                        values.append(float(treated) - float(default))
                if values:
                    intervention_effects.append(
                        {
                            "condition": condition,
                            "control_arm": default_arm,
                            "intervention_arm": intervention_arm,
                            "contrast": "cpu_dma_latency_intervention_minus_control",
                            "metric": metric_name,
                            **_metric_record(
                                values,
                                seed_base + 700 + len(intervention_effects),
                                unit,
                            ),
                        }
                    )

        for metric_name, unit in metric_specs:
            differences = []
            for replicate in all_replicates:
                if metric_name.startswith("timerlat_") and metric_name.endswith("_p99"):
                    kind = metric_name.removeprefix("timerlat_").removesuffix("_p99")

                    def timer_value(arm: str, condition: str) -> Any:
                        return (
                            timerlat_summaries.get((arm, replicate, condition), {})
                            .get(kind, {})
                            .get("p99")
                        )

                    default_base = timer_value(default_arm, "baseline")
                    default_pressure = timer_value(default_arm, "cpu_pressure")
                    treated_base = timer_value(intervention_arm, "baseline")
                    treated_pressure = timer_value(intervention_arm, "cpu_pressure")
                elif metric_name.startswith("turbostat_cpu_"):
                    default_base = _turbostat_median(
                        turbostat_trial_summaries,
                        (default_arm, replicate, "baseline"),
                        metric_name,
                    )
                    default_pressure = _turbostat_median(
                        turbostat_trial_summaries,
                        (default_arm, replicate, "cpu_pressure"),
                        metric_name,
                    )
                    treated_base = _turbostat_median(
                        turbostat_trial_summaries,
                        (intervention_arm, replicate, "baseline"),
                        metric_name,
                    )
                    treated_pressure = _turbostat_median(
                        turbostat_trial_summaries,
                        (intervention_arm, replicate, "cpu_pressure"),
                        metric_name,
                    )
                else:
                    value_map = probe_values[metric_name]
                    default_base = value_map.get((default_arm, replicate, "baseline"))
                    default_pressure = value_map.get((default_arm, replicate, "cpu_pressure"))
                    treated_base = value_map.get((intervention_arm, replicate, "baseline"))
                    treated_pressure = value_map.get((intervention_arm, replicate, "cpu_pressure"))
                if all(
                    value is not None
                    for value in (default_base, default_pressure, treated_base, treated_pressure)
                ):
                    differences.append(
                        (float(treated_pressure) - float(treated_base))
                        - (float(default_pressure) - float(default_base))
                    )
            if differences:
                interaction_effects.append(
                    {
                        "condition": "cpu_pressure_minus_baseline",
                        "control_arm": default_arm,
                        "intervention_arm": intervention_arm,
                        "contrast": "difference_in_differences",
                        "metric": metric_name,
                        **_metric_record(
                            differences,
                            seed_base + 900 + len(interaction_effects),
                            unit,
                        ),
                    }
                )

    per_trial = []
    for trial in campaign.get("trials", []):
        arm = trial["arm"]
        replicate = trial["replicate"]
        condition = trial["condition"]
        run = probe_summaries.get((arm, replicate, condition), {})
        timer = timerlat_summaries.get((arm, replicate, condition), {}) if arm in timerlat_arms else {}
        turbostat = turbostat_trial_summaries.get((arm, replicate, condition))
        probe_metrics = {
            metric: _probe_value(run, metric, probe_cpu, timerlat_cpu)
            for metric in _PROBE_METRICS
        }
        per_trial.append(
            {
                "replicate": replicate,
                "arm": arm,
                "condition": condition,
                "trial_status": trial.get("status"),
                "trial_error": trial.get("error"),
                "run_id": run.get("run_id"),
                "probe_samples": run.get("samples"),
                "clockpressure_metrics": probe_metrics,
                "clockpressure_wakeup_p99_ns": probe_metrics["clockpressure_wakeup_p99"],
                "clockpressure_crossstamp_fit_rate_ppm": probe_metrics[
                    "clockpressure_crossstamp_fit_rate"
                ],
                "clockpressure_monotonic_vs_raw_rate_ppm": probe_metrics[
                    "clockpressure_monotonic_vs_raw_rate"
                ],
                "cpu_c10_aggregate_residency_pct": probe_metrics[
                    "cpu_c10_aggregate_residency"
                ],
                "cpu_c9_aggregate_residency_pct": probe_metrics[
                    "cpu_c9_aggregate_residency"
                ],
                "probe_cpu_c9_residency_pct": probe_metrics[
                    "probe_cpu_c9_residency"
                ],
                "probe_cpu_c10_residency_pct": probe_metrics[
                    "probe_cpu_c10_residency"
                ],
                "timerlat_cpu_c9_residency_pct": probe_metrics[
                    "timerlat_cpu_c9_residency"
                ],
                "timerlat_cpu_c10_residency_pct": probe_metrics[
                    "timerlat_cpu_c10_residency"
                ],
                "probe_adjacent_sample_migrations": probe_metrics[
                    "probe_adjacent_sample_migrations"
                ],
                "timerlat_p99_ns": {kind: data.get("p99") for kind, data in timer.items()},
                "run_integrity": run.get("integrity", {}),
                "timerlat_trace": trial.get("timerlat_trace"),
                "timerlat_trace_sha256": trial.get("timerlat_trace_sha256"),
                "timerlat_trace_integrity": trial.get("timerlat_trace_integrity"),
                "timerlat_activation_integrity": trial.get("timerlat_activation_integrity"),
                "timerlat_buffer_stats": _parse_trace_buffer_stats(
                    trial.get("tracefs_restoration", {}).get("cpu_buffer_stats")
                ) if arm in timerlat_arms else None,
                "timerlat_user_worker": trial.get("timerlat_user_worker") if arm in timerlat_arms else None,
                "cpu_dma_latency_request": trial.get("cpu_dma_latency_request"),
                "cpu_idle_transition_analysis": trial.get("cpu_idle_transition_summary"),
                "turbostat_cpu_telemetry": turbostat,
            }
        )

    timerlat_trials = [trial for trial in per_trial if trial["arm"] in timerlat_arms]
    trace_integrity_counts = {
        state: sum(trial.get("timerlat_trace_integrity") == state for trial in timerlat_trials)
        for state in ("ok", "mismatch", "missing")
    }
    timerlat_integrity = {
        "trace_integrity_counts": trace_integrity_counts,
        "matched_irq_thread_activations": sum(
            (trial.get("timerlat_activation_integrity") or {}).get(
                "matched_irq_thread_activations", 0
            )
            for trial in timerlat_trials
        ),
        "user_return_activations": sum(
            (trial.get("timerlat_activation_integrity") or {}).get(
                "user_return_activations", 0
            )
            for trial in timerlat_trials
        ),
        "incomplete_irq_thread_activations": sum(
            (trial.get("timerlat_activation_integrity") or {}).get(
                "incomplete_irq_thread_activations", 0
            )
            for trial in timerlat_trials
        ),
        "duplicate_activation_events": sum(
            (trial.get("timerlat_activation_integrity") or {}).get(
                "duplicate_activation_events", 0
            )
            for trial in timerlat_trials
        ),
        "malformed_latency_lines": sum(
            (trial.get("timerlat_activation_integrity") or {}).get(
                "malformed_latency_lines", 0
            )
            for trial in timerlat_trials
        ),
        "trace_buffer_overrun": sum(
            (trial.get("timerlat_buffer_stats") or {}).get("overrun", 0)
            for trial in timerlat_trials
        ),
        "trace_buffer_commit_overrun": sum(
            (trial.get("timerlat_buffer_stats") or {}).get("commit_overrun", 0)
            for trial in timerlat_trials
        ),
        "trace_buffer_dropped_events": sum(
            (trial.get("timerlat_buffer_stats") or {}).get("dropped_events", 0)
            for trial in timerlat_trials
        ),
    }

    return {
        "schema": "clockpressure.timerlat-campaign-analysis.v1",
        "campaign_id": campaign_id,
        "campaign_status": campaign.get("analysis_status", campaign.get("status")),
        "campaign_recorded_status": campaign.get("status"),
        "campaign_status_note": campaign.get("analysis_status_note"),
        "external_elapsed_time_reference": None,
        "clockrate_claim_allowed": False,
        "turbostat_capture": turbostat_summary,
        "observer_effects": observer_effects,
        "intervention_effects": intervention_effects,
        "interaction_effects": interaction_effects,
        "timerlat_integrity": timerlat_integrity,
        "paired_contrasts": contrasts,
        "per_trial": per_trial,
        "interpretation_limits": [
            "timerlat reports Linux interrupt, thread, and return-to-userspace latency; it is not an independent clock",
            "the pinned timerlat reader and FIFO scheduling policy add an observer workload on its selected CPU",
            "CLOCK_MONOTONIC wake lateness measures timer delivery and execution delay, not elapsed-time rate error",
            "bootstrap intervals resample paired run summaries and do not account for calibration uncertainty or campaign-to-campaign variation",
            "no calibrated independent elapsed-time reference is acquired by this campaign",
            *(
                [
                    "turbostat adds a periodic observer; its recorded CPU affinity and scheduling policy are part of the measurement condition"
                ]
                if turbostat_summary is not None
                else []
            ),
        ],
    }


def analyze_campaign(campaign_path: Path) -> dict[str, Any]:
    campaign_path = campaign_path.expanduser().resolve()
    campaign = json.loads(campaign_path.read_text())
    root = campaign_path.parent
    if campaign.get("schema") != "clockpressure.timerlat-campaign.v1":
        raise ValueError(f"unsupported campaign schema in {campaign_path}")
    incomplete_trials = [
        trial for trial in campaign.get("trials", []) if trial.get("status") != "complete"
    ]
    if campaign.get("status") == "complete" and incomplete_trials:
        campaign["analysis_status"] = "failed"
        campaign["analysis_status_note"] = (
            "one or more trial records are not complete even though the stored campaign status is complete; "
            "the analyzer treats this campaign as failed"
        )

    probe_summaries: dict[tuple[str, int, str], dict[str, Any]] = {}
    arms = campaign.get("design", {}).get("arms") or ("timerlat_disabled", "timerlat_user")
    configured_timerlat_arms = campaign.get("design", {}).get("timerlat_arms")
    if not configured_timerlat_arms or "timerlat_disabled" in configured_timerlat_arms:
        timerlat_arms = {arm for arm in arms if arm.startswith("timerlat_user")}
    else:
        timerlat_arms = set(configured_timerlat_arms)
    for arm in arms:
        run_root = root / "runs" / arm
        if not run_root.is_dir():
            continue
        report = analyze(run_root)
        (root / f"analysis-{arm}.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n"
        )
        for run in report["runs"]:
            replicate = run.get("replicate")
            condition = run.get("condition")
            if replicate is not None and condition is not None:
                probe_summaries[(arm, int(replicate), str(condition))] = run

    timerlat_summaries: dict[tuple[str, int, str], dict[str, Any]] = {}
    idle_tracepoint = campaign.get("design", {}).get("cpu_idle_tracepoint")
    idle_cpu = int(idle_tracepoint["cpu"]) if idle_tracepoint else None
    idle_state_names = {
        int(key): str(value)
        for key, value in (idle_tracepoint.get("state_names", {}) if idle_tracepoint else {}).items()
    }
    for trial in campaign.get("trials", []):
        arm = str(trial.get("arm"))
        if arm not in timerlat_arms:
            continue
        key = (arm, int(trial["replicate"]), str(trial["condition"]))
        recorded_trace = trial.get("timerlat_trace")
        trace_path = _resolve_artifact(root, recorded_trace) if recorded_trace else None
        if trace_path is None:
            trial["timerlat_trace_integrity"] = "missing"
            if trial.get("status") == "complete":
                raise ValueError(f"completed timerlat trial is missing its trace: {recorded_trace}")
            continue
        digest = hashlib.sha256(trace_path.read_bytes()).hexdigest()
        if digest != trial.get("timerlat_trace_sha256"):
            trial["timerlat_trace_integrity"] = "mismatch"
            raise ValueError(f"timerlat trace checksum mismatch: {trace_path}")
        trial["timerlat_trace_integrity"] = "ok"
        trial["timerlat_trace"] = trace_path.relative_to(root).as_posix()
        parsed = analyze_trace(trace_path)
        trial["timerlat_analysis_summary"] = parsed["latency_ns"]
        trial["timerlat_activation_integrity"] = {
            "matched_irq_thread_activations": parsed["matched_irq_thread_activation_count"],
            "user_return_activations": parsed["user_return_activation_count"],
            "incomplete_irq_thread_activations": parsed["incomplete_irq_thread_activation_count"],
            "duplicate_activation_events": parsed["duplicate_activation_event_count"],
            "malformed_latency_lines": parsed["malformed_latency_line_count"],
        }
        if idle_cpu is not None:
            idle_analysis = analyze_idle_transitions(
                trace_path,
                cpu=idle_cpu,
                state_names=idle_state_names,
            )
            trial["cpu_idle_transition_summary"] = idle_analysis
        timerlat_summaries[key] = parsed["latency_ns"]

    turbostat_summary, turbostat_trial_summaries = analyze_turbostat_capture(root, campaign)
    report = build_report(
        campaign,
        probe_summaries,
        timerlat_summaries,
        turbostat_summary,
        turbostat_trial_summaries,
    )
    (root / "timerlat-campaign-analysis.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    (root / "timerlat-campaign-analysis.md").write_text(_markdown(report))
    return report


def _format(value: Any) -> str:
    return "—" if value is None else f"{value:.6g}" if isinstance(value, (int, float)) else str(value)


def _markdown(report: dict[str, Any]) -> str:
    rows = []
    for trial in report["per_trial"]:
        timer = trial["timerlat_p99_ns"]
        rows.append(
            "| {replicate} | {arm} | {condition} | {samples} | {probe} | {irq} | {thread} | {user} | {crossstamp} | {mono_raw} | {c9} | {c10} | {probe_c9} | {probe_c10} | {timerlat_c9} | {timerlat_c10} | {migrations} |".format(
                replicate=trial["replicate"],
                arm=trial["arm"],
                condition=trial["condition"],
                samples=trial["probe_samples"] or "—",
                probe=_format(trial["clockpressure_wakeup_p99_ns"]),
                irq=_format(timer.get("irq")),
                thread=_format(timer.get("thread")),
                user=_format(timer.get("user_return")),
                crossstamp=_format(trial["clockpressure_crossstamp_fit_rate_ppm"]),
                mono_raw=_format(trial["clockpressure_monotonic_vs_raw_rate_ppm"]),
                c9=_format(trial["cpu_c9_aggregate_residency_pct"]),
                c10=_format(trial["cpu_c10_aggregate_residency_pct"]),
                probe_c9=_format(trial["probe_cpu_c9_residency_pct"]),
                probe_c10=_format(trial["probe_cpu_c10_residency_pct"]),
                timerlat_c9=_format(trial["timerlat_cpu_c9_residency_pct"]),
                timerlat_c10=_format(trial["timerlat_cpu_c10_residency_pct"]),
                migrations=_format(trial["probe_adjacent_sample_migrations"]),
            )
        )
    contrast_rows = [
        "| {arm} | {condition} | {metric} | {n} | {median} | {interval} |".format(
            arm=contrast.get(
                "arm",
                f"{contrast['control_arm']}→{contrast['intervention_arm']}"
                if "control_arm" in contrast
                else "both arms",
            ),
            condition=contrast.get("condition", contrast.get("contrast")),
            metric=contrast["metric"],
            n=contrast["paired_difference_n"],
            median=_format(contrast["paired_difference"].get("median")),
            interval=(
                f"{_format(contrast['mean_bootstrap_95_percent_interval'].get('lower_2_5_percent'))} to "
                f"{_format(contrast['mean_bootstrap_95_percent_interval'].get('upper_97_5_percent'))} {contrast['unit']}"
                if contrast.get("mean_bootstrap_95_percent_interval")
                else "not estimable (<3 pairs)"
            ),
        )
        for contrast in [
            *report["paired_contrasts"],
            *report["observer_effects"],
            *report["intervention_effects"],
            *report["interaction_effects"],
        ]
    ]
    turbostat_rows = []
    for trial in report["per_trial"]:
        telemetry = trial.get("turbostat_cpu_telemetry")
        if not telemetry:
            continue
        metrics = telemetry.get("metrics", {})
        medians = {name: metrics.get(name, {}).get("median") for name in _TURBOSTAT_METRICS}
        turbostat_rows.append(
            "| {replicate} | {arm} | {condition} | {status} | {n} | {busy} | {mhz} | {c10} | {watt} | {temp} |".format(
                replicate=trial["replicate"],
                arm=trial["arm"],
                condition=trial["condition"],
                status=telemetry.get("status"),
                n=telemetry.get("sample_count", 0),
                busy=_format(medians["Busy%"]),
                mhz=_format(medians["Bzy_MHz"]),
                c10=_format(medians["C10%"]),
                watt=_format(medians["PkgWatt"]),
                temp=_format(medians["PkgTmp"]),
            )
        )
    turbostat_section = []
    if report.get("turbostat_capture"):
        capture = report["turbostat_capture"]
        turbostat_section = [
            "## Turbostat CPU telemetry",
            "",
            f"Capture: `{capture.get('capture_status')}` on CPU {capture.get('cpu')}; "
            f"{capture.get('parsed_cpu_sample_count', 0)} parsed CPU rows from `{capture.get('raw_output')}`.",
            f"Sampler process state after the first sample: `{capture.get('observer_process_state')}`; "
            f"at shutdown: `{capture.get('observer_process_state_at_stop')}`. "
            "The recorded affinity is diagnostic; turbostat may migrate while reading per-CPU counters.",
            "",
            "Samples are joined to each probe's host CLOCK_REALTIME start/end markers. The 1-second (or configured) samples can straddle condition edges; wall-clock alignment is not an independent elapsed-time reference.",
            "",
            "| Replicate | Arm | Condition | Join | Samples | Busy% median | Bzy MHz median | C10% median | Package W median | Package °C median |",
            "| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            *turbostat_rows,
            "",
            "`Pkg%pc6` and `Pk%pc10` are retained in JSON when present; zero values do not establish that the corresponding package state was entered.",
            "",
        ]
    return "\n".join(
        [
            "# Timerlat controlled campaign analysis",
            "",
            f"Campaign: `{report['campaign_id']}` ({report['campaign_status']})",
            "",
            "All latency values are nanoseconds. Timerlat is a latency tracer, not an elapsed-time reference.",
            "",
            "## Per-trial outcomes",
            "",
            "| Replicate | Arm | Condition | Probe samples | ClockPressure wake P99 (ns) | Timerlat IRQ P99 (ns) | Thread P99 (ns) | User-return P99 (ns) | PHC/MONORAW fit (ppm) | MONOTONIC/RAW (ppm) | Aggregate C9 (%) | Aggregate C10 (%) | Probe CPU C9 (%) | Probe CPU C10 (%) | Timerlat CPU C9 (%) | Timerlat CPU C10 (%) | Probe migrations |",
            "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            *rows,
            "",
            "## Paired contrasts",
            "",
            "| Arm | Contrast | Metric | Matched runs | Median paired change | Descriptive 95% mean interval |",
            "| --- | --- | --- | ---: | ---: | ---: |",
            *contrast_rows,
            "",
            *turbostat_section,
            "## Interpretation limits",
            "",
            *[f"- {item}" for item in report["interpretation_limits"]],
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    args = parser.parse_args()
    report = analyze_campaign(args.campaign)
    print(
        f"analyzed campaign {report['campaign_id']} with {len(report['per_trial'])} trial records "
        f"(status: {report['campaign_status']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
