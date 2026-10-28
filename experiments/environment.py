"""Pseudonymized, read-only environment inventory for experiment manifests."""

from __future__ import annotations

import glob
import os
import platform
import re
import subprocess
from pathlib import Path
from typing import Any


def _read(path: str | Path) -> str | None:
    try:
        return Path(path).read_text().strip()
    except (OSError, UnicodeError):
        return None


def _run(argv: list[str], timeout: float = 4.0) -> str | None:
    try:
        result = subprocess.run(
            argv, check=False, capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _cpuinfo() -> dict[str, Any]:
    lines = _read("/proc/cpuinfo") or ""
    first: dict[str, str] = {}
    flags: list[str] = []
    for line in lines.splitlines():
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        if key == "flags":
            flags = value.split()
        elif key in {"vendor_id", "model name", "cpu family", "model", "stepping"}:
            first.setdefault(key, value)
        elif key == "microcode":
            first.setdefault(key, value)
    return {
        "vendor": first.get("vendor_id"),
        "model_name": first.get("model name"),
        "family": first.get("cpu family"),
        "model": first.get("model"),
        "stepping": first.get("stepping"),
        "microcode": first.get("microcode"),
        "timing_capability_flags": [
            name
            for name in (
                "tsc",
                "constant_tsc",
                "nonstop_tsc",
                "tsc_reliable",
                "rdtscp",
                "art",
                "tsc_deadline_timer",
                "aperfmperf",
            )
            if name in flags
        ],
        "feature_count": len(flags),
    }


def _clock_file_summary() -> dict[str, Any]:
    root = Path("/sys/devices/system/clocksource/clocksource0")
    return {
        "current": _read(root / "current_clocksource"),
        "available": (_read(root / "available_clocksource") or "").split(),
        "hpet_device_present": Path("/dev/hpet").exists(),
        "rtc_devices": sorted(glob.glob("/dev/rtc*")),
        "rtc_names": {
            Path(path).name: _read(Path("/sys/class/rtc") / Path(path).name / "name")
            for path in sorted(glob.glob("/dev/rtc[0-9]*"))
        },
    }


def _frequency_policies() -> list[dict[str, Any]]:
    policies = []
    for directory in sorted(glob.glob("/sys/devices/system/cpu/cpufreq/policy*")):
        root = Path(directory)
        values = {
            key: _read(root / key)
            for key in (
                "related_cpus",
                "scaling_driver",
                "scaling_governor",
                "scaling_min_freq",
                "scaling_max_freq",
                "cpuinfo_min_freq",
                "cpuinfo_max_freq",
                "base_frequency",
                "energy_performance_preference",
            )
        }
        values["policy"] = root.name
        policies.append(values)
    return policies


def _idle_states() -> list[dict[str, Any]]:
    states = []
    for directory in sorted(glob.glob("/sys/devices/system/cpu/cpu0/cpuidle/state*")):
        root = Path(directory)
        states.append(
            {
                "state": root.name,
                "name": _read(root / "name"),
                "latency_us": _read(root / "latency"),
                "residency_us": _read(root / "residency"),
                "disabled": _read(root / "disable"),
            }
        )
    return states


def _thermal_readings() -> dict[str, Any]:
    zones = []
    for directory in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
        root = Path(directory)
        zones.append(
            {
                "zone": root.name,
                "type": _read(root / "type"),
                "temp_millidegree_c": _read(root / "temp"),
            }
        )
    hwmon = []
    for directory in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        root = Path(directory)
        sensors: dict[str, str] = {}
        for path in sorted(root.glob("*_input")):
            if path.name.startswith(("temp", "in", "power", "energy")):
                value = _read(path)
                if value is not None:
                    sensors[path.name] = value
        hwmon.append({"device": root.name, "name": _read(root / "name"), "inputs": sensors})
    return {"thermal_zones": zones, "hwmon": hwmon}


def _ptp_devices() -> list[dict[str, Any]]:
    devices = []
    for path in sorted(glob.glob("/sys/class/ptp/ptp*")):
        root = Path(path)
        device = root / "device"
        driver_link = device / "driver"
        devices.append(
            {
                "device": root.name,
                "clock_name": _read(root / "clock_name"),
                "driver": Path(os.path.realpath(driver_link)).name
                if driver_link.exists()
                else None,
                "pci_device_id": _read(device / "device"),
                "clock_device_present": Path("/dev") .joinpath(root.name).exists(),
            }
        )
    return devices


def _chrony_tracking() -> dict[str, str] | None:
    tracking = _run(["chronyc", "tracking"])
    if tracking is None:
        return None
    # Keep correction/uncertainty data but omit upstream host and IP identity.
    fields: dict[str, str] = {}
    for line in tracking.splitlines():
        match = re.match(r"^([^:]+):\s*(.*)$", line)
        if match and match.group(1) not in {"Reference ID", "Ref time (UTC)"}:
            fields[match.group(1)] = match.group(2)
    return fields


def _tool_versions() -> dict[str, str | None]:
    commands = {
        "gcc": ["gcc", "--version"],
        "clang": ["clang", "--version"],
        "bpftool": ["bpftool", "version"],
        "bpftrace": ["bpftrace", "--version"],
        "perf": ["perf", "version"],
        "pahole": ["pahole", "--version"],
        "python3": ["python3", "--version"],
        "ethtool": ["ethtool", "--version"],
    }
    versions = {}
    for name, argv in commands.items():
        output = _run(argv)
        versions[name] = output.splitlines()[0] if output else None
    return versions


def snapshot_environment(host_alias: str) -> dict[str, Any]:
    """Collect only reproducibility data; omit host serials, UUIDs and addresses."""
    try:
        os_release = {}
        for line in Path("/etc/os-release").read_text().splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                os_release[key] = value.strip('"')
    except OSError:
        os_release = {}

    pstate = {
        name: _read(f"/sys/devices/system/cpu/intel_pstate/{name}")
        for name in ("status", "min_perf_pct", "max_perf_pct", "no_turbo")
    }
    ptp = _ptp_devices()
    event_names = (
        "sched/sched_wakeup",
        "sched/sched_switch",
        "sched/sched_migrate_task",
        "timer/hrtimer_expire_entry",
        "timer/hrtimer_expire_exit",
        "irq/irq_handler_entry",
        "irq/irq_handler_exit",
        "irq/softirq_entry",
        "irq/softirq_exit",
        "power/cpu_frequency",
        "power/cpu_idle",
    )
    trace_events = {
        event: (Path("/sys/kernel/tracing/events") / event / "enable").exists()
        for event in event_names
    }
    return {
        "host_alias": host_alias,
        "os": {
            "id": os_release.get("ID"),
            "version_id": os_release.get("VERSION_ID"),
            "pretty_name": os_release.get("PRETTY_NAME"),
            "kernel": platform.release(),
            "kernel_version": platform.version(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
        },
        "firmware": {
            "vendor": _read("/sys/class/dmi/id/sys_vendor"),
            "product": _read("/sys/class/dmi/id/product_name"),
            "board_vendor": _read("/sys/class/dmi/id/board_vendor"),
            "board_name": _read("/sys/class/dmi/id/board_name"),
            "bios_version": _read("/sys/class/dmi/id/bios_version"),
            "bios_date": _read("/sys/class/dmi/id/bios_date"),
            "microcode": _cpuinfo().get("microcode"),
            "virtualization": _run(["systemd-detect-virt"]),
        },
        "cpu": {
            **_cpuinfo(),
            "online": _read("/sys/devices/system/cpu/online"),
            "topology": _run(["lscpu", "-p=CPU,CORE,SOCKET,NODE"]),
            "cpuidle_driver": _read("/sys/devices/system/cpu/cpuidle/current_driver"),
            "cpuidle_governor": _read("/sys/devices/system/cpu/cpuidle/current_governor"),
            "idle_states_cpu0": _idle_states(),
        },
        "power": {
            "frequency_policies": _frequency_policies(),
            "intel_pstate": pstate,
            "mem_sleep_options": _read("/sys/power/mem_sleep"),
            "thermal": _thermal_readings(),
            "powercap_paths": sorted(glob.glob("/sys/class/powercap/*")),
        },
        "timekeeping": {
            "clocksource": _clock_file_summary(),
            "ptp_devices": ptp,
            "ptp_interpretation": "NIC PHC is a candidate distinct clock; independence and calibration are unverified",
            "chrony_tracking": _chrony_tracking(),
            "ntp_enabled": _run(["timedatectl", "show", "-p", "NTP"]).split("=", 1)[-1]
            if _run(["timedatectl", "show", "-p", "NTP"])
            else None,
            "synchronized": _run(["timedatectl", "show", "-p", "NTPSynchronized"]).split("=", 1)[-1]
            if _run(["timedatectl", "show", "-p", "NTPSynchronized"])
            else None,
            "rtc_time": _read("/sys/class/rtc/rtc0/time"),
            "rtc_date": _read("/sys/class/rtc/rtc0/date"),
        },
        "kernel_observability": {
            "btf_vmlinux": Path("/sys/kernel/btf/vmlinux").exists(),
            "tracefs": Path("/sys/kernel/tracing/available_events").exists(),
            "tracepoints": trace_events,
            "perf_event_paranoid": _read("/proc/sys/kernel/perf_event_paranoid"),
            "tools": _tool_versions(),
        },
    }
