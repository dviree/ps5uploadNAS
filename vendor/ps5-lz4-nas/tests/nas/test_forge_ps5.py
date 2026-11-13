"""PS5 Forge delivery: release integrity and both supported launch paths."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from test_community import app


class ForgePs5Tests(unittest.TestCase):
    def test_download_verifies_payload_and_uses_cache(self):
        payload = b"\x7fELF" + b"test payload"
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(app, 'ENGINE_DIR', Path(tmp)), \
             patch.object(app, 'FORGE_PS5_SHA256', hashlib.sha256(payload).hexdigest()), \
             patch('urllib.request.urlopen') as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = payload
            elf = app.forge_ps5_elf()
            self.assertEqual(elf.read_bytes(), payload)
            self.assertEqual(app.forge_ps5_elf(), elf)
            urlopen.assert_called_once()

    def test_invalid_payload_is_never_sent(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(app, 'ENGINE_DIR', Path(tmp)), \
             patch('urllib.request.urlopen') as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b"\x7fELFwrong"
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                app.forge_ps5_elf()
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_ftp_install_starts_via_payload_manager(self):
        with tempfile.TemporaryDirectory() as tmp:
            elf = Path(tmp) / 'forge.elf'
            elf.write_bytes(b'\x7fELFtest')
            ftp = MagicMock()
            with patch.object(app, 'get_settings', return_value={'ps5_ftp': '192.0.2.5:2121'}), \
                 patch.object(app, 'forge_ps5_elf', return_value=elf), \
                 patch.object(app, 'ps5_ftp_connect', return_value=ftp), \
                 patch.object(app, 'ps5_ftp_mkdirs'), \
                 patch.object(app, 'pm_path', return_value=app.FORGE_PS5_PATH), \
                 patch.object(app, 'pm_load', return_value='Payload loaded'):
                result = app.forge_ps5_install()
            self.assertIn('Payload Manager', result['started'])
            self.assertEqual(result['installed'], app.FORGE_PS5_PATH)
            self.assertEqual(ftp.storbinary.call_args.args[1].read(), elf.read_bytes())

    def test_elf_loader_fallback_without_ftp(self):
        with tempfile.TemporaryDirectory() as tmp:
            elf = Path(tmp) / 'forge.elf'
            elf.write_bytes(b'\x7fELFtest')
            sock = MagicMock()
            sock.__enter__.return_value = sock
            with patch.object(app, 'get_settings', return_value={'ps5_ftp': '192.0.2.5:2121'}), \
                 patch.object(app, 'forge_ps5_elf', return_value=elf), \
                 patch.object(app, 'ps5_ftp_connect', side_effect=OSError('FTP offline')), \
                 patch.object(app, 'ELFLDR_PORTS', [9021]), \
                 patch('socket.create_connection', return_value=sock):
                result = app.forge_ps5_install()
            self.assertEqual(result['installed'], None)
            self.assertIn('9021', result['started'])
            sock.sendall.assert_called_once_with(elf.read_bytes())


if __name__ == '__main__':
    unittest.main()
