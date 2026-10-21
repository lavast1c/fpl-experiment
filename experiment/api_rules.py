"""Save the rule settings the FPL API publishes, so rules are read from data, not from memory.

Writes data/rules/{season}_api_rules.json. The validator (phase 2) reads its rules from here,
and anything it needs that is NOT in this file goes on the "couldn't verify" list.
"""

from pathlib import Path

from . import config
from .files import write_json


def extract_rules(bootstrap: dict) -> dict:
    return {
        "season": config.SEASON,
        "game_settings": bootstrap.get("game_settings"),
        "game_config": bootstrap.get("game_config"),
        "chips": bootstrap.get("chips"),
        # Squad limits per position live on element_types (squad_select, squad_min_play, ...).
        "positions": [
            {k: v for k, v in p.items() if k.startswith(("id", "singular", "plural", "squad", "ui_shirt"))}
            for p in bootstrap.get("element_types", [])
        ],
        "number_of_gameweeks": len(bootstrap.get("events", [])),
        "number_of_players": len(bootstrap.get("elements", [])),
    }


def save_rules(bootstrap: dict, source_file: str, out_dir: Path = config.RULES_DIR) -> Path:
    rules = extract_rules(bootstrap)
    rules["source_file"] = source_file
    path = out_dir / f"{config.SEASON}_api_rules.json"
    write_json(path, rules)
    return path
