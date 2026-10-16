/*
 * LZ4 Compression - NAS notifications.
 *
 * There is no PS5 toast on a NAS; notifications go to the log (and the
 * container's stdout), and the web page already shows job results.
 */

#include <string.h>

#include "lzc_diag.h"
#include "lzc_notify.h"

void
lzc_notify_operation_done(const char *action, const char *game,
                         const char *status, const char *detail) {
  lzc_log("notify %s %s: %s%s%s", action ? action : "",
          game && game[0] ? game : "Game", status ? status : "",
          detail && detail[0] ? " - " : "", detail ? detail : "");
}

void
lzc_notify_message(const char *title, const char *detail) {
  lzc_log("notify %s%s%s", title && title[0] ? title : "Notice",
          detail && detail[0] ? ": " : "", detail ? detail : "");
}
