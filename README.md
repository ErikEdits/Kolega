# CoreControl

**Kostenloses Windows-PC-Control-Center mit verständlicher Systemdiagnose.**

CoreControl prüft deinen PC, zeigt Live-Werte und erklärt gefundene Probleme in einfacher Sprache:
Was wurde erkannt, wie wichtig ist es, was könnte die Ursache sein, was kannst du tun und welche
Risiken hat eine Lösung. CoreControl ändert nichts ohne deine ausdrückliche Bestätigung.

> Status: **Version 0.1.1 (Testversion)**. Getestet automatisch auf Windows Server (GitHub) und
> Linux, noch **nicht auf echten Windows-10/11-PCs mit unterschiedlicher Hardware**. Siehe
> [Testbericht](docs/TESTBERICHT.md).

## Funktionen

| Bereich | Was es kann |
|---|---|
| **Systemdiagnose** (Hauptfunktion) | Regelbasierte Prüfung von Temperaturen, Auslastung, Arbeitsspeicher, Speicherplatz, Laufwerkszustand, Windows-Fehlerprotokollen (Bluescreens, unerwartete Neustarts, Hardware- und Laufwerksfehler, Grafiktreiber-Abstürze), Geräten mit Problemen, Treiberalter, Windows-Version, Autostart, Netzwerk. Jeder Befund mit Ursachen, Empfehlungen, Risiken und Angabe, wie sicher die Diagnose ist. |
| **Dashboard** | CPU, GPU, RAM, Speicher mit Ringanzeigen, Auslastungsdiagramm, Temperaturen, Lüfter, Schnellaktionen, letzte Ereignisse, Netzwerk. Kacheln ein-/ausblendbar und sortierbar. |
| **Live-Monitoring** | Diagramme für CPU, RAM, GPU, Temperaturen, Datenträger, Netzwerk (2×/Sekunde, einstellbar von 0,25 s bis 10 s), Tabelle aller Sensoren. |
| **Hardware & Treiber** | Windows-Version, CPU, Mainboard, BIOS, RAM-Riegel, Grafikkarten mit Treiberversion/-datum, Laufwerke mit Zustand, Treiberliste, Links zu offiziellen Treiberseiten. |
| **Fehlerprotokolle** | Windows-Ereignisse verständlich gruppiert und erklärt. |
| **Verlauf** | Diagramme über Stunden, Tage, Wochen (Minuten-/Stundenmittel, Aufbewahrung einstellbar). |
| **Speicher & Dateien** | Größte Ordner und Dateien, Verteilung nach Dateityp, Einschätzung „wichtig/entbehrlich“, sichere Bereinigung (Vorschau, Bestätigung, Papierkorb). |
| **Prozesse / Autostart / Programme** | Prozesse suchen, sortieren und nach Bestätigung beenden (Systemprozesse geschützt), Autostart umkehrbar deaktivieren, installierte Programme, Windows-Werkzeuge. |
| **Netzwerk** | Ping zu Router und Internet, Paketverlust, Schwankung, DNS, Erkennung von Anmeldeseiten (Hotel-WLAN), LAN/WLAN-Infos. Kein Speedtest. |
| **Gaming** | Werte beim Spielen, Mini-Monitor (immer im Vordergrund), Spiele-Starter (Steam, Epic, eigene EXE), ehrliche Hinweise ohne „FPS-Booster“. |
| **Berichte & Feedback** | Diagnosebericht als HTML/TXT, persönliche Daten werden auf Wunsch entfernt; technischer Fehlerbericht für die Fehlersuche. Nichts wird automatisch hochgeladen. |
| **Design** | Dunkel/Hell, freie Akzentfarbe, Deutsch/Englisch, Animationen (Voll/Reduziert/Aus), Symbol neben der Uhr. |

## Herunterladen und starten

1. Die Datei **`CoreControl.exe`** herunterladen (siehe [Benutzeranleitung](docs/BENUTZERANLEITUNG.md#1-herunterladen)).
2. Doppelklick. Es ist keine Installation nötig (portable EXE).
3. Windows zeigt beim ersten Start evtl. „Der Computer wurde durch Windows geschützt“, weil die EXE nicht
   kostenpflichtig signiert ist: **„Weitere Informationen“ → „Trotzdem ausführen“**.

Optional für CPU-Temperatur, Lüfter und Spannungen: das kostenlose
[LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases) als Administrator
starten. CoreControl liest die Werte dann mit; es installiert selbst keinen Treiber.

## Datenschutz

- Alles läuft lokal. Ohne dein Zutun werden keine Daten gesendet.
- Netzwerkverbindungen nur für: Netzwerktest (Ping/DNS/Webtest), Update-Prüfung (nur wenn eingeschaltet), Links.
- Gespeichert werden: Einstellungen, zusammengefasste Messwerte (Verlauf), Protokoll, Aktivitätsliste – nur auf deinem PC
  (`%APPDATA%\CoreControl`, `%LOCALAPPDATA%\CoreControl`).

## Für Entwickler

```bash
pip install -r requirements-dev.txt
python -m corecontrol            # starten
pytest                           # Tests
python tools/build_exe.py        # portable EXE bauen (unter Windows) → dist/CoreControl.exe
```

Bei jedem Push baut GitHub Actions automatisch die EXE auf Windows und führt alle Tests aus
(`.github/workflows/build.yml`). Eine Veröffentlichung (Release) mit EXE und SHA256-Prüfsumme entsteht
durch einen Tag `v*` oder von Hand: **Actions → Test und Windows-Build → Run workflow**, Branch `main`,
Versionsnummer eintragen (muss zu `corecontrol/__init__.py` passen).

Dokumentation:
- [Benutzeranleitung](docs/BENUTZERANLEITUNG.md)
- [Technik & Entscheidungen](docs/ARCHITEKTUR.md)
- [Testbericht & bekannte Einschränkungen](docs/TESTBERICHT.md)
- [Verwendete Bibliotheken & Lizenzen](corecontrol/assets/THIRD_PARTY_LICENSES.md)

## Lizenz

GNU General Public License v3.0 – siehe [LICENSE](LICENSE). Keine Gewähr: Empfehlungen sind Hinweise.
Vor Änderungen am System wichtige Daten sichern.
