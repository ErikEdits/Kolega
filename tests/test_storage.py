"""Speicheranalyse und sichere Bereinigung: nichts ohne Bestätigung, nichts außerhalb erlaubter Bereiche."""

import os
import time

import pytest

from corecontrol.storage import cleanup, scanner
from corecontrol.storage.cleanup import CleanupCategory, delete_files, safe_root, validate_for_delete
from corecontrol.storage.safety import classify, ext_category, is_protected_path


def make_tree(base):
    (base / "a" / "b" / "c").mkdir(parents=True)
    (base / "a" / "big.mkv").write_bytes(b"x" * 50_000)
    (base / "a" / "b" / "doc.pdf").write_bytes(b"x" * 10_000)
    (base / "a" / "b" / "c" / "tiny.txt").write_bytes(b"x" * 10)
    (base / "z.zip").write_bytes(b"x" * 20_000)
    return base


def test_scan_sizes_and_types(tmp_path):
    make_tree(tmp_path)
    r = scanner.scan(str(tmp_path))
    assert r.total == 80_010 and r.files == 4
    assert r.largest[0][0] == 50_000 and r.largest[0][1].endswith("big.mkv")
    assert r.dir_sizes[str(tmp_path)] == 80_010
    assert r.dir_sizes[str(tmp_path / "a")] == 60_010
    assert r.by_type["video"] == 50_000 and r.by_type["archive"] == 20_000
    children = dict(r.children(str(tmp_path)))
    assert children[str(tmp_path / "a")] == 60_010


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="keine Symlinks")
def test_scan_does_not_follow_links(tmp_path):
    make_tree(tmp_path / "data")
    try:
        os.symlink(tmp_path / "data", tmp_path / "loop", target_is_directory=True)
    except OSError:
        pytest.skip("Symlink nicht erlaubt")
    r = scanner.scan(str(tmp_path))
    assert r.total == 80_010
    assert r.links_skipped >= 1


def test_scan_marks_inaccessible_folders(tmp_path, monkeypatch):
    make_tree(tmp_path)
    real = os.scandir
    secret = str(tmp_path / "a" / "b")

    def fake(path):
        if os.path.normpath(path) == os.path.normpath(secret):
            raise PermissionError("Zugriff verweigert")
        return real(path)

    monkeypatch.setattr(scanner.os, "scandir", fake)
    r = scanner.scan(str(tmp_path))
    assert r.denied_count == 1 and r.denied == [secret]
    assert r.total == 70_000  # big.mkv + z.zip


def test_scan_can_be_cancelled(tmp_path):
    make_tree(tmp_path)

    class Ctx:
        cancelled = True

        def progress(self, _):
            pass

    r = scanner.scan(str(tmp_path), ctx=Ctx())
    assert r.cancelled


def test_extension_categories():
    assert ext_category("Film.MKV") == "video"
    assert ext_category("x.unknownext") == "other"


def _fake_windows_env(monkeypatch, base):
    """Alle relevanten Windows-Ordner auf Testordner umleiten (unabhängig vom echten Rechner)."""
    for var, sub in (("WINDIR", "Windows"), ("SystemRoot", "Windows"), ("ProgramFiles", "Program Files"),
                     ("ProgramFiles(x86)", "Program Files (x86)"), ("ProgramData", "ProgramData"),
                     ("USERPROFILE", "Users/max"), ("APPDATA", "Users/max/AppData/Roaming"),
                     ("LOCALAPPDATA", "Users/max/AppData/Local"), ("TEMP", "Users/max/AppData/Local/Temp")):
        monkeypatch.setenv(var, str(base / sub))


def test_protection_rules(monkeypatch, tmp_path):
    _fake_windows_env(monkeypatch, tmp_path)
    monkeypatch.setenv("WINDIR", str(tmp_path / "Windows"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "Program Files"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "Users" / "max"))
    monkeypatch.setenv("TEMP", str(tmp_path / "Users" / "max" / "AppData" / "Local" / "Temp"))
    assert classify(str(tmp_path / "Windows" / "System32" / "kernel32.dll")) == "system"
    assert classify(str(tmp_path / "Windows" / "Temp" / "x.tmp")) == "temp"
    assert classify(str(tmp_path / "Program Files" / "App" / "app.exe")) == "program"
    assert classify(str(tmp_path / "Users" / "max" / "Videos" / "film.mp4")) == "user"
    assert classify(str(tmp_path / "pagefile.sys")) == "system"
    assert is_protected_path(str(tmp_path / "Windows" / "explorer.exe"))
    assert is_protected_path(str(tmp_path / "Program Files" / "App" / "app.exe"))
    assert is_protected_path(str(tmp_path / "Users" / "max"))  # Profilordner selbst
    assert not is_protected_path(str(tmp_path / "Users" / "max" / "Videos" / "film.mp4"))


def test_safe_root_rejects_dangerous_temp(monkeypatch, tmp_path):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert not safe_root("C:\\" if os.name == "nt" else "/")
    assert not safe_root(str(tmp_path))  # Benutzerordner selbst
    assert not safe_root("relativ/temp")
    assert not safe_root(str(tmp_path / "Dokumente"), "user_temp")  # kein „temp“ im Namen
    assert safe_root(str(tmp_path / "AppData" / "Local" / "Temp"), "user_temp")


def test_delete_requires_confirmation(tmp_path):
    f = tmp_path / "Temp" / "a.tmp"
    f.parent.mkdir()
    f.write_text("x")
    with pytest.raises(PermissionError):
        delete_files([(str(f), 1)], [str(f.parent)], confirmed=False)
    assert f.exists()


def test_delete_only_inside_allowed_roots_and_verifies(tmp_path):
    root = tmp_path / "Temp"
    root.mkdir()
    inside = root / "old.tmp"
    inside.write_text("x" * 10)
    outside = tmp_path / "wichtig.docx"
    outside.write_text("geheim")
    trashed = []

    def fake_trash(p):
        trashed.append(p)
        os.remove(p)

    res = delete_files([(str(inside), 10), (str(outside), 6), (str(root / "fehlt.tmp"), 1)], [str(root)],
                       confirmed=True, trash_func=fake_trash)
    assert res.deleted == 1 and res.deleted_bytes == 10
    assert outside.exists()
    reasons = dict(res.skipped)
    assert reasons[str(outside)] == "outside"
    assert reasons[str(root / "fehlt.tmp")] == "missing"
    assert trashed == [str(inside)]


def test_delete_reports_failures_honestly(tmp_path):
    root = tmp_path / "Temp"
    root.mkdir()
    f = root / "locked.tmp"
    f.write_text("x")

    def failing_trash(p):
        raise PermissionError("gesperrt")

    res = delete_files([(str(f), 1)], [str(root)], confirmed=True, trash_func=failing_trash)
    assert res.deleted == 0 and res.failed == [(str(f), "access_denied")]
    assert f.exists()

    def silent_noop(p):
        pass  # behauptet Erfolg, löscht aber nichts

    res = delete_files([(str(f), 1)], [str(root)], confirmed=True, trash_func=silent_noop)
    assert res.deleted == 0 and res.failed == [(str(f), "still_exists")]


def test_delete_refuses_directories_and_links(tmp_path):
    root = tmp_path / "Temp"
    (root / "sub").mkdir(parents=True)
    assert validate_for_delete(str(root / "sub"), [str(root)]) == "directory"
    if hasattr(os, "symlink"):
        target = tmp_path / "echt.txt"
        target.write_text("x")
        try:
            os.symlink(target, root / "link.txt")
            assert validate_for_delete(str(root / "link.txt"), [str(root)]) == "link"
        except OSError:
            pass


def test_cleanup_scan_respects_age(tmp_path, monkeypatch):
    root = tmp_path / "Temp"
    root.mkdir()
    old = root / "old.tmp"
    new = root / "new.tmp"
    old.write_text("x" * 100)
    new.write_text("y" * 100)
    past = time.time() - 10 * 86400
    os.utime(old, (past, past))
    cat = CleanupCategory("user_temp", [str(root)], default_selected=True)
    monkeypatch.setattr(cleanup, "category_definitions", lambda: [cat])
    cats = cleanup.scan_categories(min_age_days=2)
    assert [f.path for f in cats[0].files] == [str(old)]
    assert cats[0].total == 100


def test_classification_ignores_temp_above_base(monkeypatch, tmp_path):
    """Ein „Temp“ oberhalb des Windows-Ordners darf die Einordnung nicht beeinflussen (gefunden im Windows-CI)."""
    base = tmp_path / "Temp" / "x"
    _fake_windows_env(monkeypatch, tmp_path / "andere")
    monkeypatch.setenv("WINDIR", str(base / "Windows"))
    monkeypatch.setenv("LOCALAPPDATA", str(base / "Local"))
    monkeypatch.setenv("TEMP", str(tmp_path / "anderswo"))
    assert classify(str(base / "Windows" / "System32" / "a.dll")) == "system"
    assert classify(str(base / "Windows" / "Temp" / "a.tmp")) == "temp"
    assert classify(str(base / "Local" / "Google" / "Chrome" / "Cache" / "f_000001")) == "temp"
    assert classify(str(base / "Local" / "Spiel" / "save.dat")) == "appdata"
