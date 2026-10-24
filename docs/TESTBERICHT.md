# CoreControl – Testbericht

Stand: 22.10.2026, Version 0.1.0. Hier steht nur, was tatsächlich gelaufen ist.

## 1. Automatische Tests

Bei jeder Änderung laufen auf GitHub zwei Prüfungen (`.github/workflows/build.yml`):

| Prüfung | Wo | Was |
|---|---|---|
| Fehlerprüfung (ruff) | Linux und Windows | Findet Programmierfehler ohne Programmstart, z. B. Variablen, die ein Modul verdecken, undefinierte Namen |
| pytest (101 Tests) | Linux und Windows Server 2025 | Siehe Tabelle unten |
| Windows-Selbsttest (`tools/windows_selftest.py`) | Windows Server 2025 | Ruft alle echten Windows-Messquellen auf und gibt die gelesenen Werte aus |
| EXE bauen | Windows | PyInstaller, eine Datei |
| EXE-Starttest | Windows | Startet die fertige EXE, öffnet alle 14 Seiten, speichert Bilder, prüft das Protokoll auf Fehler |

### Testbereiche (pytest)

| Datei | Anzahl | Prüft |
|---|---|---|
| `test_diagnosis_rules.py` | 27 | Diagnose-Regeln: Temperatur-/Last-/RAM-/Speicher-/Laufwerksbefunde, Bluescreens, Geräte, Treiber, Windows-Editionen und Support-Ende, Netzwerkfälle (offline, Router weg, DNS, Ping gesperrt, Paketverlust, Anmeldeseite, schwaches WLAN, virtuelle Maschine), fehlende Sensoren landen unter „Nicht geprüft“, ein Regelfehler stoppt die Diagnose nicht, jeder Befund hat Texte in beiden Sprachen |
| `test_gui.py` | 12 | Alle Seiten laden ohne Fehler, Sprache/Design wechseln, Seitenübergang läuft und endet, Hover-Animation und „Aus“-Modus, Animationstakt stoppt im Leerlauf, Suche, keine Attribute verdecken Qt-Funktionen, Bestätigungsdialog verlangt Häkchen, **Abläufe mit Bestätigung**: Prozess beenden (echter Kindprozess), Datei löschen, Bereinigung, Einstellungen importieren (Abbrechen ändert nichts, Bestätigen führt aus) |
| `test_storage.py` | 13 | Einordnung System/Programm/Benutzer/Temp, gesperrte Pfade, Löschen nur mit Bestätigung, nur in erlaubten Ordnern, keine Ordner/Verknüpfungen, ehrliche Fehlerliste, Nachkontrolle, Analyse folgt keinen Verknüpfungen, markiert gesperrte Ordner, Abbruch |
| `test_parsers.py` | 18 | Ereignisprotokoll (Bluescreen, Kernel-Power, App-Abstürze, unbekannte Ereignisse ohne erfundene Bedeutung), LibreHardwareMonitor-Daten, PDH-GPU-Zähler, WLAN-Ausgabe (deutsch, Standortberechtigung), Steam/Epic, Autostart-Markierungen, Programmdaten, Versionsvergleich |
| `test_settings.py` | 10 | Standardwerte, falsche Typen/Bereiche werden korrigiert, kaputte Datei wird gesichert, Export/Import |
| `test_i18n_fmt.py` | 9 | Gleiche Schlüssel und Platzhalter in Deutsch/Englisch, alle im Code verwendeten Schlüssel existieren, Zahlenformat |
| `test_reports_history.py` | 7 | Bericht TXT/HTML, persönliche Daten werden überall entfernt, Verlauf (Minutenwerte, Aufbewahrung, Verdichtung, ausgeschaltet = nichts gespeichert) |
| `test_processes_updates.py` | 5 | Geschützte Prozesse, Beenden nur mit Bestätigung, Erkennung wiederverwendeter Prozess-IDs, Update-Prüfung |

Ergebnis: alle 101 Tests bestanden, lokal (Linux) und auf GitHub (Linux und Windows), Lauf vom 22.10.2026.

## 2. Ergebnisse des Windows-Selbsttests (echte Werte, GitHub-Server)

Der GitHub-Rechner ist eine virtuelle Maschine (Windows Server 2025, AMD EPYC, 8 GB RAM, keine echte Grafikkarte,
kein WLAN). Gelesen wurden u. a.:

| Bereich | Ergebnis |
|---|---|
| Hardware (WMI, Registry) | Windows-Version mit Build/Edition, CPU, Mainboard/BIOS, 2 RAM-Module, Grafikadapter mit Treiber, 2 NVMe-Laufwerke mit Zustand „fehlerfrei“, Laufwerksbelegung, 1 Gerät ohne Treiber erkannt (in 273 ms) |
| Live-Messung | CPU-Last und -Takt, RAM, Datenträgeraktivität, Netzwerk, Prozessanzahl; GPU über PDH-Zähler; LibreHardwareMonitor korrekt als „läuft nicht“ erkannt. Dauer je Messung (Version 0.1.1, 20 Messungen im 0,25-s-Takt): Median 3,6 ms, höchstens 3,8 ms |
| Ereignisprotokolle | 18 Ereignisse in 7 Tagen gelesen und eingeordnet (46 ms) |
| Netzwerk | Gateway, DNS (OK), Webtest (OK), Adapter mit 50 Gbit/s (aus WMI). Ping ist in Azure gesperrt; nach der Korrektur (Abschnitt 3) meldet die Diagnose das als Hinweis „Pings werden blockiert“ statt als „offline“ |
| Autostart / Programme / Prozesse | 3 / 59 / 139 Einträge gelesen |
| Bereinigung (nur Analyse) | 7 Kategorien gelesen, nichts gelöscht |
| Gesamtdiagnose mit Netzwerk | 35 s, Bericht TXT und HTML erzeugt. Ergebnis nach den Korrekturen: 1 Warnung (ein Gerät ohne Treiber – in der VM tatsächlich vorhanden), 2 Hinweise, 7 × OK, 4 Bereiche „nicht geprüft“ mit Grund (CPU-/GPU-Temperatur, Laufwerks-Details ohne Admin, Server-Edition) |
| EXE | 45,6 MB; Oberfläche nach 0,27 s bereit (nach dem Entpacken); alle 14 Seiten ohne Fehler im Protokoll |

## 3. Durch Tests gefundene und behobene Fehler

| Fehler | Gefunden durch | Behoben |
|---|---|---|
| Datei unter `C:\Windows` wurde als „Temp“ eingestuft, weil ein Ordner darüber „Temp“ hieß | Windows-CI | Einordnung nur relativ zum Basisordner, Regressionstest |
| Absturz beim ersten Öffnen von „Verlauf“ (Attribut `metric` überdeckte eine Qt-Funktion) | GUI-Test | Umbenannt, Test prüft alle Seiten auf solche Überdeckungen |
| Prozess beenden, Bereinigung, Datei löschen, Einstellungen importieren: Die Aktion selbst lief nach der Bestätigung, aber danach brach der Ablauf mit einem Fehler ab, statt das Ergebnis zu melden (eine Variable verdeckte das Meldungsmodul). Hinweise wie „Bitte zuerst einen Prozess in der Liste auswählen.“ erschienen ebenfalls nicht | Beim Prüfen der Anleitung gegen den Code; pyflakes bestätigt | Behoben, die vier Abläufe werden jetzt durchgespielt, ruff im CI |
| Diagnose meldete auf der VM „Keine Netzwerkverbindung“ (kritisch), obwohl das Internet funktionierte | Windows-Selbsttest | Adapter mit Gateway zählen, „offline“ nur ohne Internet |
| Windows Server 2025 wurde als „Windows 11 24H2 ohne Support“ gemeldet; Enterprise/Education wurden nach Home/Pro-Fristen bewertet | Windows-Selbsttest | Editionen werden unterschieden, Server/LTSC nicht bewertet |
| Microsoft-Standard-Grafiktreiber (Datum 2006) als „veralteter Treiber“ gemeldet | Windows-Selbsttest | Nur NVIDIA/AMD/Intel-Treiber werden nach Alter bewertet |
| Netzwerkgeschwindigkeit über 4,29 Gbit/s wurde als 4294 Mbit/s angezeigt | Windows-Selbsttest | Wert aus WMI |
| IPv6-Adressen mit „::“ wurden in Berichten nicht entfernt | Test | Behoben |
| Bei gesperrtem Ping stand im OK-Befund „Paketverlust 100 %“ | Windows-Selbsttest | Eigener Text ohne Ping-Werte |
| Ohne laufendes LibreHardwareMonitor hielt die Suche danach jede zweite Messung bis zu 0,6 s auf; die Live-Anzeige lief dadurch ungleichmäßig | Rückmeldung vom ersten echten PC (Ryzen 5 7500F, Radeon RX 9070 XT) und Windows-Selbsttest | Suche im eigenen Thread, nur alle 10 s (Version 0.1.1) |
| Zeitachsen-Beschriftungen überlappten sich in schmalen Diagrammen | Bildschirmfoto vom echten PC | Beschriftung auf runden Uhrzeiten mit Mindestabstand, Test |

## 4. Bekannte Einschränkungen

- **Nicht auf echter PC-Hardware getestet.** Alles oben lief auf Linux und einer Windows-Server-VM ohne
  Grafikkarte, Lüfter, Akku und WLAN. Ungetestet sind insbesondere:
  NVIDIA-Werte über NVML, AMD-Treiberwerte über ADL (ab 0.1.2; nur mit simulierten Treiberwerten getestet),
  Intel-Grafikkarten, LibreHardwareMonitor-Anbindung mit echten Sensoren, WLAN-Anzeige,
  Laptops, Windows 10, Bildschirmskalierung über 100 %, Mehrbildschirm, Tray-Benachrichtigungen,
  echtes Verschieben in den Papierkorb unter Windows, Autostart-Umschalten, Adminfunktionen.
- **Oberfläche nur automatisch geprüft** (ohne Bildschirm). Ob Animationen auf schwachen PCs flüssig wirken,
  muss ein Mensch beurteilen; im Zweifel „Reduziert“ oder „Aus“ wählen.
- CPU-Temperatur und Lüfter nur mit LibreHardwareMonitor. Ohne steht „Nicht verfügbar“.
- Laufwerks-Detailwerte (Verschleiß, Temperatur, Lesefehler) nur mit Administratorrechten.
- Keine FPS-Anzeige, kein Speedtest, keine automatische Spiele-Optimierung (bewusst, siehe Architektur).
- Die EXE ist nicht signiert → Windows SmartScreen warnt beim ersten Start. Manche Virenscanner melden
  PyInstaller-EXEs fälschlich; der Quelltext ist öffentlich nachvollziehbar.
- Fristen zum Windows-Support stammen aus dem Microsoft-Lebenszyklus mit Stand Oktober 2026 und müssen bei neuen
  Windows-Versionen im Programm nachgetragen werden.
- Der Verlauf zeichnet nur auf, solange CoreControl läuft.
- Die Suche findet Funktionen und Einstellungen, keine Dateien.

## 5. Manuelle Tests – bitte auf einem echten PC durchführen

| # | Test | Erwartung |
|---|---|---|
| 1 | EXE starten (SmartScreen-Hinweis bestätigen) | Fenster erscheint in wenigen Sekunden |
| 2 | Dashboard 1 Minute beobachten | Werte ändern sich 2× pro Sekunde, nichts ruckelt |
| 3 | Systemdiagnose starten | Ergebnis nach < 1 Minute; Befunde plausibel? Falsche Befunde bitte melden |
| 4 | LibreHardwareMonitor als Admin starten | Nach wenigen Sekunden CPU-Temperatur und Lüfter sichtbar |
| 5 | Monitoring mit Spiel/Last | Diagramme laufen weich, GPU-Last passt zum Task-Manager |
| 6 | Speicher → Bereinigung → Suchen → Bereinigen (Papierkorb) | Zusammenfassung erscheint, nach Bestätigung landen Dateien im Papierkorb |
| 7 | Autostart: einen Eintrag aus- und wieder einschalten | Task-Manager zeigt denselben Zustand |
| 8 | Netzwerk → Verbindung testen | Werte plausibel (Router-Ping meist < 5 ms per Kabel) |
| 9 | Gaming → Mini-Monitor über einem Spiel (Fenstermodus/randloses Fenster) | Bleibt sichtbar |
| 10 | Einstellungen → Animationen „Aus“ / Englisch / Hell | Wirkt sofort |
| 11 | Berichte → HTML speichern | Bericht öffnet im Browser, Benutzername ersetzt |
| 12 | Fenster schließen, erneut starten | Startet normal, Einstellungen bleiben |

Gefundene Fehler bitte mit **Berichte & Feedback → Fehlerbericht exportieren** und einem Screenshot melden.
