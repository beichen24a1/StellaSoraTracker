"""Run core and desktop-interface regressions without a GUI runtime."""
import faulthandler
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if __name__ == '__main__':
    faulthandler.dump_traceback_later(60, repeat=True)
    try:
        suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    finally:
        faulthandler.cancel_dump_traceback_later()
    raise SystemExit(not result.wasSuccessful())
