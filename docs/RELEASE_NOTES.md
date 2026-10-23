## CoreControl 0.1.0 – erste Testversion

Kostenloses Windows-PC-Control-Center mit verständlicher Systemdiagnose.

**Herunterladen:** `CoreControl.exe` unten bei *Assets*. Keine Installation nötig.
Windows SmartScreen warnt beim ersten Start, weil die EXE nicht signiert ist:
„Weitere Informationen“ → „Trotzdem ausführen“.

**Prüfsumme:** `CoreControl.exe.sha256.txt` enthält den SHA256-Wert. Prüfen in PowerShell:
`Get-FileHash .\CoreControl.exe -Algorithm SHA256`

### Enthalten
- Systemdiagnose mit Ursachen, Empfehlungen, Risiken und Sicherheitsangabe
- Dashboard, Live-Monitoring, Verlauf
- Hardware & Treiber, Fehlerprotokolle verständlich erklärt
- Speicheranalyse und sichere Bereinigung (Vorschau, Bestätigung, Papierkorb)
- Prozesse, Autostart, Programme, Windows-Werkzeuge
- Netzwerktest (Router, Internet, DNS, Paketverlust; kein Speedtest)
- Gaming: Mini-Monitor, Spiele-Starter
- Berichte (HTML/TXT) mit Entfernen persönlicher Daten, Fehlerbericht
- Dunkel/Hell, Akzentfarben, Deutsch/Englisch, Animationen einstellbar

### Hinweise
- Für CPU-Temperatur und Lüfter wird LibreHardwareMonitor benötigt (kostenlos, separat).
- Noch nicht auf vielen echten PCs getestet. Bitte Fehler über *Berichte & Feedback → Fehlerbericht exportieren* melden.
- Details: README, Benutzeranleitung und Testbericht im Repository (`docs/`).
