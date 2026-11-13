/* ShadowMountPlus (PS5-LZ4 NAS): SMP's HTTP/JSON API listens on
 * 127.0.0.1:10101, on the PS5 only; this passes a fixed set of its routes
 * through for the NAS page (list games, icons, unmount, uninstall = take a
 * game off the home screen without touching its source, rescan, its logs, and moving a game between drives with ShadowMountPlus's own
 * checked job). Nothing that deletes a source is passed.
 *   POST /api/smp?route=/api/v1/games   (body: SMP's JSON request)
 *   GET  /api/smp-icon?title_id=PPSA01234 */
#define SMP_PORT 10101
#define SMP_MAX (8 << 20)

static const char *smp_routes[] = { "/api/v1/version", "/api/v1/games",
    "/api/v1/games/info", "/api/v1/games/unmount", "/api/v1/games/uninstall",
    "/api/v1/scan", "/api/v1/storage", "/api/v1/debug-log", "/api/v1/kernel-log",
    "/api/v1/games/move", "/api/v1/games/storage/status", "/api/v1/games/storage/cancel", NULL };

/* One request to SMP; returns the response body (malloc'ed, NUL-ended) or
 * NULL. *len gets its length. */
static char *
smp_call(const char *method, const char *route, const char *body, long blen, size_t *len)
{
	struct sockaddr_in sa;
	char hdr[512], *buf, *p;
	size_t cap = SMP_MAX, got = 0;
	int s = socket(AF_INET, SOCK_STREAM, 0);
	struct timeval tv = { 20, 0 };

	if (s < 0)
		return NULL;
	setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
	memset(&sa, 0, sizeof(sa));
	sa.sin_family = AF_INET;
	sa.sin_port = htons(SMP_PORT);
	sa.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
	if (connect(s, (struct sockaddr *)&sa, sizeof(sa)) != 0) {
		close(s);
		return NULL;
	}
	snprintf(hdr, sizeof(hdr), "%s %s HTTP/1.1\r\nHost: 127.0.0.1\r\n"
	    "Content-Type: application/json\r\nContent-Length: %ld\r\n"
	    "Connection: close\r\n\r\n", method, route, blen);
	send_all(s, hdr, strlen(hdr));
	if (blen > 0)
		send_all(s, body, (size_t)blen);
	if (!(buf = malloc(cap + 1))) {
		close(s);
		return NULL;
	}
	for (;;) {
		ssize_t n = recv(s, buf + got, cap - got, 0);
		if (n <= 0)
			break;
		got += (size_t)n;
		if (got >= cap)
			break;
	}
	close(s);
	buf[got] = 0;
	if (!(p = strstr(buf, "\r\n\r\n"))) {
		free(buf);
		return NULL;
	}
	p += 4;
	{
		/* de-chunk if needed */
		char *te = strcasestr(buf, "transfer-encoding: chunked");
		size_t o = 0;
		if (te && te < p) {
			char *q = p;
			while (q < buf + got) {
				long n = strtol(q, &q, 16);
				if (n <= 0 || !(q = strstr(q, "\r\n")))
					break;
				q += 2;
				if (q + n > buf + got)
					n = (long)(buf + got - q);
				memmove(buf + o, q, (size_t)n);
				o += (size_t)n;
				q += n + 2;
			}
			buf[o] = 0;
			*len = o;
			return buf;
		}
	}
	*len = got - (size_t)(p - buf);
	memmove(buf, p, *len + 1);
	return buf;
}

static void
smp_api(int fd, const char *path, const char *body, long blen)
{
	char route[64];
	size_t n = 0;
	char *res;
	int i, ok = 0;

	if (!query_param(path, "route", route, sizeof(route))) {
		send_json(fd, "{\"status\":22,\"error\":\"route missing\"}");
		return;
	}
	for (i = 0; smp_routes[i]; i++)
		if (!strcmp(route, smp_routes[i]))
			ok = 1;
	if (!ok) {
		send_json(fd, "{\"status\":1,\"error\":\"route not allowed\"}");
		return;
	}
	res = smp_call("POST", route, blen > 0 ? body : "{}", blen > 0 ? blen : 2, &n);
	if (!res) {
		send_json(fd, "{\"status\":111,\"error\":\"ShadowMountPlus does not answer on 127.0.0.1:10101 (is it running, version 1.7 or newer?)\"}");
		return;
	}
	send_json(fd, res);
	free(res);
}

static void
smp_icon_api(int fd, const char *path)
{
	char tid[16], route[96];
	size_t n = 0;
	char *res;

	if (!query_param(path, "title_id", tid, sizeof(tid)) || strlen(tid) != 9) {
		send_text(fd, "error:bad title id");
		return;
	}
	snprintf(route, sizeof(route), "/api/v1/games/icon?title_id=%s&size=thumb", tid);
	res = smp_call("GET", route, "", 0, &n);
	if (!res || n < 8 || memcmp(res, "\x89PNG", 4) != 0) {
		free(res);
		send_text(fd, "error:no icon");
		return;
	}
	send_png(fd, (const unsigned char *)res, n);
	free(res);
}

/* POST /api/notify (body: plain text, up to 200 characters): a notification
 * on the PS5, for what the NAS starts or finishes there. */
static void
notify_api(int fd, const char *body, long blen)
{
	char msg[208];
	long i, n = blen < 200 ? blen : 200;

	if (n <= 0) {
		send_json(fd, "{\"ok\":false,\"error\":\"empty\"}");
		return;
	}
	for (i = 0; i < n; i++)
		msg[i] = (body[i] == '\r' || body[i] == '\n') ? ' ' : body[i];
	msg[n] = 0;
	notify_user(msg);
	send_json(fd, "{\"ok\":true}");
}
