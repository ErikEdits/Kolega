"""Einstellungen: fehlerhafte, unvollständige und unbekannte Werte dürfen nie zum Absturz führen."""

import json

from corecontrol.core.settings import SCHEMA, Settings, defaults, validate_dict, validate_value


def test_defaults_are_valid():
    for key, value in defaults().items():
        v, warn = validate_value(key, value)
        assert warn is None, key
        assert v == value, key


def test_missing_file_uses_defaults(tmp_path):
    s = Settings(tmp_path / "nope.json")
    assert s.load() == []
    assert s.get("ui.theme") == "system"


def test_corrupt_json_is_backed_up_and_defaults_used(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{ das ist kein json", encoding="utf-8")
    s = Settings(p)
    warnings = s.load()
    assert warnings == ["invalid:file"]
    assert s.get("monitor.interval_ms") == SCHEMA["monitor.interval_ms"].default
    assert (tmp_path / "settings.broken.json").exists()


def test_wrong_types_and_ranges_are_corrected():
    res = validate_dict({"values": {
        "ui.theme": "pink",                 # ungültige Auswahl
        "monitor.interval_ms": 5,           # zu klein -> Minimum
        "history.retention_days": 99999,    # zu groß -> Maximum
        "notify.enabled": "ja",             # falscher Typ
        "thresholds.ram_warn": float("nan"),
        "ui.accent": "#12345G",             # keine Farbe
        "dashboard.tiles": ["cpu", "cpu", "unbekannt", 5, "ram"],
        "foo.bar": 1,                       # unbekannter Schlüssel
    }})
    v = res.values
    assert v["ui.theme"] == "system"
    assert v["monitor.interval_ms"] == SCHEMA["monitor.interval_ms"].min
    assert v["history.retention_days"] == SCHEMA["history.retention_days"].max
    assert v["notify.enabled"] is True
    assert v["thresholds.ram_warn"] == 90
    assert v["ui.accent"] == "#2f7bff"
    assert v["dashboard.tiles"] == ["cpu", "ram"]
    assert "unknown:foo.bar" in res.warnings
    assert any(w.startswith("clamped:monitor.interval_ms") for w in res.warnings)


def test_critical_threshold_never_below_warning():
    res = validate_dict({"thresholds.cpu_temp_warn": 90, "thresholds.cpu_temp_crit": 70})
    assert res.values["thresholds.cpu_temp_crit"] == 90
    res = validate_dict({"thresholds.disk_free_warn_pct": 5, "thresholds.disk_free_crit_pct": 20})
    assert res.values["thresholds.disk_free_crit_pct"] == 5


def test_games_list_validation():
    res = validate_dict({"gaming.games": [{"name": "A", "target": "C:/a.exe"}, {"name": ""}, "x",
                                          {"name": "B", "target": "steam://rungameid/1", "source": "evil"}]})
    games = res.values["gaming.games"]
    assert [g["name"] for g in games] == ["A", "B"]
    assert games[1]["source"] == "manual"


def test_save_load_roundtrip_and_listener(tmp_path):
    p = tmp_path / "s.json"
    s = Settings(p)
    seen = []
    s.on_change(lambda k, v: seen.append((k, v)))
    s.set("ui.theme", "dark")
    s.set("ui.theme", "dark")  # keine Änderung -> kein zweites Signal
    assert seen == [("ui.theme", "dark")]
    s2 = Settings(p)
    s2.load()
    assert s2.get("ui.theme") == "dark"


def test_export_import(tmp_path):
    a = Settings(tmp_path / "a.json")
    a.set("ui.language", "en")
    a.set("ui.window_geometry", "abc")
    exp = tmp_path / "export.json"
    assert a.export_to(exp)
    data = json.loads(exp.read_text(encoding="utf-8"))
    assert "ui.window_geometry" not in data["values"]
    b = Settings(tmp_path / "b.json")
    warnings = b.import_from(exp)
    assert warnings == []
    assert b.get("ui.language") == "en"


def test_import_partial_file_only_changes_given_keys(tmp_path):
    s = Settings(tmp_path / "s.json")
    s.set("ui.theme", "light")
    f = tmp_path / "partial.json"
    f.write_text(json.dumps({"values": {"ui.language": "en", "monitor.interval_ms": "schnell"}}), encoding="utf-8")
    warnings = s.import_from(f)
    assert s.get("ui.theme") == "light"
    assert s.get("ui.language") == "en"
    assert s.get("monitor.interval_ms") == SCHEMA["monitor.interval_ms"].default
    assert "invalid:monitor.interval_ms" in warnings


def test_get_returns_copies(tmp_path):
    s = Settings(tmp_path / "s.json")
    tiles = s.get("dashboard.tiles")
    tiles.append("x")
    assert "x" not in s.get("dashboard.tiles")


def test_old_default_interval_is_migrated_but_own_choice_kept(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"version": 1, "values": {"monitor.interval_ms": 1000}}), encoding="utf-8")
    s = Settings(p)
    s.load()
    assert s.get("monitor.interval_ms") == 500
    p.write_text(json.dumps({"version": 1, "values": {"monitor.interval_ms": 2000}}), encoding="utf-8")
    s.load()
    assert s.get("monitor.interval_ms") == 2000
    # Ab Version 2 bleibt auch 1000 erhalten (bewusst gewählt)
    p.write_text(json.dumps({"version": 2, "values": {"monitor.interval_ms": 1000}}), encoding="utf-8")
    s.load()
    assert s.get("monitor.interval_ms") == 1000
