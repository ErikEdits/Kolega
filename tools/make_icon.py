"""Erzeugt corecontrol/assets/corecontrol.ico aus dem gezeichneten Logo.

Aufruf: python tools/make_icon.py
"""

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from corecontrol.ui.logo import render_logo  # noqa: E402

SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def main() -> None:
    QApplication(sys.argv)
    images = []
    for s in SIZES:
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        render_logo(s).save(buf, "PNG")
        images.append((s, bytes(buf.data())))
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, data = b"", b""
    for s, png in images:
        dim = 0 if s >= 256 else s
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset + len(data))
        data += png
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corecontrol", "assets", "corecontrol.ico")
    with open(out, "wb") as fh:
        fh.write(header + entries + data)
    print("geschrieben:", out, len(header + entries + data), "Bytes")


if __name__ == "__main__":
    main()
