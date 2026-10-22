"""Programmstart von CoreControl."""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys
import time

from corecontrol import APP_NAME, __version__
from corecontrol.core import paths
from corecontrol.core.logging_setup import install_excepthooks, record_error, setup_logging
from corecontrol.core.settings import Settings

log = logging.getLogger("corecontrol")


def _instance_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return f"CoreControl-{user}"


def _try_activate_existing() -> bool:
    """Läuft CoreControl schon, wird das vorhandene Fenster nach vorne geholt."""
    from PySide6.QtNetwork import QLocalSocket

    sock = QLocalSocket()
    sock.connectToServer(_instance_name())
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True
    return False


def _start_instance_server(window):
    from PySide6.QtNetwork import QLocalServer

    QLocalServer.removeServer(_instance_name())
    server = QLocalServer()
    if server.listen(_instance_name()):
        def on_conn():
            c = server.nextPendingConnection()
            if c is not None:
                c.readyRead.connect(lambda: (c.readAll(), window.bring_to_front()))
        server.newConnection.connect(on_conn)
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="CoreControl")
    parser.add_argument("--minimized", action="store_true", help="Minimiert starten (z. B. beim Windows-Start)")
    parser.add_argument("--screenshot", metavar="ORDNER", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    args, _ = parser.parse_known_args(argv)

    t0 = time.perf_counter()
    setup_logging()
    install_excepthooks()
    log.info("%s %s startet (Python %s, %s)", APP_NAME, __version__, sys.version.split()[0], sys.platform)

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    if not args.screenshot and _try_activate_existing():
        log.info("CoreControl läuft bereits – vorhandenes Fenster aktiviert.")
        return 0

    from corecontrol import i18n

    settings = Settings(paths.settings_file())
    settings.load()
    i18n.set_language(i18n.resolve_language(settings.get("ui.language")))

    from corecontrol.ui.theme import theme

    theme.apply(settings.get("ui.theme"), settings.get("ui.accent"))

    from corecontrol.monitoring.live import Sampler
    from corecontrol.ui.context import AppContext

    ctx = AppContext(settings)
    ctx.sampler = Sampler(settings.get("monitor.interval_ms"), settings.get("sensors.lhm_enabled"),
                          settings.get("sensors.lhm_port"))
    try:
        from corecontrol.history.store import HistoryRecorder, HistoryStore

        ctx.history = HistoryStore(paths.history_db())
        ctx.history.purge(settings.get("history.retention_days"))
        recorder = HistoryRecorder(ctx.history, lambda: settings.get("history.enabled"))
        ctx.sampler.add_consumer(recorder.add)
    except Exception as exc:
        record_error("history:init", exc)
        ctx.history = None
    ctx.sampler.start()

    from corecontrol.ui.alerts import AlertMonitor
    from corecontrol.ui.bus import bus
    from corecontrol.ui.main_window import MainWindow
    from corecontrol.ui.tray import Tray

    window = MainWindow(ctx)
    ctx.tray = Tray(ctx)
    ctx.tray.set_enabled(settings.get("tray.enabled"))
    ctx.alerts = AlertMonitor(ctx)
    ctx.sampler.sampled.connect(ctx.alerts.on_sample)
    _wire_banner(ctx, window)
    _wire_settings(ctx, window)
    server = _start_instance_server(window) if not args.screenshot else None  # noqa: F841

    if args.screenshot:
        from corecontrol.ui.screenshots import take_screenshots

        QTimer.singleShot(400, lambda: take_screenshots(ctx, window, args.screenshot))
    elif args.minimized or settings.get("startup.minimized"):
        if ctx.tray.available():
            window.hide()
        else:
            window.showMinimized()
    else:
        window.show()

    if settings.get("auto.diagnosis_on_start") and not args.screenshot:
        QTimer.singleShot(2500, lambda: ctx.run_diagnosis())
    interval_h = settings.get("auto.diagnosis_interval_h")
    diag_timer = QTimer()
    diag_timer.timeout.connect(lambda: ctx.run_diagnosis())
    if interval_h > 0:
        diag_timer.start(interval_h * 3600 * 1000)
    ctx._diag_timer = diag_timer
    purge_timer = QTimer()
    purge_timer.timeout.connect(lambda: ctx.history and ctx.history.purge(settings.get("history.retention_days")))
    purge_timer.start(3600 * 1000)
    if settings.get("updates.check_on_start") and not args.screenshot:
        QTimer.singleShot(6000, lambda: _check_updates_silent(ctx))

    log.info("Oberfläche bereit nach %.0f ms", (time.perf_counter() - t0) * 1000)
    rc = app.exec()
    ctx.sampler.stop()
    from corecontrol.ui.workers import wait_all

    wait_all(2000)
    if ctx.history is not None:
        ctx.history.close()
    settings.save()
    log.info("CoreControl beendet.")
    return rc


def _wire_banner(ctx, window) -> None:
    from corecontrol.i18n import tr
    from corecontrol.ui.bus import bus

    def update(*_):
        alerts = ctx.alerts.active() if ctx.alerts else []
        if alerts:
            a = alerts[0]
            more = len(alerts) - 1
            text = a.text + (" " + tr("banner.more", n=more) if more > 0 else "")
            window.show_banner(a.level, a.title, text, tr("banner.details"), a.target)
            return
        res = ctx.diagnosis_result
        if res is not None:
            crit = res.count("critical")
            if crit:
                window.show_banner("critical", tr("banner.diag_critical", n=crit), tr("banner.diag_critical_text"),
                                   tr("banner.show"), "diagnosis")
                return
        window.hide_banner()

    ctx.alerts.changed.connect(update)
    ctx.diagnosis_finished.connect(update)
    bus.language_changed.connect(update)


def _wire_settings(ctx, window) -> None:
    from corecontrol import i18n
    from corecontrol.ui.bus import bus
    from corecontrol.ui.theme import theme

    def changed(key, value):
        st = ctx.settings
        if key in ("ui.theme", "ui.accent"):
            theme.apply(st.get("ui.theme"), st.get("ui.accent"))
        elif key == "ui.language":
            i18n.set_language(i18n.resolve_language(value))
            bus.language_changed.emit()
        elif key in ("monitor.interval_ms", "monitor.background_interval_ms"):
            visible = window.isVisible() and not window.isMinimized()
            ctx.sampler.set_interval(st.get("monitor.interval_ms" if visible else "monitor.background_interval_ms"))
        elif key in ("sensors.lhm_enabled", "sensors.lhm_port"):
            ctx.sampler.set_lhm(st.get("sensors.lhm_enabled"), st.get("sensors.lhm_port"))
        elif key == "tray.enabled":
            ctx.tray.set_enabled(bool(value))
        elif key == "auto.diagnosis_interval_h":
            ctx._diag_timer.stop()
            if value > 0:
                ctx._diag_timer.start(value * 3600 * 1000)
        elif key == "startup.with_windows":
            from corecontrol.system.autostart import set_self_autostart

            set_self_autostart(bool(value))

    ctx.setting_changed.connect(changed)


def _check_updates_silent(ctx) -> None:
    from corecontrol.i18n import tr
    from corecontrol.ui.workers import run_task
    from corecontrol.updates.checker import check_for_update

    def done(res):
        if res and res.update_available and ctx.tray is not None:
            ctx.tray.notify("CoreControl", tr("updates.available_notify", version=res.latest_version))

    run_task(check_for_update, on_done=done, context="updates")


if __name__ == "__main__":
    sys.exit(main())
