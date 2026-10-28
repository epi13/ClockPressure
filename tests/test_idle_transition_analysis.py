import tempfile
import unittest
from pathlib import Path

from analysis.analyze_idle_transitions import analyze_idle_transitions


class TestIdleTransitionAnalysis(unittest.TestCase):
    def test_attributes_irq_latency_to_open_idle_state_on_same_cpu(self):
        trace = (
            "swapper/7-0 [007] .... 10.000000: cpu_idle: state=8 cpu_id=7\n"
            "<idle>-0 [007] d.h1. 10.000100: #1 context irq timer_latency 30000 ns\n"
            "<...>-12 [007] ....1 10.000110: #1 context thread timer_latency 31000 ns\n"
            "swapper/7-0 [007] .... 10.000200: cpu_idle: state=4294967295 cpu_id=7\n"
            "swapper/7-0 [007] .... 11.000000: cpu_idle: state=3 cpu_id=7\n"
            "<idle>-0 [007] d.h1. 11.000020: #2 context irq timer_latency 9000 ns\n"
            "swapper/7-0 [007] .... 11.000040: cpu_idle: state=4294967295 cpu_id=7\n"
            "swapper/6-0 [006] .... 12.000000: cpu_idle: state=8 cpu_id=6\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "trace"
            path.write_text(trace)

            result = analyze_idle_transitions(
                path,
                cpu=7,
                state_names={3: "C3", 8: "C10"},
            )

        self.assertEqual(result["timerlat_irq_events"], 2)
        self.assertEqual(result["matched_idle_state_activations"], 2)
        self.assertEqual(result["unmatched_timerlat_irq_events"], 0)
        self.assertEqual(result["cpu_idle_events"], 4)
        self.assertEqual(result["completed_idle_intervals"], 2)
        states = {item["state_id"]: item for item in result["per_state"]}
        self.assertEqual(states[8]["state_name"], "C10")
        self.assertEqual(states[8]["timerlat_irq_latency_ns"]["median"], 30000)
        self.assertEqual(states[8]["trace_entry_to_irq_ns"]["median"], 100000)
        self.assertEqual(states[8]["trace_entry_to_exit_ns"]["median"], 200000)
        self.assertEqual(states[3]["state_name"], "C3")
        self.assertEqual(states[3]["timerlat_irq_latency_ns"]["median"], 9000)
        self.assertFalse(result["open_idle_interval_at_trace_end"])

    def test_reports_unmatched_irq_and_exit_without_inventing_state(self):
        trace = (
            "<idle>-0 [007] d.h1. 1.000000: #1 context irq timer_latency 100 ns\n"
            "swapper/7-0 [007] .... 1.000010: cpu_idle: state=4294967295 cpu_id=7\n"
            "<idle>-0 [007] d.h1. 2.000000: #2 context irq timer_latency 200 ns\n"
            "swapper/7-0 [007] .... 2.000010: cpu_idle: state=8 cpu_id=7\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "trace"
            path.write_text(trace)
            result = analyze_idle_transitions(path, cpu=7)

        self.assertEqual(result["matched_idle_state_activations"], 0)
        self.assertEqual(result["unmatched_timerlat_irq_events"], 2)
        self.assertEqual(result["unmatched_idle_exits"], 1)
        self.assertEqual(result["completed_idle_intervals"], 0)
        self.assertTrue(result["open_idle_interval_at_trace_end"])

    def test_joins_irq_immediately_after_idle_exit_with_bounded_lookback(self):
        trace = (
            "swapper/7-0 [007] .... 10.000000: cpu_idle: state=8 cpu_id=7\n"
            "swapper/7-0 [007] .... 10.010000: cpu_idle: state=4294967295 cpu_id=7\n"
            "<idle>-0 [007] d.h1. 10.010001: #1 context irq timer_latency 30000 ns\n"
            "swapper/7-0 [007] .... 11.000000: cpu_idle: state=3 cpu_id=7\n"
            "swapper/7-0 [007] .... 11.000100: cpu_idle: state=4294967295 cpu_id=7\n"
            "<idle>-0 [007] d.h1. 11.000126: #2 context irq timer_latency 31000 ns\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "trace"
            path.write_text(trace)
            result = analyze_idle_transitions(path, cpu=7, state_names={3: "C3", 8: "C10"})

        self.assertEqual(result["timerlat_irq_events"], 2)
        self.assertEqual(result["matched_idle_state_activations"], 1)
        self.assertEqual(result["matched_after_idle_exit"], 1)
        self.assertEqual(result["matched_while_idle_state_open"], 0)
        self.assertEqual(result["unmatched_timerlat_irq_events"], 1)
        self.assertEqual(result["post_exit_match_lookback_ns"], 25_000)
        states = {item["state_id"]: item for item in result["per_state"]}
        self.assertEqual(states[8]["timerlat_irq_phase_counts"]["after_idle_exit"], 1)
        self.assertEqual(states[8]["trace_exit_to_irq_ns"]["median"], 1000)
        self.assertEqual(states[3]["timerlat_irq_activations"], 0)

    def test_rejects_cpu_idle_header_and_payload_cpu_mismatch(self):
        trace = "swapper/7-0 [007] .... 1.000000: cpu_idle: state=8 cpu_id=6\n"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "trace"
            path.write_text(trace)
            result = analyze_idle_transitions(path, cpu=7)

        self.assertEqual(result["cpu_idle_events"], 0)
        self.assertEqual(result["malformed_cpu_idle_events"], 1)


if __name__ == "__main__":
    unittest.main()
