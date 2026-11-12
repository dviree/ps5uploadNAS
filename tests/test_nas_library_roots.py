"""The combined image exposes an existing Zstd mount without losing NAS settings."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/nas-supervisor.py'
spec = importlib.util.spec_from_file_location('nas_supervisor_test', SCRIPT)
supervisor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supervisor)
spec = importlib.util.spec_from_file_location('configure_zstd_test', SCRIPT.with_name('configure-zstd-folder.py'))
mount_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mount_config)


class MountedLibrary(unittest.TestCase):
    def test_updater_migration_saves_backup_and_preserves_executable_mode(self):
        with tempfile.TemporaryDirectory() as root:
            updater, zstd = Path(root) / 'update.sh', Path(root) / 'packed'
            zstd.mkdir()
            original = '#!/bin/sh\ndocker run -d --name ps5upload -v /games:/games:ro image:latest\n'
            updater.write_text(original)
            updater.chmod(0o750)
            subprocess.run([sys.executable, str(SCRIPT.with_name('configure-zstd-folder.py')),
                            str(updater), str(zstd)], check=True, capture_output=True)
            self.assertEqual(updater.with_name('update.sh.before-zstd').read_text(), original)
            self.assertEqual(updater.stat().st_mode & 0o777, 0o750)
            self.assertIn('source=' + str(zstd) + ',target=/zstd', updater.read_text())
            subprocess.run(['bash', '-n', str(updater)], check=True)

    def test_existing_docker_updater_keeps_other_mounts_and_is_idempotent(self):
        before = 'docker pull image:latest\ndocker run -d --name ps5upload \\\n  -v /existing:/games:ro -e PS5UPLOAD_BROWSE_ROOTS=/games image:latest\n'
        after = mount_config.add_mount(before, '/games/packed zstd')
        self.assertIn("--mount 'type=bind,source=/games/packed zstd,target=/zstd'", after)
        self.assertIn('-v /existing:/games:ro', after)
        self.assertIn('-e PS5UPLOAD_BROWSE_ROOTS=/games', after)
        self.assertEqual(mount_config.add_mount(after, '/games/packed zstd'), after)

    def test_existing_mount_is_not_replaced_and_other_containers_are_not_changed(self):
        with self.assertRaises(ValueError):
            mount_config.add_mount('docker run --name ps5upload -v /other:/zstd image\n', '/games/zstd')
        with self.assertRaises(ValueError):
            mount_config.add_mount('docker run --name something-else image\n', '/games/zstd')

    def test_adds_existing_zstd_mount_to_both_views_without_losing_roots(self):
        with tempfile.TemporaryDirectory() as root:
            env = {'PS5LZ4_ZSTD_OUTPUT': root,
                   'PS5UPLOAD_BROWSE_ROOTS': '/games,/pkgs,/downloads',
                   'PS5UPLOAD_COLLECTION_ROOTS': '/games'}
            supervisor.configure_library_roots(env)
            self.assertEqual(env['PS5UPLOAD_BROWSE_ROOTS'], '/games,/pkgs,/downloads,' + root)
            self.assertEqual(env['PS5UPLOAD_COLLECTION_ROOTS'], '/games,' + root)
            supervisor.configure_library_roots(env)
            self.assertEqual(env['PS5UPLOAD_BROWSE_ROOTS'].split(',').count(root), 1)

    def test_an_unmounted_folder_is_not_advertised_or_created(self):
        with tempfile.TemporaryDirectory() as root:
            missing = str(Path(root) / 'missing')
            env = {'PS5LZ4_ZSTD_OUTPUT': missing, 'PS5UPLOAD_BROWSE_ROOTS': '/games'}
            before = env.copy()
            supervisor.configure_library_roots(env)
            self.assertEqual(env, before)
            self.assertFalse(Path(missing).exists())

    def test_trailing_slash_does_not_duplicate_existing_mount(self):
        with tempfile.TemporaryDirectory() as root:
            env = {'PS5LZ4_ZSTD_OUTPUT': root,
                   'PS5UPLOAD_BROWSE_ROOTS': root + '/',
                   'PS5UPLOAD_COLLECTION_ROOTS': root}
            supervisor.configure_library_roots(env)
            self.assertEqual(env['PS5UPLOAD_BROWSE_ROOTS'], root + '/')
            self.assertEqual(env['PS5UPLOAD_COLLECTION_ROOTS'], root)


if __name__ == '__main__':
    unittest.main()
