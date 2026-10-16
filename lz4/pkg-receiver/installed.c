/* installed (PS5-LZ4 NAS): what is already on the PS5, for the page's
 * "Installed" / "On PS5" marks. GET /api/installed answers
 *   {"apps":[{"id":"CUSA00001","ver":"01.06","patch":true},...],
 *    "files":[{"path":"/data/homebrew/x.exfat","size":N},...]}
 * apps: the folders in /user/app (version from the app's param.sfo or
 * param.json, where one is found); patch: /user/patch/<id> exists; files:
 * what is in the homebrew folders the page copies images to. */

static int
inst_read(const char *file, char *buf, size_t sz)
{
	int f = open(file, O_RDONLY);
	ssize_t n;

	if (f < 0)
		return -1;
	n = read(f, buf, sz - 1);
	close(f);
	if (n <= 0)
		return -1;
	buf[n] = 0;
	return (int)n;
}

/* APP_VER from a param.sfo */
static int
inst_sfo_ver(const char *file, char *out, size_t sz)
{
	static unsigned char b[65536];
	int n = inst_read(file, (char *)b, sizeof(b));
	uint32_t keys, data, cnt, i;

	if (n < 0x14 || memcmp(b, "\0PSF", 4) != 0)
		return -1;
	memcpy(&keys, b + 0x08, 4);
	memcpy(&data, b + 0x0C, 4);
	memcpy(&cnt, b + 0x10, 4);
	for (i = 0; i < cnt && 0x14 + i * 16 + 16 <= (uint32_t)n; i++) {
		const unsigned char *e = b + 0x14 + i * 16;
		uint16_t koff;
		uint32_t len, doff;

		memcpy(&koff, e, 2);
		memcpy(&len, e + 4, 4);
		memcpy(&doff, e + 12, 4);
		if (keys + koff >= (uint32_t)n ||
		    strcmp((const char *)b + keys + koff, "APP_VER") != 0)
			continue;
		if (data + doff + len > (uint32_t)n || len == 0)
			return -1;
		snprintf(out, sz, "%.*s", (int)strnlen((const char *)b + data + doff, len),
		    (const char *)b + data + doff);
		return 0;
	}
	return -1;
}

/* contentVersion from a PS5 param.json */
static int
inst_json_ver(const char *file, char *out, size_t sz)
{
	static char b[65536];
	char *p, *q;

	if (inst_read(file, b, sizeof(b)) < 0 || !(p = strstr(b, "\"contentVersion\"")))
		return -1;
	if (!(p = strchr(p + 16, '"')) || !(q = strchr(p + 1, '"')))
		return -1;
	snprintf(out, sz, "%.*s", (int)(q - p - 1), p + 1);
	return 0;
}

static void
inst_ver(const char *id, char *out, size_t sz)
{
	static const char *sfo[] = { "/system_data/priv/appmeta/%s/param.sfo",
	    "/user/appmeta/%s/param.sfo", "/user/app/%s/sce_sys/param.sfo" };
	static const char *js[] = { "/system_data/priv/appmeta/%s/param.json",
	    "/user/appmeta/%s/param.json", "/user/app/%s/sce_sys/param.json" };
	char file[256];
	size_t i;

	out[0] = 0;
	for (i = 0; i < sizeof(sfo) / sizeof(sfo[0]); i++) {
		snprintf(file, sizeof(file), sfo[i], id);
		if (inst_sfo_ver(file, out, sz) == 0)
			return;
		snprintf(file, sizeof(file), js[i], id);
		if (inst_json_ver(file, out, sz) == 0)
			return;
	}
}

static void
installed_api(int fd)
{
	static const char *dirs[] = { "/data/homebrew", "/mnt/usb0/homebrew",
	    "/mnt/usb1/homebrew", "/mnt/ext0/homebrew", "/mnt/ext1/homebrew" };
	size_t cap = 256 * 1024, off = 0, i;
	char *j = malloc(cap), ver[32], esc[600], file[600];
	DIR *dp;
	struct dirent *de;
	struct stat st;
	int first = 1;

	if (!j) {
		send_text(fd, "error:out of memory");
		return;
	}
	off += snprintf(j + off, cap - off, "{\"apps\":[");
	if ((dp = opendir("/user/app"))) {
		while ((de = readdir(dp)) != NULL && off < cap - 512) {
			if (strlen(de->d_name) != 9 || de->d_name[0] == '.')
				continue;
			inst_ver(de->d_name, ver, sizeof(ver));
			json_escape(ver, esc, sizeof(esc));
			snprintf(file, sizeof(file), "/user/patch/%s", de->d_name);
			off += snprintf(j + off, cap - off,
			    "%s{\"id\":\"%s\",\"ver\":\"%s\",\"patch\":%s}",
			    first ? "" : ",", de->d_name, esc,
			    stat(file, &st) == 0 ? "true" : "false");
			first = 0;
		}
		closedir(dp);
	}
	off += snprintf(j + off, cap - off, "],\"files\":[");
	first = 1;
	for (i = 0; i < sizeof(dirs) / sizeof(dirs[0]); i++) {
		if (!(dp = opendir(dirs[i])))
			continue;
		while ((de = readdir(dp)) != NULL && off < cap - 1024) {
			if (de->d_name[0] == '.')
				continue;
			snprintf(file, sizeof(file), "%s/%s", dirs[i], de->d_name);
			if (stat(file, &st) != 0)
				continue;
			json_escape(file, esc, sizeof(esc));
			off += snprintf(j + off, cap - off,
			    "%s{\"path\":\"%s\",\"size\":%lld,\"dir\":%s}",
			    first ? "" : ",", esc, (long long)st.st_size,
			    S_ISDIR(st.st_mode) ? "true" : "false");
			first = 0;
		}
		closedir(dp);
	}
	snprintf(j + off, cap - off, "]}");
	send_json(fd, j);
	free(j);
}

/* GET /api/df?path=/mnt/usb0 : {"ok":true,"total":N,"free":N} for any drive
 * (pkg-receiver's own /api/space covers /data only). */
static void
df_api(int fd, const char *path)
{
	char p[256], out[160];
	struct statvfs sv;

	if (!query_param(path, "path", p, sizeof(p)) || p[0] != '/' || strstr(p, "..") ||
	    (strncmp(p, "/data", 5) != 0 && strncmp(p, "/mnt/", 5) != 0 && strncmp(p, "/user", 5) != 0)) {
		send_json(fd, "{\"ok\":false,\"error\":\"bad path\"}");
		return;
	}
	if (statvfs(p, &sv) != 0) {
		send_json(fd, "{\"ok\":false,\"error\":\"no such drive\"}");
		return;
	}
	snprintf(out, sizeof(out), "{\"ok\":true,\"total\":%llu,\"free\":%llu}",
	    (unsigned long long)sv.f_blocks * sv.f_frsize,
	    (unsigned long long)sv.f_bavail * sv.f_frsize);
	send_json(fd, out);
}

/* POST /api/uninstall?tid=PPSA01234 : unregister a title from the home
 * screen (sceAppInstUtilAppUnInstall), e.g. after its game folder was
 * deleted. The page's own launcher can't be removed this way. */
typedef int (*uninstall_fn)(const char *);

static void
uninstall_api(int fd, const char *path)
{
	char tid[16], out[160];
	uninstall_fn f;
	int rc, i;

	if (!query_param(path, "tid", tid, sizeof(tid)) || strlen(tid) != 9) {
		send_json(fd, "{\"ok\":false,\"error\":\"bad title id\"}");
		return;
	}
	for (i = 0; i < 9; i++)
		if (!((tid[i] >= 'A' && tid[i] <= 'Z') || (tid[i] >= '0' && tid[i] <= '9'))) {
			send_json(fd, "{\"ok\":false,\"error\":\"bad title id\"}");
			return;
		}
	if (!strcmp(tid, "PKGS12800")) {
		send_json(fd, "{\"ok\":false,\"error\":\"that is this page's launcher\"}");
		return;
	}
	if (installer_init() != 0) {
		send_json(fd, "{\"ok\":false,\"error\":\"AppInstUtil not available\"}");
		return;
	}
	f = (uninstall_fn)dlsym(g_applib, "sceAppInstUtilAppUnInstall");
	if (!f) {
		send_json(fd, "{\"ok\":false,\"error\":\"sceAppInstUtilAppUnInstall not found\"}");
		return;
	}
	rc = f(tid);
	snprintf(out, sizeof(out), "{\"ok\":%s,\"rc\":\"0x%08X\"}", rc == 0 ? "true" : "false", (unsigned)rc);
	send_json(fd, out);
}
