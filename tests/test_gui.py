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
