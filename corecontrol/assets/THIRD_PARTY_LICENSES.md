# Verwendete Bibliotheken und Lizenzen / Third-party components

CoreControl selbst steht unter der GNU General Public License v3.0 (siehe LICENSE).
CoreControl itself is licensed under the GNU General Public License v3.0 (see LICENSE).

| Komponente / Component | Zweck / Purpose | Lizenz / License |
|---|---|---|
| Python 3 | Programmiersprache / runtime | PSF License |
| Qt 6 / PySide6 (Essentials) | Benutzeroberfläche / user interface | LGPL-3.0 |
| psutil | CPU, RAM, Datenträger, Netzwerk, Prozesse | BSD-3-Clause |
| pywin32 (nur Windows) | WMI, Windows-Ereignisprotokolle | PSF-2.0 |
| nvidia-ml-py (pynvml) | NVIDIA-GPU-Werte über den Treiber (NVML) | BSD-3-Clause |
| Send2Trash | Dateien in den Papierkorb verschieben | BSD-3-Clause |
| Lucide Icons | Symbole / icons | ISC (Teile MIT, Feather) |
| PyInstaller (nur zum Erstellen der EXE) | Erstellen der portablen EXE | GPL-2.0 mit Bootloader-Ausnahme |

Optional, nicht mitgeliefert / optional, not bundled:

| Programm | Zweck | Lizenz |
|---|---|---|
| LibreHardwareMonitor | CPU-Temperatur, Lüfter, Spannungen (wird nur gelesen, wenn der Benutzer es selbst startet) | MPL-2.0 |

Lizenztexte / license texts:
- Qt/PySide6: https://www.qt.io/licensing/open-source-lgpl-obligations — die PySide6-Bibliotheken liegen in der EXE als
  austauschbare DLLs vor (Ordner-Version) bzw. werden beim Start entpackt.
- psutil: https://github.com/giampaolo/psutil/blob/master/LICENSE
- pywin32: https://github.com/mhammond/pywin32/blob/main/Pythonwin/License.txt
- nvidia-ml-py: https://pypi.org/project/nvidia-ml-py/
- Send2Trash: https://github.com/arsenetar/send2trash/blob/master/LICENSE
- Lucide: https://github.com/lucide-icons/lucide/blob/main/LICENSE (Kopie: assets/icons/LICENSE-lucide.txt)
- LibreHardwareMonitor: https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/blob/master/LICENSE
