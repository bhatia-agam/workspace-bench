"""model_multihop name forms (plan 0076 rev 2 / F / G / H): the reviewed literal country and cutoff
tables and the ``mc`` block builder, shared by ``scripts/build_model_multihop_bank.py`` (the
registered bank) and ``wsbench.adapt.mmh`` (the adapted sets, plan 0078)."""

from typing import Any

from wsbench import mc

ORDER_SEED = "mmh-2026-11-06"  # mc.seeded_shuffle seed prefix of every item's option order

# ---------------------------------------------------------------------------------------------
# Country names (plan rev 2): canonical name -> extra accepted forms (English only, hand-checked).
# Applied to EVERY option that is a country, cutoff options included ("USA", "south korea").
# Left out on purpose: bare "Korea" (both Koreas are options of one item), "Macedonia" (the Greek
# region; Greece and North Macedonia share an item), "Emirates" (the airline), "Saudi", "Persia",
# "Siam", "Ceylon", "England" / "Scotland" / "Wales" (parts of the UK, not its name).
COUNTRY_ALIASES: dict[str, list[str]] = {
    "Afghanistan": [],
    "Algeria": [],
    "Angola": [],
    "Argentina": [],
    "Armenia": [],
    "Australia": [],
    "Austria": [],
    "Azerbaijan": [],
    "Bahrain": [],
    "Bangladesh": [],
    "Belarus": [],
    "Belgium": [],
    "Benin": [],
    "Bosnia and Herzegovina": ["Bosnia", "Bosnia-Herzegovina", "Bosnia & Herzegovina", "BiH"],
    "Botswana": [],
    "Brazil": ["Brasil"],
    "Brunei": ["Brunei Darussalam"],
    "Bulgaria": [],
    "Burkina Faso": [],
    "Burundi": [],
    "Cambodia": [],
    "Cameroon": [],
    "Canada": [],
    "Cape Verde": ["Cabo Verde"],
    "Chile": [],
    "China": ["People's Republic of China", "PRC", "Mainland China"],
    "Colombia": [],
    "Costa Rica": [],
    "Croatia": [],
    "Cuba": [],
    "Cyprus": [],
    "Czech Republic": ["Czechia"],
    "DR Congo": [
        "Democratic Republic of the Congo",
        "Democratic Republic of Congo",
        "DRC",
        "D.R. Congo",
        "Congo-Kinshasa",
    ],
    "Denmark": [],
    "Dominican Republic": [],
    "Ecuador": [],
    "Egypt": [],
    "El Salvador": [],
    "Eswatini": ["Swaziland"],
    "Finland": [],
    "France": [],
    "Georgia": [],
    "Germany": [],
    "Ghana": [],
    "Greece": [],
    "Guatemala": [],
    "Guinea": [],
    "Honduras": [],
    "Hungary": [],
    "Iceland": [],
    "India": [],
    "Indonesia": [],
    "Iran": [],
    "Iraq": [],
    "Ireland": ["Republic of Ireland"],
    "Israel": [],
    "Italy": [],
    "Ivory Coast": ["Côte d'Ivoire"],
    "Japan": [],
    "Jordan": [],
    "Kazakhstan": [],
    "Kenya": [],
    "Kuwait": [],
    "Laos": ["Lao PDR"],
    "Lebanon": [],
    "Lesotho": [],
    "Libya": [],
    "Lithuania": [],
    "Luxembourg": [],
    "Malawi": [],
    "Malaysia": [],
    "Mali": [],
    "Mauritania": [],
    "Mexico": [],
    "Montenegro": [],
    "Morocco": [],
    "Mozambique": [],
    "Myanmar": ["Burma"],
    "Namibia": [],
    "Nepal": [],
    "Netherlands": ["Holland"],
    "New Zealand": ["NZ"],
    "Nicaragua": [],
    "Niger": [],
    "Nigeria": [],
    "North Macedonia": [],
    "Norway": [],
    "Oman": [],
    "Pakistan": [],
    "Palestine": ["State of Palestine"],
    "Panama": [],
    "Paraguay": [],
    "Peru": [],
    "Philippines": [],
    "Poland": [],
    "Portugal": [],
    "Qatar": [],
    "Russia": ["Russian Federation"],
    "Rwanda": [],
    "Saudi Arabia": ["KSA"],
    "Senegal": [],
    "Serbia": [],
    "Singapore": [],
    "Slovakia": ["Slovak Republic"],
    "Slovenia": [],
    "South Africa": [],
    "South Korea": ["Republic of Korea"],
    "Spain": [],
    "Sri Lanka": [],
    "Sudan": [],
    "Sweden": [],
    "Switzerland": [],
    "Syria": [],
    # the Republic of China: a form of Taiwan where Taiwan is an option, a blocker of China's
    # "China" where it is not (COUNTRY_BLOCKERS); "People's Republic of China" outranks it
    "Taiwan": ["Republic of China", "Republic of China (Taiwan)"],
    "Tajikistan": [],
    "Tanzania": [],
    "Thailand": [],
    "Togo": [],
    "Tunisia": [],
    "Turkey": ["Türkiye"],
    "Uganda": [],
    "Ukraine": [],
    "United Arab Emirates": ["UAE", "U.A.E."],
    "United Kingdom": ["UK", "U.K.", "Britain", "Great Britain"],
    "United States": [
        "US",
        "U.S.",
        "USA",
        "U.S.A.",
        "United States of America",
        "America",
    ],
    "Uruguay": [],
    "Venezuela": [],
    "Vietnam": ["Viet Nam"],
    "Zambia": [],
    "Zimbabwe": [],
    # plan 0076 rev G: the other foil strings of the invented items (their own gw foils)
    "Bahamas": ["The Bahamas"],
    "Belize": [],
    "Bermuda": [],
    "Chad": [],
    "Estonia": [],
    "Fiji": [],
    "Guyana": [],
    "Hong Kong": [],
    "Jamaica": [],
    "Kyrgyzstan": ["Kyrgyz Republic"],
    "Latvia": [],
    "Liberia": [],
    "Madagascar": [],
    "Mauritius": [],
    "Mongolia": [],
    "Papua New Guinea": ["PNG"],
    "Romania": [],
    "Sierra Leone": [],
    "Solomon Islands": [],
    "São Tomé and Príncipe": [],
    "Trinidad and Tobago": [],
    "Turkmenistan": [],
    "Uzbekistan": [],
    "Yemen": [],
    # plan 0078 R53 (tier C): the sibling clusters' countries the table lacked (hand-checked)
    "Barbados": [],
    "Bolivia": [],
    "Ethiopia": [],
    "Gambia": ["The Gambia"],
    "Guam": [],
    "Malta": [],
    "Moldova": [],
    "San Marino": [],
}

# Longer names that are NOT the country but contain one of its forms; their spans hide the
# shorter form inside them (the judge's containment rule, extended to these non-option names).
COUNTRY_BLOCKERS: dict[str, list[str]] = {
    "United States": ["South America", "Latin America", "North America", "Central America"],
    "Ireland": ["Northern Ireland"],
    "Guinea": [
        "Papua New Guinea",
        "New Guinea",
        "Equatorial Guinea",
        "Guinea-Bissau",
        "Guinea Bissau",
        "Guinea\u2013Bissau",  # an en dash is not a hyphen to name_spans' glued guard
    ],
    # South Korea's "Republic of Korea" sits inside the North's long name; dropped where North
    # Korea is itself an option (its forms then do this)
    "South Korea": ["Democratic People's Republic of Korea", "DPRK", "North Korea"],
    "China": ["Republic of China (Taiwan)", "Republic of China"],
    "Sudan": ["South Sudan"],
    "Mexico": ["New Mexico", "Gulf of Mexico"],
    "Niger": ["Niger Delta", "Niger River", "River Niger", "Niger State"],
    "Jordan": ["Jordan River", "River Jordan"],
    "Cyprus": ["Northern Cyprus"],
    # the US state (applied wherever Georgia is an option; it matters where the United States is
    # one too, e.g. r12iv3306); the blocker hides Georgia only, never the "U.S." inside it
    "Georgia": [
        "Atlanta, Georgia",
        "Savannah, Georgia",
        "U.S. state of Georgia",
        "US state of Georgia",
        "state of Georgia",
    ],  # not "Georgia, USA" / "Georgia (U.S. state)": they name the United States themselves
}

# ---------------------------------------------------------------------------------------------
# Cutoff options (plan rev 2): every non-country option of the 28 cutoff items -> its accepted
# forms (the option string itself is always a form). Hand-reviewed; no leading-token rule. A
# maker alone ("Toyota" for the GR010) is not a form of a product; neither is the item's hop
# answer (H100, Snapdragon, Memphis, BHP's ticker aside, which IS its name).
_TAB = {
    "S9 Ultra": "Samsung Galaxy Tab S9 Ultra",
    "S10 Ultra": "Samsung Galaxy Tab S10 Ultra",
    "S11 Ultra": "Samsung Galaxy Tab S11 Ultra",
    "S8 Ultra": "Samsung Galaxy Tab S8 Ultra",
}


def _tab(short: str) -> list[str]:
    return [f"Samsung Galaxy Tab {short}", f"Galaxy Tab {short}", f"Tab {short}", short]


_S7P = ["Samsung Galaxy Tab S7+", "Galaxy Tab S7+", "Tab S7+", "Galaxy Tab S7 Plus", "Tab S7 Plus"]


def _snap(gen: str) -> list[str]:
    s = gen.replace("Gen ", "Gen")
    return [f"Snapdragon {gen}", gen, f"Snapdragon {s}", s]


_ARCH = {a: [a] for a in ("Hopper", "Volta", "Ampere", "Blackwell", "Rubin")}

CUTOFF_FORMS: dict[str, list[str]] = {
    # r9rh0979 (Canon flagship)
    "Canon EOS R5": ["Canon EOS R5", "EOS R5", "Canon R5", "EOS-R5"],
    "Canon EOS R1": ["Canon EOS R1", "EOS R1", "Canon R1", "EOS-R1"],
    "Canon EOS R3": ["Canon EOS R3", "EOS R3", "Canon R3", "EOS-R3"],
    "Canon EOS-1D X Mark III": [
        "Canon EOS-1D X Mark III",
        "EOS-1D X Mark III",
        "EOS 1D X Mark III",
        "1D X Mark III",
        "1DX Mark III",
        "EOS-1DX Mark III",
    ],
    "Canon EOS-1D X Mark II": [
        "Canon EOS-1D X Mark II",
        "EOS-1D X Mark II",
        "EOS 1D X Mark II",
        "1D X Mark II",
        "1DX Mark II",
        "EOS-1DX Mark II",
    ],
    # r11rh1892 (Le Mans 2026 winning manufacturer)
    "Toyota": ["Toyota"],
    "Ferrari": ["Ferrari"],
    "Porsche": ["Porsche"],
    "Cadillac": ["Cadillac"],
    "BMW": ["BMW"],
    # r2co0492, r9rh2068, r17rh0580 (Galaxy Tab S Ultra)
    **{full: _tab(short) for short, full in _TAB.items()},
    **{f"Galaxy Tab {short}": _tab(short) for short in _TAB},
    "Samsung Galaxy Tab S7+": _S7P,
    "Galaxy Tab S7+": _S7P,
    # r2co0457 (Parkland's acquirer)
    "Suncor Energy": ["Suncor Energy", "Suncor"],
    "Sunoco LP": ["Sunoco LP", "Sunoco"],
    "Alimentation Couche-Tard": ["Alimentation Couche-Tard", "Couche-Tard", "Couche Tard"],
    "Shell": ["Shell"],
    "Murphy USA": ["Murphy USA"],
    # r2co0431 (Estée Lauder CEO)
    "William P. Lauder": ["William P. Lauder", "William Lauder", "William P Lauder"],
    "Stéphane de La Faverie": ["Stéphane de La Faverie", "de La Faverie", "La Faverie"],
    "Fabrizio Freda": ["Fabrizio Freda", "Freda"],
    "Hein Schumacher": ["Hein Schumacher"],  # bare "Schumacher" is Michael Schumacher
    "Alan Jope": ["Alan Jope", "Jope"],
    # r11rh1888 (Le Mans 2025 winning car)
    "Toyota GR010 Hybrid": ["Toyota GR010 Hybrid", "Toyota GR010", "GR010 Hybrid", "GR010"],
    "Ferrari 499P": ["Ferrari 499P", "499P"],
    "Porsche 963": ["Porsche 963"],
    "Cadillac V-Series.R": ["Cadillac V-Series.R", "V-Series.R", "Cadillac V-Series R"],
    "BMW M Hybrid V8": ["BMW M Hybrid V8", "M Hybrid V8"],
    # r17rh0646, r11rh0060 (Nvidia data-centre architecture)
    **_ARCH,
    # r17rh0493 (most valuable Canadian company)
    "Enbridge Inc": ["Enbridge Inc", "Enbridge"],
    "Shopify": ["Shopify"],
    "Royal Bank of Canada": ["Royal Bank of Canada", "RBC"],
    "Toronto-Dominion Bank": ["Toronto-Dominion Bank", "Toronto-Dominion", "TD Bank"],
    "Canadian Pacific Kansas City": ["Canadian Pacific Kansas City", "CPKC", "Canadian Pacific"],
    # r17rh0675, r17rh0660 (Snapdragon in the current flagship)
    "Snapdragon 8 Gen 3": _snap("8 Gen 3"),
    "Snapdragon 8 Gen 1": _snap("8 Gen 1"),
    "Snapdragon 8 Gen 2": _snap("8 Gen 2"),
    "Snapdragon 8 Elite": ["Snapdragon 8 Elite", "8 Elite"],
    "Snapdragon 8 Elite Gen 5": _snap("8 Elite Gen 5"),
    # r17rh0578 (Huawei Mate X foldable)
    **{f"Huawei Mate {m}": [f"Huawei Mate {m}", f"Mate {m}"] for m in ("X5", "X2", "X6", "X7")},
    "Huawei Mate Xs 2": ["Huawei Mate Xs 2", "Mate Xs 2", "Mate Xs2"],
    # r9rh1275 (President of the Generalitat Valenciana)
    "Ximo Puig": ["Ximo Puig", "Puig"],
    "Juanfran Pérez Llorca": [
        "Juanfran Pérez Llorca",
        "Juan Francisco Pérez Llorca",
        "Pérez Llorca",
    ],
    "Carlos Mazón": ["Carlos Mazón", "Mazón"],
    "Francisco Camps": ["Francisco Camps", "Camps"],
    "Alberto Fabra": ["Alberto Fabra", "Fabra"],
    # r11rh1896 (first Boeing 777-9 operator)
    "Emirates": ["Emirates", "Emirates Airline"],
    "Lufthansa": ["Lufthansa"],
    "Qatar Airways": ["Qatar Airways"],
    "Cathay Pacific": ["Cathay Pacific", "Cathay"],
    "Singapore Airlines": ["Singapore Airlines"],
    # r11rh1800 (most valuable Australian company)
    "BHP Group": ["BHP Group", "BHP", "BHP Billiton"],
    "Commonwealth Bank of Australia": [
        "Commonwealth Bank of Australia",
        "Commonwealth Bank",
        "CommBank",
        "CBA",
    ],
    "CSL": ["CSL", "CSL Limited"],
    "Westpac": ["Westpac"],
    "Wesfarmers": ["Wesfarmers"],
    # r9rh0060 (fastest TOP500 machine)
    "Frontier": ["Frontier"],
    "El Capitan": ["El Capitan"],
    "Aurora": ["Aurora"],
    "Fugaku": ["Fugaku"],
    "JUPITER": ["JUPITER"],
    # cs_cs00808 (Geneva November 2025 top lot); gw's option strings are lower case
    "Christie's": ["Christie's", "Christies"],
    "phillips": ["phillips"],
    "sothebys": ["sothebys", "Sotheby's", "Sotheby"],
    "bonhams": ["bonhams"],
    "antiquorum": ["antiquorum"],
    # r17rh0393 (Governor of the Bank of Italy)
    "Ignazio Visco": ["Ignazio Visco", "Visco"],
    "Fabio Panetta": ["Fabio Panetta", "Panetta"],
    "Mario Draghi": ["Mario Draghi", "Draghi"],
    "Daniele Franco": ["Daniele Franco"],
    "Fabrizio Saccomanni": ["Fabrizio Saccomanni", "Saccomanni"],
    # r13co0219 (latest FLUX model)
    "FLUX.1": ["FLUX.1"],
    # "." after "FLUX.1" is no word boundary for name_spans: the 1.1 spellings are forms here,
    # so their longer span hides FLUX.1's inside "FLUX.1.1"
    "FLUX1.1 [pro]": [
        "FLUX1.1 [pro]",
        "FLUX 1.1 [pro]",
        "FLUX.1.1 [pro]",
        "FLUX1.1 Pro",
        "FLUX 1.1 Pro",
        "FLUX.1.1 Pro",
        "FLUX1.1",
        "FLUX.1.1",
        "FLUX 1.1",
    ],
    "FLUX1.1 [pro] Ultra": [
        "FLUX1.1 [pro] Ultra",
        "FLUX 1.1 [pro] Ultra",
        "FLUX1.1 Pro Ultra",
        "FLUX 1.1 Pro Ultra",
        "FLUX.1.1 Pro Ultra",
    ],
    "FLUX.1 Kontext": ["FLUX.1 Kontext", "FLUX Kontext"],
    "FLUX.2": ["FLUX.2", "FLUX 2"],
    # r9rh1034 (top smartphone SoC vendor 2025); a vendor's chip brand is not its name
    "Qualcomm": ["Qualcomm"],
    "MediaTek": ["MediaTek"],
    "Apple": ["Apple"],
    "Unisoc": ["Unisoc"],
    "Samsung Electronics": ["Samsung Electronics", "Samsung"],
    # r9rh1122 (top air-cargo airport); the served city alone is the hop answer, not a form
    "Memphis International Airport": [
        "Memphis International Airport",
        "Memphis International",
        "Memphis Airport",
        "MEM",
    ],
    "Hong Kong International Airport": [
        "Hong Kong International Airport",
        "Hong Kong International",
        "Hong Kong Airport",
        "Chek Lap Kok",
        "HKIA",
        "HKG",
    ],
    "Shanghai Pudong International Airport": [
        "Shanghai Pudong International Airport",
        "Pudong International Airport",
        "Shanghai Pudong International",
        "Shanghai Pudong",
        "Pudong Airport",
        "PVG",
    ],
    "Narita International Airport": [
        "Narita International Airport",
        "Narita International",
        "Narita Airport",
        "Narita",
        "NRT",
    ],
    "John F. Kennedy International Airport": [
        "John F. Kennedy International Airport",
        "John F Kennedy International Airport",
        "JFK International Airport",
        "JFK Airport",
        "Kennedy Airport",
        "JFK",
    ],
    # r17rh0657 (current GeForce xx50 card)
    "RTX 5090": ["RTX 5090", "GeForce RTX 5090"],
    "GeForce GTX 1050": ["GeForce GTX 1050", "GTX 1050"],
    "GeForce GTX 1650": ["GeForce GTX 1650", "GTX 1650"],
    "GeForce RTX 3050": ["GeForce RTX 3050", "RTX 3050"],
    "GeForce RTX 4050 Laptop GPU": [
        "GeForce RTX 4050 Laptop GPU",
        "RTX 4050 Laptop GPU",
        "RTX 4050 Laptop",
        "RTX 4050",
    ],
    # r9rh0721 (current flagship Nothing Phone)
    "Nothing Phone (2a)": ["Nothing Phone (2a)", "Phone (2a)", "Nothing Phone 2a"],
    "Nothing Phone (3)": ["Nothing Phone (3)", "Phone (3)", "Nothing Phone 3"],
    "Nothing Phone (2)": ["Nothing Phone (2)", "Phone (2)", "Nothing Phone 2"],
    "Nothing Phone (1)": ["Nothing Phone (1)", "Phone (1)", "Nothing Phone 1"],
    "Nothing Phone (3a) Pro": ["Nothing Phone (3a) Pro", "Phone (3a) Pro", "Nothing Phone 3a Pro"],
    # r13co0078 (latest Surface Go)
    "Surface Go 3": ["Surface Go 3", "Microsoft Surface Go 3"],
    "Microsoft Surface Go 4": ["Microsoft Surface Go 4", "Surface Go 4"],
    "Microsoft Surface Go 2": ["Microsoft Surface Go 2", "Surface Go 2"],
    "Microsoft Surface Go": ["Microsoft Surface Go", "Surface Go"],
    "Microsoft Surface 3": ["Microsoft Surface 3", "Surface 3"],
}

# Non-option names that contain a cutoff option's form (the same containment as COUNTRY_BLOCKERS)
CUTOFF_BLOCKERS: dict[str, list[str]] = {
    "Emirates": ["United Arab Emirates"],
    "Canon EOS R5": [
        "Canon EOS R5 Mark II",
        "Canon R5 Mark II",
        "EOS R5 Mark II",
        "EOS-R5 Mark II",
        "R5 Mark II",
        "EOS R5 C",
    ],
    "Nothing Phone (2a)": ["Nothing Phone (2a) Plus", "Phone (2a) Plus"],
    "GeForce RTX 3050": ["RTX 3050 Ti"],
    "Aurora": ["Aurora Borealis"],
    "Snapdragon 8 Gen 1": ["Snapdragon 8+ Gen 1", "8+ Gen 1"],
    "Snapdragon 8 Gen 3": ["Snapdragon 8s Gen 3", "8s Gen 3"],
    "GeForce GTX 1050": ["GTX 1050 Ti"],
    "GeForce GTX 1650": ["GTX 1650 Super", "GTX 1650 Ti"],
}

# Case-checked forms (mmh-forms-v2, judge._spans): an all-capitals form (an abbreviation: "US",
# "UK", "JFK", "JUPITER") counts only in capitals ("us" is a pronoun); any other listed form
# ("China", "Turkey", "Shell", "Frontier") counts in any spelling that is not all lower case
# ("CHINA" yes; "china" the material, "turkey" the bird, "guinea pig", "shell" no).
EXACT_CASE = frozenset(
    {
        "US",
        "UK",
        "NZ",
        "KSA",
        "BiH",
        "DRC",
        "PRC",
        "RBC",
        "CBA",
        "CSL",
        "MEM",
        "HKG",
        "PVG",
        "NRT",
        "JFK",
        "Chile",
        "China",
        "Chad",  # also a first name; only "chad" in lower case is rejected
        "Bermuda",  # "bermuda shorts" / "bermuda grass" in lower case
        "PNG",
        "Turkey",
        "Guinea",
        "Panama",
        "Jordan",
        "Georgia",
        "Shell",
        "Apple",
        "Frontier",
        "Aurora",
        "JUPITER",
        "Hopper",
        "Volta",
        "Ampere",
        "Blackwell",
        "Rubin",
        "Camps",
        "Emirates",
        "Cathay",
    }
)

# ---------------------------------------------------------------------------------------------


def _fold(s: str) -> str:
    return " ".join(mc.fold(s).split())


_COUNTRY_KEY: dict[str, str] = {}
for _c, _al in COUNTRY_ALIASES.items():
    for _f in (_c, *_al):
        assert _fold(_f) not in _COUNTRY_KEY, _f
        _COUNTRY_KEY[_fold(_f)] = _c


def country_of(option: str) -> str | None:
    """The canonical country an option names (by name or alias, any case), else None."""
    return _COUNTRY_KEY.get(_fold(option))


def raw_forms(
    option: str, extra: dict[str, list[str]] | None = None, exact: frozenset[str] = EXACT_CASE
) -> list[str]:
    """The option's accepted forms before the shared-form rule: the option string, then the
    country table (any country option), the cutoff table, or (plan 0078, an adapted cutoff
    option) ``extra``, the item's own reviewed forms."""
    c = country_of(option)
    if c is not None:
        listed = [c, *COUNTRY_ALIASES[c]]
    elif option in CUTOFF_FORMS:
        listed = CUTOFF_FORMS[option]
    elif extra is not None and option in extra:
        listed = extra[option]
    else:
        raise SystemExit(f"no forms for option {option!r}: add it to a literal table")
    out: list[str] = []
    seen: set[str] = set()
    for f in (option, *listed):
        k = f if f in exact else _fold(f)
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out


def blockers_of(option: str, extra: dict[str, list[str]] | None = None) -> list[str]:
    c = country_of(option)
    if c:
        return list(COUNTRY_BLOCKERS.get(c, []))
    if option in CUTOFF_BLOCKERS or option in CUTOFF_FORMS or extra is None:  # the table wins
        return list(CUTOFF_BLOCKERS.get(option, []))
    return list(extra.get(option, []))


def mc_block(
    item_id: str,
    bridge: str,
    decoys: list[str],
    extra_forms: dict[str, list[str]] | None = None,
    extra_blockers: dict[str, list[str]] | None = None,
    extra_exact: frozenset[str] = frozenset(),
) -> tuple[dict[str, Any], list[str]]:
    """The item's ``mc`` block and the forms withheld (a form two options share). ``extra_*``
    (plan 0078): an adapted cutoff item's own reviewed forms, blockers and case-checked forms for
    options in no literal table; the registered bank passes none."""
    exact_set = EXACT_CASE | extra_exact
    opts = [bridge, *decoys]
    assert len(set(map(_fold, opts))) == len(opts), (item_id, opts)
    forms = {o: raw_forms(o, extra_forms, exact_set) for o in opts}
    owners: dict[str, set[str]] = {}
    for o, fs in forms.items():
        for f in fs:
            owners.setdefault(f if f in exact_set else _fold(f), set()).add(o)
    shared = {k for k, os_ in owners.items() if len(os_) > 1}
    withheld = sorted(
        f for fs in forms.values() for f in fs if (f if f in exact_set else _fold(f)) in shared
    )
    forms = {
        o: [f for f in fs if (f if f in exact_set else _fold(f)) not in shared]
        for o, fs in forms.items()
    }
    for o, fs in forms.items():
        assert fs and fs[0] == o, (item_id, o, withheld)  # the option string itself survives
    opt_keys = {_fold(f) for fs in forms.values() for f in fs}
    blk = {o: blockers_of(o, extra_blockers) for o in opts}
    blockers = sorted({b for o in opts for b in blk[o] if _fold(b) not in opt_keys})
    # mmh-forms-v3: a blocker hides only the options that list it (``mc.blocker_of``), so "U.S.
    # state of Georgia" hides Georgia and leaves the United States' "U.S." counted
    blocker_of = {b: sorted(o for o in opts if b in blk[o]) for b in blockers}
    for b, owners_b in blocker_of.items():
        assert owners_b, (item_id, b)
    exact = sorted({f for fs in forms.values() for f in fs if f in exact_set})
    order = mc.seeded_shuffle(opts, f"{ORDER_SEED}|{item_id}")
    block: dict[str, Any] = {"order": order, "gold": bridge, "forms": {o: forms[o] for o in order}}
    if exact:
        block["exact_case"] = exact
    if blockers:
        block["blockers"] = blockers
        block["blocker_of"] = blocker_of
    return block, withheld
