# Dependencies and provenance

ClockPressure does not vendor or import external measurement code. The implementation and experimental design in this repository are authored here and remain under the repository's Apache-2.0 license. Python modules use only the Python standard library; no Python packages are installed by the runner.

| Capability | Dependency | Required? | Recorded provenance |
| --- | --- | --- | --- |
| Native sampler | Linux x86-64, GCC-compatible C11 compiler, glibc/Linux `clock_gettime`, `clock_nanosleep`, `sched_getcpu` and affinity APIs | Required | Compiler string in native metadata; OS/kernel and compiler version in the run manifest |
| RDTSCP capture | x86 CPU with CPUID RDTSCP support | Optional | CPUID support flag and per-sample TSC/AUX fields |
| PTP hardware-clock reads | Linux dynamic clock IDs, readable `/dev/ptpN` and a PTP clock driver | Optional | Device, driver, clock resolution and open result in manifest/probe header |
| BPF scheduler witness | Linux scheduler tracepoints, BTF/tracefs support as required by kernel, `bpftrace`, permission to load tracing programs | Optional | Kernel/tracepoint list, bpftrace version, target PID and retained observer output/diagnostics |
| Environment inventory | Python 3, `lscpu`, `timedatectl`, optional `chronyc`, optional `ethtool` | Partial | Tool versions and values available from sysfs/procfs; unavailable fields remain null |
| Analysis and test | Python 3 standard library and `unittest` | Required | Analysis source path and code revision in run manifests |

The initial worker had GCC, clang, bpftool and bpftrace. `perf`, `pahole` and libbpf development headers/libraries were not found in standard paths. The native sampler does not use libbpf. No package installation, kernel module, daemon, service, sysctl, boot argument, firmware setting or clocksource change is performed by ClockPressure. Root access is used temporarily only when needed to read a protected PHC and attach/detach the eBPF observer.

Run manifests record the repository commit, versions available at run time, environment snapshot and SHA-256 for raw artifacts. The synthetic contract demo and its tests contain no copied external code or machine-measurement data. Data retention and privacy are defined in [DATA_AND_REPRODUCIBILITY.md](DATA_AND_REPRODUCIBILITY.md).
