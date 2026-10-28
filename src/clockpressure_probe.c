#include <errno.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <fcntl.h>
#include <sched.h>
#include <signal.h>
#include <sys/types.h>

#if defined(__x86_64__) || defined(__i386__)
#include <cpuid.h>
#endif

#ifndef CLOCKFD
#define CLOCKFD 3
#endif

#define NS_PER_SEC UINT64_C(1000000000)
#define NS_PER_MS UINT64_C(1000000)
#define NS_PER_US UINT64_C(1000)
#define MAX_RUN_ID 80
#define MAX_CONDITION 40

typedef struct {
    uint64_t monotonic_ns;
    uint64_t raw_ns;
    uint64_t boottime_ns;
    uint64_t realtime_ns;
    uint64_t tai_ns;
    uint64_t ptp_ns;
    uint64_t tsc;
    uint32_t tsc_aux;
    int cpu_before;
    int cpu_after;
    uint64_t bracket_ns;
    bool monotonic_ok;
    bool raw_ok;
    bool boottime_ok;
    bool realtime_ok;
    bool tai_ok;
    bool ptp_ok;
    bool ptp_attempted;
    int ptp_errno;
    bool tsc_ok;
} snapshot_t;

typedef struct {
    const char *mode;
    const char *run_id;
    const char *condition;
    const char *ptp_path;
    uint64_t duration_ns;
    uint64_t period_ns;
    uint64_t start_delay_ns;
    uint64_t samples;
    int pin_cpu;
} options_t;

static volatile sig_atomic_t interrupted = 0;

static void
on_signal(int signo)
{
    (void)signo;
    interrupted = 1;
}

static uint64_t
timespec_ns(const struct timespec *ts)
{
    return (uint64_t)ts->tv_sec * NS_PER_SEC + (uint64_t)ts->tv_nsec;
}

static struct timespec
ns_timespec(uint64_t ns)
{
    struct timespec ts;
    ts.tv_sec = (time_t)(ns / NS_PER_SEC);
    ts.tv_nsec = (long)(ns % NS_PER_SEC);
    return ts;
}

static bool
read_clock(clockid_t clock_id, uint64_t *value)
{
    struct timespec ts;
    if (clock_gettime(clock_id, &ts) != 0)
        return false;
    *value = timespec_ns(&ts);
    return true;
}

static bool
rdtscp_supported(void)
{
#if defined(__x86_64__) || defined(__i386__)
    unsigned int eax = 0, ebx = 0, ecx = 0, edx = 0;
    unsigned int max = __get_cpuid_max(0x80000000U, NULL);
    if (max < 0x80000001U || !__get_cpuid(0x80000001U, &eax, &ebx, &ecx, &edx))
        return false;
    return (edx & (1U << 27)) != 0;
#else
    return false;
#endif
}

static bool
read_tsc(uint64_t *ticks, uint32_t *aux)
{
#if defined(__x86_64__) || defined(__i386__)
    unsigned int lo, hi, cpu;
    __asm__ __volatile__("lfence; rdtscp; lfence"
                         : "=a"(lo), "=d"(hi), "=c"(cpu)
                         :
                         : "memory");
    *ticks = ((uint64_t)hi << 32) | lo;
    *aux = cpu;
    return true;
#else
    (void)ticks;
    (void)aux;
    return false;
#endif
}

static clockid_t
fd_clockid(int fd)
{
    return (clockid_t)((~(clockid_t)fd << 3) | CLOCKFD);
}

static bool
valid_label(const char *value, size_t max_len)
{
    size_t i, len = strlen(value);
    if (len == 0 || len > max_len)
        return false;
    for (i = 0; i < len; ++i) {
        unsigned char ch = (unsigned char)value[i];
        if (!((ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') ||
              (ch >= '0' && ch <= '9') || ch == '-' || ch == '_'))
            return false;
    }
    return true;
}

static bool
parse_u64(const char *text, uint64_t *value)
{
    char *end = NULL;
    unsigned long long parsed;
    errno = 0;
    parsed = strtoull(text, &end, 10);
    if (errno != 0 || end == text || *end != '\0')
        return false;
    *value = (uint64_t)parsed;
    return true;
}

static bool
set_affinity(int cpu)
{
    cpu_set_t set;
    if (cpu < 0)
        return true;
    if (cpu >= CPU_SETSIZE) {
        fprintf(stderr, "pin CPU %d exceeds CPU_SETSIZE=%d\n", cpu, CPU_SETSIZE);
        return false;
    }
    CPU_ZERO(&set);
    CPU_SET(cpu, &set);
    if (sched_setaffinity(0, sizeof(set), &set) != 0) {
        fprintf(stderr, "sched_setaffinity(%d): %s\n", cpu, strerror(errno));
        return false;
    }
    return true;
}

static void
snapshot(snapshot_t *s, clockid_t ptp_clock, bool want_tsc)
{
    uint64_t bracket_start = 0, bracket_end = 0;
    memset(s, 0, sizeof(*s));
    s->cpu_before = sched_getcpu();
    s->monotonic_ok = read_clock(CLOCK_MONOTONIC, &s->monotonic_ns);
    bracket_start = s->monotonic_ns;
    s->raw_ok = read_clock(CLOCK_MONOTONIC_RAW, &s->raw_ns);
    s->boottime_ok = read_clock(CLOCK_BOOTTIME, &s->boottime_ns);
    s->realtime_ok = read_clock(CLOCK_REALTIME, &s->realtime_ns);
#ifdef CLOCK_TAI
    s->tai_ok = read_clock(CLOCK_TAI, &s->tai_ns);
#endif
    if (ptp_clock != (clockid_t)-1) {
        s->ptp_attempted = true;
        s->ptp_ok = read_clock(ptp_clock, &s->ptp_ns);
        if (!s->ptp_ok)
            s->ptp_errno = errno;
    }
    if (want_tsc)
        s->tsc_ok = read_tsc(&s->tsc, &s->tsc_aux);
    s->cpu_after = sched_getcpu();
    if (read_clock(CLOCK_MONOTONIC, &bracket_end) && bracket_end >= bracket_start)
        s->bracket_ns = bracket_end - bracket_start;
}

static void
json_u64(const char *key, bool ok, uint64_t value, bool comma)
{
    printf("\"%s\":", key);
    if (ok)
        printf("%" PRIu64, value);
    else
        printf("null");
    if (comma)
        putchar(',');
}

static void
json_string(const char *key, const char *value, bool comma)
{
    const unsigned char *cursor = (const unsigned char *)value;
    printf("\"%s\":\"", key);
    for (; *cursor != '\0'; ++cursor) {
        if (*cursor == '"' || *cursor == '\\') {
            putchar('\\');
            putchar((int)*cursor);
        } else if (*cursor < 0x20) {
            printf("\\u%04x", (unsigned int)*cursor);
        } else {
            putchar((int)*cursor);
        }
    }
    putchar('"');
    if (comma)
        putchar(',');
}

static void
print_snapshot_fields(const snapshot_t *s)
{
    json_u64("monotonic_ns", s->monotonic_ok, s->monotonic_ns, true);
    json_u64("monotonic_raw_ns", s->raw_ok, s->raw_ns, true);
    json_u64("boottime_ns", s->boottime_ok, s->boottime_ns, true);
    json_u64("realtime_ns", s->realtime_ok, s->realtime_ns, true);
    json_u64("tai_ns", s->tai_ok, s->tai_ns, true);
    json_u64("ptp_ns", s->ptp_ok, s->ptp_ns, true);
    printf("\"ptp_errno\":");
    if (s->ptp_attempted && !s->ptp_ok)
        printf("%d", s->ptp_errno);
    else
        printf("null");
    putchar(',');
    json_u64("tsc_ticks", s->tsc_ok, s->tsc, true);
    printf("\"tsc_aux\":");
    if (s->tsc_ok)
        printf("%" PRIu32, s->tsc_aux);
    else
        printf("null");
    printf(",\"cpu_before\":%d,\"cpu_after\":%d,\"read_bracket_ns\":%" PRIu64,
           s->cpu_before, s->cpu_after, s->bracket_ns);
}

static bool
sleep_until(uint64_t deadline_ns)
{
    struct timespec deadline = ns_timespec(deadline_ns);
    int rc;
    do {
        rc = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &deadline, NULL);
    } while (rc == EINTR && !interrupted);
    if (rc != 0 && rc != EINTR) {
        fprintf(stderr, "clock_nanosleep: %s\n", strerror(rc));
        return false;
    }
    return rc == 0;
}

static uint64_t
resolution_ns(clockid_t clock_id, bool *ok)
{
    struct timespec ts;
    *ok = clock_getres(clock_id, &ts) == 0;
    return *ok ? timespec_ns(&ts) : 0;
}

static void
print_probe_metadata(const options_t *opts, int ptp_fd,
                     uint64_t ptp_resolution, bool ptp_resolution_ok,
                     bool tsc_ok)
{
    bool mono_ok, raw_ok, boot_ok, realtime_ok, tai_ok;
    uint64_t mono_res = resolution_ns(CLOCK_MONOTONIC, &mono_ok);
    uint64_t raw_res = resolution_ns(CLOCK_MONOTONIC_RAW, &raw_ok);
    uint64_t boot_res = resolution_ns(CLOCK_BOOTTIME, &boot_ok);
    uint64_t realtime_res = resolution_ns(CLOCK_REALTIME, &realtime_ok);
    uint64_t tai_res = 0;
#ifdef CLOCK_TAI
    tai_res = resolution_ns(CLOCK_TAI, &tai_ok);
#else
    tai_ok = false;
#endif
    printf("{\"kind\":\"metadata\",\"schema\":\"clockpressure.sample.v1\",");
    printf("\"run_id\":\"%s\",\"condition\":\"%s\",\"pid\":%ld,",
           opts->run_id, opts->condition, (long)getpid());
    printf("\"uid\":%ld,\"euid\":%ld,\"duration_ns\":%" PRIu64
           ",\"period_ns\":%" PRIu64 ",\"pin_cpu\":%d,",
           (long)getuid(), (long)geteuid(), opts->duration_ns, opts->period_ns, opts->pin_cpu);
    json_string("ptp_path", opts->ptp_path ? opts->ptp_path : "", true);
    printf("\"ptp_open\":%s,\"ptp_fd\":%d,", ptp_fd >= 0 ? "true" : "false", ptp_fd);
    json_u64("monotonic_resolution_ns", mono_ok, mono_res, true);
    json_u64("raw_resolution_ns", raw_ok, raw_res, true);
    json_u64("boottime_resolution_ns", boot_ok, boot_res, true);
    json_u64("realtime_resolution_ns", realtime_ok, realtime_res, true);
    json_u64("tai_resolution_ns", tai_ok, tai_res, true);
    json_u64("ptp_resolution_ns", ptp_resolution_ok, ptp_resolution, true);
    printf("\"rdtscp_supported\":%s,\"compiler\":\"%s\"}\n",
           tsc_ok ? "true" : "false", __VERSION__);
}

static bool
run_probe(const options_t *opts)
{
    int ptp_fd = -1;
    clockid_t ptp_clock = (clockid_t)-1;
    bool ptp_res_ok = false;
    uint64_t ptp_res = 0;
    bool tsc_ok = rdtscp_supported();
    uint64_t start_delay_end = 0, start_mono = 0, end_mono = 0;
    uint64_t next_deadline = 0, missed = 0;
    snapshot_t s;

    if (opts->ptp_path) {
        ptp_fd = open(opts->ptp_path, O_RDONLY | O_CLOEXEC);
        if (ptp_fd >= 0) {
            ptp_clock = fd_clockid(ptp_fd);
            ptp_res = resolution_ns(ptp_clock, &ptp_res_ok);
        } else {
            fprintf(stderr, "open PTP device %s: %s\n", opts->ptp_path, strerror(errno));
        }
    }

    print_probe_metadata(opts, ptp_fd, ptp_res, ptp_res_ok, tsc_ok);
    fflush(stdout);

    if (opts->start_delay_ns > 0) {
        if (!read_clock(CLOCK_MONOTONIC, &start_delay_end)) {
            fprintf(stderr, "clock_gettime(CLOCK_MONOTONIC): %s\n", strerror(errno));
            goto error;
        }
        start_delay_end += opts->start_delay_ns;
        if (!sleep_until(start_delay_end) && !interrupted)
            goto error;
    }
    if (interrupted)
        goto interrupted_run;

    snapshot(&s, ptp_clock, tsc_ok);
    if (!s.monotonic_ok || !s.raw_ok) {
        fprintf(stderr, "required start clock read failed\n");
        goto error;
    }
    start_mono = s.monotonic_ns;
    end_mono = start_mono + opts->duration_ns;
    next_deadline = start_mono + opts->period_ns;
    printf("{\"kind\":\"start\",\"run_id\":\"%s\",", opts->run_id);
    print_snapshot_fields(&s);
    printf("}\n");
    fflush(stdout);

    while (!interrupted && next_deadline <= end_mono) {
        uint64_t observed_mono = 0;
        uint64_t lateness = 0;
        uint64_t skip_count = 0;
        if (!sleep_until(next_deadline)) {
            if (interrupted)
                break;
            goto error;
        }
        snapshot(&s, ptp_clock, tsc_ok);
        if (!s.monotonic_ok || !s.raw_ok) {
            fprintf(stderr, "required clock read failed in sample\n");
            goto error;
        }
        observed_mono = s.monotonic_ns;
        lateness = observed_mono >= next_deadline ? observed_mono - next_deadline : 0;
        printf("{\"kind\":\"sample\",\"run_id\":\"%s\",\"seq\":%" PRIu64
               ",\"deadline_monotonic_ns\":%" PRIu64
               ",\"wakeup_lateness_ns\":%" PRIu64 ",\"skipped_periods_before\":",
               opts->run_id, (next_deadline - start_mono) / opts->period_ns - 1,
               next_deadline, lateness);
        while (next_deadline <= observed_mono) {
            next_deadline += opts->period_ns;
            ++skip_count;
        }
        if (skip_count > 0) {
            missed += skip_count - 1;
            printf("%" PRIu64, skip_count - 1);
        } else {
            printf("0");
        }
        printf(",");
        print_snapshot_fields(&s);
        printf("}\n");
        fflush(stdout);
        if (skip_count == 0)
            next_deadline += opts->period_ns;
    }

    if (!interrupted)
        (void)sleep_until(end_mono);
interrupted_run:
    snapshot(&s, ptp_clock, tsc_ok);
    printf("{\"kind\":\"end\",\"run_id\":\"%s\",\"interrupted\":%s,"
           "\"missed_deadlines\":%" PRIu64 ",",
           opts->run_id, interrupted ? "true" : "false", missed);
    print_snapshot_fields(&s);
    printf("}\n");
    fflush(stdout);
    if (ptp_fd >= 0)
        close(ptp_fd);
    return !interrupted;

error:
    if (ptp_fd >= 0)
        close(ptp_fd);
    return false;
}

static int
compare_u64(const void *a, const void *b)
{
    uint64_t va = *(const uint64_t *)a;
    uint64_t vb = *(const uint64_t *)b;
    return (va > vb) - (va < vb);
}

static uint64_t
percentile(const uint64_t *values, size_t n, double p)
{
    size_t idx;
    if (n == 0)
        return 0;
    idx = (size_t)(p * (double)(n - 1) + 0.5);
    return values[idx];
}

static bool
run_overhead(const options_t *opts)
{
    uint64_t *mono_gap, *raw_gap, *boot_gap, *realtime_gap, *tai_gap, *ptp_gap = NULL;
    size_t n = (size_t)opts->samples, i;
    size_t mono_n = 0, raw_n = 0, boot_n = 0, realtime_n = 0, tai_n = 0, ptp_n = 0;
    uint64_t mono_fail = 0, raw_fail = 0, boot_fail = 0, realtime_fail = 0, tai_fail = 0, ptp_fail = 0;
    int ptp_fd = -1;
    clockid_t ptp_clock = (clockid_t)-1;
    uint64_t a, b;
#ifdef CLOCK_TAI
    const bool tai_available = true;
#else
    const bool tai_available = false;
#endif
    if ((uint64_t)n != opts->samples || n == 0 || n > 10000000) {
        fprintf(stderr, "overhead sample count must be between 1 and 10000000\n");
        return false;
    }
    mono_gap = calloc(n, sizeof(*mono_gap));
    raw_gap = calloc(n, sizeof(*raw_gap));
    boot_gap = calloc(n, sizeof(*boot_gap));
    realtime_gap = calloc(n, sizeof(*realtime_gap));
    tai_gap = calloc(n, sizeof(*tai_gap));
    if (!mono_gap || !raw_gap || !boot_gap || !realtime_gap || !tai_gap)
        goto allocation_error;
    if (opts->ptp_path) {
        ptp_fd = open(opts->ptp_path, O_RDONLY | O_CLOEXEC);
        if (ptp_fd >= 0) {
            ptp_clock = fd_clockid(ptp_fd);
            ptp_gap = calloc(n, sizeof(*ptp_gap));
            if (!ptp_gap)
                goto allocation_error;
        } else {
            fprintf(stderr, "open PTP device %s: %s\n", opts->ptp_path, strerror(errno));
        }
    }

    for (i = 0; i < n; ++i) {
        if (read_clock(CLOCK_MONOTONIC, &a) && read_clock(CLOCK_MONOTONIC, &b) && b >= a)
            mono_gap[mono_n++] = b - a;
        else
            ++mono_fail;
        if (read_clock(CLOCK_MONOTONIC_RAW, &a) && read_clock(CLOCK_MONOTONIC_RAW, &b) && b >= a)
            raw_gap[raw_n++] = b - a;
        else
            ++raw_fail;
        if (read_clock(CLOCK_BOOTTIME, &a) && read_clock(CLOCK_BOOTTIME, &b) && b >= a)
            boot_gap[boot_n++] = b - a;
        else
            ++boot_fail;
        if (read_clock(CLOCK_REALTIME, &a) && read_clock(CLOCK_REALTIME, &b) && b >= a)
            realtime_gap[realtime_n++] = b - a;
        else
            ++realtime_fail;
#ifdef CLOCK_TAI
        if (read_clock(CLOCK_TAI, &a) && read_clock(CLOCK_TAI, &b) && b >= a)
            tai_gap[tai_n++] = b - a;
        else
            ++tai_fail;
#endif
        if (ptp_clock != (clockid_t)-1) {
            if (read_clock(ptp_clock, &a) && read_clock(ptp_clock, &b) && b >= a)
                ptp_gap[ptp_n++] = b - a;
            else
                ++ptp_fail;
        }
    }
    qsort(mono_gap, mono_n, sizeof(*mono_gap), compare_u64);
    qsort(raw_gap, raw_n, sizeof(*raw_gap), compare_u64);
    qsort(boot_gap, boot_n, sizeof(*boot_gap), compare_u64);
    qsort(realtime_gap, realtime_n, sizeof(*realtime_gap), compare_u64);
    qsort(tai_gap, tai_n, sizeof(*tai_gap), compare_u64);
    if (ptp_gap)
        qsort(ptp_gap, ptp_n, sizeof(*ptp_gap), compare_u64);
    printf("{\"kind\":\"overhead\",\"schema\":\"clockpressure.overhead.v1\","
           "\"samples\":%zu,\"pin_cpu\":%d,", n, opts->pin_cpu);
    json_string("ptp_path", opts->ptp_path ? opts->ptp_path : "", true);
    printf("\"euid\":%ld,\"ptp_open\":%s,", (long)geteuid(), ptp_fd >= 0 ? "true" : "false");
#define PRINT_STATS(name, values, count, failures, available) \
    do { \
        printf("\"%s\":{\"available\":%s,\"valid_pairs\":%zu,\"failed_pairs\":%" PRIu64 ",", \
               name, (available) ? "true" : "false", count, failures); \
        if (count > 0) \
            printf("\"min_ns\":%" PRIu64 ",\"median_ns\":%" PRIu64 ",\"p95_ns\":%" PRIu64 "," \
                   "\"p99_ns\":%" PRIu64 ",\"max_ns\":%" PRIu64 "},", \
                   percentile(values, count, 0.0), percentile(values, count, 0.50), \
                   percentile(values, count, 0.95), percentile(values, count, 0.99), \
                   percentile(values, count, 1.0)); \
        else \
            printf("\"min_ns\":null,\"median_ns\":null,\"p95_ns\":null,\"p99_ns\":null,\"max_ns\":null},"); \
    } while (0)
    PRINT_STATS("monotonic_pair_gap", mono_gap, mono_n, mono_fail, true);
    PRINT_STATS("monotonic_raw_pair_gap", raw_gap, raw_n, raw_fail, true);
    PRINT_STATS("boottime_pair_gap", boot_gap, boot_n, boot_fail, true);
    PRINT_STATS("realtime_pair_gap", realtime_gap, realtime_n, realtime_fail, true);
    PRINT_STATS("tai_pair_gap", tai_gap, tai_n, tai_fail, tai_available);
    if (ptp_gap) {
        PRINT_STATS("ptp_pair_gap", ptp_gap, ptp_n, ptp_fail, true);
    } else {
        printf("\"ptp_pair_gap\":{\"available\":false,\"valid_pairs\":0,\"failed_pairs\":0,"
               "\"min_ns\":null,\"median_ns\":null,\"p95_ns\":null,\"p99_ns\":null,\"max_ns\":null},");
    }
#undef PRINT_STATS
    printf("\"interpretation\":\"inter-read gap includes userspace and call overhead; not isolated vDSO/kernel service time\"}\n");
    free(mono_gap);
    free(raw_gap);
    free(boot_gap);
    free(realtime_gap);
    free(tai_gap);
    free(ptp_gap);
    if (ptp_fd >= 0)
        close(ptp_fd);
    return true;

allocation_error:
    fprintf(stderr, "allocation failed for overhead samples\n");
    free(mono_gap);
    free(raw_gap);
    free(boot_gap);
    free(realtime_gap);
    free(tai_gap);
    free(ptp_gap);
    if (ptp_fd >= 0)
        close(ptp_fd);
    return false;
}

static void
usage(const char *program)
{
    fprintf(stderr,
            "Usage:\n"
            "  %s --mode probe --duration-sec N --period-us N [options]\n"
            "  %s --mode overhead --samples N [options]\n"
            "Options: --run-id LABEL --condition LABEL --start-delay-ms N\n"
            "         --pin-cpu N (default -1, unpinned) --ptp-device PATH\n",
            program, program);
}

int
main(int argc, char **argv)
{
    options_t opts = {
        .mode = "probe",
        .run_id = "unlabeled",
        .condition = "unspecified",
        .ptp_path = NULL,
        .duration_ns = 30 * NS_PER_SEC,
        .period_ns = 10 * NS_PER_MS,
        .start_delay_ns = 0,
        .samples = 100000,
        .pin_cpu = -1,
    };
    int i;
    bool ok;
    struct sigaction sa;

    for (i = 1; i < argc; ++i) {
        const char *value = NULL;
        uint64_t parsed = 0;
        if (i + 1 < argc && strncmp(argv[i], "--", 2) == 0)
            value = argv[++i];
        else if (strcmp(argv[i], "--help") == 0) {
            usage(argv[0]);
            return 0;
        } else {
            usage(argv[0]);
            return 2;
        }

        if (strcmp(argv[i - 1], "--mode") == 0)
            opts.mode = value;
        else if (strcmp(argv[i - 1], "--run-id") == 0)
            opts.run_id = value;
        else if (strcmp(argv[i - 1], "--condition") == 0)
            opts.condition = value;
        else if (strcmp(argv[i - 1], "--ptp-device") == 0)
            opts.ptp_path = value;
        else if (strcmp(argv[i - 1], "--pin-cpu") == 0) {
            char *end = NULL;
            long cpu;
            errno = 0;
            cpu = strtol(value, &end, 10);
            if (errno || end == value || *end || cpu < -1 || cpu > 1048576) {
                fprintf(stderr, "invalid pin CPU: %s\n", value);
                return 2;
            }
            opts.pin_cpu = (int)cpu;
        } else if (strcmp(argv[i - 1], "--duration-sec") == 0) {
            if (!parse_u64(value, &parsed) || parsed == 0 || parsed > 86400) {
                fprintf(stderr, "duration must be 1..86400 seconds\n");
                return 2;
            }
            opts.duration_ns = parsed * NS_PER_SEC;
        } else if (strcmp(argv[i - 1], "--period-us") == 0) {
            if (!parse_u64(value, &parsed) || parsed == 0 || parsed > 10000000) {
                fprintf(stderr, "period must be 1..10000000 microseconds\n");
                return 2;
            }
            opts.period_ns = parsed * NS_PER_US;
        } else if (strcmp(argv[i - 1], "--start-delay-ms") == 0) {
            if (!parse_u64(value, &parsed) || parsed > 60000) {
                fprintf(stderr, "start delay must be 0..60000 milliseconds\n");
                return 2;
            }
            opts.start_delay_ns = parsed * NS_PER_MS;
        } else if (strcmp(argv[i - 1], "--samples") == 0) {
            if (!parse_u64(value, &parsed) || parsed == 0 || parsed > 10000000) {
                fprintf(stderr, "samples must be 1..10000000\n");
                return 2;
            }
            opts.samples = parsed;
        } else {
            fprintf(stderr, "unknown option: %s\n", argv[i - 1]);
            usage(argv[0]);
            return 2;
        }
    }

    if (strcmp(opts.mode, "probe") != 0 && strcmp(opts.mode, "overhead") != 0) {
        fprintf(stderr, "mode must be probe or overhead\n");
        return 2;
    }
    if (!valid_label(opts.run_id, MAX_RUN_ID) || !valid_label(opts.condition, MAX_CONDITION)) {
        fprintf(stderr, "run ID and condition must be short alphanumeric labels\n");
        return 2;
    }
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = on_signal;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);
    if (!set_affinity(opts.pin_cpu))
        return 2;

    if (strcmp(opts.mode, "overhead") == 0)
        ok = run_overhead(&opts);
    else
        ok = run_probe(&opts);
    return ok ? 0 : 1;
}
