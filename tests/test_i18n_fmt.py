"""Übersetzungen vollständig, Platzhalter gleich; Formatierung sprachabhängig."""

import ast
import os
import re
import string

from corecontrol import i18n
from corecontrol.core import fmt
from corecontrol.i18n import T, de, en, tr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _placeholders(v) -> set:
    texts = v if isinstance(v, (list, tuple)) else [v]
    out = set()
    for t in texts:
        out |= {f[1] for f in string.Formatter().parse(t) if f[1]}
    return out


def test_same_keys_in_both_languages():
    assert set(de.STRINGS) == set(en.STRINGS)


def test_same_placeholders_and_types():
    for k in de.STRINGS:
        assert type(de.STRINGS[k]) is type(en.STRINGS[k]), k
        assert _placeholders(de.STRINGS[k]) == _placeholders(en.STRINGS[k]), k


def test_no_empty_texts():
    for lang in (de.STRINGS, en.STRINGS):
        for k, v in lang.items():
            assert v, k


def _literal_keys_in_source() -> set:
    keys = set()
    for base, _dirs, files in os.walk(os.path.join(ROOT, "corecontrol")):
        for f in files:
            if not f.endswith(".py") or base.endswith("i18n"):
                continue
            tree = ast.parse(open(os.path.join(base, f), encoding="utf-8").read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                    args = node.args
                    idx = {"tr": 0, "T": 0, "tr_list": 0, "label": 0, "button": 0, "bind_text": 1, "Card": 0,
                           "SettingRow": 0, "EmptyState": 1, "tool_button": 1, "PageHeader": 0}.get(name)
                    if idx is not None and len(args) > idx and isinstance(args[idx], ast.Constant) \
                            and isinstance(args[idx].value, str) and re.fullmatch(r"[a-z_0-9]+(\.[a-zA-Z_0-9]+)+", args[idx].value):
                        keys.add(args[idx].value)
                    if name == "make" and len(args) >= 2 and isinstance(args[1], ast.Constant):
                        keys.add(f"diag.{args[1].value}.title")
                        keys.add(f"diag.{args[1].value}.detected")
    return keys


def test_all_literal_keys_exist():
    missing = sorted(k for k in _literal_keys_in_source() if k not in de.STRINGS)
    assert missing == []


def test_missing_key_returns_key_instead_of_crashing():
    assert tr("gibt.es.nicht") == "gibt.es.nicht"


def test_bad_params_do_not_crash():
    assert "{n}" in tr("banner.more")  # Platzhalter fehlt -> Rohtext


def test_lazy_text_follows_language():
    t = T("common.na")
    i18n.set_language("de")
    assert str(t) == "Nicht verfügbar"
    i18n.set_language("en")
    assert str(t) == "Not available"


def test_number_formatting():
    assert fmt.number(1234.5, 1, "de") == "1.234,5"
    assert fmt.number(1234.5, 1, "en") == "1,234.5"
    i18n.set_language("de")
    assert fmt.bytes_(1536) == "1,5 KB"
    assert fmt.bytes_(0) == "0 B"
    assert fmt.bytes_(None) == "Nicht verfügbar"
    assert fmt.temp(None) == "Nicht verfügbar"
    assert fmt.temp(54.4) == "54 °C"
    assert fmt.rate_bits(125_000) == "1,0 Mbit/s"
    assert fmt.mhz(3600) == "3,60 GHz"


def test_lazy_quantities_reformat_on_language_change():
    t = T("diag.ram_ok.detected", pct=fmt.Pct(42.0), used=fmt.Bytes(1.5 * 1024**3), total=fmt.Bytes(16 * 1024**3))
    i18n.set_language("de")
    assert "1,5 GB" in str(t)
    i18n.set_language("en")
    assert "1.5 GB" in str(t)
