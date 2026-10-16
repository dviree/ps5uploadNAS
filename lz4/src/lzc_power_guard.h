/*
 * LZ4 Compression - keep PS5 idle/display timers reset during operations.
 */

#pragma once

void lzc_power_guard_start(void);

/* Keep the PS5 out of rest mode for the next `seconds` (at most an hour),
 * e.g. while a NAS sends a game over FTP; 0 lets it rest again. Returns the
 * seconds left. */
long lzc_power_guard_hold(long seconds);

/* Put the PS5 in rest mode in two seconds, e.g. when a NAS that woke it has
 * nothing left to send. 0 when started, -1 while a job runs, -2 when the
 * console offers no way to do it, -3 when the thread could not start. */
int lzc_power_guard_rest(void);
