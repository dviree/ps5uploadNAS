"""Regression tests for upgrading a NAS install made before separate Zstd output."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


WRAPPER = Path(__file__).resolve().parents[2] / "nas-lz4/lz4-ps5.sh"


class ZstdUpdateTests(unittest.TestCase):
    def test_old_install_adds_bind_and_recreates_even_with_same_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            bin_dir = base / "bin"
            bin_dir.mkdir()
            docker = bin_dir / "docker"
            docker.write_text('#!/bin/sh\nprintf "%s | %s\\n" "$*" "${COMPOSE_FILE:-unset}" >> "$DOCKER_LOG"\n'
                              'case "$*" in *"State.Running"*) echo true;; *"inspect -f"*) echo same-image;; esac\n')
            docker.chmod(0o755)
            (bin_dir / "sleep").write_text("#!/bin/sh\nexit 0\n")
            (bin_dir / "sleep").chmod(0o755)
            shutil.copy2(WRAPPER, base / "lz4-ps5.sh")
            (base / "lz4-ps5.sh").chmod(0o755)
            target = base / "ps5zstd"
            (base / ".env").write_text(f"PUID={os.getuid()}\nPGID={os.getgid()}\n"
                                       f"CONTAINER=test\nIMAGE=test-image\nLIBRARY={base}/library\n"
                                       f"ZSTD_OUTPUT={target}\n")
            (base / "docker-compose.yml").write_text("services:\n  ps5-lz4: {}\n  ps5-lz4-ui: {}\n")
            log = base / "docker.log"
            env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", DOCKER_LOG=str(log))
            result = subprocess.run([str(base / "lz4-ps5.sh"), "update"], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(target.is_dir())
            self.assertIn(f'{target}:/output-zstd:ro', (base / "docker-compose.zstd.yml").read_text())
            self.assertIn("COMPOSE_FILE=docker-compose.yml:docker-compose.zstd.yml", (base / ".env").read_text())
            self.assertIn("compose -p ps5-lz4 up -d | docker-compose.yml:docker-compose.zstd.yml", log.read_text())
            first = log.read_text()
            result = subprocess.run([str(base / "lz4-ps5.sh"), "update"], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("already up to date", result.stdout)
            self.assertEqual(log.read_text().count("compose -p ps5-lz4 up -d"), first.count("compose -p ps5-lz4 up -d"))


if __name__ == "__main__":
    unittest.main()
