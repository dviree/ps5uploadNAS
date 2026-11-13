"""Size estimate from a sample: close to compressing the whole game in chunks."""
import os
from pathlib import Path
import random
import shutil
import tempfile
import unittest
from unittest.mock import patch
from test_community import app


@unittest.skipUnless(shutil.which("lz4") and shutil.which("zstd"), "needs the lz4 and zstd tools")
class EstimateTests(unittest.TestCase):
    def test_folder_estimate_and_compressed_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp) / "Example Game 1"
            (game / "data").mkdir(parents=True)
            random.seed(2)
            words = [bytes(random.choice(b"abcdefgh") for _ in range(6)) for _ in range(300)]
            (game / "data" / "text.bin").write_bytes(b" ".join(random.choice(words) for _ in range(400000)))
            (game / "data" / "noise.bin").write_bytes(os.urandom(1_500_000))
            entry = type("E", (), {"id": "g", "path": game})()
            with patch.object(app, "game_entry", lambda gid: entry), patch.object(app, "_estimates", {}):
                r = app.estimate_game("g")
            src = r["source_bytes"]
            self.assertEqual(src, sum(p.stat().st_size for p in game.rglob("*") if p.is_file()))
            for k in ("lz4", "zstd"):
                self.assertLess(r[k]["bytes"], src)
            self.assertLess(r["zstd"]["bytes"], r["lz4"]["bytes"])
            image = Path(tmp) / "x.ffpfsc"
            image.touch()
            entry.path = image
            with patch.object(app, "game_entry", lambda gid: entry), self.assertRaises(ValueError):
                app.estimate_game("g")


if __name__ == "__main__":
    unittest.main()
