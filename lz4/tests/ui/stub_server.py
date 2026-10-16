# Stub of the LZ4 Compression payload API for testing the web UI on a PC.
# Usage: python stub_server.py <repo>/assets <port>   (needs Pillow)
import io, json, os, re, sys, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from PIL import Image, ImageDraw
ASSETS = sys.argv[1]; PORT = int(sys.argv[2])
_ws = open(os.path.join(os.path.dirname(ASSETS), 'src', 'lzc_websrv.c')).read()
_post = _ws[_ws.index('if(!strcmp(req->method, "POST"))'):]
POST_ALLOW = set(re.findall(r'"(/api/[^"]+)"', _post[:_post.index('return websrv_send_error_json(req->fd, 404')]))
STATE = {'requests': [], 'profile': None, 'lists': {}, 'job': {'busy': False}, 'history': []}
G = 1024 ** 3
def game(**kw):
    base = dict(instanceId='', mountStatus='mounted', validation='', primaryAction='Compress', amprPath='', amprVersion='',
        amprSha256='', amprLatestVersion='', amprLatestSha256='', amprOriginalSha256='', sourceSize=40 * G, freeBytes=400 * G,
        requiredBytes=40 * G, extraBytes=0, streamMinFreeBytes=0, streamExtraBytes=0, compressionSourceSize=0, compressedSize=0,
        savedBytes=0, aprIndexed=False, amprHotSwapOptimized=False, amprPresent=False, amprUpdateNeeded=False,
        amprUpdateSupported=False, amprOriginalAvailable=False, amprOriginalSize=0, sizePending=False, sizeStatus='measured',
        sizeEstimated=False, sizeMeasuredAt=1, sizeRefreshing=False, canStreamDelete=True, isMounted=True, hasIcon=True,
        iconSize=1, iconMtime=1, outputExists=False, canMoveToUsb=True, canMoveToInternal=True, lz4Packed=False,
        lz4Supported=False, lz4ProfileAvailable=False, lz4PackCount=0, lz4Files=0)
    base.update(kw); base['instanceId'] = base['titleId'] + ':' + base['sourcePath']; return base
GAMES = [
    game(titleId='PPSA01325', name='ASTRO BOT', sourceKind='folder', sourcePath='/mnt/usb0/homebrew/PPSA01325-app',
         outputPath='/mnt/usb0/homebrew/PPSA01325.ffpfsc', storage='usb', amprPresent=True, lz4Supported=True,
         lz4AutoProfile={'id': 'astrobot', 'label': 'ASTRO BOT', 'tested': 'ASTRO BOT (PPSA21567, 01.019.000)', 'match': 'title'}),
    game(titleId='PPSA99058', name='Overdrive', sourceKind='folder', sourcePath='/data/homebrew/PPSA99058',
         outputPath='/data/homebrew/PPSA99058.ffpfsc', storage='internal', sourceSize=300 * 1024 * 1024, isApp=True),
    game(titleId='PPSA04264', name='Marvel Spider-Man', sourceKind='folder', sourcePath='/data/homebrew/PPSA04264-app-lz4',
         outputPath='/data/homebrew/PPSA04264.ffpfsc', storage='internal', amprPresent=True, lz4Packed=True,
         lz4PackCount=4, lz4Files=5210, canMoveToInternal=False),
    game(titleId='PPSA00001', name='Plain Game', sourceKind='folder', sourcePath='/data/homebrew/PPSA00001',
         outputPath='/data/homebrew/PPSA00001.ffpfsc', storage='internal', canMoveToInternal=False, hasIcon=False),
    game(titleId='PPSA02222', name='Gran Turismo 7', sourceKind='compressed', sourcePath='/data/homebrew/PPSA02222.ffpfsc',
         outputPath='/data/homebrew/PPSA02222.ffpfsc', storage='internal', canMoveToInternal=False, compressedSize=60 * G),
    game(titleId='PPSA03333', name='Returnal', sourceKind='image', sourcePath='/mnt/ext1/homebrew/PPSA03333.exfat',
         outputPath='/mnt/ext1/homebrew/PPSA03333.ffpfsc', storage='ext1', isMounted=False, mountStatus='on-demand'),
] + [game(titleId='PPSA9%04d' % i, name='Test Game %d' % i, sourceKind='folder', sourcePath='/data/homebrew/PPSA9%04d' % i,
          outputPath='/data/homebrew/PPSA9%04d.ffpfsc' % i, storage='internal', canMoveToInternal=False) for i in range(1, 9)]
COLORS = [(214, 64, 52), (40, 110, 220), (240, 170, 30), (30, 160, 110), (140, 70, 200), (220, 80, 150), (60, 180, 200), (120, 120, 130)]
_icon_cache = {}
def icon_png(tid, size):
    key = (tid, size)
    if key in _icon_cache: return _icon_cache[key]
    i = sum(map(ord, tid)) % len(COLORS); c = COLORS[i]; c2 = COLORS[(i + 3) % len(COLORS)]
    im = Image.new('RGB', (size, size)); d = ImageDraw.Draw(im)
    for y in range(size):
        t = y / size; d.line([(0, y), (size, y)], fill=tuple(int(c[k] * (1 - t) + c2[k] * t) for k in range(3)))
    d.ellipse([size * .2, size * .2, size * .8, size * .8], outline=(255, 255, 255), width=max(2, size // 40))
    b = io.BytesIO(); im.save(b, 'PNG'); _icon_cache[key] = b.getvalue(); return _icon_cache[key]
def profile_status(tid):
    p = STATE['profile']
    inc = [{'name': n, 'present': n in STATE['lists']} for n in (['astro.rule-001.include.txt'] if p else [])]
    return {'titleId': tid, 'exists': bool(p), 'size': len(p or b''), 'mtime': 1, 'includes': inc, 'error': ''}
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send_body(self, code, ctype, b):
        self.send_response(code); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def send_json(self, obj, code=200): self.send_body(code, 'application/json', json.dumps(obj, default=lambda o: o.decode('latin-1')).encode())
    def handle_any(self, method):
        u = urllib.parse.urlparse(self.path); q = dict(urllib.parse.parse_qsl(u.query)); path = u.path
        length = int(self.headers.get('Content-Length') or 0); body = self.rfile.read(length) if length else b''
        if method == 'POST' and path.startswith('/api/') and path not in POST_ALLOW:
            STATE['requests'].append({'method': method, 'path': path, 'query': q, 'rejected': True})
            return self.send_json({'ok': False, 'error': 'not found'}, 404)
        if path.startswith('/api/'):
            STATE['requests'].append({'method': method, 'path': path, 'query': q, 'body': len(body)})
        if path == '/api/status': return self.send_json({'ok': True, 'name': 'LZ4 Compression', 'version': 'v1.3.0'})
        if path == '/api/lzc/games':
            running = {op['titleId']: op for op in STATE['history'] if op.get('status') == 'running'}
            return self.send_json({'games': [dict(g, activeOp=running[g['titleId']]) if g['titleId'] in running else g for g in GAMES]})
        if path == '/api/lzc/history': return self.send_json({'history': STATE['history']})
        if path == '/api/lzc/job': return self.send_json(STATE['job'])
        if path == '/api/lzc/ui-settings': return self.send_json({'theme': 'light'})
        if path == '/api/lzc/icon': return self.send_body(200, 'image/png', icon_png(q.get('titleId', ''), 256 if q.get('size') == 'thumb' else 512))
        if path == '/api/lzc/usb': return self.send_json({'usb': [{'id': 'usb1', 'name': 'USB 1', 'root': '/mnt/usb1', 'targetRoot': '/mnt/usb1/homebrew', 'totalBytes': 2000 * G, 'freeBytes': 900 * G}]})
        if path == '/api/lzc/ampr/versions': return self.send_json({'versions': []})
        if path == '/api/lzc/size-priority': return self.send_json({'ok': True})
        if path == '/api/lzc/uncompress-plan':
            tid = q.get('titleId', '')
            return self.send_json({'ok': True, 'titleId': tid, 'sourcePath': q.get('sourcePath', ''), 'nestedName': tid + '.exfat',
                                   'nestedType': 'exfat', 'imageExtension': '.exfat', 'filesOutputPath': '/data/homebrew/%s-app' % tid,
                                   'imageOutputPath': '/data/homebrew/%s.exfat' % tid, 'requiredBytes': 90 * G,
                                   'freeBytes': 60 * G, 'extraBytes': 30 * G})
        if path == '/api/lzc/lz4/configs':
            name = ''.join(ch for ch in q.get('name', '').lower() if ch.isalnum())
            configs = [
                {'path': '/mnt/usb1/toml_profiles/astrobot.toml', 'name': 'astrobot.toml', 'where': 'USB 1', 'size': 3100},
                {'path': '/data/LZ4Compression/import/%s.toml' % q.get('titleId', ''), 'name': '%s.toml' % q.get('titleId', ''),
                 'where': 'Import folder', 'size': 2048},
            ]
            for c in configs: c['match'] = c['name'].split('.')[0].lower() in (q.get('titleId', '').lower(), name)
            configs.sort(key=lambda c: (not c['match'], c['name']))
            return self.send_json({'importDir': '/data/LZ4Compression/import', 'configs': configs})
        if path == '/api/lzc/lz4/profile' and q.get('action') == 'import':
            STATE['profile'] = b'[pack]\nlevel = 12\n'
            return self.send_json(profile_status(q.get('titleId')))
        if path == '/api/lzc/lz4/profile':
            if method == 'POST' and q.get('action') != 'delete':
                if q.get('file', 'profile.toml') == 'profile.toml': STATE['profile'] = body
                else: STATE['lists'][q['file']] = body
            if q.get('action') == 'delete': STATE['profile'] = None; STATE['lists'] = {}
            return self.send_json(profile_status(q.get('titleId')))
        if path in ('/api/lzc/lz4-pack', '/api/lzc/lz4-unpack', '/api/lzc/lz4-verify'):
            return self.send_json({'ok': True, 'id': 'op-%d' % len(STATE['requests'])})
        if path == '/api/lzc/qr':
            qr = os.environ.get('LZC_QR_BIN')
            if qr and os.path.exists(qr):
                import subprocess
                png = subprocess.run([qr, q.get('text', ''), q.get('scale', '6')], capture_output=True).stdout
                if png: return self.send_body(200, 'image/png', png)
            return self.send_body(200, 'image/png', icon_png('QR', 256))
        if path.startswith('/api/'): return self.send_json({'ok': True})
        # Test files for the PS5 app's updater and game reports (LZC_FAKE_DIR).
        if path.startswith('/fake/') and os.environ.get('LZC_FAKE_DIR'):
            name = os.path.basename(path)
            try:
                data = open(os.path.join(os.environ['LZC_FAKE_DIR'], name), 'rb').read()
            except OSError:
                return self.send_body(404, 'text/plain', b'nope')
            return self.send_body(200, 'application/json' if name.endswith('.json') else 'application/octet-stream', data)
        if path == '/__state': return self.send_json(STATE)
        if path == '/__set':
            STATE.update(json.loads(body or b'{}')); return self.send_json({'ok': True})
        name = 'lz4-compression.html' if path in ('/', '/index.html') else path.lstrip('/')
        try:
            data = open(os.path.join(ASSETS, name), 'rb').read()
        except OSError:
            return self.send_body(404, 'text/plain', b'nope')
        ext = name.rsplit('.', 1)[-1]
        ctype = {'html': 'text/html', 'js': 'text/javascript', 'css': 'text/css', 'png': 'image/png', 'svg': 'image/svg+xml'}.get(ext, 'application/octet-stream')
        self.send_body(200, ctype, data)
    def do_GET(self): self.handle_any('GET')
    def do_POST(self): self.handle_any('POST')
ThreadingHTTPServer(('127.0.0.1', PORT), H).serve_forever()
