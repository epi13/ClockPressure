import json
import subprocess
import unittest
from pathlib import Path


class TestProbeIntegration(unittest.TestCase):
    def test_overhead_probe_reports_valid_and_failed_pairs(self):
        probe = Path(__file__).resolve().parents[1] / "build" / "clockpressure-probe"
        result = subprocess.run(
            [str(probe), "--mode", "overhead", "--samples", "100", "--pin-cpu", "-1"],
            capture_output=True,
            text=True,
            check=True,
            timeout=4,
        )
        report = json.loads(result.stdout)
        self.assertEqual(report["kind"], "overhead")
        self.assertEqual(report["samples"], 100)
        for name in (
            "monotonic_pair_gap",
            "monotonic_raw_pair_gap",
            "boottime_pair_gap",
            "realtime_pair_gap",
            "tai_pair_gap",
        ):
            self.assertEqual(
                report[name]["valid_pairs"] + report[name]["failed_pairs"],
                100 if report[name]["available"] else 0,
            )
        self.assertFalse(report["ptp_pair_gap"]["available"])

    def test_native_probe_emits_start_samples_and_end(self):
        probe = Path(__file__).resolve().parents[1] / "build" / "clockpressure-probe"
        result = subprocess.run(
            [
                str(probe),
                "--mode",
                "probe",
                "--run-id",
                "test-probe",
                "--condition",
                "test",
                "--duration-sec",
                "1",
                "--period-us",
                "50000",
                "--pin-cpu",
                "-1",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=4,
        )
        events = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(events[0]["kind"], "metadata")
        self.assertEqual(events[1]["kind"], "start")
        samples = [event for event in events if event["kind"] == "sample"]
        end = next(event for event in events if event["kind"] == "end")
        self.assertEqual(len(samples), 20)
        self.assertFalse(end["interrupted"])
        elapsed = end["monotonic_raw_ns"] - events[1]["monotonic_raw_ns"]
        self.assertGreaterEqual(elapsed, 1_000_000_000)
        self.assertLess(elapsed, 1_100_000_000)
