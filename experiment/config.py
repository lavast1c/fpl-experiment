"""Settings shared by the whole project: where files live and how politely we use the FPL API."""

from pathlib import Path

SEASON = "2026-27"

# --- Folders -------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"              # every API response, gzipped, one folder per gameweek
SNAPSHOT_DIR = DATA_DIR / "snapshots"   # the player table every agent receives
RULES_DIR = DATA_DIR / "rules"          # rule settings read from the API

# --- FPL API -------------------------------------------------------------
API_BASE = "https://fantasy.premierleague.com/api/"

# The only endpoints this project is allowed to read in phase 1.
# Anything else must be added here on purpose (see METHODS.md).
ALLOWED_ENDPOINTS = ("bootstrap-static/", "fixtures/", "event-status/")

# Identify ourselves honestly. No cookies, logins or auth headers are ever sent.
USER_AGENT = "fpl-agents-experiment/0.1 (research project; https://github.com/lavast1c/fpl-experiment)"
REQUEST_TIMEOUT_SECONDS = 30

# Wait at least this long between two requests to the FPL API.
REQUEST_DELAY_SECONDS = 3.0

# Hard limit: how many times one endpoint may be downloaded per gameweek folder.
# Going over it needs --force, and is logged.
MAX_FETCHES_PER_GAMEWEEK = 4

# Reuse a cached response if it is younger than this (hours).
CACHE_MAX_AGE_HOURS = {
    "bootstrap-static/": 6,
    "fixtures/": 6,
    "event-status/": 1,
}

# --- Snapshot ------------------------------------------------------------
FIXTURES_AHEAD = 3            # how many upcoming gameweeks of fixtures each player row shows
CHARS_PER_TOKEN = 3.5         # rough token estimate (see METHODS.md); exact counts come from real calls
SNAPSHOT_FILTER = "all"   # chosen 2026-10-21 for now; must be fixed before the first real gameweek
