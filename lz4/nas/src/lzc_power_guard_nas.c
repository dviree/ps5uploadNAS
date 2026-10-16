/*
 * LZ4 Compression - NAS power guard. A NAS does not idle into rest mode
 * mid-job the way a PS5 does, so there is nothing to keep awake.
 */

#include "lzc_power_guard.h"

void
lzc_power_guard_start(void) {
}

long
lzc_power_guard_hold(long seconds) {
  return seconds < 0 ? 0 : seconds > 3600 ? 3600 : seconds;
}

int
lzc_power_guard_rest(void) {
  return -2;
}
