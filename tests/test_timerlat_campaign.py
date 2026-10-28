import hashlib
import argparse
import json
import os
import struct
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from analysis.analyze_timerlat_campaign import analyze_campaign, build_report
import experiments.run_timerlat_campaign as timerlat_runner
from experiments.run_timerlat_campaign import (
    CpuDmaLatencyRequest,
    TracefsTimerlat,
    _empty_trace,
    _normalized_event_filter,
    _option_enabled,
)


class TestTimerlatCampaignAnalysis(unittest.TestCase):
    def test_pairs_probe_and_timerlat_metrics_by_arm_and_replicate(self):
        campaign = {
            "campaign_id": "fixture-campaign",
            "status": "complete",
            "design": {"probe_cpu": 6, "timerlat_cpu": 7},
            "trials": [
                {
                    "replicate": 1,
                    "arm": "timerlat_user",
                    "condition": "baseline",
                    "timerlat_trace": "baseline.trace",
                    "timerlat_trace_sha256": "abc",
                }
            ],
        }
        probe = {}
        for arm in ("timerlat_disabled", "timerlat_user"):
            for replicate in (1, 2):
                baseline = 100 if arm == "timerlat_disabled" else 110
                for condition, delta in (
                    ("baseline", 0),
                    ("cpu_pressure", -2 if arm == "timerlat_disabled" else -4),
                    ("recovery", 0),
                ):
                    probe[(arm, replicate, condition)] = {
                        "run_id": f"{arm}-{replicate}-{condition}",
                        "samples": 100,
                        "wakeup_lateness_ns": {"p99": baseline + delta},
                        "paired_crossstamp_dynamics": {
                            "least_squares_rate_difference_ppm": -0.3 + (0.00002 if condition == "cpu_pressure" else 0)
                        },
                        "internal_rate_comparisons": {
                            "monotonic_vs_raw": {"difference_ppm_vs_raw": -11.5}
                        },
                        "environment_telemetry": {
                            "cpu_idle_residency_pct_of_cpu_capacity_by_state_name": {
                                "C9": 2 if condition != "cpu_pressure" else 5,
                                "C10": 95 if condition == "baseline" else 50 if condition == "cpu_pressure" else 95,
                            },
                            "cpu_idle_residency_pct_by_cpu_state_name": {
                                "cpu6": {
                                    "C9": 20 if condition != "cpu_pressure" else 30,
                                    "C10": 80 if condition != "cpu_pressure" else 90,
                                },
                                "cpu7": {
                                    "C9": 10 if condition != "cpu_pressure" else 15,
                                    "C10": 95 if condition != "cpu_pressure" else 70,
                                },
                            },
                        },
                        "sample_cpu_migrations_between_adjacent_samples": 0,
                        "integrity": {"probe.jsonl": "ok"},
                    }
        timerlat = {}
        for replicate in (1, 2):
            for condition, irq in (("baseline", 100), ("cpu_pressure", 140), ("recovery", 105)):
                timerlat[("timerlat_user", replicate, condition)] = {
                    "irq": {"p99": irq},
                    "thread": {"p99": irq + 10},
                    "user_return": {"p99": irq + 20},
                }

        report = build_report(campaign, probe, timerlat)
        contrasts = {
            (item.get("arm"), item["contrast"], item["metric"]): item
            for item in report["paired_contrasts"]
        }
        self.assertEqual(
            contrasts[("timerlat_disabled", "pressure_minus_baseline", "clockpressure_wakeup_p99")][
                "paired_difference"]["median"
            ],
            -2,
        )
        self.assertEqual(
            contrasts[("timerlat_user", "pressure_minus_baseline", "timerlat_irq_p99")][
                "paired_difference"]["median"
            ],
            40,
        )
        self.assertAlmostEqual(
            contrasts[("timerlat_disabled", "pressure_minus_baseline", "clockpressure_crossstamp_fit_rate")][
                "paired_difference"]["median"
            ],
            0.00002,
        )
        self.assertEqual(
            contrasts[("timerlat_disabled", "pressure_minus_baseline", "cpu_c10_aggregate_residency")][
                "paired_difference"]["median"
            ],
            -45,
        )
        self.assertEqual(
            contrasts[("timerlat_user", "pressure_minus_baseline", "probe_cpu_c10_residency")][
                "paired_difference"]["median"
            ],
            10,
        )
        self.assertEqual(
            contrasts[("timerlat_user", "pressure_minus_baseline", "timerlat_cpu_c10_residency")][
                "paired_difference"]["median"
            ],
            -25,
        )
        self.assertEqual(
            contrasts[("timerlat_user", "pressure_minus_baseline", "probe_cpu_c9_residency")][
                "paired_difference"]["median"
            ],
            10,
        )
        self.assertEqual(
            report["observer_effects"][0]["paired_difference"]["median"],
            10,
        )
        self.assertEqual(report["per_trial"][0]["timerlat_trace_sha256"], "abc")


class TestTracefsHelpers(unittest.TestCase):
    def test_normalizes_stale_tracefs_filter_diagnostics(self):
        self.assertEqual(
            _normalized_event_filter("none\n ^\nparse_error: Field not found: cpu_id\n"),
            "none",
        )
        self.assertEqual(
            _normalized_event_filter("cpu_id == 7\n ^\nparse_error: stale\n"),
            "cpu_id == 7",
        )
        self.assertIsNone(_normalized_event_filter(None))

    def test_cpu_idle_tracepoint_filter_is_enabled_and_restored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = {
                "current_tracer": "nop\n",
                "tracing_on": "1\n",
                "buffer_size_kb": "7\n",
                "trace_clock": "local global counter\n",
                "available_tracers": "nop timerlat\n",
                "set_event": "\n",
                "trace": "# entries-in-buffer/entries-written: 0/0 #P:8\n",
                "osnoise/options": "NO_OSNOISE_WORKLOAD\n",
                "osnoise/cpus": "0-7\n",
                "osnoise/timerlat_period_us": "1000\n",
                "events/power/cpu_idle/enable": "0\n",
                "events/power/cpu_idle/filter": "none\n",
                "osnoise/per_cpu/cpu7/timerlat_fd": "",
                "per_cpu/cpu7/stats": "entries: 0\noverrun: 0\n",
            }
            for relative, value in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value)

            before = {
                "current_tracer": "nop",
                "tracing_on": "1",
                "buffer_size_kb": "7",
                "trace_clock": "local global counter",
                "timerlat_period_us": "1000",
                "osnoise_cpus": "0-7",
                "osnoise_workload_enabled": False,
                "osnoise_options_raw": "NO_OSNOISE_WORKLOAD",
                "enabled_events": "",
                "cpu_idle_event_enabled": "0",
                "cpu_idle_event_filter": "none",
                "trace_empty": True,
            }
            with mock.patch.object(
                TracefsTimerlat,
                "_settings",
                side_effect=[before, before.copy()],
            ):
                tracefs = TracefsTimerlat(root, 7, 10000, 64, cpu_idle_cpu=7)
                tracefs.start()
                self.assertEqual((root / "events/power/cpu_idle/enable").read_text().strip(), "1")
                self.assertEqual(
                    (root / "events/power/cpu_idle/filter").read_text().strip(),
                    "cpu_id == 7",
                )
                result = tracefs.stop_and_restore()

            self.assertTrue(result["restored"])
            self.assertEqual((root / "events/power/cpu_idle/enable").read_text().strip(), "0")
            self.assertEqual((root / "events/power/cpu_idle/filter").read_text().strip(), "0")
            self.assertEqual((root / "current_tracer").read_text().strip(), "nop")
            self.assertEqual((root / "tracing_on").read_text().strip(), "1")

    def test_restore_error_names_path_and_keeps_collected_trace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = {
                "current_tracer": "nop\n",
                "tracing_on": "1\n",
                "buffer_size_kb": "7\n",
                "trace_clock": "local global counter\n",
                "available_tracers": "nop timerlat\n",
                "set_event": "\n",
                "trace": "# entries-in-buffer/entries-written: 0/0 #P:8\n",
                "osnoise/options": "NO_OSNOISE_WORKLOAD\n",
                "osnoise/cpus": "0-7\n",
                "osnoise/timerlat_period_us": "1000\n",
                "events/power/cpu_idle/enable": "0\n",
                "events/power/cpu_idle/filter": "none\n",
                "osnoise/per_cpu/cpu7/timerlat_fd": "",
                "per_cpu/cpu7/stats": "entries: 0\noverrun: 0\n",
            }
            for relative, value in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value)

            tracefs = TracefsTimerlat(root, 7, 10000, 64, cpu_idle_cpu=7)
            tracefs.changed = True
            (root / "current_tracer").write_text("timerlat\n")
            (root / "tracing_on").write_text("1\n")
            (root / "events/power/cpu_idle/enable").write_text("1\n")
            (root / "events/power/cpu_idle/filter").write_text("cpu_id == 7\n")
            (root / "trace").write_text("captured trace evidence\n")

            real_write = timerlat_runner._write

            def fail_filter_reset(path, value):
                if path == root / "events/power/cpu_idle/filter" and value == "0":
                    raise OSError(22, "invalid argument")
                if path == root / "trace" and value == "":
                    path.write_text("# entries-in-buffer/entries-written: 0/0 #P:8\n")
                    return
                real_write(path, value)

            with mock.patch.object(timerlat_runner, "_write", side_effect=fail_filter_reset):
                result = tracefs.stop_and_restore()

        self.assertEqual(result["trace"], "captured trace evidence\n")
        self.assertFalse(result["restored"])
        self.assertTrue(
            any("events/power/cpu_idle/filter" in error and "invalid argument" in error
                for error in result["errors"])
        )

    def test_trace_empty_requires_zero_entries_written(self):
        self.assertTrue(_empty_trace("# entries-in-buffer/entries-written: 0/0 #P:8\n"))
        self.assertFalse(_empty_trace("# entries-in-buffer/entries-written: 0/4 #P:8\n"))
        self.assertFalse(_empty_trace("trace has no recognizable buffer summary"))

    def test_option_state_respects_negative_token(self):
        self.assertTrue(_option_enabled("DEFAULTS OSNOISE_WORKLOAD", "OSNOISE_WORKLOAD"))
        self.assertFalse(_option_enabled("DEFAULTS NO_OSNOISE_WORKLOAD", "OSNOISE_WORKLOAD"))
        self.assertFalse(_option_enabled("DEFAULTS NO_OSNOISE_WORKLOAD OSNOISE_WORKLOAD", "OSNOISE_WORKLOAD"))

    def test_campaign_analysis_reparses_checksumming_raw_trace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            trace_dir = root / "timerlat" / "timerlat_user"
            trace_dir.mkdir(parents=True)
            trace = trace_dir / "sample.trace"
            trace.write_text(
                "<idle>-0 [007] d.h1. 1.0: #1 context irq timer_latency 20 ns\n"
                "<...>-12 [007] ....1 1.1: #1 context thread timer_latency 30 ns\n"
                "<idle>-0 [007] d.h1. 2.0: #2 context irq timer_latency 25 ns\n"
                "<...>-12 [007] ....1 2.1: #2 context thread timer_latency 35 ns\n"
                "<...>-12 [007] ....1 2.2: #2 context user-ret timer_latency 40 ns\n"
            )
            campaign_path = root / "campaign.json"
            campaign_path.write_text(
                json.dumps(
                    {
                        "schema": "clockpressure.timerlat-campaign.v1",
                        "campaign_id": "raw-trace-fixture",
                        "status": "complete",
                        "trials": [
                            {
                                "arm": "timerlat_user",
                                "condition": "baseline",
                                "replicate": 1,
                                "status": "complete",
                                "timerlat_trace": "/worker/archive/timerlat/timerlat_user/sample.trace",
                                "timerlat_trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
                                "timerlat_analysis_summary": {"irq": {"p99": 999}},
                                "tracefs_restoration": {
                                    "cpu_buffer_stats": "entries: 4\noverrun: 0\ncommit overrun: 0\ndropped events: 0\n"
                                },
                            }
                        ],
                    }
                )
            )

            report = analyze_campaign(campaign_path)
            result = report["per_trial"][0]
            self.assertEqual(result["timerlat_trace_integrity"], "ok")
            self.assertEqual(result["timerlat_p99_ns"]["irq"], 25)
            self.assertEqual(result["timerlat_p99_ns"]["thread"], 35)
            self.assertEqual(result["timerlat_activation_integrity"]["matched_irq_thread_activations"], 2)
            self.assertEqual(result["timerlat_buffer_stats"]["overrun"], 0)
            self.assertEqual(report["timerlat_integrity"]["trace_buffer_dropped_events"], 0)
            self.assertEqual(report["timerlat_integrity"]["user_return_activations"], 1)

    def test_campaign_analysis_joins_cpu_idle_state_to_timerlat_irq(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            trace_dir = root / "timerlat" / "timerlat_user"
            trace_dir.mkdir(parents=True)
            trace = trace_dir / "sample.trace"
            trace.write_text(
                "swapper/7-0 [007] .... 1.000000: cpu_idle: state=8 cpu_id=7\n"
                "<idle>-0 [007] d.h1. 1.000100: #1 context irq timer_latency 30000 ns\n"
                "<...>-12 [007] ....1 1.000110: #1 context thread timer_latency 31000 ns\n"
                "<...>-12 [007] ....1 1.000120: #1 context user-ret timer_latency 32000 ns\n"
                "swapper/7-0 [007] .... 1.000200: cpu_idle: state=4294967295 cpu_id=7\n"
            )
            campaign_path = root / "campaign.json"
            campaign_path.write_text(
                json.dumps(
                    {
                        "schema": "clockpressure.timerlat-campaign.v1",
                        "campaign_id": "idle-transition-fixture",
                        "status": "complete",
                        "design": {
                            "arms": ["timerlat_user"],
                            "timerlat_arms": ["timerlat_user"],
                            "cpu_idle_tracepoint": {
                                "event": "power:cpu_idle",
                                "cpu": 7,
                                "state_names": {"8": "C10"},
                            },
                        },
                        "trials": [
                            {
                                "arm": "timerlat_user",
                                "condition": "baseline",
                                "replicate": 1,
                                "status": "complete",
                                "timerlat_trace": "timerlat/timerlat_user/sample.trace",
                                "timerlat_trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
                            }
                        ],
                    }
                )
            )

            report = analyze_campaign(campaign_path)

        idle = report["per_trial"][0]["cpu_idle_transition_analysis"]
        self.assertEqual(idle["timerlat_irq_events"], 1)
        self.assertEqual(idle["matched_idle_state_activations"], 1)
        self.assertEqual(idle["per_state"][0]["state_name"], "C10")
        self.assertEqual(idle["per_state"][0]["timerlat_irq_latency_ns"]["p99"], 30000)

    def test_analyzer_flags_complete_manifest_with_failed_trial(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign_path = root / "campaign.json"
            campaign_path.write_text(
                json.dumps(
                    {
                        "schema": "clockpressure.timerlat-campaign.v1",
                        "campaign_id": "misreported-failure",
                        "status": "complete",
                        "design": {
                            "arms": ["timerlat_user"],
                            "timerlat_arms": ["timerlat_user"],
                        },
                        "trials": [
                            {
                                "arm": "timerlat_user",
                                "condition": "baseline",
                                "replicate": 1,
                                "status": "failed",
                                "error": "thermal stop",
                            }
                        ],
                    }
                )
            )

            report = analyze_campaign(campaign_path)

            self.assertEqual(report["campaign_status"], "failed")
            self.assertEqual(report["campaign_recorded_status"], "complete")
            self.assertEqual(report["per_trial"][0]["trial_status"], "failed")

    def test_campaign_failure_is_not_overwritten_as_complete(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = argparse.Namespace(
                design="observer",
                duration_sec=1,
                period_us=100,
                repeats=1,
                cpu_load_workers=4,
                load_cpus=[1, 2, 3, 4],
                probe_cpu=6,
                timerlat_cpu=7,
                recovery_seconds=0,
                warmup_sec=0,
                fifo_priority=90,
                buffer_kb=64,
                seed=42,
                host_alias="test-host",
                tracefs_root="/tmp/tracefs-test",
                cpu_dma_latency_path="/dev/cpu_dma_latency",
                dma_latency_us=0,
                control_dma_latency_us=None,
                intertrial_cooldown_sec=0,
                data_dir=str(Path(temporary) / "campaign"),
            )
            tracefs = mock.MagicMock()
            tracefs.before = {"current_tracer": "nop"}
            with (
                mock.patch.object(timerlat_runner.os, "geteuid", return_value=0),
                mock.patch.object(timerlat_runner.os, "sched_getaffinity", return_value=set(range(8))),
                mock.patch.object(timerlat_runner, "TracefsTimerlat", return_value=tracefs),
                mock.patch.object(timerlat_runner, "snapshot_environment", return_value={}),
                mock.patch.object(
                    timerlat_runner.subprocess,
                    "run",
                    return_value=mock.Mock(stdout="deadbeef\n"),
                ),
                mock.patch.object(
                    timerlat_runner,
                    "_run_trial",
                    return_value={"status": "failed", "error": "thermal stop"},
                ),
            ):
                campaign_path = timerlat_runner.run_campaign(args)

            campaign = json.loads(campaign_path.read_text())
            self.assertEqual(campaign["status"], "failed")
            self.assertEqual(campaign["trials"][0]["status"], "failed")

    def test_qos_campaign_compares_two_active_request_arms(self):
        campaign = {
            "campaign_id": "qos-fixture",
            "status": "complete",
            "design": {
                "arms": ["timerlat_user_pm_qos_control", "timerlat_user_pm_qos"],
                "timerlat_arms": ["timerlat_user_pm_qos_control", "timerlat_user_pm_qos"],
                "cpu_dma_latency_intervention": {
                    "arm": "timerlat_user_pm_qos",
                    "control_arm": "timerlat_user_pm_qos_control",
                    "requested_us": 800,
                    "control_requested_us": 1000,
                },
            },
            "trials": [],
        }
        probes = {}
        timers = {}
        for arm, delta in (
            ("timerlat_user_pm_qos_control", 0),
            ("timerlat_user_pm_qos", -100),
        ):
            for condition, condition_delta in (("baseline", 0), ("cpu_pressure", -10), ("recovery", 0)):
                probes[(arm, 1, condition)] = {
                    "wakeup_lateness_ns": {"p99": 1000 + delta + condition_delta},
                    "paired_crossstamp_dynamics": {"least_squares_rate_difference_ppm": -0.3},
                    "integrity": {},
                }
                timers[(arm, 1, condition)] = {
                    "irq": {"p99": 300 + delta + condition_delta},
                    "thread": {"p99": 350 + delta + condition_delta},
                    "user_return": {"p99": 400 + delta + condition_delta},
                }
        report = build_report(campaign, probes, timers)
        effects = {
            (item["condition"], item["metric"]): item
            for item in report["intervention_effects"]
        }
        self.assertEqual(
            effects[("baseline", "clockpressure_wakeup_p99")]["paired_difference"]["median"],
            -100,
        )
        self.assertEqual(
            effects[("baseline", "timerlat_irq_p99")]["paired_difference"]["median"],
            -100,
        )
        interactions = {item["metric"]: item for item in report["interaction_effects"]}
        self.assertEqual(
            interactions["clockpressure_wakeup_p99"]["paired_difference"]["median"],
            0,
        )
        self.assertEqual(
            interactions["timerlat_irq_p99"]["paired_difference"]["median"],
            0,
        )

    def test_cpu_dma_latency_request_is_applied_and_released(self):
        effective = {"value": 2_000_000_000}

        def fake_open(_path, flags):
            return 11 if flags & os.O_RDWR else 10

        def fake_read(_fd, _length):
            return struct.pack("=i", effective["value"])

        def fake_write(_fd, value):
            effective["value"] = struct.unpack("=i", value)[0]
            return len(value)

        def fake_close(fd):
            if fd == 11:
                effective["value"] = 2_000_000_000

        with (
            mock.patch.object(Path, "is_char_device", return_value=True),
            mock.patch("experiments.run_timerlat_campaign.os.open", side_effect=fake_open),
            mock.patch("experiments.run_timerlat_campaign.os.read", side_effect=fake_read),
            mock.patch("experiments.run_timerlat_campaign.os.write", side_effect=fake_write),
            mock.patch("experiments.run_timerlat_campaign.os.close", side_effect=fake_close),
        ):
            request = CpuDmaLatencyRequest(Path("/dev/cpu_dma_latency"), 0)
            request.start()
            self.assertEqual(effective["value"], 0)
            state = request.close()

        self.assertEqual(state["effective_before_us"], 2_000_000_000)
        self.assertEqual(state["effective_during_us"], 0)
        self.assertEqual(state["effective_after_us"], 2_000_000_000)
        self.assertTrue(state["restored"])

    def test_qos_control_and_intervention_arms_have_distinct_targets(self):
        args = argparse.Namespace(
            dma_latency_us=800,
            control_dma_latency_us=1000,
        )
        self.assertEqual(
            timerlat_runner._qos_requested_value(args, "timerlat_user_pm_qos_control"),
            1000,
        )
        self.assertEqual(
            timerlat_runner._qos_requested_value(args, "timerlat_user_pm_qos"),
            800,
        )
        self.assertIsNone(
            timerlat_runner._qos_requested_value(args, "timerlat_user_default")
        )


if __name__ == "__main__":
    unittest.main()
