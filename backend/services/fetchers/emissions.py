"""
Fuel burn & CO2 emissions estimator.
Based on manufacturer-published cruise fuel burn rates (GPH at long-range cruise).
1 US gallon of Jet-A produces ~21.1 lbs (9.57 kg) of CO2.

Piston entries use 100LL (avgas), which is close enough to Jet-A in CO2 yield
(~8.4 kg/gal vs 9.57 kg/gal); we keep one constant to stay simple — the result
is a slight over-estimate for piston aircraft, which is preferable to under.
"""

JET_A_CO2_KG_PER_GALLON = 9.57

# ICAO type code -> gallons per hour at long-range cruise
FUEL_BURN_GPH: dict[str, int] = {
    # ── Gulfstream ─────────────────────────────────────────────────────
    "GLF6": 430,   # G650/G650ER
    "G700": 480,   # G700
    "GLF5": 390,   # G550
    "GVSP": 400,   # GV-SP
    "GLF4": 330,   # G-IV
    # ── Bombardier business ────────────────────────────────────────────
    "GL7T": 490,   # Global 7500
    "GLEX": 430,   # Global Express/6000/6500
    "GL5T": 420,   # Global 5000/5500
    "CL35": 220,   # Challenger 350
    "CL60": 310,   # Challenger 604/605
    "CL30": 200,   # Challenger 300
    "CL65": 320,   # Challenger 650
    # ── Bombardier regional jets ──────────────────────────────────────
    "CRJ2": 360,   # CRJ-100/200
    "CRJ7": 380,   # CRJ-700
    "CRJ9": 410,   # CRJ-900
    "CRJX": 440,   # CRJ-1000
    # ── Dassault ───────────────────────────────────────────────────────
    "F7X":  350,   # Falcon 7X
    "F8X":  370,   # Falcon 8X
    "F900": 285,   # Falcon 900/900EX/900LX
    "F2TH": 230,   # Falcon 2000
    "FA50": 240,   # Falcon 50
    # ── Cessna Citation ────────────────────────────────────────────────
    "CITX": 280,   # Citation X
    "C750": 280,   # Citation X (alt code)
    "C68A": 195,   # Citation Latitude
    "C700": 230,   # Citation Longitude
    "C680": 220,   # Citation Sovereign
    "C56X": 195,   # Citation Excel/XLS/XLS+
    "C560": 190,   # Citation Excel/XLS (legacy)
    "C550": 165,   # Citation II/Bravo/V
    "C525": 80,    # Citation CJ1
    "C25A": 100,   # CJ1+ / 525A
    "C25B": 110,   # CJ2+ / 525B
    "C25C": 130,   # CJ4 (some operators)
    "C510": 75,    # Citation Mustang
    "C650": 240,   # Citation III/VI/VII
    "CJ3":  120,   # CJ3
    "CJ4":  135,   # CJ4
    # ── Cessna piston / turboprop singles & twins ─────────────────────
    "C172": 9,     # Skyhawk
    "C152": 6,
    "C150": 6,
    "C170": 8,
    "C177": 11,
    "C180": 12,
    "C182": 13,    # Skylane
    "C185": 14,
    "C206": 15,
    "C208": 50,    # Caravan (turboprop)
    "C210": 18,
    "C310": 32,
    "C340": 38,
    "C414": 36,
    "C421": 40,
    # ── Boeing mainline ────────────────────────────────────────────────
    "B737": 850,   # 737-700 / BBJ
    "B738": 920,   # 737-800
    "B739": 880,   # 737-900/900ER
    "B38M": 700,   # 737-8 MAX
    "B39M": 740,   # 737-9 MAX
    "B752": 1100,  # 757-200
    "B753": 1200,  # 757-300
    "B762": 1400,  # 767-200
    "B763": 1450,  # 767-300/300ER
    "B764": 1500,  # 767-400ER
    "B772": 1850,  # 777-200
    "B77L": 1900,  # 777-200LR / 777F
    "B77W": 2050,  # 777-300ER
    "B788": 1200,  # 787-8
    "B789": 1300,  # 787-9
    "B78X": 1350,  # 787-10
    "B744": 3050,  # 747-400
    "B748": 2900,  # 747-8
    # ── Airbus mainline ────────────────────────────────────────────────
    "A318": 780,   # A318
    "A319": 850,   # A319
    "A320": 900,   # A320
    "A321": 990,   # A321
    "A19N": 580,   # A319neo
    "A20N": 580,   # A320neo
    "A21N": 700,   # A321neo
    "A332": 1500,  # A330-200
    "A333": 1550,  # A330-300
    "A338": 1300,  # A330-800neo
    "A339": 1350,  # A330-900neo
    "A343": 1800,  # A340-300
    "A346": 2100,  # A340-600
    "A359": 1450,  # A350-900
    "A35K": 1600,  # A350-1000
    "A388": 3200,  # A380-800
    # ── Embraer regional / business ───────────────────────────────────
    "E135": 300,   # Legacy 600/650 (regional ERJ-135 base)
    "E145": 320,   # ERJ-145
    "E170": 460,   # E170
    "E75L": 490,   # E175-LR
    "E75S": 490,   # E175 standard
    "E175": 490,   # E175 (some)
    "E190": 580,   # E190
    "E195": 600,   # E195
    "E290": 510,   # E190-E2
    "E295": 540,   # E195-E2
    "E50P": 135,   # Phenom 300 (also Phenom 100 var)
    "E55P": 185,   # Praetor 500 / Legacy 500
    "E545": 170,   # Praetor 500 (alt)
    "E500": 80,    # Phenom 100
    # ── ATR / Bombardier / Saab turboprops ────────────────────────────
    "AT43": 230,   # ATR 42-300/-320
    "AT45": 230,   # ATR 42-500
    "AT46": 250,   # ATR 42-600
    "AT72": 300,   # ATR 72-200/-210
    "AT75": 280,   # ATR 72-500
    "AT76": 280,   # ATR 72-600
    "DH8A": 220,   # Dash 8 -100
    "DH8B": 240,   # Dash 8 -200
    "DH8C": 280,   # Dash 8 -300
    "DH8D": 300,   # Dash 8 Q400
    "SF34": 200,   # Saab 340
    "SB20": 220,   # Saab 2000
    # ── Pilatus / Daher single-engine turboprops ──────────────────────
    "PC24": 115,   # PC-24
    "PC12": 60,    # PC-12
    "TBM7": 60,    # TBM 700/850
    "TBM8": 65,    # TBM 850 alt
    "TBM9": 70,    # TBM 900/930/940/960
    "M600": 60,    # Piper M600
    "P46T": 22,    # PA-46 Meridian (turboprop variant)
    # ── Learjet ────────────────────────────────────────────────────────
    "LJ60": 195,   # Learjet 60
    "LJ75": 185,   # Learjet 75
    "LJ45": 175,   # Learjet 45
    "LJ31": 165,   # Learjet 31
    "LJ40": 175,   # Learjet 40
    "LJ55": 195,   # Learjet 55
    # ── Hawker / Beechjet ─────────────────────────────────────────────
    "H25B": 210,   # Hawker 800/800XP
    "H25C": 215,   # Hawker 900XP
    "BE40": 150,   # Beechjet 400 / Hawker 400XP
    "PRM1": 130,   # Premier I
    # ── Beechcraft King Air ───────────────────────────────────────────
    "B350": 100,   # King Air 350
    "B200": 80,    # King Air 200/250
    "BE20": 80,    # K-Air 200 (alt)
    "BE9L": 60,    # K-Air 90
    "BE9T": 70,    # K-Air F90
    "BE10": 100,   # K-Air 100
    "BE30": 90,    # K-Air 300
    # ── Beechcraft / Cirrus / Piper / Mooney pistons ──────────────────
    "BE23": 9,     # Sundowner
    "BE33": 13,    # Bonanza 33
    "BE35": 14,    # Bonanza V-tail
    "BE36": 16,    # A36 Bonanza
    "BE55": 24,    # Baron 55
    "BE58": 28,    # Baron 58
    "BE76": 17,    # Duchess
    "BE95": 20,    # Travel Air
    "P28A": 10,    # PA-28 Warrior/Archer
    "P28B": 11,    # PA-28 Cherokee
    "P28R": 12,    # PA-28R Arrow
    "P32R": 14,    # PA-32R Lance/Saratoga
    "PA11": 5,     # Cub Special
    "PA12": 6,     # Super Cruiser
    "PA18": 6,     # Super Cub
    "PA22": 8,     # Tri-Pacer
    "PA23": 18,    # Apache / Aztec
    "PA24": 12,    # Comanche
    "PA25": 12,    # Pawnee
    "PA28": 10,    # PA-28 generic
    "PA30": 16,    # Twin Comanche
    "PA31": 30,    # Navajo
    "PA32": 14,    # Cherokee Six / Saratoga
    "PA34": 18,    # Seneca
    "PA38": 5,     # Tomahawk
    "PA44": 17,    # Seminole
    "PA46": 18,    # Malibu / Mirage / Matrix
    "M20P": 12,    # Mooney M20 (generic)
    "SR20": 11,    # Cirrus SR20
    "SR22": 16,    # Cirrus SR22
    "S22T": 19,    # SR22T (turbo)
    "DA40": 9,     # Diamond DA40
    "DA42": 14,    # Diamond DA42 TwinStar
    "DA62": 17,    # Diamond DA62
    "DV20": 6,     # Diamond Katana
    # ── Helicopters (civilian) ────────────────────────────────────────
    "A109": 60,    # AW109
    "A119": 50,    # AW119
    "A139": 130,   # AW139
    "A169": 90,    # AW169
    "A189": 145,   # AW189
    "AS35": 55,    # AS350 AStar
    "AS50": 55,    # AStar (alt)
    "AS65": 110,   # Dauphin
    "B06":  35,    # Bell 206 JetRanger
    "B407": 50,    # Bell 407
    "B412": 145,   # Bell 412
    "B429": 80,    # Bell 429
    "B505": 35,    # Bell 505
    "EC30": 50,    # H125 / EC130
    "EC35": 70,    # EC135
    "EC45": 85,    # EC145
    "EC75": 130,   # EC175
    "H125": 55,
    "H130": 50,
    "H135": 70,
    "H145": 85,
    "H155": 110,
    "H160": 95,
    "H175": 130,
    "R22":  9,     # Robinson R22 (piston)
    "R44":  16,    # Robinson R44 (piston)
    "R66":  30,    # Robinson R66 (turbine)
    "S76":  140,   # Sikorsky S-76
    "S92":  220,   # Sikorsky S-92
}

# Common string names -> ICAO type code
_ALIASES: dict[str, str] = {
    "Gulfstream G650": "GLF6", "Gulfstream G650ER": "GLF6", "G650": "GLF6", "G650ER": "GLF6",
    "Gulfstream G700": "G700",
    "Gulfstream G550": "GLF5", "G550": "GLF5", "G500": "GLF5",
    "Gulfstream GV": "GVSP", "Gulfstream G-V": "GVSP", "GV": "GVSP",
    "Gulfstream G-IV": "GLF4", "Gulfstream GIV": "GLF4", "G450": "GLF4",
    "Global 7500": "GL7T", "Bombardier Global 7500": "GL7T",
    "Global 6000": "GLEX", "Global Express": "GLEX", "Bombardier Global 6000": "GLEX",
    "Global 5000": "GL5T",
    "Challenger 350": "CL35", "Challenger 300": "CL30",
    "Challenger 604": "CL60", "Challenger 605": "CL60", "Challenger 650": "CL65",
    "Falcon 7X": "F7X", "Dassault Falcon 7X": "F7X",
    "Falcon 8X": "F8X", "Dassault Falcon 8X": "F8X",
    "Falcon 900": "F900", "Falcon 900LX": "F900", "Falcon 900EX": "F900",
    "Falcon 2000": "F2TH",
    "Citation X": "CITX", "Citation Latitude": "C68A", "Citation Longitude": "C700",
    "Boeing 757-200": "B752", "757-200": "B752", "Boeing 757": "B752",
    "Boeing 767-200": "B762", "767-200": "B762", "Boeing 767": "B762",
    "Boeing 787-8": "B788", "Boeing 787": "B788",
    "Boeing 737": "B737", "737 BBJ": "B737", "BBJ": "B737",
    "Airbus A340-300": "A343", "A340-300": "A343", "A340": "A343",
    "Airbus A318": "A318",
    "Pilatus PC-24": "PC24", "PC-24": "PC24",
    "Legacy 500": "E55P", "Legacy 600": "E135", "Phenom 300": "E50P",
    "Learjet 60": "LJ60", "Learjet 75": "LJ75",
    "Hawker 800": "H25B", "Hawker 900XP": "H25C",
    "King Air 350": "B350", "King Air 200": "B200",
}


def get_emissions_info(model: str) -> dict | None:
    """
    Given an aircraft model string (ICAO type code or common name),
    return emissions info dict or None if unknown.
    """
    if not model:
        return None
    model_clean = model.strip()
    model_upper = model_clean.upper()
    # Try direct ICAO code match first
    gph = FUEL_BURN_GPH.get(model_upper)
    if gph is None:
        # Try alias lookup
        code = _ALIASES.get(model_clean)
        if code:
            gph = FUEL_BURN_GPH.get(code)
    if gph is None:
        # Friendly names from the Plane-Alert DB often lead with the ICAO type
        # code as the first token (e.g. "B200 Super King Air"). Probe each
        # token against FUEL_BURN_GPH directly.
        for token in model_upper.replace("-", " ").replace(",", " ").split():
            candidate = FUEL_BURN_GPH.get(token)
            if candidate is not None:
                gph = candidate
                break
    if gph is None:
        # Fuzzy: check if any alias is a substring
        model_lower = model_clean.lower()
        for alias, code in _ALIASES.items():
            if alias.lower() in model_lower or model_lower in alias.lower():
                gph = FUEL_BURN_GPH.get(code)
                if gph:
                    break
    if gph is None:
        return None
    return {
        "fuel_gph": gph,
        "co2_kg_per_hour": round(gph * JET_A_CO2_KG_PER_GALLON, 1),
    }
