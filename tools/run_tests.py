"""Run the suite with Qt deferred deletions flushed between test cases."""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


class QtTestResult(unittest.TextTestResult):
    def stopTest(self, test):
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            # Many existing cases close windows without entering QApplication.exec().
            # Closing alone leaves their large widget trees alive across stylesheet changes.
            for widget in app.topLevelWidgets():
                if not widget.isVisible() and widget.parent() is None:
                    widget.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        super().stopTest(test)


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    result = unittest.TextTestRunner(verbosity=2, resultclass=QtTestResult).run(suite)
    raise SystemExit(not result.wasSuccessful())
