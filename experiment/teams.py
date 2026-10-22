"""The 9 AI teams: 3 models x 3 memory types (brief section 3.1)."""

from dataclasses import dataclass

from . import config

MEMORY_TYPES = ("none", "self", "verified")
ALLOWED_MODELS = set(config.MODELS.values())


@dataclass(frozen=True)
class Team:
    id: str          # e.g. "S-self"
    model: str       # exact model ID
    memory: str      # none / self / verified


TEAMS = [Team(f"{letter}-{memory}", model, memory)
         for letter, model in config.MODELS.items() for memory in MEMORY_TYPES]


def starting_squad_source(team: Team) -> str | None:
    """Shared start (METHODS.md, 2026-10-22): a memory team's first squad is a copy of the squad its
    model's no-memory team picked, so the three memory types of a model start from the same squad."""
    return None if team.memory == "none" else f"{team.id.split('-')[0]}-none"


def check_model(model: str) -> None:
    """Refuse anything but the three exact model IDs (no Fable, no aliases)."""
    if model not in ALLOWED_MODELS or "fable" in model.lower():
        raise ValueError(f"Model {model!r} is not allowed. Use one of {sorted(ALLOWED_MODELS)}.")


for _team in TEAMS:
    check_model(_team.model)
