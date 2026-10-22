"""Oberflächentest (läuft ohne Bildschirm): alle Seiten laden, Sprache/Design wechseln,
Animationen laufen und enden, „Aus“ schaltet sie ab, Suche findet Funktionen."""

import time

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture()
def window(qapp, tmp_path):
    from corecontrol.core.settings import Settings
    from corecontrol.monitoring.live import Sampler
    from corecontrol.ui import anim
    from corecontrol.ui.context import AppContext
    from corecontrol.ui.main_window import MainWindow
    from corecontrol.ui.theme import theme

    st = Settings(tmp_path / "s.json")
    st.set("auto.diagnosis_on_start", False)
    anim.install(qapp, "full")
    theme.apply("dark", "#2f7bff")
    ctx = AppContext(st)
    ctx.sampler = Sampler(250, False, 8085)
    ctx.sampler.start()
    w = MainWindow(ctx)
    w.resize(1500, 950)
    w.show()
    qapp.processEvents()
    yield w, ctx, qapp
    ctx.sampler.stop()
    w.quit_app()
    qapp.processEvents()


def _wait(qapp, seconds):
    end = time.time() + seconds
    while time.time() < end:
        qapp.processEvents()
        time.sleep(0.01)


def test_all_pages_load_without_errors(window):
    from corecontrol.core.logging_setup import recent_errors
    from corecontrol.ui.main_window import NAV, ErrorPage

    w, ctx, qapp = window
    before = len(recent_errors())
    for pid, *_ in NAV:
        w.navigate(pid)
        _wait(qapp, 0.15)
        assert not isinstance(w.page(pid), ErrorPage), pid
    _wait(qapp, 0.6)
    assert len(recent_errors()) == before, [e.message for e in recent_errors()[before:]]


def test_language_and_theme_switch(window):
    from corecontrol import i18n
    from corecontrol.ui.theme import theme

    w, ctx, qapp = window
    w.navigate("settings")
    ctx.settings.set("ui.language", "en")
    i18n.set_language("en")
    from corecontrol.ui.bus import bus

    bus.language_changed.emit()
    _wait(qapp, 0.2)
    assert w.sidebar.buttons["settings"].text() == "Settings"
    ctx.settings.set("ui.theme", "light")
    theme.apply("light", "#22c55e")
    _wait(qapp, 0.2)
    assert not theme.palette.dark
    i18n.set_language("de")
    bus.language_changed.emit()
    assert w.sidebar.buttons["settings"].text() == "Einstellungen"


def test_page_transition_runs_and_finishes(window):
    w, ctx, qapp = window
    w.navigate("dashboard")
    _wait(qapp, 0.4)
    w.navigate("hardware")
    assert w.stack._overlay is not None  # Übergang läuft
    _wait(qapp, 0.6)
    assert w.stack._overlay is None  # und ist beendet
    assert w.stack.currentWidget() is w.page("hardware")


def test_button_hover_animation_and_off_mode(window):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QEnterEvent

    from corecontrol.ui import anim
    from corecontrol.ui.widgets.controls import AnimatedButton

    w, ctx, qapp = window
    btn = AnimatedButton("Test")
    btn.setProperty("role", "primary")
    w.page("dashboard").body.addWidget(btn)
    btn.show()
    qapp.processEvents()
    qapp.sendEvent(btn, QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
    _wait(qapp, 0.05)
    mid = btn._vals.get("hover", 0)
    _wait(qapp, 0.4)
    assert 0 < mid < 1 or btn._vals.get("hover") == 1.0
    assert btn._vals.get("hover") == 1.0
    btn.grab()  # Zeichnen funktioniert
    anim.set_level("off")
    qapp.sendEvent(btn, QEvent(QEvent.Type.Leave))
    assert btn._vals.get("hover") == 0.0  # ohne Animation sofort
    anim.set_level("full")


def test_ticker_stops_when_idle(window):
    from corecontrol.ui import anim

    w, ctx, qapp = window
    ctx.sampler.stop()
    _wait(qapp, 1.2)
    assert not anim.ticker()._timer.isActive()


def test_search_finds_features(window):
    w, ctx, qapp = window
    box = w.topbar.search
    box.proxy.set_text("speicher")
    texts = [box.proxy.index(i, 0).data() for i in range(box.proxy.rowCount())]
    assert any("Speicher" in t for t in texts)
    box.proxy.set_text("geräte")
    assert box.proxy.rowCount() >= 1
    box.execute("nav:settings#history")
    _wait(qapp, 0.8)
    assert w.current_page_id() == "settings"


def test_no_attribute_shadows_qt_methods(window):
    """Regressionstest: Ein Attribut namens „metric“ überschrieb eine Qt-Funktion und führte zum Absturz."""
    from PySide6.QtCore import SignalInstance
    from PySide6.QtWidgets import QWidget

    w, ctx, qapp = window
    from corecontrol.ui.main_window import NAV

    for pid, *_ in NAV:
        w.page(pid)
    qt_names = set(dir(QWidget))
    problems = []
    for obj in [w] + w.findChildren(QWidget):
        try:
            attrs = {k for k, v in vars(obj).items() if not isinstance(v, SignalInstance)}
        except TypeError:
            continue
        clash = {a for a in attrs & qt_names if not a.startswith("_")}
        if clash:
            problems.append((type(obj).__name__, sorted(clash)))
    assert problems == []


# ---- Abläufe mit Bestätigung (Dialog wird simuliert) ------------------------------------

@pytest.fixture()
def dialogs(monkeypatch):
    """Ersetzt Bestätigungs- und Meldungsfenster, merkt sich ihre Aufrufe."""
    from corecontrol.ui import msg
    from corecontrol.ui.dialogs import ConfirmDialog

    calls = {"ask": [], "info": [], "warn": [], "answer": True}

    def ask(parent, title, message, *args, **kwargs):
        calls["ask"].append((title, message, args, kwargs))
        return calls["answer"]

    monkeypatch.setattr(ConfirmDialog, "ask", staticmethod(ask))
    monkeypatch.setattr(msg, "info", lambda parent, title, text: calls["info"].append(text))
    monkeypatch.setattr(msg, "warn", lambda parent, title, text: calls["warn"].append(text))
    return calls


def test_confirm_dialog_needs_check(window):
    from corecontrol.ui.dialogs import ConfirmDialog

    w, ctx, qapp = window
    d = ConfirmDialog(w, "Titel", "Text", "Details", require_check="Geprüft")
    assert not d.ok.isEnabled()
    d.check.setChecked(True)
    assert d.ok.isEnabled()
    d.reject()


def test_end_process_flow(window, dialogs):
    import subprocess
    import sys

    import psutil

    from corecontrol.system.processes import ProcessRow

    w, ctx, qapp = window
    w.navigate("processes")
    page = w.page("processes")
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        p = psutil.Process(child.pid)
        row = ProcessRow(child.pid, p.name(), 0.0, 0, "", p.exe(), "running", p.create_time(), False)
        page._selected = lambda: row

        dialogs["answer"] = False
        page._end()
        assert len(dialogs["ask"]) == 1 and child.poll() is None  # abgebrochen → läuft weiter

        dialogs["answer"] = True
        page._end()
        child.wait(10)
        assert dialogs["info"] and not dialogs["warn"]
    finally:
        if child.poll() is None:
            child.kill()


def test_delete_single_file_flow(window, dialogs, tmp_path, monkeypatch):
    from corecontrol.storage import cleanup

    w, ctx, qapp = window
    w.navigate("storage")
    page = w.page("storage")
    f = tmp_path / "gross.bin"
    f.write_bytes(b"x" * 100)
    page.files_table.selected_key = lambda: str(f)
    page._sizes = {str(f): 100}
    page._render_scan = lambda: None
    seen = []

    def fake_delete(files, roots, confirmed, permanent=False, ctx=None):
        seen.append((files, confirmed, permanent))
        return cleanup.DeleteResult(deleted=1, deleted_bytes=100)

    monkeypatch.setattr(cleanup, "delete_files", fake_delete)
    dialogs["answer"] = False
    page._delete_file()
    assert not seen
    dialogs["answer"] = True
    page.scan_result = type("R", (), {"largest": [(100, str(f))]})()
    page._delete_file()
    assert seen == [([(str(f), 100)], True, False)]  # nur bestätigt, in den Papierkorb
    assert dialogs["info"]
    assert page.scan_result.largest == []


def test_cleanup_flow(window, dialogs, tmp_path, monkeypatch):
    from corecontrol.storage import cleanup

    w, ctx, qapp = window
    w.navigate("storage")
    page = w.page("storage")
    files = [(str(tmp_path / "a.tmp"), 10), (str(tmp_path / "b.tmp"), 20)]
    page._selected_files = lambda: (files, [str(tmp_path)])
    page._scan_cleanup = lambda: None
    seen = []

    def fake_delete(f, roots, confirmed, permanent=False, ctx=None):
        seen.append((f, roots, confirmed, permanent))
        return cleanup.DeleteResult(deleted=2, deleted_bytes=30)

    monkeypatch.setattr(cleanup, "delete_files", fake_delete)
    dialogs["answer"] = False
    page._clean()
    _wait(qapp, 0.3)
    assert not seen
    dialogs["answer"] = True
    page._clean()
    end = time.time() + 5
    while not dialogs["info"] and time.time() < end:
        _wait(qapp, 0.05)
    assert seen == [(files, [str(tmp_path)], True, False)]
    assert dialogs["info"]
    # Die Zusammenfassung nennt jede Datei
    _title, _message, args, kwargs = dialogs["ask"][-1]
    assert all(p in args[0] for p, _ in files)
    assert kwargs.get("require_check")


def test_settings_import_flow(window, dialogs, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    w, ctx, qapp = window
    w.navigate("settings")
    page = w.page("settings")
    path = tmp_path / "export.json"
    ctx.settings.set("thresholds.ram_warn", 77)
    assert ctx.settings.export_to(path)
    ctx.settings.set("thresholds.ram_warn", 90)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(path), "")))
    page._import()
    assert ctx.settings.get("thresholds.ram_warn") == 77
    assert dialogs["info"] and not dialogs["warn"]
