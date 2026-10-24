## CoreControl 0.1.1 – schnellere Live-Anzeige

**Herunterladen:** `CoreControl.exe` unten bei *Assets*. Keine Installation nötig.
Windows SmartScreen warnt beim ersten Start, weil die EXE nicht signiert ist:
„Weitere Informationen“ → „Trotzdem ausführen“.

**Prüfsumme:** `CoreControl.exe.sha256.txt` enthält den SHA256-Wert. Prüfen in PowerShell:
`Get-FileHash .\CoreControl.exe -Algorithm SHA256`

### Neu in 0.1.1
- Live-Werte werden 2× pro Sekunde gemessen statt 1×. Noch schneller: Einstellungen → Messung & Sensoren →
  Messintervall 0,25 s.
- Gleichmäßiger Takt: Lief LibreHardwareMonitor nicht, hielt die Suche danach jede zweite Messung bis zu
  0,6 s auf. Das passiert jetzt in einem eigenen Hintergrund-Thread.
- Diagramme laufen nach echter Uhrzeit; die Zeitachse zeigt runde Uhrzeiten ohne Überlappung.
- „Auslagerungsdatei“ und „Grafikspeicher“ brechen nicht mehr mitten im Wert um.

### Enthalten (seit 0.1.0)
- Systemdiagnose mit Ursachen, Empfehlungen, Risiken und Sicherheitsangabe
- Dashboard, Live-Monitoring, Verlauf, Hardware & Treiber, Fehlerprotokolle
- Speicheranalyse und sichere Bereinigung (Vorschau, Bestätigung, Papierkorb)
- Prozesse, Autostart, Programme, Netzwerktest, Gaming (Mini-Monitor, Spiele-Starter)
- Berichte (HTML/TXT) mit Entfernen persönlicher Daten, Fehlerbericht
- Dunkel/Hell, Akzentfarben, Deutsch/Englisch, Animationen einstellbar

### Hinweise
- Für CPU-Temperatur und Lüfter wird LibreHardwareMonitor benötigt (kostenlos, separat).
- Noch nicht auf vielen echten PCs getestet. Bitte Fehler über *Berichte & Feedback → Fehlerbericht exportieren* melden.
