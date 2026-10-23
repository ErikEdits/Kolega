"""Windows-Ereignisprotokolle lesen und verständlich zusammenfassen.

Gelesen werden die Protokolle „System“ und „Anwendung“ (ohne Adminrechte möglich):
alle Fehler/kritischen Ereignisse sowie ausgewählte aussagekräftige Warnungen.
Bekannte Ereignisse werden Kategorien mit Erklärung zugeordnet. Unbekannte
Ereignisse werden nur gezählt und mit Originaltext angezeigt – es wird keine
Bedeutung erfunden.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from corecontrol.core.platform import IS_WINDOWS

log = logging.getLogger(__name__)

NS = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}

# Warnungen (Level 3), die trotzdem gelesen werden, weil sie aussagekräftig sind
INTERESTING_WARNING_IDS = (37, 4101, 153, 17, 19, 47, 129, 2004, 1014, 51)


@dataclass
class EventRecord:
    channel: str
    provider: str
    event_id: int
    level: int
    time: datetime
    data: dict[str, str] = field(default_factory=dict)
    data_list: list[str] = field(default_factory=list)
    message: str = ""


# (Provider in Kleinbuchstaben, Event-IDs (leer = alle), Kategorie, Schweregrad)
RULES: list[tuple[tuple[str, ...], tuple[int, ...], str, str]] = [
    (("microsoft-windows-wer-systemerrorreporting", "bugcheck"), (1001,), "bluescreen", "critical"),
    (("microsoft-windows-kernel-power",), (41,), "unexpected_shutdown", "warning"),
    (("eventlog",), (6008,), "unexpected_shutdown_6008", "warning"),
    (("microsoft-windows-whea-logger",), (1, 18, 20, 46), "whea_fatal", "critical"),
    (("microsoft-windows-whea-logger",), (17, 19, 47), "whea_corrected", "warning"),
    (("microsoft-windows-whea-logger",), (), "whea_other", "warning"),
    (("disk",), (7,), "disk_bad_block", "critical"),
    (("disk",), (11, 15), "disk_controller", "critical"),
    (("disk",), (51, 153), "disk_io_retry", "warning"),
    (("ntfs", "microsoft-windows-ntfs"), (55,), "ntfs_corruption", "critical"),
    (("ntfs", "microsoft-windows-ntfs"), (98, 140), "ntfs_check", "warning"),
    (("storahci", "stornvme", "iastora", "iastorac", "iastorv", "amd_sata", "storport"), (129, 11, 153), "storage_reset", "warning"),
    (("display",), (4101,), "gpu_tdr", "warning"),
    (("nvlddmkm",), (), "gpu_driver_nvidia", "warning"),
    (("amdkmdag", "amdkmdap", "amdwddmg"), (), "gpu_driver_amd", "warning"),
    (("application error",), (1000,), "app_crash", "info"),
    (("application hang",), (1002,), "app_hang", "info"),
    ((".net runtime",), (1026,), "app_crash_dotnet", "info"),
    (("service control manager",), (7000, 7001, 7009, 7011, 7022, 7023, 7024, 7031, 7034, 7043), "service_failure", "info"),
    (("microsoft-windows-kernel-processor-power",), (37,), "cpu_throttled", "warning"),
    (("microsoft-windows-resource-exhaustion-detector",), (2004,), "low_memory", "warning"),
    (("microsoft-windows-dns-client",), (1014,), "dns_timeout", "info"),
    (("microsoft-windows-windowsupdateclient",), (20, 31), "update_failed", "warning"),
    (("microsoft-windows-kernel-pnp",), (219, 411), "driver_load_failed", "info"),
    (("microsoft-windows-distributedcom", "dcom"), (10016, 10010, 10005), "harmless_dcom", "ok"),
]

CATEGORY_GROUP = {
    "bluescreen": "stability", "unexpected_shutdown": "stability", "unexpected_shutdown_6008": "stability",
    "whea_fatal": "hardware", "whea_corrected": "hardware", "whea_other": "hardware",
    "disk_bad_block": "storage", "disk_controller": "storage", "disk_io_retry": "storage",
    "ntfs_corruption": "storage", "ntfs_check": "storage", "storage_reset": "storage",
    "gpu_tdr": "gpu", "gpu_driver_nvidia": "gpu", "gpu_driver_amd": "gpu",
    "app_crash": "software", "app_hang": "software", "app_crash_dotnet": "software",
    "service_failure": "software", "update_failed": "software", "driver_load_failed": "drivers",
    "cpu_throttled": "thermal", "low_memory": "memory", "dns_timeout": "network",
    "harmless_dcom": "harmless", "other": "other",
}

# Häufige Bluescreen-Codes → Bereich, der am häufigsten betroffen ist (nur Hinweis, keine Diagnose)
BUGCHECKS: dict[int, tuple[str, str]] = {
    0x0A: ("IRQL_NOT_LESS_OR_EQUAL", "driver"),
    0x1A: ("MEMORY_MANAGEMENT", "ram"),
    0x1E: ("KMODE_EXCEPTION_NOT_HANDLED", "driver"),
    0x3B: ("SYSTEM_SERVICE_EXCEPTION", "driver"),
    0x50: ("PAGE_FAULT_IN_NONPAGED_AREA", "ram_driver"),
    0x7A: ("KERNEL_DATA_INPAGE_ERROR", "disk"),
    0x7E: ("SYSTEM_THREAD_EXCEPTION_NOT_HANDLED", "driver"),
    0x7F: ("UNEXPECTED_KERNEL_MODE_TRAP", "hardware"),
    0x9F: ("DRIVER_POWER_STATE_FAILURE", "driver_power"),
    0xC2: ("BAD_POOL_CALLER", "driver"),
    0x19: ("BAD_POOL_HEADER", "driver_ram"),
    0xD1: ("DRIVER_IRQL_NOT_LESS_OR_EQUAL", "driver"),
    0xEF: ("CRITICAL_PROCESS_DIED", "system_files"),
    0xF4: ("CRITICAL_OBJECT_TERMINATION", "disk"),
    0x101: ("CLOCK_WATCHDOG_TIMEOUT", "cpu"),
    0x109: ("CRITICAL_STRUCTURE_CORRUPTION", "ram_driver"),
    0x113: ("VIDEO_DXGKRNL_FATAL_ERROR", "gpu"),
    0x116: ("VIDEO_TDR_FAILURE", "gpu"),
    0x117: ("VIDEO_TDR_TIMEOUT_DETECTED", "gpu"),
    0x119: ("VIDEO_SCHEDULER_INTERNAL_ERROR", "gpu"),
    0x124: ("WHEA_UNCORRECTABLE_ERROR", "hardware"),
    0x133: ("DPC_WATCHDOG_VIOLATION", "driver_storage"),
    0x139: ("KERNEL_SECURITY_CHECK_FAILURE", "driver_ram"),
    0x154: ("UNEXPECTED_STORE_EXCEPTION", "disk"),
    0x1E0: ("ATTEMPTED_SWITCH_FROM_DPC", "driver"),
    0xC000021A: ("STATUS_SYSTEM_PROCESS_TERMINATED", "system_files"),
}


@dataclass
class EventGroup:
    category: str
    severity: str
    count: int = 0
    first: datetime | None = None
    last: datetime | None = None
    examples: list[EventRecord] = field(default_factory=list)
    details: Counter = field(default_factory=Counter)  # z. B. Programmnamen, Bluescreen-Codes
    provider: str = ""
    event_id: int = 0

    @property
    def group(self) -> str:
        return CATEGORY_GROUP.get(self.category, "other")


@dataclass
class EventSummary:
    days: int
    groups: list[EventGroup] = field(default_factory=list)
    total: int = 0
    read_errors: list[str] = field(default_factory=list)
    available: bool = True

    def get(self, category: str) -> EventGroup | None:
        return next((g for g in self.groups if g.category == category), None)


def classify(rec: EventRecord) -> tuple[str, str]:
    prov = rec.provider.lower()
    for providers, ids, category, severity in RULES:
        if prov in providers and (not ids or rec.event_id in ids):
            return category, severity
    sev = "warning" if rec.level == 1 else "info"
    return "other", sev


_HEX = re.compile(r"0x[0-9a-fA-F]+")


def bugcheck_code(rec: EventRecord) -> int | None:
    """Bluescreen-Code aus Event 1001 (WER) oder Kernel-Power 41 lesen."""
    if "BugcheckCode" in rec.data:
        try:
            v = int(rec.data["BugcheckCode"])
            return v or None
        except ValueError:
            return None
    candidates = [rec.data.get("param1", "")] + rec.data_list[:1] + [rec.message]
    for c in candidates:
        m = _HEX.search(c or "")
        if m:
            try:
                return int(m.group(0), 16) or None
            except ValueError:
                pass
    return None


def detail_key(category: str, rec: EventRecord) -> str | None:
    if category in ("app_crash", "app_hang"):
        return (rec.data_list[0] if rec.data_list else rec.data.get("param1", "")) or None
    if category == "app_crash_dotnet":
        m = re.search(r"(?:Application|Anwendung):\s*([^\r\n]+)", rec.message or "")
        return m.group(1).strip() if m else None
    if category == "service_failure":
        return rec.data.get("param1") or (rec.data_list[0] if rec.data_list else None)
    if category in ("bluescreen", "unexpected_shutdown"):
        code = bugcheck_code(rec)
        return f"0x{code:08X}" if code else None
    return None


def summarize(records: list[EventRecord], days: int) -> EventSummary:
    groups: dict[tuple[str, str, int], EventGroup] = {}
    for rec in records:
        category, sev = classify(rec)
        key = (category, rec.provider if category == "other" else "", rec.event_id if category == "other" else 0)
        g = groups.get(key)
        if g is None:
            g = groups[key] = EventGroup(category, sev, provider=rec.provider, event_id=rec.event_id)
        g.count += 1
        g.first = min(g.first, rec.time) if g.first else rec.time
        g.last = max(g.last, rec.time) if g.last else rec.time
        if len(g.examples) < 5:
            g.examples.append(rec)
        d = detail_key(category, rec)
        if d:
            g.details[d] += 1
    # Kernel-Power 41 mit Bluescreen-Code ist bereits ein Bluescreen-Hinweis
    order = {"critical": 0, "warning": 1, "info": 2, "ok": 3}
    out = sorted(groups.values(), key=lambda g: (order.get(g.severity, 9), -g.count))
    return EventSummary(days=days, groups=out, total=len(records))


# ---- Lesen (Windows) ----------------------------------------------------------
def parse_event_xml(xml: str, channel: str = "") -> EventRecord | None:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    sys_el = root.find("e:System", NS)
    if sys_el is None:
        return None
    prov = sys_el.find("e:Provider", NS)
    provider = (prov.get("Name") or prov.get("EventSourceName") or "") if prov is not None else ""
    eid_el = sys_el.find("e:EventID", NS)
    lvl_el = sys_el.find("e:Level", NS)
    tc = sys_el.find("e:TimeCreated", NS)
    ch = sys_el.find("e:Channel", NS)
    try:
        eid = int(eid_el.text) if eid_el is not None and eid_el.text else 0
        # Bei manchen Quellen enthält die ID noch Qualifizierer-Bits
        eid &= 0xFFFF
    except ValueError:
        eid = 0
    try:
        level = int(lvl_el.text) if lvl_el is not None and lvl_el.text else 0
    except ValueError:
        level = 0
    t = _parse_time(tc.get("SystemTime") if tc is not None else None)
    data: dict[str, str] = {}
    data_list: list[str] = []
    ed = root.find("e:EventData", NS)
    if ed is not None:
        for d in ed.findall("e:Data", NS):
            val = (d.text or "").strip()
            name = d.get("Name")
            if name:
                data[name] = val
            data_list.append(val)
    ud = root.find("e:UserData", NS)
    if ud is not None:
        for el in ud.iter():
            if el is not ud and el.text and el.text.strip() and len(list(el)) == 0:
                tag = el.tag.split("}")[-1]
                data.setdefault(tag, el.text.strip())
                data_list.append(el.text.strip())
    return EventRecord(channel=(ch.text if ch is not None and ch.text else channel), provider=provider, event_id=eid,
                       level=level, time=t, data=data, data_list=data_list)


def _parse_time(value: str | None) -> datetime:
    if not value:
        return datetime.now()
    v = value.rstrip("Z")
    if "." in v:
        head, frac = v.split(".", 1)
        v = f"{head}.{frac[:6]}"
    for f in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(v, f).replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        except ValueError:
            continue
    return datetime.now()


def build_query(days: int) -> str:
    ms = int(days * 86400 * 1000)
    ids = " or ".join(f"EventID={i}" for i in INTERESTING_WARNING_IDS)
    return f"*[System[(Level=1 or Level=2 or ({ids})) and TimeCreated[timediff(@SystemTime) <= {ms}]]]"


def read_events(days: int = 30, max_per_channel: int = 1500, with_messages: bool = True, ctx=None) -> EventSummary:
    if not IS_WINDOWS:
        return EventSummary(days=days, available=False, read_errors=["not_windows"])
    import pywintypes
    import win32evtlog

    records: list[EventRecord] = []
    errors: list[str] = []
    query = build_query(days)
    meta_cache: dict[str, object] = {}
    for channel in ("System", "Application"):
        if ctx is not None and getattr(ctx, "cancelled", False):
            break
        try:
            h = win32evtlog.EvtQuery(channel, win32evtlog.EvtQueryChannelPath | win32evtlog.EvtQueryReverseDirection, query)
        except pywintypes.error as exc:
            errors.append(f"{channel}: {exc.strerror}")
            continue
        count = 0
        while count < max_per_channel:
            try:
                batch = win32evtlog.EvtNext(h, 100, -1, 0)
            except pywintypes.error as exc:
                if exc.winerror != 259:  # ERROR_NO_MORE_ITEMS
                    errors.append(f"{channel}: {exc.strerror}")
                break
            if not batch:
                break
            for ev in batch:
                try:
                    xml = win32evtlog.EvtRender(ev, win32evtlog.EvtRenderEventXml)
                except pywintypes.error:
                    continue
                rec = parse_event_xml(xml, channel)
                if rec is None:
                    continue
                if with_messages:
                    rec.message = _format_message(win32evtlog, ev, rec.provider, meta_cache)
                records.append(rec)
                count += 1
    summary = summarize(records, days)
    summary.read_errors = errors
    return summary


def _format_message(win32evtlog, ev, provider: str, cache: dict) -> str:
    try:
        meta = cache.get(provider)
        if meta is None and provider not in cache:
            try:
                meta = win32evtlog.EvtOpenPublisherMetadata(provider)
            except Exception:
                meta = None
            cache[provider] = meta
        if meta is None:
            return ""
        msg = win32evtlog.EvtFormatMessage(meta, ev, win32evtlog.EvtFormatMessageEvent)
        return (msg or "").strip()[:2000]
    except Exception:
        return ""


def window_start(days: int) -> datetime:
    return datetime.now() - timedelta(days=days)
