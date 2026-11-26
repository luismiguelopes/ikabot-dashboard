"""Replace every real name in dashboard API responses with a stable fictional one.

Used by take_screenshots.py so README screenshots never show real cities, players,
islands, alliances, coordinates or secrets. The same real name always maps to the same
fake name, so the pages stay consistent across screenshots.
"""
import random
import re

# Keys whose string value is a city, player or island name.
NAME_KEYS = {
    "islandName", "nearestOwnCity", "cityName", "playerName", "targetCityName",
    "targetPlayerName", "targetOwner", "from_player", "target_player", "origin_city",
    "target_city", "from_city", "to_city", "target_city_name", "fromCity", "toCity",
    "ownerName", "player", "owner", "city", "island", "originCityName", "player_name",
    "city_name", "island_name", "targetIslandName", "originName", "targetName",
}
ALLY_KEYS = {"allyTag", "ally", "allyName", "ally_tag"}
SECRET_RE = re.compile(r"token|chat_?id|webhook|secret|password|email", re.I)
COORD_KEYS = {"islandX", "islandY", "x", "y", "island_x", "island_y", "targetX", "targetY",
              "originX", "originY"}
# Movement texts look like "City (Player)".
CITY_PLAYER_RE = re.compile(r"^(.*?) \((.*)\)$")
COORD_TEXT_RE = re.compile(r"\[(\d{1,3}):(\d{1,3})\]")
COORD_OFFSET = 23
OWN_PLAYER_FAKE = "PlayerOne"
KEEP_CITIES = 10        # own cities shown; the real count would identify the account

# Numbers under these keys are not quantities (ids, times, levels, coordinates, settings).
NOT_A_QUANTITY_RE = re.compile(
    r"(id|Id|ID)$|_id$|time|Time|(^|_)ts$|Ts$|At$|_at$|epoch|Epoch|until|Until|since|Since|"
    r"secs|Secs|seconds|Seconds|eta|Eta|ETA|duration|Duration|interval|Interval|hours|Hours|"
    r"mins|Mins|minutes|Minutes|level|Level|version|offset|pct|Pct|percent|Percent|ratio|"
    r"Ratio|limit|Limit|threshold|Threshold|In$|delay|Delay|radius|Radius|page|Page|"
    r"^(x|y)$|X$|Y$|^max|^min|Max$|Min$")
PT_THOUSANDS_RE = re.compile(r"^\d{1,3}(\.\d{3})+$")

# Game vocabulary from the Portuguese server, shown in English so the screenshots do not
# point at a server. Longest phrases first, so "Mercado Negro" wins over "Mercado".
GAME_TERMS = {
    # buildings
    "Academia": "Academy", "Armazém": "Warehouse", "Arquivo de Cartas Marítimas": "Sea Chart Archive",
    "Atelier de Arquitectura": "Architect's Office", "Carpintaria": "Carpenter",
    "Caves de Vinho": "Wine Cellar", "Câmara Municipal": "Town Hall", "Depósito": "Dump",
    "Embaixada": "Embassy", "Espionagem": "Hideout", "Estaleiro Comercial": "Dockyard",
    "Estaleiro": "Shipyard", "Forja de Cronos": "Chronos' Forge",
    "Fortaleza dos Piratas": "Pirate Fortress", "Fábrica de Pirotecnia": "Firework Test Area",
    "Guarda Florestal": "Forester's House", "Mercado Negro": "Black Market",
    "Mercado": "Trading Post", "Muralha da Cidade": "Town Wall", "Museu": "Museum",
    "Oculista": "Optician", "Oficina": "Workshop", "Palácio": "Palace", "Pedreiro": "Stonemason",
    "Porto Mercantil": "Trading Port", "Quartel": "Barracks",
    "Residência do Governador": "Governor's Residence", "Santuário dos Deuses": "Gods' Shrine",
    "Taberna": "Tavern", "Templo": "Temple", "Viticultor": "Winegrower",
    "Torre do Alquimista": "Alchemist's Tower", "Prensa de Vinho": "Wine Press",
    "Vidreiro": "Glassblower", "Lenhador": "Forester",
    # units
    "Fundeiro": "Slinger", "Espadachim": "Swordsman", "Hoplita": "Hoplite",
    "Fuzileiro": "Sulphur Carabineer", "Morteiro": "Mortar", "Catapulta": "Catapult",
    "Aríete a vapor": "Steam Ram", "Aríete": "Battering Ram", "Gigante a Vapor": "Steam Giant",
    "Balão-bombardeiro": "Balloon-Bombardier", "Cozinheiro": "Cook", "Médico": "Doctor",
    "Giracóptero": "Gyrocopter", "Arqueiro": "Archer", "Lanceiro": "Spearman",
    "Espartano": "Spartan", "Trirreme": "Ram-Ship", "Lança-Chamas": "Fire Ship",
    "Submergível": "Diving Boat", "Barco Balista": "Ballista Ship",
    "Barco Catapulta": "Catapult Ship", "Barco Morteiro": "Mortar Ship",
    "Lança-foguetes": "Rocket Ship", "Lancha rápida": "Paddle Speedboat",
    "Porta-balões": "Balloon Carrier", "Reparador": "Tender",
    # wonders
    "Templo de Poseidon": "Temple of Poseidon", "Forja de Hefesto": "Hephaestus' Forge",
    "Sagrado de Hades": "Hades' Holy Grove", "Fortaleza de Ares": "Ares' Stronghold",
    "Templo de Atena": "Temple of Athena", "Jardins de Demeter": "Demeter's Gardens",
    "Templo de Hermes": "Temple of Hermes", "Templo de Gaia": "Temple of Gaia",
    "Colosso": "Colossus",
    # missions
    "Ocupar porto": "Occupy port", "Ocupar cidade": "Occupy town", "Pilhar": "Pillage",
    "Transportar": "Transport", "Bloquear porto": "Blockade",
    "Estacionar tropas": "Station troops", "Estacionar frota": "Station fleet",
    "Defender": "Defend", "Regressar": "Return", "em curso": "underway",
    "A carregar": "loading", "a carregar": "loading", "a regressar": "returning",
    "regresso": "return",
}

OWN_FAKE = ["Thalassa", "Kymopolis", "Argyra", "Helion", "Myrtos", "Delphinia", "Korinna",
            "Lykaia", "Naxara", "Orestia", "Pelagos", "Selinous", "Zephyra", "Ambrakia",
            "Theronia", "Kalydon", "Mesembria", "Akanthos", "Olbia", "Kerkyra"]
SYLLABLES = ["ka", "lo", "ra", "mi", "tho", "ne", "va", "dri", "sel", "po", "ru", "ta", "ze",
             "li", "or", "ban", "che", "di", "fen", "gor", "hal", "is", "ju", "kor", "mar",
             "nos", "pel", "quin", "sar", "tul", "ur", "vel", "wen", "xan", "yor", "zul"]
# Words that are data, not names: a player who calls a city "Crystal" must not rename the
# crystal resource everywhere.
RESOURCE_WORDS = ("wood", "wine", "marble", "crystal", "glass", "sulfur", "cristal", "vinho",
                  "madeira", "enxofre", "marmore", "mármore")


class Anonymizer:
    def __init__(self, seed=42, scale=None, keep_cities=KEEP_CITIES):
        self.rng = random.Random(seed)
        # One factor for every quantity keeps ratios (warehouse fill, wine runway) right.
        # It is random per run and never stored, so real values cannot be recovered.
        self.scale = scale if scale is not None else random.SystemRandom().uniform(.55, .8)
        self.keep_cities = keep_cities
        self.dropped = set()       # real names of own cities left out of the screenshots
        self._terms_re = re.compile(
            r"(?<!\w)(" + "|".join(re.escape(t) for t in sorted(GAME_TERMS, key=len, reverse=True))
            + r")(?!\w)")
        self.map = {}
        self.allies = {}
        self.used = set(OWN_FAKE) | {OWN_PLAYER_FAKE}
        self.own = []
        self.own_player = None
        self.protected = {v for w in RESOURCE_WORDS for v in (w, w.capitalize(), w.upper())}
        self._re = None

    # ---- name generation --------------------------------------------------
    def _word(self, n):
        return "".join(self.rng.choice(SYLLABLES) for _ in range(n)).capitalize()

    def _fresh(self, kind):
        while True:
            if kind == "player":
                w = self._word(2)
                if self.rng.random() < .3:
                    w += str(self.rng.randint(1, 99))
            elif kind == "island":
                w = self._word(2) + self.rng.choice(["os", "ia", "on", "is"])
            else:
                w = self._word(self.rng.choice([2, 3]))
            if w not in self.used and w not in self.map:
                self.used.add(w)
                return w

    def add(self, real, kind="city"):
        if not isinstance(real, str):
            return
        real = real.strip()
        if len(real) < 2 or real in self.map or real in self.protected:
            return
        if kind == "own" and len(self.own) < len(OWN_FAKE):
            fake = OWN_FAKE[len(self.own)]
            self.own.append(real)
        else:
            fake = self._fresh("city" if kind == "own" else kind)
        self.map[real] = fake
        self._re = None

    def add_ally(self, tag):
        if isinstance(tag, str) and tag.strip() and tag not in self.allies:
            self.allies[tag] = "".join(self.rng.choice("ABCDEFGHKLMNPRSTVWXZ")
                                       for _ in range(self.rng.choice([3, 4])))

    def set_own_player(self, name):
        if name and name not in self.protected:
            self.own_player = name
            self.map[name] = OWN_PLAYER_FAKE
            self._re = None

    # ---- seeding ----------------------------------------------------------
    def seed(self, data, military=None, movements=None, others=()):
        """Learn names from the API payloads.

        data      -- /api/data (own cities are the keys of empireData)
        military  -- /api/military (unit names are protected vocabulary)
        movements -- /api/movements (own player = the player behind an own city)
        others    -- any other payloads to harvest names from
        """
        empire = (data or {}).get("empireData", {}) or {}
        for city in empire.values():
            if isinstance(city, dict):
                self.protected.update(city.keys())          # building names
        for city in ((military or {}).get("byCityName", {}) or {}).values():
            for section in ("troops", "fleet"):
                for unit in (city.get(section) or {}).values():
                    if isinstance(unit, dict) and unit.get("name"):
                        self.protected.add(unit["name"])    # unit names
        own_names = sorted(set(empire) | set(((military or {}).get("byCityName") or {})))
        for name in own_names:
            self.add(name, "own")
        if self.keep_cities:
            self.dropped = set(own_names[self.keep_cities:])
        for mv in movements or []:
            for field in ("origin", "destination"):
                m = CITY_PLAYER_RE.match(str(mv.get(field, "")))
                if m and m.group(1) in own_names and not self.own_player:
                    self.set_own_player(m.group(2))
        for payload in (data, military, movements, *others):
            self.harvest(payload)
        self._fix_collisions()

    def _fix_collisions(self):
        """A generated name may happen to be another real name; regenerate it."""
        reals = set(self.map)
        self.used |= reals
        for real, fake in list(self.map.items()):
            if fake in reals and real != self.own_player:
                self.map[real] = self._fresh("island")
        self._re = None

    def harvest(self, o, parent=None):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str):
                    if k in NAME_KEYS:
                        lk = k.lower()
                        kind = ("player" if "player" in lk or "owner" in lk
                                else "island" if "island" in lk else "city")
                        self.add(v, kind)
                    elif k in ALLY_KEYS:
                        self.add_ally(v)
                    elif k in ("origin", "destination"):
                        m = CITY_PLAYER_RE.match(v)
                        if m:
                            self.add(m.group(2), "player")
                            self.add(m.group(1))
                        else:
                            self.add(v)
                    elif k == "name" and parent in ("ownCities", "buys"):
                        self.add(v)
                self.harvest(v, k)
        elif isinstance(o, list):
            for x in o:
                self.harvest(x, parent)

    # ---- transforming -----------------------------------------------------
    def _regex(self):
        if self._re is None:
            names = sorted(self.map, key=len, reverse=True)
            if not names:
                self._re = re.compile(r"(?!x)x")
            else:
                self._re = re.compile(
                    r"(?<!\w)(" + "|".join(re.escape(n) for n in names) + r")(?!\w)")
        return self._re

    @staticmethod
    def coord(v):
        return (v - 1 + COORD_OFFSET) % 100 + 1

    def text(self, s):
        if not s:
            return s
        if s in self.map:
            return self.map[s]
        if s in self.allies:
            return self.allies[s]
        s = self._regex().sub(lambda m: self.map[m.group(1)], s)
        s = self._terms_re.sub(lambda m: GAME_TERMS[m.group(1)], s)
        return COORD_TEXT_RE.sub(
            lambda m: "[%d:%d]" % (self.coord(int(m.group(1))), self.coord(int(m.group(2)))), s)

    def quantity(self, key, v):
        """Scale a number if it is a quantity (resources, gold, ships, loot...)."""
        if isinstance(v, bool) or not isinstance(key, str) or NOT_A_QUANTITY_RE.search(key):
            return v
        if isinstance(v, (int, float)) and 100 <= abs(v) < 1e9:
            scaled = v * self.scale
            return int(round(scaled)) if isinstance(v, int) else round(scaled, 2)
        if isinstance(v, str) and PT_THOUSANDS_RE.match(v):
            n = int(round(int(v.replace(".", "")) * self.scale))
            return f"{n:,}".replace(",", ".")
        return v

    def _is_dropped(self, o):
        return isinstance(o, dict) and any(
            isinstance(o.get(k), str) and o[k] in self.dropped
            for k in ("cityName", "name", "city_name"))

    def transform(self, o):
        """Return a copy of a JSON payload with names, coordinates, quantities, game terms
        and secrets replaced, and the own cities beyond keep_cities left out."""
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                if k in self.dropped:
                    continue
                nk = self.text(k) if isinstance(k, str) else k
                if isinstance(k, str) and SECRET_RE.search(k) and isinstance(v, str) and v:
                    out[nk] = ""
                elif k in COORD_KEYS and isinstance(v, int) and 0 < v <= 100:
                    out[nk] = self.coord(v)
                elif k in ALLY_KEYS and isinstance(v, str):
                    out[nk] = self.allies.get(v, v)
                elif isinstance(v, (int, float, str)) and not isinstance(v, bool) \
                        and self.quantity(k, v) is not v:
                    out[nk] = self.quantity(k, v)
                else:
                    out[nk] = self.transform(v)
            return out
        if isinstance(o, list):
            return [self.transform(x) for x in o if not self._is_dropped(x)]
        if isinstance(o, str):
            return self.text(o)
        return o

    def leaks(self, text):
        """Real names (4+ characters) still present in a transformed payload."""
        return {real for real in self.map
                if len(real) >= 4
                and re.search(r"(?<!\w)" + re.escape(real) + r"(?!\w)", text)}
