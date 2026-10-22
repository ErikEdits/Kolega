"""Speicheranalyse: größte Ordner und Dateien, Verteilung nach Dateityp.

- Verknüpfungen und Junctions werden nicht verfolgt (keine Doppelzählung, keine Endlosschleifen).
- Ordner ohne Zugriffsrechte werden übersprungen und als „nicht zugänglich“ gemeldet.
- OneDrive-Platzhalter („nur online verfügbar“) belegen keinen lokalen Platz und
  werden getrennt ausgewiesen.
- Es wird nur gelesen, nichts verändert.
"""

from __future__ import annotations

import heapq
import os
import time
from dataclasses import dataclass, field

from corecontrol.storage.safety import ext_category

FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
CLOUD_ONLY = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS

TREE_DEPTH = 4  # Bis zu dieser Tiefe werden Ordnergrößen einzeln gespeichert


@dataclass
class ScanResult:
    root: str
    total: int = 0
    files: int = 0
    dirs: int = 0
    largest: list[tuple[int, str]] = field(default_factory=list)  # (Größe, Pfad), absteigend
    dir_sizes: dict[str, int] = field(default_factory=dict)
    dir_files: dict[str, int] = field(default_factory=dict)
    by_type: dict[str, int] = field(default_factory=dict)
    by_type_count: dict[str, int] = field(default_factory=dict)
    denied: list[str] = field(default_factory=list)
    denied_count: int = 0
    links_skipped: int = 0
    cloud_only: int = 0
    cloud_only_size: int = 0
    cancelled: bool = False
    seconds: float = 0.0

    def children(self, path: str) -> list[tuple[str, int]]:
        """Unterordner eines Ordners mit Größe (nur bis TREE_DEPTH verfügbar)."""
        base = os.path.normpath(path)
        out = []
        for p, s in self.dir_sizes.items():
            if os.path.dirname(p) == base and p != base:
                out.append((p, s))
        return sorted(out, key=lambda x: -x[1])


def scan(root: str, ctx=None, top_n: int = 300, progress_every: float = 0.25) -> ScanResult:
    root = os.path.normpath(os.path.abspath(root))
    res = ScanResult(root=root)
    t0 = time.perf_counter()
    last_progress = 0.0
    heap: list[tuple[int, str]] = []
    root_depth = root.rstrip(os.sep).count(os.sep)
    # Iterative Tiefensuche; Größen werden nach dem Durchlauf nach oben addiert
    stack: list[str] = [root]
    own_size: dict[str, int] = {}
    own_files: dict[str, int] = {}
    while stack:
        if ctx is not None and ctx.cancelled:
            res.cancelled = True
            break
        d = stack.pop()
        res.dirs += 1
        size_here = 0
        files_here = 0
        try:
            it = os.scandir(d)
        except PermissionError:
            res.denied_count += 1
            if len(res.denied) < 200:
                res.denied.append(d)
            continue
        except OSError:
            res.denied_count += 1
            if len(res.denied) < 200:
                res.denied.append(d)
            continue
        with it:
            for e in it:
                try:
                    st = e.stat(follow_symlinks=False)
                    attrs = getattr(st, "st_file_attributes", 0)
                    if e.is_symlink() or attrs & FILE_ATTRIBUTE_REPARSE_POINT and not attrs & CLOUD_ONLY:
                        res.links_skipped += 1
                        continue
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
                        continue
                    size = st.st_size
                    if attrs & CLOUD_ONLY:
                        res.cloud_only += 1
                        res.cloud_only_size += size
                        continue
                except OSError:
                    continue
                files_here += 1
                size_here += size
                cat = ext_category(e.name)
                res.by_type[cat] = res.by_type.get(cat, 0) + size
                res.by_type_count[cat] = res.by_type_count.get(cat, 0) + 1
                if len(heap) < top_n:
                    heapq.heappush(heap, (size, e.path))
                elif size > heap[0][0]:
                    heapq.heapreplace(heap, (size, e.path))
        res.files += files_here
        res.total += size_here
        own_size[d] = size_here
        own_files[d] = files_here
        now = time.perf_counter()
        if ctx is not None and now - last_progress > progress_every:
            last_progress = now
            ctx.progress({"files": res.files, "size": res.total, "dir": d})
    # Ordnergrößen aufsummieren (tiefe Ordner werden dem Vorfahren auf TREE_DEPTH zugeschlagen)
    for d, size in own_size.items():
        depth = d.rstrip(os.sep).count(os.sep) - root_depth
        p = d
        while depth > TREE_DEPTH:
            p = os.path.dirname(p)
            depth -= 1
        while True:
            res.dir_sizes[p] = res.dir_sizes.get(p, 0) + size
            res.dir_files[p] = res.dir_files.get(p, 0) + own_files[d]
            if p == root or len(p) <= len(root):
                break
            parent = os.path.dirname(p)
            if parent == p:
                break
            p = parent
    res.largest = sorted(heap, reverse=True)
    res.seconds = time.perf_counter() - t0
    return res
