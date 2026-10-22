"""Netzwerkdiagnose: Ping, Paketverlust, DNS, Internet-Erreichbarkeit, Adapter- und WLAN-Infos.

Wichtig: Das ist KEIN Speedtest. Gemessen werden Erreichbarkeit, Antwortzeiten und
Paketverlust. Schlägt ein Test fehl (z. B. offline), wird das als Ergebnis gemeldet –
es werden nie Werte erfunden.
"""

from __future__ import annotations

import concurrent.futures
import ctypes
import logging
import re
import socket
import statistics
import struct
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field

import psutil

from corecontrol.core.platform import IS_WINDOWS, decode_console, run_hidden

log = logging.getLogger(__name__)

CONNECT_TEST_URL = "http://www.msftconnecttest.com/connecttest.txt"
CONNECT_TEST_BODY = "Microsoft Connect Test"


@dataclass
class PingStats:
    host: str
    sent: int = 0
    received: int = 0
    rtts: list[float] = field(default_factory=list)
    method: str = "icmp"
    error: str = ""

    @property
    def loss_pct(self) -> float | None:
        return None if self.sent == 0 else 100.0 * (self.sent - self.received) / self.sent

    @property
    def avg(self) -> float | None:
        return statistics.fmean(self.rtts) if self.rtts else None

    @property
    def min(self) -> float | None:
        return min(self.rtts) if self.rtts else None

    @property
    def max(self) -> float | None:
        return max(self.rtts) if self.rtts else None

    @property
    def jitter(self) -> float | None:
        if len(self.rtts) < 2:
            return None
        return statistics.fmean(abs(a - b) for a, b in zip(self.rtts[1:], self.rtts[:-1]))

    @property
    def reachable(self) -> bool:
        return self.received > 0


@dataclass
class DnsResult:
    domain: str
    ok: bool
    ms: float | None = None
    addresses: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class HttpResult:
    ok: bool
    captive_portal: bool = False
    ms: float | None = None
    error: str = ""


@dataclass
class AdapterInfo:
    name: str
    kind: str              # ethernet, wifi, virtual, loopback, other
    up: bool
    speed_mbps: int | None
    ipv4: list[str] = field(default_factory=list)
    ipv6: list[str] = field(default_factory=list)
    mac: str = ""
    gateway: list[str] = field(default_factory=list)
    dns: list[str] = field(default_factory=list)
    dhcp: bool | None = None
    description: str = ""


@dataclass
class WifiInfo:
    available: bool
    ssid: str = ""
    signal_pct: int | None = None
    rx_mbps: float | None = None
    tx_mbps: float | None = None
    channel: str = ""
    radio: str = ""
    band: str = ""
    state: str = ""
    location_denied: bool = False
    error: str = ""


@dataclass
class NetworkResult:
    started: float
    gateway: str | None = None
    gateway_ping: PingStats | None = None
    internet_pings: list[PingStats] = field(default_factory=list)
    dns: list[DnsResult] = field(default_factory=list)
    http: HttpResult | None = None
    adapters: list[AdapterInfo] = field(default_factory=list)
    wifi: WifiInfo | None = None
    any_adapter_up: bool = True
    errors: list[str] = field(default_factory=list)

    @property
    def internet_ok(self) -> bool:
        return any(p.reachable for p in self.internet_pings) or bool(self.http and self.http.ok)

    @property
    def dns_ok(self) -> bool | None:
        if not self.dns:
            return None
        return any(d.ok for d in self.dns)

    @property
    def best_internet(self) -> PingStats | None:
        ok = [p for p in self.internet_pings if p.reachable]
        return min(ok, key=lambda p: p.loss_pct or 0) if ok else (self.internet_pings[0] if self.internet_pings else None)


# ---- Ping --------------------------------------------------------------------
class _IcmpPinger:
    """Windows-ICMP über iphlpapi (keine Adminrechte, kein Konsolenprogramm)."""

    def __init__(self):
        from ctypes import wintypes

        class IP_OPTION_INFORMATION(ctypes.Structure):
            _fields_ = [("Ttl", ctypes.c_ubyte), ("Tos", ctypes.c_ubyte), ("Flags", ctypes.c_ubyte),
                        ("OptionsSize", ctypes.c_ubyte), ("OptionsData", ctypes.c_void_p)]

        class ICMP_ECHO_REPLY(ctypes.Structure):
            _fields_ = [("Address", ctypes.c_ulong), ("Status", ctypes.c_ulong), ("RoundTripTime", ctypes.c_ulong),
                        ("DataSize", ctypes.c_ushort), ("Reserved", ctypes.c_ushort), ("Data", ctypes.c_void_p),
                        ("Options", IP_OPTION_INFORMATION)]

        self.Reply = ICMP_ECHO_REPLY
        self.lib = ctypes.WinDLL("iphlpapi.dll")
        self.lib.IcmpCreateFile.restype = wintypes.HANDLE
        self.lib.IcmpSendEcho.argtypes = [wintypes.HANDLE, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ushort,
                                          ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong]
        self.lib.IcmpSendEcho.restype = ctypes.c_ulong
        self.lib.IcmpCloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.lib.IcmpCreateFile()
        if not self.handle or self.handle == wintypes.HANDLE(-1).value:
            raise OSError("IcmpCreateFile failed")

    def ping(self, ip: str, timeout_ms: int) -> float | None:
        addr = struct.unpack("<I", socket.inet_aton(ip))[0]
        data = b"CoreControl-ping" * 2
        buf_size = ctypes.sizeof(self.Reply) + len(data) + 8 + 64
        buf = ctypes.create_string_buffer(buf_size)
        n = self.lib.IcmpSendEcho(self.handle, addr, data, len(data), None, buf, buf_size, timeout_ms)
        if n == 0:
            return None
        reply = self.Reply.from_buffer_copy(buf.raw[: ctypes.sizeof(self.Reply)])
        if reply.Status != 0:
            return None
        return float(reply.RoundTripTime)

    def close(self):
        try:
            self.lib.IcmpCloseHandle(self.handle)
        except Exception:
            pass


def resolve_ipv4(host: str, timeout: float = 3.0) -> str | None:
    try:
        socket.inet_aton(host)
        return host
    except OSError:
        pass
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(socket.getaddrinfo, host, None, socket.AF_INET)
    try:
        infos = fut.result(timeout=timeout)
        return infos[0][4][0] if infos else None
    except Exception:
        return None
    finally:
        ex.shutdown(wait=False)


def _ping_subprocess(ip: str, timeout_ms: int) -> float | None:
    """Fallback außerhalb von Windows (für Entwicklung/Tests)."""
    try:
        out = subprocess.run(["ping", "-c", "1", "-W", str(max(1, timeout_ms // 1000)), ip], capture_output=True,
                             timeout=timeout_ms / 1000 + 2)
    except Exception:
        return None
    m = re.search(r"time[=<]([\d.]+)", out.stdout.decode(errors="replace"))
    return float(m.group(1)) if out.returncode == 0 and m else None


def ping_series(host: str, count: int = 10, timeout_ms: int = 1000, interval: float = 0.2, ctx=None) -> PingStats:
    stats = PingStats(host)
    ip = resolve_ipv4(host)
    if ip is None:
        stats.error = "resolve"
        stats.sent = count
        return stats
    pinger = None
    if IS_WINDOWS:
        try:
            pinger = _IcmpPinger()
        except Exception as exc:
            stats.error = f"icmp: {exc}"
    try:
        for i in range(count):
            if ctx is not None and ctx.cancelled:
                break
            stats.sent += 1
            rtt = pinger.ping(ip, timeout_ms) if pinger else _ping_subprocess(ip, timeout_ms)
            if rtt is not None:
                stats.received += 1
                stats.rtts.append(rtt)
            if i < count - 1:
                time.sleep(interval)
    finally:
        if pinger:
            pinger.close()
    return stats


# ---- DNS / HTTP -------------------------------------------------------------
def dns_check(domain: str, timeout: float = 4.0) -> DnsResult:
    t0 = time.perf_counter()
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(socket.getaddrinfo, domain, 443, 0, socket.SOCK_STREAM)
    try:
        infos = fut.result(timeout=timeout)
        ms = (time.perf_counter() - t0) * 1000
        addrs = sorted({i[4][0] for i in infos})
        return DnsResult(domain, True, ms, addrs[:4])
    except concurrent.futures.TimeoutError:
        return DnsResult(domain, False, error="timeout")
    except socket.gaierror as exc:
        return DnsResult(domain, False, error=f"gaierror {exc.errno}")
    except Exception as exc:
        return DnsResult(domain, False, error=str(exc))
    finally:
        ex.shutdown(wait=False)


def http_check(timeout: float = 6.0, opener=None) -> HttpResult:
    t0 = time.perf_counter()
    try:
        open_fn = opener or urllib.request.urlopen
        req = urllib.request.Request(CONNECT_TEST_URL, headers={"User-Agent": "CoreControl"})
        with open_fn(req, timeout=timeout) as resp:
            body = resp.read(200).decode("utf-8", errors="replace")
        ms = (time.perf_counter() - t0) * 1000
        if CONNECT_TEST_BODY in body:
            return HttpResult(True, False, ms)
        return HttpResult(False, True, ms, error="unexpected content")
    except Exception as exc:
        return HttpResult(False, False, error=str(exc)[:200])


# ---- Gateway / Adapter --------------------------------------------------------
def default_gateway() -> str | None:
    if IS_WINDOWS:
        try:
            from ctypes import wintypes

            class MIB_IPFORWARDROW(ctypes.Structure):
                _fields_ = [(n, wintypes.DWORD) for n in (
                    "dest", "mask", "policy", "next_hop", "if_index", "type", "proto", "age", "next_hop_as",
                    "m1", "m2", "m3", "m4", "m5")]

            row = MIB_IPFORWARDROW()
            dest = struct.unpack("<I", socket.inet_aton("1.1.1.1"))[0]
            rc = ctypes.WinDLL("iphlpapi.dll").GetBestRoute(dest, 0, ctypes.byref(row))
            if rc == 0 and row.next_hop:
                return socket.inet_ntoa(struct.pack("<I", row.next_hop))
        except Exception as exc:
            log.info("GetBestRoute: %s", exc)
        return None
    try:
        with open("/proc/net/route", encoding="utf-8") as fh:
            for line in fh.readlines()[1:]:
                parts = line.split()
                if len(parts) > 2 and parts[1] == "00000000" and parts[2] != "00000000":
                    return socket.inet_ntoa(struct.pack("<I", int(parts[2], 16)))
    except OSError:
        pass
    return None


def _kind(name: str, desc: str) -> str:
    n = f"{name} {desc}".lower()
    if any(x in n for x in ("loopback", "pseudo-interface")) or name == "lo":
        return "loopback"
    if any(x in n for x in ("wi-fi", "wifi", "wlan", "wireless", "802.11", "drahtlos")) or name.startswith("wl"):
        return "wifi"
    if any(x in n for x in ("virtual", "vmware", "hyper-v", "vethernet", "virtualbox", "tap-", "wintun", "wireguard",
                            "tailscale", "zerotier", "docker", "vpn", "bluetooth")) or name.startswith(("veth", "docker", "br-", "virbr")):
        return "virtual"
    if any(x in n for x in ("ethernet", "lan", "realtek", "intel(r) ethernet", "gbe", "killer e")) or name.startswith(("eth", "en")):
        return "ethernet"
    return "other"


def list_adapters() -> list[AdapterInfo]:
    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()
    wmi_info: dict[str, dict] = {}
    if IS_WINDOWS:
        try:
            from corecontrol.system import wmi

            nics = wmi.query("SELECT NetConnectionID, Description, MACAddress, Index FROM Win32_NetworkAdapter "
                             "WHERE NetConnectionID IS NOT NULL", ["NetConnectionID", "Description", "MACAddress", "Index"])
            cfgs = {r["Index"]: r for r in wmi.query(
                "SELECT Index, DefaultIPGateway, DNSServerSearchOrder, DHCPEnabled FROM Win32_NetworkAdapterConfiguration",
                ["Index", "DefaultIPGateway", "DNSServerSearchOrder", "DHCPEnabled"])}
            for n in nics:
                c = cfgs.get(n.get("Index"), {})
                wmi_info[str(n.get("NetConnectionID"))] = {
                    "description": n.get("Description") or "",
                    "gateway": [g for g in (c.get("DefaultIPGateway") or []) if g],
                    "dns": [d for d in (c.get("DNSServerSearchOrder") or []) if d],
                    "dhcp": c.get("DHCPEnabled"),
                }
        except Exception as exc:
            log.info("WMI-Netzwerkdetails nicht verfügbar: %s", exc)
    out = []
    for name, st in stats.items():
        info = wmi_info.get(name, {})
        a = AdapterInfo(name=name, kind=_kind(name, info.get("description", "")), up=bool(st.isup),
                        speed_mbps=int(st.speed) if st.speed else None, description=info.get("description", ""),
                        gateway=info.get("gateway", []), dns=info.get("dns", []), dhcp=info.get("dhcp"))
        for ad in addrs.get(name, []):
            if ad.family == socket.AF_INET:
                a.ipv4.append(ad.address)
            elif ad.family == socket.AF_INET6:
                a.ipv6.append(ad.address.split("%")[0])
            elif ad.family == getattr(psutil, "AF_LINK", -1):
                a.mac = ad.address
        out.append(a)
    order = {"ethernet": 0, "wifi": 1, "other": 2, "virtual": 3, "loopback": 4}
    out.sort(key=lambda a: (not a.up, order.get(a.kind, 9), a.name))
    return out


_WIFI_KEYS = {
    "ssid": ("ssid",),
    "signal": ("signal",),
    "rx": ("receive rate", "empfangsrate"),
    "tx": ("transmit rate", "übertragungsrate", "sendegeschwindigkeit"),
    "channel": ("channel", "kanal"),
    "radio": ("radio type", "funktyp"),
    "band": ("band",),
    "state": ("state", "status"),
}


def parse_netsh_wlan(text: str) -> WifiInfo:
    info = WifiInfo(available=False)
    low = text.lower()
    if ("location" in low and "permission" in low) or "standortberechtigung" in low or "standortdienste" in low:
        info.location_denied = True
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        k, v = key.strip().lower(), val.strip()
        if k.startswith("bssid") or k.startswith("ap bssid"):
            continue
        for field_name, prefixes in _WIFI_KEYS.items():
            if any(k.startswith(p) for p in prefixes):
                if field_name == "ssid" and not info.ssid:
                    info.ssid = v
                elif field_name == "signal":
                    m = re.search(r"(\d+)", v)
                    info.signal_pct = int(m.group(1)) if m else None
                elif field_name in ("rx", "tx"):
                    try:
                        setattr(info, f"{field_name}_mbps", float(v.replace(",", ".")))
                    except ValueError:
                        pass
                elif field_name == "channel" and not info.channel:
                    info.channel = v
                elif field_name == "radio":
                    info.radio = v
                elif field_name == "band":
                    info.band = v
                elif field_name == "state" and not info.state:
                    info.state = v
                break
    info.available = bool(info.ssid or info.signal_pct is not None)
    return info


def wifi_info() -> WifiInfo:
    if not IS_WINDOWS:
        return WifiInfo(available=False, error="not_windows")
    res = run_hidden(["netsh", "wlan", "show", "interfaces"], timeout=8)
    if res is None:
        return WifiInfo(available=False, error="netsh")
    text = decode_console(res.stdout) + decode_console(res.stderr)
    return parse_netsh_wlan(text)


# ---- Gesamttest ---------------------------------------------------------------
def run_network_test(targets: list[str], dns_domains: list[str], ping_count: int = 10, ctx=None,
                     progress=None) -> NetworkResult:
    r = NetworkResult(started=time.time())

    def step(name):
        if progress:
            progress(name)

    step("adapters")
    try:
        r.adapters = list_adapters()
        r.any_adapter_up = any(a.up and a.kind in ("ethernet", "wifi", "other") and a.ipv4 for a in r.adapters)
    except Exception as exc:
        r.errors.append(f"adapters: {exc}")
    try:
        if any(a.kind == "wifi" and a.up for a in r.adapters):
            r.wifi = wifi_info()
    except Exception as exc:
        r.errors.append(f"wifi: {exc}")
    step("gateway")
    r.gateway = default_gateway()
    if r.gateway:
        r.gateway_ping = ping_series(r.gateway, ping_count, 1000, 0.15, ctx)
    step("internet")
    for t in targets[:3]:
        if ctx is not None and ctx.cancelled:
            break
        r.internet_pings.append(ping_series(t, ping_count, 1500, 0.2, ctx))
    step("dns")
    for d in dns_domains[:5]:
        r.dns.append(dns_check(d))
    step("http")
    r.http = http_check()
    return r
