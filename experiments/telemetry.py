"""Low-rate system context snapshots around the native timing probe."""

from __future__ import annotations

import glob
import os
import time
from pathlib import Path
from typing import Any


def _read(path: str | Path) -> str | None:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def _read_int(path: str | Path) -> int | None:
    value = _read(path)
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def sample_context() -> dict[str, Any]:
    before = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
    frequencies = {}
    for directory in sorted(glob.glob("/sys/devices/system/cpu/cpufreq/policy*")):
        root = Path(directory)
        frequencies[root.name] = {
            name: _read(root / name)
            for name in ("scaling_cur_freq", "cpuinfo_avg_freq", "scaling_governor")
        }
    temperatures = {}
    for directory in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
        root = Path(directory)
        temperatures[root.name] = {
            "type": _read(root / "type"),
            "temp_millidegree_c": _read(root / "temp"),
        }
    for directory in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        root = Path(directory)
        name = _read(root / "name") or root.name
        for path in sorted(root.glob("temp*_input")):
            value = _read(path)
            if value is not None:
                temperatures[f"{name}/{path.name}"] = {"temp_millidegree_c": value}
    cpuidle_states = {}
    for cpu_dir in sorted(glob.glob("/sys/devices/system/cpu/cpu[0-9]*")):
        cpu_name = Path(cpu_dir).name
        states = {}
        for state_dir in sorted(Path(cpu_dir, "cpuidle").glob("state*")):
            state_name = state_dir.name
            name = _read(state_dir / "name")
            time_usec = _read_int(state_dir / "time")
            usage = _read_int(state_dir / "usage")
            if name is not None or time_usec is not None or usage is not None:
                states[state_name] = {
                    "name": name,
                    "time_usec": time_usec,
                    "usage": usage,
                }
        if states:
            cpuidle_states[cpu_name] = states
    pressure = {name: _read(f"/proc/pressure/{name}") for name in ("cpu", "memory", "io")}
    loadavg = _read("/proc/loadavg")
    memory_available = None
    meminfo = _read("/proc/meminfo")
    if meminfo:
        for line in meminfo.splitlines():
            if line.startswith("MemAvailable:"):
                memory_available = line.split(":", 1)[1].strip()
                break
    sensetrace_cgroup = Path("/sys/fs/cgroup/system.slice/sensetrace.service")
    sensetrace_cpu = {}
    cpu_stat = _read(sensetrace_cgroup / "cpu.stat")
    if cpu_stat:
        sensetrace_cpu = {
            key: value
            for key, value in (line.split() for line in cpu_stat.splitlines() if len(line.split()) == 2)
        }
    after = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
    return {
        "clock_id": "CLOCK_MONOTONIC_RAW",
        "monotonic_raw_ns_before": before,
        "monotonic_raw_ns_after": after,
        "snapshot_bracket_ns": after - before,
        "frequencies_khz": frequencies,
        "temperatures": temperatures,
        "cpuidle_states": cpuidle_states,
        "pressure_stall_information": pressure,
        "load_average": loadavg,
        "memory_available": memory_available,
        "sensetrace_service_cgroup": {
            "present": sensetrace_cgroup.exists(),
            "cpu_stat": sensetrace_cpu,
            "memory_current_bytes": _read(sensetrace_cgroup / "memory.current"),
            "process_count": _read(sensetrace_cgroup / "pids.current"),
        },
    }
