/* keep-awake (PS5-LZ4 NAS): keep the PS5 out of rest mode, by resetting its
 * auto power-down timer every 20 s, always (unless switched off from the
 * page) and in any case while it installs, pulls a file, or the NAS asks for
 * it (/api/keep-awake?seconds=N during its transfers). The same calls the
 * LZ4 Compression engine's power guard makes. */
extern int sceShellCoreUtilResetAutoPowerDownTimer(void) __attribute__((weak));
extern int sceSystemServicePowerTick(void) __attribute__((weak));

#define AWAKE_OFF_FLAG "/data/pkg-receiver-awake-off"

static volatile time_t g_awake_until = 0;
static volatile int g_awake_always = 1;
static volatile int g_awake_last_rc = 0;

static int
awake_needed(void)
{
	return g_awake_always || g_active_installs > 0 || g_pull_active ||
	    time(NULL) < g_awake_until;
}

static void *
awake_worker(void *arg)
{
	(void)arg;
	for (;;) {
		if (awake_needed()) {
			if (sceShellCoreUtilResetAutoPowerDownTimer)
				g_awake_last_rc = sceShellCoreUtilResetAutoPowerDownTimer();
			else
				g_awake_last_rc = -1;
			if (sceSystemServicePowerTick)
				sceSystemServicePowerTick();
		}
		sleep(20);
	}
	return NULL;
}

static void
awake_start(void)
{
	pthread_t tid;
	struct stat st;

	g_awake_always = stat(AWAKE_OFF_FLAG, &st) != 0;
	if (pthread_create(&tid, NULL, awake_worker, NULL) == 0)
		pthread_detach(tid);
}

/* GET /api/keep-awake[?seconds=N][&always=0|1] */
static void
awake_api(int fd, const char *path)
{
	char v[32], out[160];
	time_t now = time(NULL);

	if (query_param(path, "seconds", v, sizeof(v))) {
		long s = strtol(v, NULL, 10);
		if (s < 0)
			s = 0;
		if (s > 3600)
			s = 3600;
		g_awake_until = s ? now + s : 0;
	}
	if (query_param(path, "always", v, sizeof(v))) {
		g_awake_always = v[0] == '1';
		if (g_awake_always) {
			unlink(AWAKE_OFF_FLAG);
		} else {
			int f = open(AWAKE_OFF_FLAG, O_WRONLY | O_CREAT | O_TRUNC, 0644);
			if (f >= 0)
				close(f);
		}
	}
	snprintf(out, sizeof(out), "{\"ok\":true,\"always\":%s,\"left\":%ld,"
	    "\"awake\":%s,\"rc\":%d}",
	    g_awake_always ? "true" : "false",
	    g_awake_until > now ? (long)(g_awake_until - now) : 0L,
	    awake_needed() ? "true" : "false", g_awake_last_rc);
	send_json(fd, out);
}
