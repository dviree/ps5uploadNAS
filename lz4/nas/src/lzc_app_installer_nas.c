/*
 * LZ4 Compression - NAS build: there is no PS5 home screen tile to install
 * or remove. The web page is the only front end.
 */

#include "lzc_app_installer.h"

int
lzc_launcher_start(void) {
  return 0;
}

int
lzc_launcher_remove(void) {
  return 0;
}

/* No PS5 app to close and reopen after an update. */
int
lzc_relaunch_after_close(const char *title_id) {
  (void)title_id;
  return -1;
}
