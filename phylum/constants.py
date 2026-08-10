from __future__ import annotations

SCHEMA_VERSION = 12
GRID_COLS = 48
GRID_ROWS = 30
MAP_SAMPLE_COLS = 96
MAP_SAMPLE_ROWS = 60
MAX_LIVING_SPECIES = 180
MAX_PATHOGENS = 48
MAX_SCARS = 40
MAX_EVENTS_IN_MEMORY = 200
CHECKPOINT_INTERVAL = 25

EVENT_PRIORITY = {
    "mass_extinction": 120,
    "contact": 115,
    "extinction": 105,
    "pandemic": 100,
    "speciation": 90,
    "innovation": 88,
    "tool_use": 96,
    "culture": 86,
    "communication": 74,
    "learning": 70,
    "behavior": 58,
    "metamorphosis": 76,
    "symbiosis": 66,
    "life_history": 60,
    "tectonic": 82,
    "era": 80,
    "disease": 75,
    "disaster": 72,
    "predation": 62,
    "migration": 55,
    "competition": 50,
    "climate": 45,
    "observation": 10,
    "origin": 5,
}

ADJECTIVES = [
    "ashen", "brine", "cinder", "glass", "hollow", "ivory", "mire", "pale",
    "rust", "sable", "silt", "still", "thorn", "velvet", "wither", "wound",
    "amber", "basalt", "frost", "lumen", "marrow", "salt", "shale", "silver",
]
NOUNS = [
    "branch", "choir", "crawler", "fan", "filament", "gill", "lace", "mote",
    "petal", "reed", "ribbon", "spine", "veil", "worm", "frond", "bell",
    "crown", "sail", "thorn", "mat", "ray", "coil", "sponge", "mantle",
]

PATHOGEN_PREFIX = ["ashen", "black", "glass", "red", "pale", "salt", "white", "silent", "hollow", "cold"]
PATHOGEN_NOUN = ["rot", "fever", "blight", "wilt", "pox", "veil", "mold", "flux", "rash", "spore"]

ERA_PREFIXES = [
    "Origin", "Radiant", "Ash", "Drift", "Verdant", "Pale", "Rift", "Flood",
    "Glass", "Cinder", "Silent", "Thorn", "Deep", "Brine", "Hollow", "Second",
]
ERA_SUFFIXES = ["Era", "Age", "Interval", "Period", "Epoch"]

TRAIT_BOUNDS = {
    "temp_pref": (0.02, 0.98),
    "moisture_pref": (0.02, 0.98),
    "tolerance": (0.08, 0.65),
    "mobility": (0.02, 0.75),
    "fecundity": (0.04, 0.88),
    "body_size": (0.12, 12.0),
    "attack": (0.0, 1.0),
    "defense": (0.0, 1.0),
    "speed": (0.0, 1.0),
    "immune": (0.0, 1.0),
    "sociality": (0.0, 1.0),
    "aggression": (0.0, 1.0),
    "burrowing": (0.0, 1.0),
    "nocturnal": (0.0, 1.0),
    "armor": (0.0, 1.0),
    "sensory": (0.0, 1.0),
    "complexity": (0.0, 1.0),
    "engineering": (0.0, 1.0),
    "sexuality": (0.0, 1.0),
    "recombination": (0.0, 1.0),
    "lifespan": (0.05, 1.0),
    "autotrophy": (0.0, 1.0),
    "herbivory": (0.0, 1.0),
    "carnivory": (0.0, 1.0),
    "detritivory": (0.0, 1.0),
    "aquatic": (0.0, 1.0),
}

BIOME_LABELS = {
    "abyss": "DEEP OCEAN",
    "shelf": "SHALLOW SEA",
    "ice": "ICE SHEET",
    "tundra": "TUNDRA",
    "alpine": "ALPINE",
    "desert": "DESERT",
    "steppe": "STEPPE",
    "temperate": "TEMPERATE FOREST",
    "wetland": "WETLAND",
    "rainforest": "TROPICAL WETLAND",
    "barren": "BARRENS",
}
