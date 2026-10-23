"""Baut die portable Windows-EXE mit PyInstaller.

Aufruf (unter Windows, im Projektordner):
    pip install -r requirements-dev.txt
    python tools/build_exe.py            → dist/CoreControl.exe (eine einzelne Datei)
    python tools/build_exe.py --folder   → dist/CoreControl/ (Ordner, startet schneller)
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from corecontrol import __version__  # noqa: E402

VERSION_INFO = """# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers=({v0}, {v1}, {v2}, 0), prodvers=({v0}, {v1}, {v2}, 0), mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040704b0', [
      StringStruct('CompanyName', 'CoreControl Open Source'),
      StringStruct('FileDescription', 'CoreControl - PC-Diagnose und Kontrolle'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'CoreControl'),
      StringStruct('LegalCopyright', 'GNU GPL v3'),
      StringStruct('OriginalFilename', 'CoreControl.exe'),
      StringStruct('ProductName', 'CoreControl'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1031, 1200])])
  ]
)
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", action="store_true", help="Ordner-Version statt einer einzelnen EXE")
    args = ap.parse_args()
    import PyInstaller.__main__

    parts = (__version__.split(".") + ["0", "0", "0"])[:3]
    vfile = os.path.join(ROOT, "build", "version_info.txt")
    os.makedirs(os.path.dirname(vfile), exist_ok=True)
    with open(vfile, "w", encoding="utf-8") as fh:
        fh.write(VERSION_INFO.format(v0=parts[0], v1=parts[1], v2=parts[2], version=__version__))
    sep = ";" if os.name == "nt" else ":"
    opts = [
        os.path.join(ROOT, "corecontrol", "__main__.py"),
        "--name", "CoreControl",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onedir" if args.folder else "--onefile",
        "--icon", os.path.join(ROOT, "corecontrol", "assets", "corecontrol.ico"),
        "--version-file", vfile,
        "--add-data", f"{os.path.join(ROOT, 'corecontrol', 'assets')}{sep}corecontrol/assets",
        "--add-data", f"{os.path.join(ROOT, 'LICENSE')}{sep}.",
        "--paths", ROOT,
        "--hidden-import", "win32timezone",
        "--hidden-import", "pynvml",
        "--collect-submodules", "corecontrol",
        # Nicht benötigte Teile weglassen → kleinere Datei, schnellerer Start
        "--exclude-module", "tkinter",
        "--exclude-module", "unittest",
        "--exclude-module", "pydoc",
        "--exclude-module", "PySide6.QtQml",
        "--exclude-module", "PySide6.QtQuick",
        "--exclude-module", "PySide6.QtPdf",
        "--exclude-module", "PySide6.QtWebEngineCore",
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", os.path.join(ROOT, "build"),
        "--specpath", os.path.join(ROOT, "build"),
    ]
    PyInstaller.__main__.run(opts)


if __name__ == "__main__":
    main()
