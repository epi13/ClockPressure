CC ?= cc
CFLAGS ?= -O2 -g
CPPFLAGS ?=
WARNINGS = -Wall -Wextra -Wpedantic -Werror
BUILD_DIR = build
PROBE = $(BUILD_DIR)/clockpressure-probe

.PHONY: all clean check

all: $(PROBE)

$(PROBE): src/clockpressure_probe.c
	@mkdir -p $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CFLAGS) $(WARNINGS) -std=c11 -D_GNU_SOURCE -o $@ $<

check: all
	python3 -m unittest discover -s tests -v
	$(PROBE) --mode overhead --samples 1000 --pin-cpu -1

clean:
	rm -rf $(BUILD_DIR)
