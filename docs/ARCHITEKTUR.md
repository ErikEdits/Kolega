# CoreControl – Technik und Entscheidungen

## Überblick

| Teil | Technik | Warum |
|---|---|---|
| Sprache | Python 3.12 | Schnell zu entwickeln, gute Windows-Anbindung, kostenlos |
| Oberfläche | PySide6 (Qt 6 Widgets, LGPL) | Native, schnelle Desktop-Oberfläche, eigene Zeichen-Effekte möglich, kein Browser-Unterbau |
| Systemwerte | psutil, Windows-APIs über ctypes (PDH, DXGI, ICMP, Shell), WMI über pywin32 | Keine Treiber nötig, keine Adminrechte für die meisten Werte |
| NVIDIA-GPU | nvidia-ml-py (NVML aus dem Grafiktreiber) | Offizielle Schnittstelle, liefert Temperatur/Takt/Leistung ohne Zusatzprogramm |
| CPU-Temperatur, Lüfter | LibreHardwareMonitor (läuft separat, MPL 2.0) | Eigener Kernel-Treiber wäre ein Sicherheitsrisiko und nicht kostenlos signierbar |
| Papierkorb | Send2Trash | Verlässliches Verschieben in den Windows-Papierkorb |
| Symbole | Lucide (ISC-Lizenz) | Einheitliche, freie Symbole |
| EXE | PyInstaller (eine Datei, ohne Konsole) | Portable EXE ohne Installation |
| Build | GitHub Actions (Windows Server) | Kostenlos, baut und testet bei jeder Änderung |

## Ordnerstruktur

```
corecontrol/
  core/          Einstellungen, Pfade, Protokoll, Zahlenformat, Aktivitätsliste, Plattform-Helfer
  i18n/          Texte Deutsch/Englisch (de.py, en.py – gleiche Schlüssel, per Test geprüft)
  monitoring/    Live-Messung (Collector, Sampler-Thread, Ringpuffer), PDH, GPU, LibreHardwareMonitor, Hardware-Infos
  diagnostics/   Diagnose-Regeln, Ereignisprotokoll-Auswertung, Ablauf der Gesamtdiagnose
  network/       Ping (ICMP-API), DNS, Webtest, Adapter, WLAN
  storage/       Sicherheitsregeln, Ordneranalyse, Bereinigung
  system/        WMI, Prozesse, Autostart, Programme, Windows-Werkzeuge
  history/       Verlauf in SQLite (Minuten- und Stundenwerte)
  reports/       Diagnosebericht (TXT/HTML), Fehlerbericht, Entfernen persönlicher Daten
  gaming/        Spielebibliothek (Steam/Epic/eigene), Windows-Spieleinstellungen (nur anzeigen)
  updates/       Update-Prüfung (nur GitHub-Releases dieses Projekts, lädt nichts herunter)
  ui/            Hauptfenster, Seiten, Widgets, Design, Animationen, Suche, Infobereich, Mini-Monitor
tools/           EXE bauen, Symbol erzeugen, Windows-Selbsttest
tests/           Automatische Tests (pytest)
```

## Wichtige Abläufe

**Live-Messung.** Ein eigener Thread (`monitoring/live.py`) misst im eingestellten Intervall (Standard 0,5 s, im
Hintergrund 5 s) und schickt fertige Messpunkte an die Oberfläche. Die Oberfläche wartet nie auf Messungen.
Jede Messquelle ist einzeln abgesichert: Fällt eine aus, fehlt nur dieser Wert („Nicht verfügbar“).
LibreHardwareMonitor wird in einem weiteren Thread gelesen (`LhmPoller`), höchstens 1×/s, und wenn es nicht
läuft nur alle 10 s. Unter Windows dauert schon der Verbindungsversuch zu einem geschlossenen lokalen Port bis
zu ~1 s; das würde sonst die ganze Messung aufhalten.
Diagramme zeichnen nach Uhrzeit über ein festes Zeitfenster (z. B. 120 s), unabhängig vom Messtakt.

**Diagnose.** `diagnostics/engine.py` sammelt Daten (Hardware, 30 Tage Ereignisprotokoll, Live-Werte der letzten
Minute bzw. eine kurze Messung, Prozesse, Autostart, Netzwerktest) in einem Hintergrund-Task mit Fortschritt und Abbruch. Danach laufen reine
Regel-Funktionen (`diagnostics/rules.py`) ohne Systemzugriff. Deshalb lassen sie sich mit Testdaten prüfen.
Jeder Befund hat Schweregrad, Messwerte, Ursachen, Empfehlungen, Risiken und eine Sicherheitsangabe.
Fehlt eine Messquelle, wird der Bereich unter „Nicht geprüft“ mit Grund aufgeführt statt geraten.

**Löschen.** Drei Ebenen:
1. `storage/safety.py`: Einordnung (System, Programm, Benutzer, App-Daten, Temp, Unbekannt) und gesperrte Pfade.
2. `storage/cleanup.py`: nur bekannte Ordner (`safe_root` lehnt Laufwerkswurzeln, Benutzer- und Systemordner ab).
   `delete_files` verlangt `confirmed=True`, prüft jede Datei direkt vor dem Löschen erneut (innerhalb des
   erlaubten Ordners, keine Verknüpfung/Junction), löscht standardmäßig in den Papierkorb und prüft danach, ob
   die Datei wirklich weg ist.
3. Oberfläche: Zusammenfassung mit allen Pfaden, Pflicht-Häkchen.

**Prozesse beenden.** `system/processes.py`: geschützte Systemprozesse werden abgelehnt, `confirmed=True` ist Pflicht,
und vor dem Beenden wird geprüft, ob unter der Prozess-ID noch derselbe Prozess läuft (Startzeit).

**Autostart.** Deaktivieren schreibt wie der Task-Manager in `StartupApproved` (umkehrbar), Einträge werden nicht
gelöscht. Nach dem Schreiben wird nachgelesen, ob die Änderung angekommen ist.

**Berichte.** Ein Bericht wird als Struktur aufgebaut und dann als TXT oder HTML ausgegeben (HTML mit Escaping).
`reports/redact.py` ersetzt Benutzername, PC-Name, E-Mail-, IP- und MAC-Adressen und WLAN-Namen.

## Entscheidungen (und was bewusst weggelassen wurde)

| Entscheidung | Grund |
|---|---|
| Temperaturen über LibreHardwareMonitor statt eigenem Treiber | Ein Kernel-Treiber braucht Adminrechte und eine Signatur; bekannte freie Treiber (WinRing0) gelten als Sicherheitslücke. |
| Kein Speedtest | Kostenlose, verlässliche Messserver ohne Nutzungsbedingungs-Probleme gibt es nicht. Der Netzwerktest misst Erreichbarkeit, Paketverlust, Schwankung, DNS. |
| Keine FPS-Anzeige | Braucht PresentMon (Intel, MIT-Lizenz) als Zusatzprogramm mit Adminrechten. Möglicher nächster Schritt. |
| Keine automatische Treiber-Installation | Laut Auftrag; nur Links zu offiziellen Herstellerseiten. |
| Kein Microsoft-Konto-Login | Ein sicherer Login lohnt sich ohne Cloud-Funktion nicht; Einstellungen lassen sich exportieren/importieren. |
| Update-Prüfung ohne Download | Zeigt nur die neue Version und öffnet die offizielle Release-Seite. Kein automatisches Ausführen von Dateien. |
| Normale Windows-Titelleiste | Eine selbstgezeichnete Titelleiste bricht Fenster-Andocken (Snap), Barrierefreiheit und Windows-Verhalten. Unter Windows 11 wird die Titelleiste in Hintergrundfarbe eingefärbt. |
| Portable EXE statt Installer | Einfacher zu verteilen; ein Installer ist optional für später. |
| GPL-3.0 für das Projekt | Verträgt sich mit allen verwendeten Bibliotheken (LGPL, MIT, BSD, ISC, MPL). |

## Design und Animationen

- Farben und Abstände: `ui/theme.py` (dunkles Mitternachts-Design und helles Design, frei wählbare Akzentfarbe).
- Hintergrund mit Verlauf und zwei weichen Lichtflecken, einmal berechnet und zwischengespeichert.
- `ui/anim.py`: ein gemeinsamer Takt (30 Bilder/s), der **nur läuft, solange sich etwas bewegt**. Ohne Bewegung
  verbraucht die Oberfläche keine Rechenzeit für Animationen.
- Buttons (`ui/widgets/controls.py`) sind selbst gezeichnet: Hover hellt auf, Glow und 1,5 px Anheben, beim Klick
  kurz auf 96 % verkleinert (Hover 160–240 ms, Klick 90 ms hinein und 200 ms zurück, Kurve „OutCubic“).
- Seitenwechsel: alte Seite blendet aus und gleitet nach oben, neue gleitet von unten ein (260 ms).
- Diagramme gleiten weich weiter, Ringanzeigen und Balken laufen zum neuen Wert.
- Fenster und Dialoge blenden über die Fenster-Deckkraft ein; das übernimmt Windows' Fenstermanager (DWM) auf der
  Grafikkarte. Die Widget-Effekte selbst zeichnet Qt auf der CPU, deshalb sind sie kurz und sparsam gehalten.
- Einstellung **Animationen & Effekte**: Wie Windows (folgt „Animationseffekte“ in Windows), Voll, Reduziert
  (nur Seitenwechsel und Einblenden), Aus.

## Daten auf dem PC

| Was | Wo |
|---|---|
| Einstellungen (`settings.json`) | `%APPDATA%\CoreControl` |
| Verlauf (`history.db`), Aktivitätsliste (`activity.json`), Protokolle (`logs\`) | `%LOCALAPPDATA%\CoreControl` |

Für Tests kann der Ort mit der Umgebungsvariable `CORECONTROL_HOME` umgelenkt werden.
