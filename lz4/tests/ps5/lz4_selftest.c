/*
 * PS5 self-test for the AMPR LZ4 packer. Runs the same code Game
 * Compressor uses against /data/lz4test/game and writes
 * /data/lz4test/selftest.log and result.json:
 *   1. pack (copy) game -> out, verified against the source
 *   2. verify out again, unpack out -> unpacked, compare with game
 *   3. copy game -> inplace, pack in place, verify, unpack in place, compare
 *   4. fast and max levels for throughput
 */

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <unistd.h>

#include "ampr_pack.h"

#define BASE "/data/lz4test"

static FILE *g_log;
static double g_t0;
static double g_phase_t;
static char g_phase[32];

static double
now_s(void) {
  struct timeval tv;
  gettimeofday(&tv, NULL);
  return tv.tv_sec + tv.tv_usec / 1e6;
}

static void
logf_(const char *fmt, ...) {
  char line[1024];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(line, sizeof(line), fmt, ap);
  va_end(ap);
  if(g_log) {
    fprintf(g_log, "[%8.2f] %s\n", now_s() - g_t0, line);
    fflush(g_log);
  }
  printf("[lz4-selftest] %s\n", line);
}

static void
on_phase(void *ctx, const char *phase, const char *label) {
  (void)ctx;
  double t = now_s();
  if(g_phase[0]) logf_("  phase %s took %.2fs", g_phase, t - g_phase_t);
  snprintf(g_phase, sizeof(g_phase), "%s", phase);
  g_phase_t = t;
  logf_("  phase %s: %s", phase, label);
}

static void
on_log(void *ctx, const char *msg) {
  (void)ctx;
  logf_("  %s", msg);
}

static void
phase_end(void) {
  if(g_phase[0]) logf_("  phase %s took %.2fs", g_phase, now_s() - g_phase_t);
  g_phase[0] = 0;
}

static void
remove_tree(const char *path) {
  struct stat st;
  if(lstat(path, &st) != 0) return;
  if(S_ISDIR(st.st_mode)) {
    DIR *d = opendir(path);
    struct dirent *e;
    while(d && (e = readdir(d)) != NULL) {
      char child[1024];
      if(!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
      snprintf(child, sizeof(child), "%s/%s", path, e->d_name);
      remove_tree(child);
    }
    if(d) closedir(d);
    rmdir(path);
  } else {
    unlink(path);
  }
}

static int
copy_tree(const char *src, const char *dst) {
  struct stat st;
  if(lstat(src, &st) != 0) return -1;
  if(S_ISDIR(st.st_mode)) {
    if(mkdir(dst, 0777) != 0 && errno != EEXIST) return -1;
    DIR *d = opendir(src);
    struct dirent *e;
    int rc = 0;
    while(rc == 0 && d && (e = readdir(d)) != NULL) {
      char a[1024], b[1024];
      if(!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
      snprintf(a, sizeof(a), "%s/%s", src, e->d_name);
      snprintf(b, sizeof(b), "%s/%s", dst, e->d_name);
      rc = copy_tree(a, b);
    }
    if(d) closedir(d);
    return rc;
  }
  int in = open(src, O_RDONLY);
  int out = open(dst, O_WRONLY | O_CREAT | O_TRUNC, 0666);
  static char buf[1 << 20];
  int rc = in >= 0 && out >= 0 ? 0 : -1;
  while(rc == 0) {
    ssize_t n = read(in, buf, sizeof(buf));
    if(n < 0) rc = -1;
    if(n <= 0) break;
    if(write(out, buf, (size_t)n) != n) rc = -1;
  }
  if(in >= 0) close(in);
  if(out >= 0) close(out);
  struct timeval tv[2] = { { st.st_mtime, 0 }, { st.st_mtime, 0 } };
  utimes(dst, tv);
  return rc;
}

static int
skip_compare(const char *rel) {
  return !strcasecmp(rel, "fakelib/libSceAmpr.sprx") ||
         !strcasecmp(rel, "ampr_emu.index");
}

/* Every file under a (except the runtime/index) must be identical in b. */
static int
compare_trees(const char *a, const char *b, const char *rel, uint64_t *files,
              uint64_t *bytes) {
  char pa[1024], pb[1024];
  struct stat st;
  snprintf(pa, sizeof(pa), "%s%s%s", a, rel[0] ? "/" : "", rel);
  snprintf(pb, sizeof(pb), "%s%s%s", b, rel[0] ? "/" : "", rel);
  if(lstat(pa, &st) != 0) return -1;
  if(S_ISDIR(st.st_mode)) {
    DIR *d = opendir(pa);
    struct dirent *e;
    int rc = 0;
    while(rc == 0 && d && (e = readdir(d)) != NULL) {
      char crel[1024];
      if(!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
      snprintf(crel, sizeof(crel), "%s%s%s", rel, rel[0] ? "/" : "", e->d_name);
      rc = compare_trees(a, b, crel, files, bytes);
    }
    if(d) closedir(d);
    return rc;
  }
  if(skip_compare(rel)) return 0;
  int fa = open(pa, O_RDONLY), fb = open(pb, O_RDONLY);
  static char ba[1 << 20], bb[1 << 20];
  int rc = fa >= 0 && fb >= 0 ? 0 : -1;
  if(rc) logf_("compare: missing %s", rel);
  while(rc == 0) {
    ssize_t na = read(fa, ba, sizeof(ba));
    ssize_t nb = read(fb, bb, sizeof(bb));
    if(na != nb || (na > 0 && memcmp(ba, bb, (size_t)na))) {
      logf_("compare: %s differs", rel);
      rc = -1;
    }
    if(na <= 0) break;
    *bytes += (uint64_t)na;
  }
  if(fa >= 0) close(fa);
  if(fb >= 0) close(fb);
  (*files)++;
  return rc;
}

static int
run_pack(const char *src, const char *out, int mode, int level,
         ampr_pack_stats_t *st, double *secs) {
  ampr_pack_options_t o;
  ampr_pack_callbacks_t cb = { NULL, on_phase, NULL, NULL, NULL, on_log };
  char err[512] = {0};
  memset(&o, 0, sizeof(o));
  o.source_root = src;
  o.output_root = out;
  o.mode = mode;
  o.level = level;
  o.block_shift = 16;
  o.workers = 0;
  o.auto_loose_large = 1;
  o.learn_dir = "/data/LZ4Compression/lz4-profiles";
  o.runtime = ampr_pack_runtime_data(&o.runtime_size);
  o.verify_loose_copies = 1;
  o.cb = cb;
  if(mode == AMPR_PACK_MODE_COPY) mkdir(out, 0777);
  double t = now_s();
  int rc = ampr_pack_build(&o, st, err, sizeof(err));
  phase_end();
  *secs = now_s() - t;
  if(rc) {
    logf_("pack FAILED level=%d mode=%d: %s", level, mode, err);
  } else {
    logf_("pack ok level=%d mode=%d %.2fs packed=%llu loose=%llu auto=%llu chunks=%llu lz4=%llu raw=%llu shared=%llu logical=%llu stored=%llu packBytes=%llu removed=%llu workers=%u runtime=%d build=%s",
          level, mode, *secs, (unsigned long long)st->files_packed,
          (unsigned long long)st->files_loose,
          (unsigned long long)st->files_auto_loose, (unsigned long long)st->chunks,
          (unsigned long long)st->chunks_lz4, (unsigned long long)st->chunks_raw,
          (unsigned long long)st->chunks_shared,
          (unsigned long long)st->logical_bytes,
          (unsigned long long)st->stored_bytes,
          (unsigned long long)st->pack_bytes,
          (unsigned long long)st->removed_bytes, st->workers,
          st->runtime_installed, st->build_id);
  }
  return rc;
}

int
main(void) {
  ampr_pack_stats_t st;
  ampr_pack_callbacks_t cb = { NULL, on_phase, NULL, NULL, NULL, on_log };
  char err[512] = {0};
  double secs = 0, verify_s = 0, unpack_s = 0, fast_s = 0, max_s = 0, inplace_s = 0;
  uint64_t files = 0, bytes = 0;
  int failures = 0;
  FILE *res;

  g_t0 = now_s();
  g_log = fopen(BASE "/selftest.log", "w");
  logf_("start cpus=%ld runtime=%s %s", sysconf(_SC_NPROCESSORS_ONLN),
        ampr_pack_runtime_version(), ampr_pack_runtime_sha256());
  remove_tree(BASE "/out");
  remove_tree(BASE "/unpacked");
  remove_tree(BASE "/inplace");
  remove_tree(BASE "/out_fast");
  remove_tree(BASE "/out_max");

  if(run_pack(BASE "/game", BASE "/out", AMPR_PACK_MODE_COPY, 9, &st, &secs)) failures++;
  double t = now_s();
  if(ampr_pack_verify(BASE "/out", NULL, &cb, &st, err, sizeof(err)) != 0) {
    logf_("verify FAILED: %s", err);
    failures++;
  }
  phase_end();
  verify_s = now_s() - t;
  logf_("verify(no source) %.2fs files=%llu logical=%llu", verify_s,
        (unsigned long long)st.files_packed, (unsigned long long)st.logical_bytes);
  t = now_s();
  mkdir(BASE "/unpacked", 0777);
  if(ampr_pack_unpack(BASE "/out", BASE "/unpacked", &cb, &st, err, sizeof(err)) != 0) {
    logf_("unpack FAILED: %s", err);
    failures++;
  }
  phase_end();
  unpack_s = now_s() - t;
  files = bytes = 0;
  if(compare_trees(BASE "/game", BASE "/unpacked", "", &files, &bytes) != 0) {
    logf_("unpacked tree differs");
    failures++;
  }
  logf_("unpack %.2fs compared files=%llu bytes=%llu", unpack_s,
        (unsigned long long)files, (unsigned long long)bytes);

  if(copy_tree(BASE "/game", BASE "/inplace") != 0) {
    logf_("copy for in-place test failed");
    failures++;
  }
  ampr_pack_stats_t ist;
  if(run_pack(BASE "/inplace", NULL, AMPR_PACK_MODE_IN_PLACE, 9, &ist, &inplace_s)) failures++;
  if(ampr_pack_verify(BASE "/inplace", NULL, &cb, &st, err, sizeof(err)) != 0) {
    logf_("in-place verify FAILED: %s", err);
    failures++;
  }
  phase_end();
  if(ampr_pack_unpack(BASE "/inplace", NULL, &cb, &st, err, sizeof(err)) != 0) {
    logf_("in-place unpack FAILED: %s", err);
    failures++;
  }
  phase_end();
  files = bytes = 0;
  if(compare_trees(BASE "/game", BASE "/inplace", "", &files, &bytes) != 0) {
    logf_("in-place round trip differs");
    failures++;
  }
  logf_("in-place round trip compared files=%llu bytes=%llu", (unsigned long long)files,
        (unsigned long long)bytes);
  if(ampr_pack_tree_has_manifest(BASE "/inplace")) {
    logf_("in-place unpack left the manifest behind");
    failures++;
  }

  ampr_pack_stats_t fst, mst;
  if(run_pack(BASE "/game", BASE "/out_fast", AMPR_PACK_MODE_COPY, 1, &fst, &fast_s)) failures++;
  if(run_pack(BASE "/game", BASE "/out_max", AMPR_PACK_MODE_COPY, 12, &mst, &max_s)) failures++;
  remove_tree(BASE "/out_fast");
  remove_tree(BASE "/out_max");
  remove_tree(BASE "/inplace");
  remove_tree(BASE "/unpacked");

  res = fopen(BASE "/result.json", "w");
  if(res) {
    fprintf(res,
            "{\"ok\":%s,\"failures\":%d,\"cpus\":%ld,\"workers\":%u,"
            "\"packSeconds\":%.2f,\"verifySeconds\":%.2f,\"unpackSeconds\":%.2f,"
            "\"inplaceSeconds\":%.2f,\"fastSeconds\":%.2f,\"maxSeconds\":%.2f,"
            "\"logical\":%llu,\"stored9\":%llu,\"stored1\":%llu,\"stored12\":%llu,"
            "\"removedInPlace\":%llu}\n",
            failures ? "false" : "true", failures,
            sysconf(_SC_NPROCESSORS_ONLN), ist.workers, secs, verify_s, unpack_s,
            inplace_s, fast_s, max_s,
            (unsigned long long)ist.logical_bytes,
            (unsigned long long)ist.stored_bytes,
            (unsigned long long)fst.stored_bytes,
            (unsigned long long)mst.stored_bytes,
            (unsigned long long)ist.removed_bytes);
    fclose(res);
  }
  logf_("done failures=%d total %.2fs", failures, now_s() - g_t0);
  if(g_log) fclose(g_log);
  return failures ? 1 : 0;
}
