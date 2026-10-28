import json
import tempfile
import unittest
from pathlib import Path

from analysis.analyze_runs import (
    _bootstrap_mean_interval,
    _group_summaries,
    _period_errors,
    _paired_crossstamp_dynamics,
    _paired_crossstamp_rate,
    _paired_contrasts,
    _markdown,
    _fmt,
    _quantiles,
    _rate_comparison,
    _read_scheduler,
    _telemetry_summary,
)
from analysis.analyze_timerlat import analyze_trace


class TestAnalysis(unittest.TestCase):
    def test_report_format_preserves_small_rate_differences(self):
        self.assertEqual(_fmt(0.0000318755), "3.18755e-05")
        self.assertEqual(_fmt(434_529), "434529")

    def test_timerlat_trace_parser_pairs_irq_and_thread_samples_by_cpu(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace"
            path.write_text(
                "# tracer: timerlat\n"
                "<idle>-0 [000] d.h1. 1.0: #1 context irq timer_latency 20 ns\n"
                "<...>-12 [000] ....1 1.1: #1 context thread timer_latency 30 ns\n"
                "<...>-12 [000] ....1 1.2: #1 context user-ret timer_latency 40 ns\n"
                "<idle>-0 [001] d.h1. 1.0: #1 context irq timer_latency 40 ns\n"
                "<...>-13 [001] ....1 1.1: #1 context thread timer_latency 60 ns\n"
                "<idle>-0 [001] d.h1. 2.0: #2 context irq timer_latency 50 ns\n"
            )
            report = analyze_trace(path)
        self.assertEqual(report["latency_ns"]["irq"]["n"], 3)
        self.assertEqual(report["latency_ns"]["thread"]["n"], 2)
        self.assertEqual(report["latency_ns"]["user_return"]["median"], 40)
        self.assertEqual(report["latency_ns_by_cpu"]["000"]["thread"]["median"], 30)
        self.assertEqual(report["matched_irq_thread_activation_count"], 2)
        self.assertEqual(report["user_return_activation_count"], 1)
        self.assertEqual(report["incomplete_irq_thread_activation_count"], 1)
        self.assertEqual(report["duplicate_activation_event_count"], 0)
        self.assertEqual(report["malformed_latency_line_count"], 0)

    def test_paired_contrasts_cover_clock_timer_idle_and_recovery_metrics(self):
        runs = []
        for replicate in (1, 2, 3):
            for condition, wake, fit, c10 in (
                ("baseline", 1_000 + replicate * 100, 0.2 + replicate * 0.01, 90 + replicate),
                ("cpu_pressure", 600 + replicate * 100, 0.19 + replicate * 0.01, 40 + replicate),
                ("recovery", 1_020 + replicate * 100, 0.201 + replicate * 0.01, 91 + replicate),
            ):
                runs.append(
                    {
                        "campaign_id": "campaign-test",
                        "replicate": replicate,
                        "condition": condition,
                        "observer": "none",
                        "wakeup_lateness_ns": {"p99": wake},
                        "sample_cpu_migrations_between_adjacent_samples": {
                            "baseline": 10 + replicate,
                            "cpu_pressure": 2 + replicate,
                            "recovery": 3 + replicate,
                        }[condition],
                        "paired_crossstamp_dynamics": {
                            "least_squares_rate_difference_ppm": fit,
                        },
                        "environment_telemetry": {
                            "cpu_idle_residency_pct_of_cpu_capacity_by_state_name": {
                                "C10": c10,
                            },
                            "cpu_idle_residency_pct_by_cpu_state_name": {
                                "cpu7": {"C10": c10 - 10},
                            },
                        },
                    }
                )

        contrasts = _paired_contrasts(runs)
        indexed = {
            (item["contrast"], item["metric"]): item
            for item in contrasts
        }
        pressure_clock = indexed[
            ("cpu_pressure_minus_baseline", "paired_crossstamp_time_series_rate_difference")
        ]
        self.assertEqual(pressure_clock["paired_difference_n"], 3)
        self.assertAlmostEqual(pressure_clock["paired_difference"]["median"], -0.01)
        self.assertEqual(pressure_clock["unit"], "ppm")

        pressure_migrations = indexed[
            ("cpu_pressure_minus_baseline", "adjacent_sample_cpu_migrations")
        ]
        self.assertEqual(pressure_migrations["paired_difference"]["median"], -8)
        self.assertEqual(pressure_migrations["unit"], "count")

        pressure_c10 = indexed[("cpu_pressure_minus_baseline", "cpu_c10_idle_residency")]
        self.assertEqual(pressure_c10["paired_difference"]["median"], -50)
        self.assertEqual(pressure_c10["unit"], "percentage_points")
        pressure_cpu7 = indexed[("cpu_pressure_minus_baseline", "cpu_c10_idle_residency_cpu7")]
        self.assertEqual(pressure_cpu7["paired_difference"]["median"], -50)

        recovery_wake = indexed[("recovery_minus_baseline", "run_p99_wakeup_lateness")]
        self.assertEqual(recovery_wake["paired_difference"]["median"], 20)
        recovery_c10 = indexed[("recovery_minus_baseline", "cpu_c10_idle_residency")]
        self.assertEqual(recovery_c10["paired_difference"]["median"], 1)
        recovery_cpu7 = indexed[("recovery_minus_baseline", "cpu_c10_idle_residency_cpu7")]
        self.assertEqual(recovery_cpu7["paired_difference"]["median"], 1)

        markdown = _markdown(
            {
                "runs": [],
                "environment_group_summaries": [],
                "paired_contrasts": contrasts,
            }
        )
        self.assertIn("cpu_c10_idle_residency (percentage_points)", markdown)
        self.assertIn("cpu_c10_idle_residency_cpu7 (percentage_points)", markdown)
        self.assertIn("adjacent_sample_cpu_migrations (count)", markdown)
        self.assertIn("recovery_minus_baseline", markdown)

    def test_quantiles_use_nearest_rank_and_report_count(self):
        self.assertEqual(
            _quantiles([4, 1, 3, 2]),
            {"n": 4, "min": 1, "median": 2.5, "p95": 4, "p99": 4, "max": 4},
        )

    def test_internal_rate_comparison_keeps_endpoint_bracket_bound(self):
        start = {"monotonic_raw_ns": 10_000, "monotonic_ns": 10_100, "read_bracket_ns": 30}
        end = {"monotonic_raw_ns": 1_010_000, "monotonic_ns": 1_010_105, "read_bracket_ns": 40}
        result = _rate_comparison(start, end, "monotonic_ns")
        self.assertIsNotNone(result)
        self.assertEqual(result["difference_ppm_vs_raw"], 5)
        self.assertEqual(result["endpoint_read_bracket_bound_ppm"], 70)

    def test_paired_crossstamp_rate_uses_matched_device_and_system_times(self):
        result = _paired_crossstamp_rate(
            {
                "ptp_precise_ns": 1_000_000,
                "ptp_precise_sys_monoraw_ns": 2_000_000,
                "ptp_precise_sys_realtime_ns": 30_000_000,
            },
            {
                "ptp_precise_ns": 10_999_900,
                "ptp_precise_sys_monoraw_ns": 12_000_000,
                "ptp_precise_sys_realtime_ns": 40_000_200,
            },
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["difference_ppm_vs_paired_sys_monoraw"], -10)
        self.assertEqual(result["capture_method"], "PTP_SYS_OFFSET_PRECISE")
        self.assertIn("not quantified", result["capture_uncertainty"])
        self.assertEqual(result["sys_realtime_minus_paired_sys_monoraw_ppm"], 20)

    def test_crossstamp_dynamics_fits_offset_slope_from_paired_samples(self):
        records = [
            {"kind": "start", "ptp_precise_sys_monoraw_ns": 1_000_000_000, "ptp_precise_ns": 9_000_000_000},
            {"kind": "sample", "ptp_precise_sys_monoraw_ns": 2_000_000_000, "ptp_precise_ns": 9_999_998_000},
            {"kind": "sample", "ptp_precise_sys_monoraw_ns": 3_000_000_000, "ptp_precise_ns": 10_999_996_000},
            {"kind": "end", "ptp_precise_sys_monoraw_ns": 4_000_000_000, "ptp_precise_ns": 11_999_994_000},
        ]
        result = _paired_crossstamp_dynamics(records)
        self.assertIsNotNone(result)
        self.assertEqual(result["least_squares_rate_difference_ppm"], -2)
        self.assertEqual(result["offset_span_ns"], 6_000)
        self.assertEqual(result["absolute_fit_residual_ns"]["max"], 0)

    def test_sample_period_error_uses_skipped_sequence_delta(self):
        samples = [
            {"seq": 0, "monotonic_ns": 100_000},
            {"seq": 1, "monotonic_ns": 110_100},
            {"seq": 3, "monotonic_ns": 130_200},
        ]
        self.assertEqual(_period_errors(samples, 10_000, "monotonic_ns"), [10_000, 5_000])

    def test_bootstrap_interval_requires_independent_run_pairs(self):
        self.assertIsNone(_bootstrap_mean_interval([1, 2], 42))
        interval = _bootstrap_mean_interval([1, 2, 3], 42)
        self.assertIsNotNone(interval)
        self.assertLessEqual(interval["lower_2_5_percent"], 2)
        self.assertGreaterEqual(interval["upper_97_5_percent"], 2)
        self.assertEqual(interval, _bootstrap_mean_interval([1, 2, 3], 42))

    def test_group_summary_reads_named_internal_rate_comparisons(self):
        summary = _group_summaries(
            [
                {
                    "condition": "baseline",
                    "observer": "none",
                    "wakeup_lateness_ns": {"p99": 500},
                    "internal_rate_comparisons": {
                        "monotonic_vs_raw": {"difference_ppm_vs_raw": 4.5},
                        "ptp_vs_raw": {"difference_ppm_vs_raw": -12.0},
                    },
                }
            ]
        )
        self.assertEqual(summary[0]["run_monotonic_minus_raw_ppm"]["median"], 4.5)
        self.assertEqual(summary[0]["run_ptp_minus_raw_ppm"]["median"], -12.0)

    def test_scheduler_parser_ignores_empty_trailing_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scheduler.jsonl"
            path.write_text(
                '{"kind":"observer_start"}\n'
                '{"kind":"sched_runnable_to_run","runnable_latency_ns":123}\n\n\n'
            )
            summary, _ = _read_scheduler(path)
        self.assertEqual(summary["event_count"], 1)
        self.assertEqual(summary["malformed_line_count"], 0)
        self.assertEqual(summary["runnable_latency_ns"]["p99"], 123)

    def test_telemetry_summary_parses_physical_units_and_service_delta(self):
        records = [
            {
                "monotonic_raw_ns_before": 1_000_000_000,
                "snapshot_bracket_ns": 200,
                "cpuidle_states": {
                    "cpu0": {"state8": {"name": "C10", "time_usec": 1_000_000, "usage": 100}},
                    "cpu1": {"state8": {"name": "C10", "time_usec": 2_000_000, "usage": 200}},
                },
                "temperatures": {
                    "thermal_zone2": {
                        "type": "x86_pkg_temp",
                        "temp_millidegree_c": "41000",
                    }
                },
                "frequencies_khz": {"policy0": {"cpuinfo_avg_freq": "3000000"}},
                "pressure_stall_information": {
                    "cpu": "some avg10=1.25 avg60=0.50 avg300=0.10 total=100"
                },
                "sensetrace_service_cgroup": {
                    "cpu_stat": {"usage_usec": "1000"},
                    "memory_current_bytes": "4096",
                },
            },
            {
                "monotonic_raw_ns_before": 3_000_000_000,
                "snapshot_bracket_ns": 400,
                "cpuidle_states": {
                    "cpu0": {"state8": {"name": "C10", "time_usec": 1_500_000, "usage": 150}},
                    "cpu1": {"state8": {"name": "C10", "time_usec": 2_250_000, "usage": 225}},
                },
                "temperatures": {
                    "thermal_zone2": {
                        "type": "x86_pkg_temp",
                        "temp_millidegree_c": "43000",
                    }
                },
                "frequencies_khz": {"policy0": {"cpuinfo_avg_freq": "3600000"}},
                "pressure_stall_information": {
                    "cpu": "some avg10=2.50 avg60=1.00 avg300=0.20 total=200"
                },
                "sensetrace_service_cgroup": {
                    "cpu_stat": {"usage_usec": "1800"},
                    "memory_current_bytes": "8192",
                },
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "telemetry.jsonl"
            path.write_text("".join(json.dumps(record) + "\n" for record in records))
            summary = _telemetry_summary(path)
        self.assertEqual(summary["sample_count"], 2)
        self.assertEqual(summary["package_temperature_c"]["max"], 43)
        self.assertEqual(summary["frequency_khz_by_policy"]["policy0"]["median"], 3_300_000)
        self.assertEqual(summary["pressure_stall_avg10_pct"]["cpu"]["some"]["max"], 2.5)
        self.assertEqual(summary["sensetrace_service_cpu_usage_delta_usec"], 800)
        self.assertEqual(summary["cpu_idle_residency_delta_usec_by_state_name"]["C10"], 750_000)
        self.assertEqual(summary["cpu_idle_residency_pct_of_cpu_capacity_by_state_name"]["C10"], 18.75)
        self.assertEqual(summary["cpu_idle_residency_pct_by_cpu_state_name"]["cpu0"]["C10"], 25)
        self.assertEqual(summary["cpu_idle_residency_pct_by_cpu_state_name"]["cpu1"]["C10"], 12.5)
