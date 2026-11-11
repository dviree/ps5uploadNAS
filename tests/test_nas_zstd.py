"""Zstd-only integration: codec validation, defaults, and source retention."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'vendor/ps5-lz4-nas/nas-lz4/ps5lz4.py'
spec = importlib.util.spec_from_file_location('nas_zstd_test_app', SCRIPT)
app = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = app
spec.loader.exec_module(app)


class ZstdOnly(unittest.TestCase):
    def test_forge_verifies_and_retains_source(self):
        cmd = app.forge_command(Path('/source'), Path('/output'), 'zstd', 5)
        self.assertIn('--zstd-pack', cmd)
        self.assertIn('--full-verify', cmd)
        self.assertNotIn('--delete-source', cmd)
        self.assertEqual(cmd[cmd.index('--zstd-level') + 1], '5')
        for codec, level in [('lz4', 9), ('zstd', 23), ('zip', 5)]:
            with self.assertRaises(app.JobError):
                app.forge_command(Path('/source'), Path('/output'), codec, level)

    def test_default_request_is_zstd_and_lz4_is_rejected(self):
        with patch.object(app.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='', stderr='')) as run:
            self.assertTrue(app.run_request({'action': 'start', 'game': 'Game'})['ok'])
            cmd = run.call_args.args[0]
            self.assertEqual(cmd[cmd.index('--codec') + 1], 'zstd')
            self.assertEqual(cmd[cmd.index('--level') + 1], '5')
        with patch.object(app.subprocess, 'run') as run:
            self.assertFalse(app.run_request({'action': 'start', 'game': 'Game', 'codec': 'lz4'})['ok'])
            run.assert_not_called()

    def test_cli_rejects_lz4(self):
        result = subprocess.run([sys.executable, str(SCRIPT), 'run', '--all', '--codec', 'lz4'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('invalid choice', result.stderr)

    def test_proxy_routes_are_catalogued(self):
        document = json.loads((ROOT / 'engine/crates/ps5upload-engine/api/openapi.json').read_text())
        for path in ['/api/nas-zstd', '/api/nas-zstd/{*path}']:
            self.assertEqual(set(document['paths'][path]), {'get', 'post'})


if __name__ == '__main__':
    unittest.main()
