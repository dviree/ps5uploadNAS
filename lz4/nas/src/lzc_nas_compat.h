/*
 * LZ4 Compression - NAS (Linux) build compatibility layer.
 *
 * Force-included into every translation unit of the NAS build
 * (nas/Makefile passes -include). The engine was written against the PS5's
 * FreeBSD userland; this maps the few BSD-only interfaces it uses onto Linux
 * so the shared sources stay untouched.
 */
#pragma once

#ifdef __linux__

#include <stdint.h>
#include <sys/mount.h>
#include <sys/types.h>
#include <sys/vfs.h>

#define LZC_NAS 1

/* FreeBSD's struct statfs carries the mount source, mount point and
 * filesystem type name; Linux's does not. lzc_bsd_statfs() fills them from
 * /proc/self/mountinfo. */
#define LZC_BSD_MFSNAMELEN 32
#define LZC_BSD_MNAMELEN 1024

struct lzc_bsd_statfs {
  uint64_t f_bsize;
  uint64_t f_blocks;
  uint64_t f_bfree;
  uint64_t f_bavail;
  uint64_t f_files;
  uint64_t f_ffree;
  struct { int val[2]; } f_fsid;
  char f_fstypename[LZC_BSD_MFSNAMELEN];
  char f_mntfromname[LZC_BSD_MNAMELEN];
  char f_mntonname[LZC_BSD_MNAMELEN];
};

int lzc_bsd_statfs(const char *path, struct lzc_bsd_statfs *out);

/* Renames both the struct tag and the function in the shared sources. */
#define statfs lzc_bsd_statfs

/* FreeBSD unmount(2). */
int unmount(const char *dir, int flags);

#endif /* __linux__ */
