# CoreControl – Benutzeranleitung

Diese Anleitung ist für Menschen ohne Technikwissen geschrieben.

## 1. Herunterladen

Solange das Projekt-Repository privat ist, gibt es die EXE in GitHub unter **Actions**:

1. Auf GitHub das Repository **ErikEdits/Kolega** öffnen (eingeloggt).
2. Oben auf **Actions** klicken.
3. Den obersten Eintrag mit grünem Haken öffnen (Name „Test und Windows-Build“).
4. Ganz unten bei **Artifacts** auf **CoreControl-Windows** klicken. Es wird eine ZIP-Datei heruntergeladen.
5. ZIP-Datei entpacken (Rechtsklick → „Alle extrahieren“). Darin liegt `CoreControl.exe`.

Unter **Seitenbilder-Windows** gibt es zusätzlich Bilder aller Seiten, die bei der automatischen Prüfung
aufgenommen wurden.

Sobald eine Version mit Versionsnummer veröffentlicht ist (z. B. `v0.1.0`), liegt die EXE unter **Releases**,
zusammen mit einer Prüfsumme (SHA256), mit der man prüfen kann, dass die Datei unverändert ist.

## 2. Starten

- Doppelklick auf `CoreControl.exe`. Eine Installation ist nicht nötig. Der erste Start dauert etwas länger
  (die EXE entpackt sich kurz im Hintergrund).
- **Meldung „Der Computer wurde durch Windows geschützt“:** Das kommt, weil die EXE nicht mit einem kostenpflichtigen
  Zertifikat signiert ist. Auf **„Weitere Informationen“** und dann **„Trotzdem ausführen“** klicken.
- CoreControl braucht normalerweise **keine Administratorrechte**. Wo ein Bereich Adminrechte braucht
  (z. B. Laufwerks-Fehlerzähler, Windows-Temp-Ordner leeren, manche Prozesse), steht das dort, mit einem Knopf
  „Als Administrator neu starten“.
- Das X beendet CoreControl. Soll es im Hintergrund weiterlaufen (z. B. für Warnungen bei hohen Temperaturen):
  Einstellungen → Start & Hintergrund → **„Beim Schließen weiterlaufen“**. Dann ganz beenden über
  Rechtsklick auf das Symbol neben der Uhr → „Beenden“.

## 3. Temperaturen und Lüfter (optional)

Windows selbst liefert keine zuverlässigen CPU-Temperaturen. CoreControl liest sie deshalb aus dem kostenlosen
Programm **LibreHardwareMonitor** mit, statt selbst einen Treiber zu installieren (das wäre ein Sicherheitsrisiko).

1. [LibreHardwareMonitor herunterladen](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases)
   (Datei `LibreHardwareMonitor.zip`), entpacken.
2. `LibreHardwareMonitor.exe` mit Rechtsklick → **„Als Administrator ausführen“** starten.
3. Optional: Dort unter *Options* „Run On Windows Startup“ und „Start Minimized“ einschalten.
4. CoreControl erkennt es automatisch. Den Status siehst du unter Einstellungen → **Messung & Sensoren**.
   Falls dort „nicht gefunden“ steht: in LibreHardwareMonitor *Options → Remote Web Server → Run* aktivieren
   (Port 8085).

Ohne LibreHardwareMonitor steht bei Temperaturen und Lüftern **„Nicht verfügbar“**. Grafikkarten-Temperaturen von
NVIDIA-Karten funktionieren auch ohne.

## 4. Die Bereiche

| Bereich | Wofür |
|---|---|
| **Dashboard** | Überblick: Auslastung, Temperaturen, Lüfter, Speicher, letzte Ereignisse, Netzwerk, Schnellaktionen. Kacheln in Einstellungen → Dashboard ein-/ausblenden und sortieren. |
| **Systemdiagnose** | Knopf **„Diagnose starten“**. Dauert meist unter einer Minute (mit Netzwerktest). Danach Befunde nach Wichtigkeit (Kritisch / Warnung / Hinweis / OK). Ein Befund lässt sich aufklappen: *Was gemessen wurde*, *Mögliche Ursachen*, *Was du tun kannst*, *Risiken*, *Wie sicher ist das?*. Unten steht, welche Bereiche nicht geprüft werden konnten und warum. |
| **Monitoring & Temperaturen** | Live-Diagramme. Unten eine Tabelle aller Sensoren. |
| **Hardware & Treiber** | Alle Bauteile, Treiberversionen und -alter, Geräte mit Problemen, Links zu den offiziellen Treiberseiten (NVIDIA/AMD/Intel …). CoreControl lädt **keine** Treiber selbst herunter. |
| **Fehlerprotokolle** | Windows-Fehler der letzten Tage, gruppiert und erklärt (z. B. Bluescreen, unerwarteter Neustart, Laufwerksfehler). |
| **Verlauf** | Wie sich Temperaturen, Auslastung usw. über Stunden/Tage entwickelt haben. Nur gespeichert, solange CoreControl läuft. |
| **Speicher & Dateien** | Laufwerke, Analyse der größten Ordner/Dateien, Bereinigung. Siehe Abschnitt 5. |
| **Prozesse** | Laufende Programme mit CPU-/RAM-Verbrauch. Beenden nur nach Bestätigung; wichtige Windows-Prozesse sind gesperrt. |
| **Autostart** | Programme, die mit Windows starten. Deaktivieren ist umkehrbar (wie im Task-Manager). |
| **Programme & Tools** | Installierte Programme (Deinstallation über Windows), Abkürzungen zu Windows-Werkzeugen. |
| **Netzwerk** | Knopf **„Verbindung testen“**: Router erreichbar? Internet erreichbar? Paketverlust? DNS? Anmeldeseite (Hotel-WLAN)? Das ist **kein Geschwindigkeitstest**. |
| **Gaming** | Mini-Monitor (kleines Fenster immer im Vordergrund, verschiebbar, Rechtsklick schließt), Spiele-Starter, Hinweise zu Windows-Einstellungen. |
| **Berichte & Feedback** | Diagnosebericht speichern (HTML zum Ansehen im Browser, TXT zum Verschicken). Fehlerbericht für die Fehlersuche („Fehlerbericht exportieren“). |
| **Einstellungen** | Aussehen, Sprache, Animationen, Dashboard, Messintervall, Warnschwellen, Verlauf, Start, Automatik, Datenschutz, Info/Updates. |

Oben gibt es eine **Suche**: z. B. „Temperatur“, „Autostart“ oder „Bericht“ eintippen und Enter drücken.

## 5. Dateien löschen – was CoreControl dabei macht

CoreControl löscht nie etwas ohne deine Bestätigung. Ablauf bei **Bereinigung**:

1. „Suchen“ zeigt Kategorien mit Größe und Begründung: Temporäre Dateien (deine und die von Windows),
   Absturzabbilder, Windows-Fehlerberichte, Miniaturansichten, Shader-Cache, Browser-Cache.
2. Vorausgewählt sind nur die ersten vier. Miniaturansichten, Shader-Cache und Browser-Cache musst du selbst
   anhaken: Sie werden zwar neu erstellt, aber danach laufen Explorer, Spiele oder Browser kurz langsamer.
   Temporäre Dateien, die jünger als 2 Tage sind, werden übersprungen (einstellbar), weil Programme sie evtl.
   noch brauchen. Der Windows-Temp-Ordner braucht Administratorrechte.
3. Vor dem Löschen erscheint eine **Zusammenfassung** mit jedem Ordner, Anzahl, Größe und Risiko. Erst ein Haken
   „Ich habe die Liste geprüft“ macht den Löschen-Knopf aktiv.
4. Standard: **in den Papierkorb**. Dauerhaft löschen nur, wenn du es ausdrücklich auswählst.
5. Jede Datei wird direkt vor dem Löschen erneut geprüft (liegt sie noch im erlaubten Ordner, ist sie keine
   Verknüpfung auf einen anderen Ort?). Dateien in Benutzung werden übersprungen.

In der **Analyse** kann man große Dateien im Explorer anzeigen lassen; Dateien in Windows- und Programmordnern
werden als „System“/„Programm“ markiert und können dort nicht gelöscht werden.

## 6. Datenschutz

- CoreControl sendet von sich aus **nichts**.
- Berichte: Option „Persönliche Angaben entfernen“ (Standard: an) ersetzt Benutzername, PC-Name, E-Mail-Adressen,
  WLAN-Name, IP- und MAC-Adressen durch Platzhalter. Trotzdem vor dem Verschicken einmal durchlesen.
- Einstellungen → **Datenschutz & Daten**: Datenordner öffnen, Einstellungen exportieren/importieren.
  Einstellungen → **Verlauf**: Verlauf löschen, Aufbewahrungsdauer.
- Speicherorte: Einstellungen in `%APPDATA%\CoreControl`, Verlauf und Protokolle in `%LOCALAPPDATA%\CoreControl`.
  CoreControl entfernen = EXE löschen und diese beiden Ordner löschen.

## 7. Wenn etwas nicht funktioniert

1. **Berichte & Feedback → Fehlerfeedback**: kurz beschreiben, was passiert ist, dann **„Fehlerbericht exportieren“**.
2. Den Bericht (TXT) und ggf. einen Screenshot an den Entwickler schicken. Vorher durchlesen.
3. Wenn CoreControl gar nicht startet: Protokoll unter `%LOCALAPPDATA%\CoreControl\logs\corecontrol.log`
   (im Explorer in die Adresszeile einfügen) mitschicken.

## 8. Was CoreControl bewusst nicht macht

- Keine „Registry-Reiniger“, keine „FPS-Booster“, kein pauschales Abschalten von Diensten.
- Keine Treiber-Downloads oder -Installationen.
- Keine erfundenen Werte: Fehlt ein Sensor, steht dort „Nicht verfügbar“.
- Keine FPS-Anzeige und kein Speedtest (siehe [Testbericht – Einschränkungen](TESTBERICHT.md#4-bekannte-einschränkungen)).
