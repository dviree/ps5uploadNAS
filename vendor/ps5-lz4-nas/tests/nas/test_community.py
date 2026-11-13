"""Loads nas-lz4/ps5lz4.py as `app` for the other tests:
python -m unittest discover -s tests/nas -v."""
import importlib.util
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location('ps5lz4', Path(__file__).resolve().parents[2] / 'nas-lz4/ps5lz4.py')
app = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = app
spec.loader.exec_module(app)
