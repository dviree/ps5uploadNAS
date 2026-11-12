#!/usr/bin/env python3
"""Run the engine and its private NAS converter; stop all children together."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def configure_library_roots(environ):
    """Expose the mounted Zstd folder to Files and Collection on every upgrade."""
    zstd = environ.get('PS5LZ4_ZSTD_OUTPUT', '/zstd')
    if not Path(zstd).is_dir():
        return
    for key, default in (('PS5UPLOAD_BROWSE_ROOTS', '/pkgs,/ps5'),
                         ('PS5UPLOAD_COLLECTION_ROOTS', '')):
        roots = [r.strip() for r in environ.get(key, default).split(',') if r.strip()]
        if zstd.rstrip('/') not in [r.rstrip('/') for r in roots]:
            roots.append(zstd)
        environ[key] = ','.join(roots)


def main():
    if any(a in sys.argv[1:] for a in ('--healthcheck', '--version', '--help', '-h', '-V')):
        os.execv('/ps5upload-engine', ['/ps5upload-engine', *sys.argv[1:]])
    configure_library_roots(os.environ)
    children = []

    def stop(*_):
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: sys.exit(0))
    try:
        # Resume once before starting the request agent, as the standalone image does.
        subprocess.run(['ps5lz4', 'start', '--resume'], check=False)
        for command in (['ps5lz4', 'agent'], ['ps5lz4', 'ui', '--port', '19114'],
                        ['/ps5upload-engine', *sys.argv[1:]]):
            children.append(subprocess.Popen(command, start_new_session=True))
        while all(c.poll() is None for c in children):
            time.sleep(0.25)
        return next((c.returncode or 1 for c in children if c.poll() is not None), 1)
    finally:
        stop()
        deadline = time.monotonic() + 15
        for child in children:
            try:
                child.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()


if __name__ == '__main__':
    sys.exit(main())
