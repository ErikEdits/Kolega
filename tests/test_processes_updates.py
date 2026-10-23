"""Prozesse (Schutz, Bestätigung, PID-Wiederverwendung) und Update-Prüfung (offline, sichere Quelle)."""

import io
import json
import os
import subprocess
import sys
import urllib.error

import psutil

from corecontrol.system.processes import ProcessMonitor, end_process, is_protected
from corecontrol.updates import checker


def test_protected_processes():
    assert is_protected("csrss.exe", 600)
    assert is_protected("LSASS.EXE", 700)
    assert is_protected("anything", 0)
    assert is_protected("python", os.getpid())
    assert not is_protected("notepad.exe", 1234)


def test_end_process_requires_confirmation_and_respects_protection():
    assert end_process(1234, "notepad.exe", 0.0, confirmed=False) == "not_confirmed"
    assert end_process(700, "lsass.exe", 0.0, confirmed=True) == "protected"


def test_end_process_detects_pid_reuse_and_terminates():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        proc = psutil.Process(p.pid)
        name, ct = proc.name(), proc.create_time()
        assert end_process(p.pid, name, ct - 100, confirmed=True) == "changed"
        assert end_process(p.pid, name, ct, confirmed=True) in ("terminated", "killed")
        assert not psutil.pid_exists(p.pid) or psutil.Process(p.pid).status() == psutil.STATUS_ZOMBIE
    finally:
        try:
            p.kill()
        except Exception:
            pass
        p.wait(5)
    assert end_process(p.pid, name, ct, confirmed=True) in ("not_found", "changed")


def test_process_monitor_lists_processes():
    pm = ProcessMonitor()
    rows = pm.refresh()
    assert any(r.pid == os.getpid() and r.protected for r in rows)
    assert all(r.cpu >= 0 for r in pm.refresh())


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_update_check_variants():
    def newer(req, timeout):
        assert req.full_url == checker.API_URL
        return _Resp(json.dumps({"tag_name": "v99.0.0", "html_url": "https://evil.example/x"}).encode())

    r = checker.check_for_update(opener=newer)
    assert r.update_available and r.latest_version == "99.0.0"
    assert r.url.startswith(checker.ALLOWED_PAGE_PREFIX)  # fremde URL wird nicht übernommen

    def same(req, timeout):
        return _Resp(json.dumps({"tag_name": "v0.0.1"}).encode())

    assert checker.check_for_update(opener=same).status == "current"

    def offline(req, timeout):
        raise urllib.error.URLError("no network")

    r = checker.check_for_update(opener=offline)
    assert r.status == "offline" and "Keine Verbindung" in r.describe()

    def missing(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)

    assert checker.check_for_update(opener=missing).status == "no_release"
