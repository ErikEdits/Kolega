import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Tests sollen nie echte Benutzerdaten berühren
os.environ["CORECONTROL_HOME"] = tempfile.mkdtemp(prefix="cc_test_")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from corecontrol import i18n  # noqa: E402


@pytest.fixture(autouse=True)
def german():
    i18n.set_language("de")
    yield
    i18n.set_language("de")


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


windows_only = pytest.mark.skipif(sys.platform != "win32", reason="benötigt Windows")
