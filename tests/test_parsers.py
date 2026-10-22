"""Auswertung von Ereignis-XML, LibreHardwareMonitor-Daten, PDH-Instanzen, netsh-Ausgaben, Steam/Epic-Dateien."""

import json

from corecontrol.diagnostics.eventlog import EventRecord, bugcheck_code, build_query, classify, parse_event_xml, summarize
from corecontrol.gaming.library import epic_games, parse_vdf, steam_games, validate_target
from corecontrol.monitoring import lhm, pdh
from corecontrol.network.tests import parse_netsh_wlan
from corecontrol.system.autostart import ENABLED_BLOB, disabled_blob, extract_executable, is_enabled_flag
from corecontrol.system.programs import parse_install_date
from corecontrol.updates.checker import is_newer, parse_version

EVENT_XML = """<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
<System><Provider Name="Microsoft-Windows-WER-SystemErrorReporting" Guid="{abc}" EventSourceName="BugCheck"/>
<EventID Qualifiers="16384">1001</EventID><Level>2</Level>
<TimeCreated SystemTime="2026-10-20T08:15:30.1234567Z"/><Channel>System</Channel></System>
<EventData><Data Name="param1">0x0000009f (0x0000000000000003, 0xffffc00e, 0x0)</Data>
<Data Name="param2">C:\\WINDOWS\\Minidump\\102026-12345-01.dmp</Data></EventData></Event>"""

KP_XML = """<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event"><System>
<Provider Name="Microsoft-Windows-Kernel-Power"/><EventID>41</EventID><Level>1</Level>
<TimeCreated SystemTime="2026-10-19T10:00:00Z"/></System>
<EventData><Data Name="BugcheckCode">0</Data><Data Name="PowerButtonTimestamp">0</Data></EventData></Event>"""

APP_XML = """<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event"><System>
<Provider Name="Application Error"/><EventID Qualifiers="0">1000</EventID><Level>2</Level>
<TimeCreated SystemTime="2026-10-18T10:00:00.5Z"/></System>
<EventData><Data>game.exe</Data><Data>1.0.0.0</Data><Data>65d2c3a1</Data><Data>ntdll.dll</Data></EventData></Event>"""


def test_parse_bluescreen_event():
    rec = parse_event_xml(EVENT_XML)
    assert rec.provider == "Microsoft-Windows-WER-SystemErrorReporting"
    assert rec.event_id == 1001 and rec.level == 2
    assert classify(rec) == ("bluescreen", "critical")
    assert bugcheck_code(rec) == 0x9F


def test_kernel_power_without_bugcheck():
    rec = parse_event_xml(KP_XML)
    assert classify(rec) == ("unexpected_shutdown", "warning")
    assert bugcheck_code(rec) is None


def test_app_crash_grouping():
    recs = [parse_event_xml(APP_XML) for _ in range(3)]
    s = summarize(recs, 30)
    g = s.get("app_crash")
    assert g.count == 3 and g.details["game.exe"] == 3


def test_unknown_events_are_grouped_by_source_without_invented_meaning():
    r1 = EventRecord("System", "SomeVendorDriver", 12, 2, parse_event_xml(APP_XML).time)
    r2 = EventRecord("System", "SomeVendorDriver", 12, 2, r1.time)
    s = summarize([r1, r2], 7)
    assert s.groups[0].category == "other" and s.groups[0].count == 2


def test_invalid_xml_is_ignored():
    assert parse_event_xml("<kaputt") is None


def test_event_query_contains_time_window():
    q = build_query(7)
    assert "604800000" in q and "Level=1" in q and "EventID=4101" in q


LHM_JSON = {
    "id": 0, "Text": "Sensor", "Children": [{"id": 1, "Text": "PC", "Children": [
        {"id": 2, "Text": "AMD Ryzen 7 5800X", "ImageURL": "images_icon/cpu.png", "Children": [
            {"id": 3, "Text": "Temperatures", "Children": [
                {"id": 4, "Text": "Core (Tctl/Tdie)", "Value": "67,5 °C", "SensorId": "/amdcpu/0/temperature/2", "Type": "Temperature", "Children": []},
                {"id": 5, "Text": "CCD1 (Tdie)", "Value": "65.0 °C", "SensorId": "/amdcpu/0/temperature/3", "Type": "Temperature", "Children": []}]},
            {"id": 6, "Text": "Powers", "Children": [
                {"id": 7, "Text": "Package", "Value": "88.2 W", "SensorId": "/amdcpu/0/power/0", "Type": "Power", "Children": []}]}]},
        {"id": 8, "Text": "NVIDIA GeForce RTX 3070", "ImageURL": "images_icon/nvidia.png", "Children": [
            {"id": 9, "Text": "Temperatures", "Children": [
                {"id": 10, "Text": "GPU Core", "Value": "61.0 °C", "Children": []},
                {"id": 11, "Text": "GPU Hot Spot", "Value": "75.0 °C", "Children": []}]}]},
        {"id": 12, "Text": "ASUS ROG STRIX B550", "ImageURL": "images_icon/mainboard.png", "Children": [
            {"id": 13, "Text": "Nuvoton NCT6798D", "ImageURL": "images_icon/chip.png", "Children": [
                {"id": 14, "Text": "Fans", "Children": [
                    {"id": 15, "Text": "CPU Fan", "Value": "1234 RPM", "Children": []},
                    {"id": 16, "Text": "Fan #2", "Value": "0 RPM", "Children": []}]}]}]}]}]}


def test_lhm_json_parsing():
    sensors = lhm.parse_data_json(LHM_JSON)
    by = {(s.hardware, s.name): s for s in sensors}
    assert by[("AMD Ryzen 7 5800X", "Core (Tctl/Tdie)")].value == 67.5
    assert by[("AMD Ryzen 7 5800X", "Core (Tctl/Tdie)")].hw_kind == "cpu"
    assert by[("NVIDIA GeForce RTX 3070", "GPU Core")].kind == "temperature"
    assert by[("Nuvoton NCT6798D", "CPU Fan")].kind == "fan"
    assert by[("Nuvoton NCT6798D", "CPU Fan")].value == 1234.0
    assert lhm.pick_cpu_temp(sensors) == 67.5
    assert lhm.pick_cpu_power(sensors) == 88.2
    assert lhm.pick_gpu_temp(sensors, "NVIDIA GeForce RTX 3070") == 61.0  # nicht der Hotspot


def test_lhm_value_parsing_edge_cases():
    assert lhm.parse_value("1234 RPM") == 1234.0
    assert lhm.parse_value("–") is None
    assert lhm.parse_value(None) is None
    assert lhm.parse_value(" 45,5 °C") == 45.5
    assert lhm.parse_data_json("kaputt") == []


def test_lhm_wmi_rows():
    rows = lhm.parse_wmi_rows([{"Name": "CPU Package", "Identifier": "/intelcpu/0/temperature/0", "SensorType": "Temperature",
                                "Parent": "/intelcpu/0", "Value": 55.0}, {"Name": "x", "Value": "kaputt"}],
                              [{"Identifier": "/intelcpu/0", "Name": "Intel Core i7"}])
    assert len(rows) == 1 and rows[0].hardware == "Intel Core i7" and lhm.pick_cpu_temp(rows) == 55.0


def test_pdh_gpu_instances():
    values = {
        "pid_1_luid_0x00000000_0x0000D1B2_phys_0_eng_0_engtype_3D": 30.0,
        "pid_2_luid_0x00000000_0x0000D1B2_phys_0_eng_0_engtype_3D": 25.0,
        "pid_2_luid_0x00000000_0x0000D1B2_phys_0_eng_3_engtype_VideoDecode": 10.0,
        "pid_3_luid_0x00000000_0x0000AAAA_phys_0_eng_0_engtype_3D": 90.0,
        "garbage": 50.0,
    }
    util = pdh.gpu_util_by_luid(values)
    assert util["0x00000000_0x0000d1b2"] == 55.0
    assert util["0x00000000_0x0000aaaa"] == 90.0
    assert pdh.parse_adapter_memory_instance("luid_0x00000000_0x0000D1B2_phys_0") == "0x00000000_0x0000d1b2"


NETSH_DE = """
Es ist 1 Schnittstelle auf dem System vorhanden:

    Name                   : WLAN
    Beschreibung           : Intel(R) Wi-Fi 6 AX201 160MHz
    Status                 : Verbunden
    SSID                   : FRITZ!Box 7590 XY
    AP BSSID               : 12:34:56:78:9a:bc
    Funktyp                : 802.11ax
    Authentifizierung      : WPA2-Personal
    Kanal                  : 36
    Empfangsrate (MBit/s)  : 1201
    Übertragungsrate (MBit/s) : 960,5
    Signal                 : 74 %
"""

NETSH_LOCATION = "Netzwerkshellbefehle benötigen eine Standortberechtigung, um auf WLAN-Informationen zuzugreifen."


def test_netsh_parsing_german():
    w = parse_netsh_wlan(NETSH_DE)
    assert w.available and w.ssid == "FRITZ!Box 7590 XY" and w.signal_pct == 74
    assert w.rx_mbps == 1201 and w.tx_mbps == 960.5 and w.channel == "36"


def test_netsh_location_permission_detected():
    w = parse_netsh_wlan(NETSH_LOCATION)
    assert not w.available and w.location_denied


def test_vdf_and_steam_library(tmp_path):
    steam = tmp_path / "Steam"
    (steam / "steamapps").mkdir(parents=True)
    lib2 = tmp_path / "Games"
    (lib2 / "steamapps").mkdir(parents=True)
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n "0"\n {\n  "path" "%s"\n }\n "1"\n {\n  "path" "%s"\n }\n}\n'
        % (str(steam).replace("\\", "\\\\"), str(lib2).replace("\\", "\\\\")), encoding="utf-8")
    (steam / "steamapps" / "appmanifest_570.acf").write_text(
        '"AppState"\n{\n "appid" "570"\n "name" "Dota 2"\n "installdir" "dota 2 beta"\n}\n', encoding="utf-8")
    (lib2 / "steamapps" / "appmanifest_228980.acf").write_text(
        '"AppState"\n{\n "appid" "228980"\n "name" "Steamworks Common Redistributables"\n}\n', encoding="utf-8")
    (lib2 / "steamapps" / "appmanifest_1091500.acf").write_text(
        '"AppState"\n{\n "appid" "1091500"\n "name" "Cyberpunk 2077"\n "installdir" "Cyberpunk 2077"\n}\n', encoding="utf-8")
    games = steam_games(str(steam))
    assert sorted(g.name for g in games) == ["Cyberpunk 2077", "Dota 2"]
    assert any(g.target == "steam://rungameid/570" for g in games)
    assert parse_vdf('"a" { "b" "c\\"d" }') == {"a": {"b": 'c"d'}}


def test_epic_manifests(tmp_path):
    (tmp_path / "x.item").write_text(json.dumps({"DisplayName": "Fortnite", "AppName": "Fortnite",
                                                  "CatalogNamespace": "fn", "CatalogItemId": "abc",
                                                  "AppCategories": ["public", "games"]}), encoding="utf-8")
    (tmp_path / "y.item").write_text(json.dumps({"DisplayName": "Unreal Engine", "AppName": "UE",
                                                  "AppCategories": ["engines"]}), encoding="utf-8")
    (tmp_path / "z.item").write_text("kaputt", encoding="utf-8")
    games = epic_games(str(tmp_path))
    assert [g.name for g in games] == ["Fortnite"]
    assert games[0].target.startswith("com.epicgames.launcher://apps/fn%3Aabc%3AFortnite")


def test_game_target_validation(tmp_path):
    exe = tmp_path / "game.exe"
    exe.write_bytes(b"MZ")
    assert validate_target("steam://rungameid/570") is None
    assert validate_target(str(exe)) is None
    assert validate_target("http://evil.example/x.exe") == "unsupported_url"
    assert validate_target("cmd /c del") == "not_absolute"
    bat = tmp_path / "x.bat"
    bat.write_text("echo")
    assert validate_target(str(bat)) == "bad_extension"
    assert validate_target(str(tmp_path / "fehlt.exe")) == "missing"


def test_autostart_flags():
    assert is_enabled_flag(None) is True
    assert is_enabled_flag(ENABLED_BLOB) is True
    assert is_enabled_flag(bytes([6]) + b"\0" * 11) is True
    assert is_enabled_flag(disabled_blob(0)) is False
    assert len(disabled_blob()) == 12
    assert extract_executable('"C:\\Program Files\\App\\app.exe" --tray') == "C:\\Program Files\\App\\app.exe"
    assert extract_executable("C:\\Tools\\x.exe /min") == "C:\\Tools\\x.exe"


def test_programs_date_parsing():
    assert parse_install_date("20240115").year == 2024
    assert parse_install_date("kaputt") is None
    assert parse_install_date(None) is None


def test_version_comparison():
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert parse_version("0.2") == (0, 2, 0)
    assert parse_version("abc") is None
    assert is_newer("v0.2.0", "0.1.9")
    assert not is_newer("0.1.0", "0.1.0")
    assert not is_newer("kaputt", "0.1.0")
