/*
 * LZ4 Compression - NAS (Linux) platform shims.
 *
 * statfs/unmount for the FreeBSD-flavoured shared sources, and the few PS5
 * system service calls the engine makes. On a NAS no game can be running,
 * so the running-app queries report nothing.
 */

#include <errno.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <unistd.h>

#undef statfs

static void
mountinfo_unescape(char *s) {
  char *r = s;
  char *w = s;
  while(*r) {
    if(r[0] == '\\' && r[1] >= '0' && r[1] <= '7' && r[2] >= '0' &&
       r[2] <= '7' && r[3] >= '0' && r[3] <= '7') {
      *w++ = (char)(((r[1] - '0') << 6) | ((r[2] - '0') << 3) | (r[3] - '0'));
      r += 4;
      continue;
    }
    *w++ = *r++;
  }
  *w = 0;
}

static int
path_under_mount(const char *path, const char *mnt) {
  size_t n = strlen(mnt);
  if(!strcmp(mnt, "/")) return 1;
  if(strncmp(path, mnt, n) != 0) return 0;
  return path[n] == 0 || path[n] == '/';
}

/* Longest mount point in /proc/self/mountinfo that contains path. */
static void
fill_mount_names(const char *path, struct lzc_bsd_statfs *out) {
  char resolved[PATH_MAX];
  char line[4096];
  size_t best = 0;
  FILE *f;

  if(!realpath(path, resolved)) {
    snprintf(resolved, sizeof(resolved), "%s", path);
  }
  f = fopen("/proc/self/mountinfo", "r");
  if(!f) return;
  while(fgets(line, sizeof(line), f)) {
    /* id parent major:minor root mountpoint options [optional...] - fstype
     * source superoptions */
    char *fields[8] = {0};
    char *save = NULL;
    char *tok = strtok_r(line, " \n", &save);
    int i = 0;
    while(tok && i < 5) {
      fields[i++] = tok;
      tok = strtok_r(NULL, " \n", &save);
    }
    if(i < 5) continue;
    while(tok && strcmp(tok, "-") != 0) tok = strtok_r(NULL, " \n", &save);
    if(!tok) continue;
    char *fstype = strtok_r(NULL, " \n", &save);
    char *source = strtok_r(NULL, " \n", &save);
    if(!fstype) continue;

    char *mnt = fields[4];
    mountinfo_unescape(mnt);
    if(!path_under_mount(resolved, mnt)) continue;
    size_t len = strlen(mnt);
    if(len < best) continue;
    best = len;
    snprintf(out->f_mntonname, sizeof(out->f_mntonname), "%s", mnt);
    snprintf(out->f_fstypename, sizeof(out->f_fstypename), "%s", fstype);
    if(source) {
      mountinfo_unescape(source);
      snprintf(out->f_mntfromname, sizeof(out->f_mntfromname), "%s", source);
    } else {
      out->f_mntfromname[0] = 0;
    }
  }
  fclose(f);
}

int
lzc_bsd_statfs(const char *path, struct lzc_bsd_statfs *out) {
  struct statfs fs;
  if(!path || !out) {
    errno = EINVAL;
    return -1;
  }
  if(statfs(path, &fs) != 0) return -1;
  memset(out, 0, sizeof(*out));
  out->f_bsize = (uint64_t)fs.f_bsize;
  out->f_blocks = (uint64_t)fs.f_blocks;
  out->f_bfree = (uint64_t)fs.f_bfree;
  out->f_bavail = (uint64_t)fs.f_bavail;
  out->f_files = (uint64_t)fs.f_files;
  out->f_ffree = (uint64_t)fs.f_ffree;
  memcpy(&out->f_fsid, &fs.f_fsid, sizeof(out->f_fsid));
  fill_mount_names(path, out);
  return 0;
}

int
unmount(const char *dir, int flags) {
  return umount2(dir, flags ? MNT_FORCE : 0);
}

/* PS5 system services. Nothing runs games on the NAS. */
int
sceSystemServiceGetAppIdOfRunningBigApp(void) {
  return -1;
}

int
sceSystemServiceGetAppTitleId(int app_id, char *title_id) {
  (void)app_id;
  if(title_id) title_id[0] = 0;
  return -1;
}

uint32_t
sceLncUtilKillApp(uint32_t app_id) {
  (void)app_id;
  return 0x80020003u;
}
