#! /usr/bin/env python3
# -*- coding: utf-8 -*-
"""
One place for the settings both containers touch (P13.30).

The bot reads these files and the dashboard writes them. Each side used to carry its own copy
of the defaults and its own save code, and they drifted: saving consolidation from the UI
rebuilt the file from the dashboard's (shorter) default dict and silently dropped
`skipResources` / `respectDestCap`; every save rebuilt the file from defaults, so a field the
form did not send was reset.

Here a setting is declared once — type, default, limits — and:
  • load(name)            → defaults overlaid with what is stored (unknown stored keys kept);
  • update(name, changes) → merges `changes` onto what is stored: a key that is not sent keeps
                            its stored value, a value that cannot be read is ignored, limits
                            and the cross-field rules are applied, the file is written atomically;
  • schema(name)          → {key: type} for the bot's config validation.

Mounted in both containers (bot: function dir, dashboard: /gui). Pure stdlib, no project imports.
"""

import json
import os

LOGS_DIR = "/tmp/ikalogs/"


def _bool(default):
    return {"type": bool, "default": default}


def _int(default, lo=None, hi=None):
    return {"type": int, "default": default, "min": lo, "max": hi}


def _float(default, lo=None, hi=None):
    return {"type": float, "default": default, "min": lo, "max": hi}


def _units():
    """A unit loadout {unitId: quantity}; only positive quantities are kept."""
    return {"type": dict, "default": {}}


def _env_scan_radius():
    try:
        return max(1, min(60, int(os.getenv("WORLD_SCAN_RADIUS", 10))))
    except ValueError:
        return 10


def _text(default=""):
    return {"type": str, "default": default}


def _choice(default, choices):
    return {"type": str, "default": default, "choices": tuple(choices)}


def _str_list():
    return {"type": list, "default": []}


def _wine_rules(s):
    s["targetHours"] = max(s["targetHours"], s["thresholdHours"])
    s["donorReserveHours"] = max(s["donorReserveHours"], s["targetHours"])


def _wine_buy_rules(s):
    s["refillBelowHours"] = min(s["refillBelowHours"], s["targetHours"])
    s["criticalHours"] = min(s["criticalHours"], s["refillBelowHours"])


SPECS = {
    "consolidate": {
        "file": "consolidate_settings.json",
        "fields": {
            "enabled":        _bool(False),
            "destCityId":     _text(""),
            "destCityName":   _text(""),
            "intervalHours":  _int(6, 1, 48),
            "minSendTotal":   _int(1000, 0),
            "shipType":       _choice("transporters", ("transporters", "freighters", "both")),
            "ignoreCityIds":  _str_list(),     # source cities never drained by consolidation
            "skipResources":  _str_list(),     # resource names never sent, e.g. ["Wine"]
            "respectDestCap": _bool(True),     # never overflow the destination warehouse
        },
    },
    "wine": {
        "file": "wine_settings.json",
        "fields": {
            # on by default: a wine-out costs population, so the safe default is to balance
            "enabled":              _bool(True),
            "thresholdHours":       _int(12, 1, 168),    # act when the runway drops below this
            "targetHours":          _int(48, 1, 336),    # top the city up to this many hours
            "donorReserveHours":    _int(96, 1, 720),    # a non-producer lends only above this
            "reserveShipsFromFarm": _bool(True),         # P11.10: keep trade ships free for wine
            "reserveShips":         _int(5, 0, 100),
        },
        "rules": _wine_rules,
    },
    "wine_buy": {
        "file": "wine_buy_settings.json",
        "fields": {
            "enabled":          _bool(False),            # opt-in: the only feature that spends gold
            "dryRun":           _bool(True),             # start safe: log the plan, buy nothing
            "targetHours":      _int(72, 1, 336),
            "refillBelowHours": _int(48, 1, 336),        # deadband low-water mark
            "criticalHours":    _int(6, 1, 336),         # below this the buyer may use reserved ships
            "maxPricePerUnit":  _int(15, 1, 10000),
            "goldFloor":        _int(100000, 0),
            "maxSpendPerCycle": _int(200000, 0),
            "ignoreCityIds":    _str_list(),
        },
        "rules": _wine_buy_rules,
    },
    "spy_build": {
        "file": "spy_build_settings.json",
        "fields": {
            "enabled":             _bool(True),
            "dryRun":              _bool(True),
            "targetPerCity":       _int(0, 0, 1000),     # 0 = fill the safehouse
            "goldFloor":           _int(200000, 0, 10 ** 10),
            "crystalFloor":        _int(0, 0, 10 ** 8),  # 0 on purpose: the 5k buffer is for spies
            "maxPerPass":          _int(60, 1, 1000),
            "intervalMinutes":     _int(60, 15, 24 * 60),
            "maxCountsAgeMinutes": _int(30, 5, 240),
        },
    },
    # ── P13.30 (rest, 2026-11-16): farm, espionage, world scan, alerts ──────────────────────
    "farm": {
        "file": "farm_settings.json",
        "fields": {
            "army":                   _units(),           # empty = every troop in the origin
            "fleet":                  _units(),           # blockade loadout; empty = whole fleet
            "spyAgents":              _int(1, 1, 99),
            "shipReserveEnabled":     _bool(True),
            "reserveHorizonMin":      _int(45, 0, 720),
            "earlyRespyEnabled":      _bool(True),
            "earlyReportMaxAgeMins":  _int(120, 10),      # a fleet target's early report is stale after this
            "spyFreshnessHours":      _float(24, 0),      # 0 = never re-scout a safe target on age
            "lootCapPerRaid":         _int(0, 0),         # 0 = learn it from the real returns
            "fleetDemoteAfterSweeps": _int(3, 0),         # 0 = a fleet target stays one for ever
            "minShipFraction":        _float(0.5, 0, 1),
            "emptyReturnStrikes":     _int(2, 0),         # empty returns in a row that pause a target; 0 = never
        },
    },
    "espionage": {
        "file": "espionage_settings.json",
        "fields": {
            "processingEnabled":      _bool(True),
            "garrisonThresholdTotal": _int(50000, 0),
            "minLootTotal":           _int(50000, 0),
            "ignoreExpiryDays":       _int(60, 1, 365),   # a temporary ignore lifts after this
            "ignorePermanentAfter":   _int(4, 1, 20),     # strikes before an ignore is permanent
            "missionRetentionDays":   _int(30, 1),
        },
    },
    "world_scan": {
        "file": "world_scan_settings.json",
        "fields": {
            "enabled": _bool(True),
            "radius":  _int(_env_scan_radius, 1, 60),     # default: WORLD_SCAN_RADIUS env, else 10
        },
    },
    "alerts": {
        "file": "alert_settings.json",
        "fields": {
            "incomingEnabled": _bool(True),
            "returnEnabled":   _bool(True),
            "checkMinutes":    _int(0, 0, 120),           # 0 = only on the hourly cycle
        },
    },
    "alert_thresholds": {                                 # dashboard only (wine / storage alerts)
        "file": "alert_thresholds.json",
        "fields": {
            "wineWarning":    _int(8, 0),
            "wineCritical":   _int(2, 0),
            "storageWarning": _int(95, 0),
        },
    },
}


def path_of(name):
    return os.path.join(LOGS_DIR, SPECS[name]["file"])


def _default(field):
    d = field["default"]
    if callable(d):
        return d()
    return list(d) if isinstance(d, list) else dict(d) if isinstance(d, dict) else d


def defaults(name):
    return {k: _default(f) for k, f in SPECS[name]["fields"].items()}


def value(name, key, raw, default=None):
    """One raw stored value read as its declared field (type and limits); the field's default
    — or `default` when given — if it cannot be read."""
    field = SPECS[name]["fields"][key]
    v = _coerce(field, raw) if raw is not None else None
    if v is not None:
        return v
    return _default(field) if default is None else default


def schema(name):
    """{key: type} — what the bot's validate_configs expects in the file."""
    return {k: f["type"] for k, f in SPECS[name]["fields"].items()}


def _coerce(field, value):
    """The value as the field's type, within its limits — or None if it cannot be read."""
    kind = field["type"]
    try:
        if kind is bool:
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on")
            return bool(value)
        if kind is int or kind is float:
            if isinstance(value, bool):
                return None
            v = kind(value)
            if v != v:                       # NaN
                return None
            if field.get("min") is not None:
                v = max(field["min"], v)
            if field.get("max") is not None:
                v = min(field["max"], v)
            return v
        if kind is dict:
            if value is None:
                return {}
            if not isinstance(value, dict):
                return None
            return {str(k): int(n) for k, n in value.items() if int(n) > 0}
        if kind is list:
            if value is None:
                return []
            if not isinstance(value, (list, tuple)):
                return None
            return [str(x) for x in value]
        v = str(value if value is not None else "")
        if field.get("choices") and v not in field["choices"]:
            return None
        return v
    except (TypeError, ValueError):
        return None


def _read(path):
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load(name, path=None):
    """Current settings: every declared key present (stored value if it is usable, else the
    default); stored keys this registry does not know are passed through untouched."""
    spec = SPECS[name]
    stored = _read(path or path_of(name))
    out = dict(stored)
    for key, field in spec["fields"].items():
        value = _coerce(field, stored[key]) if key in stored else None
        out[key] = value if value is not None else defaults(name)[key]
    if spec.get("rules"):
        spec["rules"](out)
    return out


def update(name, changes, path=None):
    """Merge `changes` onto the stored settings and save. Only declared keys are taken; a key
    that is absent — or whose value cannot be read — keeps what is stored."""
    spec = SPECS[name]
    path = path or path_of(name)
    current = load(name, path)
    for key, field in spec["fields"].items():
        if key not in (changes or {}):
            continue
        value = _coerce(field, changes[key])
        if value is not None:
            current[key] = value
    if spec.get("rules"):
        spec["rules"](current)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp, "w") as f:
        json.dump(current, f, indent=2)
    os.replace(tmp, path)
    return current
