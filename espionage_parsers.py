#! /usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pure HTML/text parsers for espionage (P5.6 split out of espionage_manager). No game I/O,
no file/SQLite access — just turning game HTML into structured data. Imported (re-exported)
by espionage_manager so existing `from espionage_manager import _parse_x` call sites and the
parser tests keep working unchanged.
"""

import time

from empire_utils import logger


def _parse_safehouse_page(html, city_name):
    """
    Parse spy counts from the full safehouse page HTML (non-AJAX).
    Strips HTML tags first so regex works on clean text regardless of markup.
    Returns a dict with keys: available, inDefense, inTraining, deployed, trainable.
    """
    import re

    counts = {
        "available":  None,
        "inDefense":  None,
        "inTraining": None,
        "deployed":   None,
        "trainable":  None,
    }

    if not html:
        return counts

    # Strip tags and decode HTML entities for reliable matching
    text = re.sub(r'<[^>]+>', ' ', html)
    text = text.replace('&nbsp;', ' ').replace(' ', ' ')
    text = re.sub(r'\s+', ' ', text)

    # "24 estão em uso" → deployed on missions
    m = re.search(r'(\d+)\s+est[aã]o?\s+em\s+uso', text, re.IGNORECASE)
    if m:
        counts["deployed"] = int(m.group(1))

    # "15 estão a trabalhar na defesa" → defense assignment
    m = re.search(r'(\d+)\s+est[aã]o?\s+a\s+trabalhar\s+na\s+defesa', text, re.IGNORECASE)
    if m:
        counts["inDefense"] = int(m.group(1))

    # "1 esperam por treino" → agents in training queue
    m = re.search(r'(\d+)\s+esperam?\s+por\s+treino', text, re.IGNORECASE)
    if m:
        counts["inTraining"] = int(m.group(1))

    # "Podes treinar 40" → remaining capacity
    m = re.search(r'[Pp]odes\s+treinar\s+(\d+)', text, re.IGNORECASE)
    if m:
        counts["trainable"] = int(m.group(1))

    # "X disponíveis" → stationed agents (if shown directly)
    m = re.search(r'(\d+)\s+(?:espi[oõ]es?\s+)?dispon[ií]veis?', text, re.IGNORECASE)
    if m:
        counts["available"] = int(m.group(1))

    # derive available from known values when not shown directly:
    # available = total_trained - inDefense - deployed - inTraining
    # total_trained is not directly available; compute when all three are known
    # O HTML do jogo não tem linha explícita de "disponíveis" — inDefense é o campo correcto
    # para espiões livres ("a trabalhar na defesa" = na cidade, disponíveis para dispatch)

    # log relevant text snippet when inDefense or deployed are still missing
    if counts["inDefense"] is None or counts["deployed"] is None:
        keywords = ("treino", "defesa", "uso", "dispon", "espião", "espioes", "agente")
        snippet = " | ".join(
            seg.strip() for seg in re.split(r'[.!?\n]', text)
            if any(kw in seg.lower() for kw in keywords)
        )[:500]
        logger.warning("[espionage] safehouse %s: faltam inDefense/deployed. Texto relevante: %s",
                       city_name, snippet or "(nenhum)")

    return counts


def _parse_active_spy_missions(html):
    """
    Parse active spy deployments from safehouse overview HTML.
    Returns list of {cityId, x, y, cityName, state, countdown_secs}.
    state: 'WAITING_AT_CITY' | 'TRAVELING'
    """
    import re
    if not html:
        return []

    STATIONED = re.compile(r'esperam\s+novas\s+ordens', re.IGNORECASE)
    TRAVELING = re.compile(r'est[aá]\s+a\s+caminho', re.IGNORECASE)
    COUNTDOWN = re.compile(
        r'Chegada\s*(?:(\d+)\s*h\s*)?(?:(\d+)\s*m\s*)?(?:(\d+)\s*s)?',
        re.IGNORECASE
    )

    # Split into TR-level chunks; fall back to DIV if no TR boundaries
    chunks = re.split(r'(?=<tr[\s>])', html, flags=re.IGNORECASE)
    if len(chunks) <= 2:
        chunks = re.split(r'(?=<div[\s>])', html, flags=re.IGNORECASE)

    results = []
    for chunk in chunks:
        is_stationed = bool(STATIONED.search(chunk))
        is_traveling = bool(TRAVELING.search(chunk))
        if not is_stationed and not is_traveling:
            continue

        state = 'WAITING_AT_CITY' if is_stationed else 'TRAVELING'

        x = y = city_id = city_name = None
        xm = re.search(r'xcoord=(\d+)', chunk, re.IGNORECASE)
        ym = re.search(r'ycoord=(\d+)', chunk, re.IGNORECASE)
        cm = re.search(r'selectCity=(\d+)', chunk, re.IGNORECASE)
        if xm:
            x = int(xm.group(1))
        if ym:
            y = int(ym.group(1))
        if cm:
            city_id = cm.group(1)

        if x is None and city_id is None:
            logger.debug("[espionage] activa: chunk sem coords — a saltar")
            continue

        link_m = re.search(
            r'<a\s[^>]*(?:xcoord|selectCity)[^>]*>(.*?)</a>',
            chunk, re.DOTALL | re.IGNORECASE
        )
        if link_m:
            inner = re.sub(r'<br\s*/?>', ' ', link_m.group(1), flags=re.IGNORECASE)
            inner = re.sub(r'<[^>]+>', '', inner)
            inner = re.sub(r'\s+', ' ', inner.replace('&nbsp;', ' ')).strip()
            bracket = re.search(r'\[\s*\d+\s*:\s*\d+\s*\]', inner)
            city_name = inner[:bracket.start()].strip() if bracket else inner or None

        countdown_secs = None
        if is_traveling:
            cm2 = COUNTDOWN.search(chunk)
            if cm2 and any(cm2.groups()):
                h    = int(cm2.group(1) or 0)
                mins = int(cm2.group(2) or 0)
                secs = int(cm2.group(3) or 0)
                total = h * 3600 + mins * 60 + secs
                countdown_secs = total if total > 0 else None

        results.append({
            "cityId":         city_id,
            "x":              x,
            "y":              y,
            "cityName":       city_name,
            "state":          state,
            "countdown_secs": countdown_secs,
        })
        logger.debug("[espionage] activa: %s x=%s y=%s cityId=%s countdown=%s",
                     state, x, y, city_id, countdown_secs)

    if results:
        logger.info("[espionage] %d espião(ões) activo(s) detectado(s) no safehouse", len(results))
    return results


def _parse_arrival_countdown(html):
    """
    Parse 'Chegada Xh Ym Zs' countdown from spyMissions HTML.
    Returns seconds as int, or None if not found.
    Formats seen: '02m 56s', '1h 23m', '45s', '1h 23m 10s'
    """
    import re
    if not html:
        return None
    m = re.search(
        r'Chegada\s*'
        r'(?:(\d+)\s*h\s*)?'
        r'(?:(\d+)\s*m\s*)?'
        r'(?:(\d+)\s*s)?',
        html, re.IGNORECASE
    )
    if not m or not any(m.groups()):
        return None
    h = int(m.group(1) or 0)
    mins = int(m.group(2) or 0)
    secs = int(m.group(3) or 0)
    total = h * 3600 + mins * 60 + secs
    return total if total > 0 else None


def _parse_spy_session_id(html):
    """Try multiple patterns to extract the spy session ID from spyMissions HTML."""
    import re
    if not html:
        return None
    for pat in [
        r'name=["\']spy["\']\s+value=["\'](\d+)["\']',
        r'value=["\'](\d+)["\']\s+name=["\']spy["\']',
        r'"spy"\s*:\s*(\d+)',
        r"'spy'\s*:\s*(\d+)",
        r'\bspy\b\s*=\s*(\d+)',
    ]:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


_RESOURCE_ALT_MAP = {
    "material de construção": "wood",
    "material de constru":    "wood",
    "madeira":                "wood",
    "vinho":                  "wine",
    "mármore":                "marble",
    "marmore":                "marble",
    "cristal":                "glass",
    "enxofre":                "sulfur",
}


def _alt_to_resource_key(alt_text):
    normalized = alt_text.lower().strip()
    for k, v in _RESOURCE_ALT_MAP.items():
        if normalized == k or k in normalized:
            return v
    return None


def _parse_reports_from_html(html):
    """
    Parse all espionage reports embedded in the safehouse reports tab HTML.
    Returns dict {report_id: parsed_data}. All report content is present in the initial
    page load for both read and unread reports — no per-report AJAX call needed.
    """
    import re
    results = {}
    if not html:
        return results

    # Each report occupies a consecutive pair of TR rows:
    #   <tr id="messageID" class="espionageReports [bold]"> — header (bold = unread)
    #   <tr id="tbl_mailID" class="report [invisible]">     — detail with full resource/garrison table
    # Split the HTML at each header row so each chunk covers one full report.
    splits = list(re.finditer(r'(?=<tr[^>]+id=["\']message(\d+)["\'])', html, re.IGNORECASE))
    if not splits:
        logger.debug("[espionage] _parse_reports_from_html: nenhum relatório encontrado no HTML")
        return results

    for k, split in enumerate(splits):
        report_id = split.group(1)
        start = split.start()
        end = splits[k + 1].start() if k + 1 < len(splits) else len(html)
        chunk = html[start:end]

        header_m = re.search(
            r'<tr[^>]+id=["\']message' + re.escape(report_id) + r'["\'][^>]*class=["\']([^"\']+)["\']',
            chunk, re.IGNORECASE)
        is_unread = bool(header_m and "bold" in header_m.group(1))

        owner_m = re.search(r'class=["\']targetOwner[^"\']*["\'][^>]*>(.*?)</td>',
                            chunk, re.DOTALL | re.IGNORECASE)
        target_owner = re.sub(r'<[^>]+>', '', owner_m.group(1)).strip() if owner_m else None

        # City cell — extract from href (most reliable) then fall back to link text
        city_m = re.search(r'class=["\']targetCity[^"\']*["\'][^>]*>.*?<a\s([^>]*)>(.*?)</a>',
                           chunk, re.DOTALL | re.IGNORECASE)
        target_city = island_x = island_y = None
        target_city_id_from_report = None
        if city_m:
            attrs = city_m.group(1)
            # xcoord/ycoord from href
            xm = re.search(r'xcoord=(\d+)', attrs, re.IGNORECASE)
            ym = re.search(r'ycoord=(\d+)', attrs, re.IGNORECASE)
            cm = re.search(r'selectCity=(\d+)', attrs, re.IGNORECASE)
            if xm and ym:
                island_x = int(xm.group(1))
                island_y = int(ym.group(1))
            if cm:
                target_city_id_from_report = cm.group(1)
            # City name from link text
            city_inner = re.sub(r'<br\s*/?>', ' ', city_m.group(2), flags=re.IGNORECASE)
            city_text  = re.sub(r'<[^>]+>', '', city_inner)
            city_text  = re.sub(r'\s+', ' ', city_text).strip()
            # Strip trailing coord bracket from display name
            bracket = re.search(r'\[\s*\d+\s*:\s*\d+\s*\]', city_text)
            target_city = city_text[:bracket.start()].strip() if bracket else city_text
            # Fallback: parse coords from text if href didn't have them
            if island_x is None:
                coord_m = re.search(r'\[\s*(\d+)\s*:\s*(\d+)\s*\]', city_text)
                if coord_m:
                    island_x = int(coord_m.group(1))
                    island_y = int(coord_m.group(2))

        success = bool(re.search(r'completada com sucesso|completed successfully',
                                 chunk, re.IGNORECASE))

        # Detect arrival-only notification ("O teu espião chegou a X")
        is_arrival = bool(re.search(
            r'o teu espi[aã]o chegou\b|your spy (?:has )?arrived',
            chunk, re.IGNORECASE))

        resources = {}
        res_table_m = re.search(
            r'<table[^>]+class=["\'][^"\']*resourcesTable[^"\']*["\'][^>]*>(.*?)</table>',
            chunk, re.DOTALL | re.IGNORECASE)
        if res_table_m:
            for row_m in re.finditer(
                r'<img[^>]+alt=["\']([^"\']+)["\'].*?'
                r'<td[^>]+class=["\'][^"\']*count[^"\']*["\'][^>]*>([\d.,\s]+)</td>',
                res_table_m.group(1), re.DOTALL | re.IGNORECASE
            ):
                key = _alt_to_resource_key(row_m.group(1))
                if key:
                    count_str = row_m.group(2).replace('.', '').replace(',', '').strip()
                    try:
                        resources[key] = int(count_str)
                    except ValueError:
                        pass

        troops = None
        if re.search(r'Tropas\s+em\b|Frotas\s+em\b', chunk, re.IGNORECASE):
            # Keep {} for empty garrison — distinguishes "garrison checked, no troops" from "not a garrison report"
            troops = _parse_garrison_troops(chunk)

        results[report_id] = {
            "reportId":       report_id,
            "isUnread":       is_unread,
            "isArrival":      is_arrival,
            "targetOwner":    target_owner,
            "targetCityName": target_city,
            "targetCityId":   target_city_id_from_report,
            "islandX":        island_x,
            "islandY":        island_y,
            "success":        success,
            "resources":      resources if resources else None,
            "troops":         troops,
            "reportedAt":     int(time.time()),
        }

    logger.debug("[espionage] _parse_reports_from_html: %d relatório(s) encontrado(s)", len(results))
    return results


def _parse_garrison_troops(html):
    """
    Parse the table-structured garrison report HTML.
    Format: header row (Quartel/Estaleiro + unit names),
            data row (Tropas/Frotas em CITY + counts or "-")
    Returns {unit_name: count} for all non-zero units.
    """
    import re
    troops = {}
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL | re.IGNORECASE)
    current_headers = []
    for row in rows:
        cells_raw = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', row, re.DOTALL | re.IGNORECASE)
        cells = []
        for c in cells_raw:
            text = re.sub(r'<[^>]+>', '', c).replace('\xa0', ' ').strip()
            text = re.sub(r'\s+', ' ', text).strip()
            if not text:
                # Unit icons render name in title="" — e.g. <div class="army hoplite" title="Hoplita">
                title_m = re.search(r'\btitle=["\']([^"\']+)["\']', c, re.IGNORECASE)
                if title_m:
                    text = title_m.group(1).strip()
            cells.append(text)
        if not cells:
            continue
        first = cells[0]
        if first in ('Quartel', 'Estaleiro'):
            current_headers = cells[1:]
        elif first.startswith('Tropas em') or first.startswith('Frotas em'):
            values = cells[1:]
            for i, val in enumerate(values):
                if i >= len(current_headers):
                    break
                unit_name = current_headers[i].strip()
                if not unit_name or val in ('-', '', 'Nenhuma unidade disponível.'):
                    continue
                try:
                    count = int(val.replace('.', '').replace(',', ''))
                    if count > 0:
                        troops[unit_name] = troops.get(unit_name, 0) + count
                except ValueError:
                    pass
    return troops


def _parse_movement_datetime(s):
    """Parse the movement report's 'DD.MM.YYYY H:MM:SS' → epoch secs (local), or None.
    Only used for DURATIONS (arrival − departure), so the local-TZ assumption cancels out."""
    s = (s or "").strip()
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return int(time.mktime(time.strptime(s, fmt)))
        except (ValueError, OverflowError):
            continue
    return None


def parse_fleet_movements(html):
    """Parse a spy-on-movements report (MISSION_MOVEMENTS) into a list of movements.
    Table columns: Cidade alvo | Tempo de partida | Tempo de chegada | Acção | Quantidade.
    Returns [{'target','departure','arrival','action','qty'}] (departure/arrival = epoch).
    Empty report ('Neste momento não existem movimentos de frotas!') → []."""
    import re
    movements = []
    for row in re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL | re.IGNORECASE):
        cells = []
        for c in re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', row, re.DOTALL | re.IGNORECASE):
            text = re.sub(r'<[^>]+>', '', c).replace('\xa0', ' ')
            cells.append(re.sub(r'\s+', ' ', text).strip())
        if len(cells) < 5:
            continue
        dep = _parse_movement_datetime(cells[1])
        arr = _parse_movement_datetime(cells[2])
        if dep is None or arr is None:
            continue   # header or non-data row
        try:
            qty = int(re.sub(r'[^0-9]', '', cells[4]) or 0)
        except ValueError:
            qty = 0
        movements.append({"target": cells[0], "departure": dep, "arrival": arr,
                          "action": cells[3], "qty": qty})
    return movements


def enemy_fleet_clean_window_secs(html, city_name=None):
    """From a spy-on-movements report, how long the port stays clean after an enemy fleet
    is driven off: the (arrival − departure) of the enemy fleet RETURNING to defend (action
    contains 'Voltar', e.g. 'Defender porto(Voltar)'). The fleet flees at `departure` (when
    our blockade lands) and is back at `arrival`. TZ-safe (it's a duration). Our own waves
    ('Pilhar', …) are excluded by the action filter. Returns secs, or None."""
    cn = (city_name or "").lower()
    best = None
    for m in parse_fleet_movements(html):
        if "voltar" not in m["action"].lower():
            continue
        if cn and cn not in m["target"].lower():
            continue
        window = m["arrival"] - m["departure"]
        if window > 0 and (best is None or window < best):
            best = window
    return best
