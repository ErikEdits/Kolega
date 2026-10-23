import os
import sys

# In der EXE ohne Konsolenfenster gibt es keine Standardausgabe – Ausgaben ins Leere leiten.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

from corecontrol.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
