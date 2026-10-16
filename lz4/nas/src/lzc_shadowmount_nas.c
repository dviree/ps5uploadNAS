/*
 * LZ4 Compression - NAS build: ShadowMountPlus only exists on the PS5.
 *
 * Its hints live in /data/shadowmount on the console, and it rescans its
 * sources on its own when the games are copied back, so on the NAS hint and
 * scan requests succeed without doing anything. Mount and unmount requests
 * report that the API is unavailable, which the engine already handles.
 */

#include <stdio.h>

#include "lzc_shadowmount.h"

static void
clear_err(char *err, size_t err_size) {
  if(err && err_size) err[0] = 0;
}

int
lzc_shadowmount_write_pfsc_hints(const char *outer_path,
                                const char *nested_name, int nested_type,
                                char *err, size_t err_size) {
  (void)outer_path;
  (void)nested_name;
  (void)nested_type;
  clear_err(err, err_size);
  return 0;
}

int
lzc_shadowmount_prepare_pfsc_hints_for_title(const char *title_id,
                                            const char *outer_path,
                                            const char *nested_name,
                                            int nested_type, char *err,
                                            size_t err_size) {
  (void)title_id;
  (void)outer_path;
  (void)nested_name;
  (void)nested_type;
  clear_err(err, err_size);
  return 0;
}

int
lzc_shadowmount_prepare_image_hints_for_title(const char *title_id,
                                             const char *image_path,
                                             int nested_type, char *err,
                                             size_t err_size) {
  (void)title_id;
  (void)image_path;
  (void)nested_type;
  clear_err(err, err_size);
  return 0;
}

int
lzc_shadowmount_ensure_image_read_only(const char *image_path,
                                      int *already_present, char *err,
                                      size_t err_size) {
  (void)image_path;
  if(already_present) *already_present = 1;
  clear_err(err, err_size);
  return 0;
}

int
lzc_shadowmount_remove_pfsc_hints(const char *outer_path,
                                 const char *nested_name, int nested_type,
                                 char *err, size_t err_size) {
  (void)outer_path;
  (void)nested_name;
  (void)nested_type;
  clear_err(err, err_size);
  return 0;
}

int
lzc_shadowmount_remove_title_pfsc_hints(const char *title_id,
                                       const char *outer_path, char *err,
                                       size_t err_size) {
  (void)title_id;
  (void)outer_path;
  clear_err(err, err_size);
  return 0;
}

int
lzc_shadowmount_remove_outer_sector_hint(const char *outer_path, char *err,
                                        size_t err_size) {
  (void)outer_path;
  clear_err(err, err_size);
  return 0;
}

int
lzc_shadowmount_request_source_scan(const char *source_path, char *err,
                                   size_t err_size) {
  (void)source_path;
  clear_err(err, err_size);
  return 0;
}

int
lzc_shadowmount_request_title_source_scan(const char *title_id,
                                         const char *source_path, char *err,
                                         size_t err_size) {
  (void)title_id;
  (void)source_path;
  clear_err(err, err_size);
  return 0;
}

int
lzc_shadowmount_request_scan(char *err, size_t err_size) {
  clear_err(err, err_size);
  return 0;
}

int
lzc_shadowmount_request_mount(const char *title_id) {
  (void)title_id;
  return -1;
}

int
lzc_shadowmount_request_unmount(const char *title_id) {
  (void)title_id;
  return -1;
}

int
lzc_shadowmount_manual_remove_source(const char *source_path, char *err,
                                     size_t err_size) {
  (void)source_path;
  clear_err(err, err_size);
  return 0;
}

int
lzc_shadowmount_restart_running(char *detail, size_t detail_size) {
  if(detail && detail_size) {
    snprintf(detail, detail_size, "%s", "ShadowMountPlus is PS5-only");
  }
  return -1;
}
