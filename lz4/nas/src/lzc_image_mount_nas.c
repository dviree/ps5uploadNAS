/*
 * LZ4 Compression - read-only image mounts on a NAS (see lzc_image_mount.h).
 *
 * The PS5 build attaches .exfat images as md(4) disks. On Linux the image
 * goes through a loop device instead (`mount -o ro,loop`), which needs the
 * engine to run as root with access to /dev/loop* (a privileged container)
 * and a kernel with exFAT support. When that is not available the mount
 * fails cleanly and the job reports why; folder games never need it.
 */

#include "lzc_image_mount.h"
#include "lzc_diag.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

#define LZC_MOUNT_ROOT "/mnt/lzc"

extern char **environ;

static int g_next_unit = 0;

int
lzc_image_mount_supported(const char *image_path) {
  const char *dot = image_path ? strrchr(image_path, '.') : NULL;
  return dot && !strcasecmp(dot, ".exfat");
}

static int
path_under(const char *path, const char *root) {
  size_t n = strlen(root);
  return !strncmp(path, root, n) && (path[n] == 0 || path[n] == '/');
}

static int
run_quiet(char *const argv[]) {
  pid_t pid;
  int status = 0;
  posix_spawn_file_actions_t fa;
  posix_spawn_file_actions_init(&fa);
  posix_spawn_file_actions_addopen(&fa, STDOUT_FILENO, "/dev/null", O_WRONLY, 0);
  posix_spawn_file_actions_addopen(&fa, STDERR_FILENO, "/dev/null", O_WRONLY, 0);
  int rc = posix_spawnp(&pid, argv[0], &fa, NULL, argv, environ);
  posix_spawn_file_actions_destroy(&fa);
  if(rc != 0) {
    errno = rc;
    return -1;
  }
  while(waitpid(pid, &status, 0) < 0) {
    if(errno != EINTR) return -1;
  }
  return WIFEXITED(status) ? WEXITSTATUS(status) : -1;
}

/* The mount point is still a mount of its own. */
static int
mount_is_ours(const char *mount_point) {
  struct statfs sfs;
  return statfs(mount_point, &sfs) == 0 &&
         !strcmp(sfs.f_mntonname, mount_point);
}

int
lzc_image_mount_ro(const char *image_path, const char *title_id,
                   lzc_image_mount_t *m, char *err, size_t err_size) {
  struct stat st;
  if(!m) return -1;
  memset(m, 0, sizeof(*m));
  m->unit = -1;
  if(!lzc_image_mount_supported(image_path) || stat(image_path, &st) != 0 ||
     !S_ISREG(st.st_mode) || st.st_size <= 0) {
    snprintf(err, err_size, "%s", "image can't be mounted here");
    return -1;
  }

  int unit = __atomic_fetch_add(&g_next_unit, 1, __ATOMIC_SEQ_CST);
  (void)mkdir(LZC_MOUNT_ROOT, 0777);
  snprintf(m->mount_point, sizeof(m->mount_point), "%s/%s-loop%d",
           LZC_MOUNT_ROOT, title_id && title_id[0] ? title_id : "image", unit);
  if(mkdir(m->mount_point, 0777) != 0 && errno != EEXIST) {
    snprintf(err, err_size, "create mount point: %s", strerror(errno));
    m->mount_point[0] = 0;
    return -1;
  }

  char *argv[] = { "mount", "-t", "exfat", "-o", "ro,loop",
                   (char *)image_path, m->mount_point, NULL };
  int rc = run_quiet(argv);
  if(rc != 0 || !mount_is_ours(m->mount_point)) {
    snprintf(err, err_size, "%s",
             "mount image: loop mounting .exfat images on the NAS needs a "
             "privileged container and exFAT support in the NAS kernel");
    lzc_log("image mount failed path=%s rc=%d", image_path, rc);
    rmdir(m->mount_point);
    m->mount_point[0] = 0;
    return -1;
  }
  m->unit = unit;
  snprintf(m->image_path, sizeof(m->image_path), "%s", image_path);
  lzc_log("image mount ready path=%s at=%s", image_path, m->mount_point);
  return 0;
}

int
lzc_image_unmount(lzc_image_mount_t *m) {
  int ok = 1;
  if(!m || m->unit < 0) return 0;
  if(m->mount_point[0]) {
    if(mount_is_ours(m->mount_point)) {
      /* `mount -o loop` sets autoclear, so the loop device goes with it. */
      if(umount2(m->mount_point, 0) != 0 &&
         umount2(m->mount_point, MNT_DETACH) != 0) {
        lzc_log("image unmount failed at=%s err=%s", m->mount_point,
                strerror(errno));
        ok = 0;
      }
    }
    rmdir(m->mount_point);
  }
  lzc_log("image mount released path=%s unit=%d ok=%d", m->image_path,
          m->unit, ok);
  m->unit = -1;
  m->mount_point[0] = 0;
  return ok ? 0 : -1;
}

void
lzc_image_mount_cleanup_stale(void) {
  DIR *d = opendir(LZC_MOUNT_ROOT);
  struct dirent *ent;
  while(d && (ent = readdir(d)) != NULL) {
    char path[512];
    if(ent->d_name[0] == '.') continue;
    snprintf(path, sizeof(path), "%s/%s", LZC_MOUNT_ROOT, ent->d_name);
    if(path_under(path, LZC_MOUNT_ROOT) && mount_is_ours(path)) {
      if(umount2(path, 0) != 0) (void)umount2(path, MNT_DETACH);
      lzc_log("image mount released stale mount at=%s", path);
    }
    rmdir(path);
  }
  if(d) closedir(d);
}
