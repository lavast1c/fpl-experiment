"""Settings shared by the whole project: where files live and how politely we use the FPL API."""

from pathlib import Path

SEASON = "2026-27"

# --- Folders -------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"              # every API response, gzipped, one folder per gameweek
SNAPSHOT_DIR = DATA_DIR / "snapshots"   # the player table every agent receives
RULES_DIR = DATA_DIR / "rules"          # rule settings read from the API
TEST_CACHE_DIR = DATA_DIR / "test_cache"  # phase 3 scorer check only: git-ignored, deleted after use

# --- FPL API -------------------------------------------------------------
API_BASE = "https://fantasy.premierleague.com/api/"

# The only endpoints this project may read (regular expressions for the whole path).
# Anything else must be added here on purpose and recorded in METHODS.md.
ALLOWED_ENDPOINTS = (
    r"bootstrap-static/",
    r"fixtures/",
    r"event-status/",
    r"event/\d+/live/",            # official points and minutes per player, for scoring
)

# Endpoints about individual managers' teams. Used ONLY by the one-off scorer check
# (experiment/scorer_check.py), saved only in TEST_CACHE_DIR with names removed, then deleted.
TEST_ONLY_ENDPOINTS = (
    r"leagues-classic/314/standings/\?page_standings=\d+",   # 314 = the "Overall" league
    r"entry/\d+/history/",
    r"entry/\d+/event/\d+/picks/",
)

# Identify ourselves honestly. No cookies, logins or auth headers are ever sent.
USER_AGENT = "fpl-agents-experiment/0.1 (research project; https://github.com/lavast1c/fpl-experiment)"
REQUEST_TIMEOUT_SECONDS = 30

# Wait at least this long between two requests to the FPL API.
REQUEST_DELAY_SECONDS = 3.0

# Hard limit: how many times one endpoint may be downloaded per gameweek folder.
# Going over it needs --force, and is logged.
MAX_FETCHES_PER_GAMEWEEK = 4

# Reuse a cached response if it is younger than this (hours). Keys are ALLOWED_ENDPOINTS patterns.
CACHE_MAX_AGE_HOURS = {
    r"bootstrap-static/": 6,
    r"fixtures/": 6,
    r"event-status/": 1,
    r"event/\d+/live/": 6,
}

# --- Snapshot ------------------------------------------------------------
FIXTURES_AHEAD = 3            # how many upcoming gameweeks of fixtures each player row shows
CHARS_PER_TOKEN = 3.5         # rough token estimate (see METHODS.md); exact counts come from real calls
SNAPSHOT_FILTER = "all"   # fixed for the season on 2026-10-22 (see METHODS.md)

# --- Agents --------------------------------------------------------------
# Exact model IDs only. Never Fable, never aliases like "opus" (they can change mid-season).
MODELS = {"H": "claude-haiku-5-5", "S": "claude-sonnet-5-5", "O": "claude-opus-5-5"}
EFFORT = "medium"                       # the same for every agent (chosen 2026-10-22)
PROMPT_VERSION = "v2"                   # folder in prompts/; never edit a version once the season starts
                                        # (v2, 2026-10-22: FPL's ep_next removed from the player table)
PROMPTS_DIR = PROJECT_ROOT / "prompts"
CLAUDE_TIMEOUT_SECONDS = 900            # give up on one call after 15 minutes
DEADLINE_WARNING_HOURS = 3              # `decide` warns when the deadline is closer than this

# --- Where runs are saved -------------------------------------------------
# Real runs write into DATA_DIR (committed: the open dataset). Mock runs write into MOCK_DIR
# (git-ignored), so test data can never mix with real results.
MOCK_DIR = DATA_DIR / "mock"

# --- Memory (phase 5) -----------------------------------------------------
MEMORY_MAX_LESSONS = 8          # notes / lessons a memory team may keep (brief: ~8)
MEMORY_MAX_WORDS = 300          # total words across all notes / lessons (brief: ~300)
LESSON_MIN_USES = 5             # verified memory: decisions needed before a lesson can be removed
LESSON_REMOVE_BELOW = -1.0      # ... removed if its decisions averaged below this (points vs expected)
