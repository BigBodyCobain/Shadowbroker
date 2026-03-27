"""
Fuel burn & CO2 emissions estimator for private jets.
Based on manufacturer-published cruise fuel burn rates (GPH at long-range cruise).
1 US gallon of Jet-A produces ~21.1 lbs (9.57 kg) of CO2.
"""

JET_A_CO2_KG_PER_GALLON = 9.57

# ICAO type code -> gallons per hour at long-range cruise
FUEL_BURN_GPH: dict[str, int] = {
    # Gulfstream
    "GLF6": 430,   # G650/G650ER
    "G700": 480,   # G700
    "GLF5": 390,   # G550
    "GVSP": 400,   # GV-SP
    "GLF4": 330,   # G-IV
    # Bombardier
    "GL7T": 490,   # Global 7500
    "GLEX": 430,   # Global Express/6000/6500
    "GL5T": 420,   # Global 5000/5500
    "CL35": 220,   # Challenger 350
    "CL60": 310,   # Challenger 604/605
    "CL30": 200,   # Challenger 300
    "CL65": 320,   # Challenger 650
    # Dassault
    "F7X":  350,   # Falcon 7X
    "F8X":  370,   # Falcon 8X
    "F900": 285,   # Falcon 900/900EX/900LX
    "F2TH": 230,   # Falcon 2000
    "FA50": 240,   # Falcon 50
    # Cessna
    "CITX": 280,   # Citation X
    "C68A": 195,   # Citation Latitude
    "C700": 230,   # Citation Longitude
    "C680": 220,   # Citation Sovereign
    "C560": 190,   # Citation Excel/XLS
    "C510": 75,    # Citation Mustang
    "CJ3":  120,   # CJ3
    "CJ4":  135,   # CJ4
    # Boeing
    "B737": 850,   # BBJ (737)
    "B738": 920,   # BBJ2 (737-800)
    "B752": 1100,  # 757-200
    "B762": 1400,  # 767-200
    "B788": 1200,  # 787-8
    # Airbus
    "A318": 780,   # ACJ318
    "A319": 850,   # ACJ319
    "A320": 900,   # ACJ320
    "A343": 1800,  # A340-300
    "A346": 2100,  # A340-600
    # Pilatus
    "PC24": 115,   # PC-24
    "PC12": 60,    # PC-12
    # Embraer
    "E55P": 185,   # Legacy 500
    "E135": 300,   # Legacy 600/650
    "E50P": 135,   # Phenom 300
    "E500": 80,    # Phenom 100
    # Learjet
    "LJ60": 195,   # Learjet 60
    "LJ75": 185,   # Learjet 75
    "LJ45": 175,   # Learjet 45
    # Hawker
    "H25B": 210,   # Hawker 800/800XP
    "H25C": 215,   # Hawker 900XP
    # Beechcraft
    "B350": 100,   # King Air 350
    "B200": 80,    # King Air 200/250
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
    # Try direct ICAO code match first
    gph = FUEL_BURN_GPH.get(model_clean.upper())
    if gph is None:
        # Try alias lookup
        code = _ALIASES.get(model_clean)
        if code:
            gph = FUEL_BURN_GPH.get(code)
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
