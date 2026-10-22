"""Memory for the 6 memory teams (brief section 3.1).

Self-written memory ("self"):
    The agent sees last gameweek's results and its own notes, and returns `updated_notes`
    (at most MEMORY_MAX_LESSONS notes and MEMORY_MAX_WORDS words). We never edit them.

Verified memory ("verified"):
    Like self-written memory, but the notes are lessons with ids (L1, L2, ...). The answer says
    which lessons to keep and which new ones to add, and every decision (each player sold,
    each player bought, the captain) cites the ids of the lessons that influenced it.
    Our code then scores each cited decision against FPL's expected points at decision time:
        player bought:  value = actual points - ep_next      (bought someone who beat expectations)
        player sold:    value = ep_next - actual points      (sold someone who fell short)
        captain:        value = actual points - ep_next
    A lesson cited in at least LESSON_MIN_USES decisions whose values average below
    LESSON_REMOVE_BELOW is removed, and the agent is told which one and why.

Memory files, per team, inside the run folder (data/ or data/mock/):
    memory/{team}/gw{N}.json        memory after the gameweek N decision
    memory/{team}/latest.json       current memory (also updated when lessons are checked)
    memory/{team}/evaluations.csv   verified only: every checked decision
"""

from copy import deepcopy
from pathlib import Path

from . import config
from .files import append_csv, read_json, write_json
from .validator import Error

REMINDER = "Your notes are advice, not commitments. Re-evaluate every decision from scratch."
EVALUATION_FIELDS = ["gw", "lesson", "decision", "player", "expected", "actual", "value"]


# --- loading and saving ------------------------------------------------------------------------

def empty_memory(kind: str) -> dict:
    if kind == "self":
        return {"kind": "self", "notes": []}
    return {"kind": "verified", "next_id": 1, "lessons": [], "pending": [], "removed_notices": []}


def load_memory(base: Path, team_id: str, kind: str) -> dict:
    path = base / "memory" / team_id / "latest.json"
    return read_json(path) if path.exists() else empty_memory(kind)


def save_memory(base: Path, team_id: str, memory: dict, gw: int | None = None) -> None:
    folder = base / "memory" / team_id
    write_json(folder / "latest.json", memory)
    if gw is not None:
        write_json(folder / f"gw{gw}.json", memory)


def active_lessons(memory: dict) -> list[dict]:
    return [lesson for lesson in memory["lessons"] if lesson["status"] == "active"]


def lesson_record(lesson: dict) -> tuple[int, float | None]:
    values = [use["value"] for use in lesson["uses"] if use["value"] is not None]
    return len(values), (sum(values) / len(values) if values else None)


# --- what the agent sees ----------------------------------------------------------------------

def last_week_text(last: dict | None) -> str:
    """Last gameweek's results for this team (built by runner.last_week_results)."""
    if last is None:
        return "Last gameweek's results: none yet (this is your first gameweek)."
    if last.get("missing"):
        return f"Last gameweek's results: gameweek {last['gw']} has not been scored yet."
    lines = [f"Last gameweek (gameweek {last['gw']}): you scored {last['net_points']} points"
             + (f" ({last['points']} minus a {last['hit_points']}-point transfer cost)" if last["hit_points"] else "")
             + (f". The average FPL manager scored {last['average']}." if last.get("average") is not None else ".")]
    if last.get("chip"):
        lines.append(f"Chip played: {last['chip']}.")
    if last.get("transfers"):
        lines.append("Transfers: " + "; ".join(
            f"sold {t['out_name']} ({t['out_points']} pts), bought {t['in_name']} ({t['in_points']} pts)"
            for t in last["transfers"]))
    lines.append("Your players (points, role):")
    lines += [f"- {p['name']}: {p['points']} ({p['role']})" for p in last["players"]]
    if last.get("auto_subs_detail"):
        lines.append("Automatic substitutions: " + "; ".join(last["auto_subs_detail"]))
    return "\n".join(lines)


def memory_section(kind: str, memory: dict, last: dict | None) -> str:
    parts = ["## Your memory", "", last_week_text(last), ""]
    if kind == "self":
        notes = memory["notes"]
        parts.append("Your notes (written by you):")
        parts += [f"- {n}" for n in notes] if notes else ["(none yet)"]
    else:
        parts.append("Your lessons (each decision you cite them for is checked against FPL's expected points; "
                     "see the answer format):")
        lessons = active_lessons(memory)
        for lesson in lessons:
            uses, average = lesson_record(lesson)
            record = f"used {uses} time(s), average {average:+.1f} points vs expected" if uses else "not used yet"
            parts.append(f"- {lesson['id']}: {lesson['text']} [{record}]")
        if not lessons:
            parts.append("(none yet)")
        if memory["removed_notices"]:
            parts.append("")
            parts.append("Lessons removed since your last decision:")
            parts += [f"- {n}" for n in memory["removed_notices"]]
    parts += ["", REMINDER]
    return "\n".join(parts)


def answer_fields(kind: str) -> str:
    limits = f"at most {config.MEMORY_MAX_LESSONS} items and {config.MEMORY_MAX_WORDS} words in total"
    if kind == "self":
        return (f"- updated_notes: your notes for next gameweek, as a list of short texts ({limits}). "
                "Next gameweek you will see them together with this gameweek's results. Write whatever you want to remember.")
    return "\n".join([
        f'- lessons: {{"keep": [ids of your current lessons to keep], "new": [texts of new lessons]}} ({limits}, '
        "kept and new together). A kept lesson's text can't be changed: to change one, don't keep it and add a new one. "
        "New lessons get an id next gameweek.",
        '- lesson citations: in every transfer add "out_lesson_ids" and "in_lesson_ids", and add "captain_lesson_ids": '
        "the ids of your current lessons that influenced selling that player, buying that player and choosing your "
        "captain ([] if none). After the gameweek each cited decision is checked against FPL's expected points "
        "(ep_next) at the time: a player bought or a captain who scores above his ep_next counts as positive, a player "
        "sold who scores below his ep_next counts as positive. A lesson cited in at least "
        f"{config.LESSON_MIN_USES} decisions whose decisions average more than {-config.LESSON_REMOVE_BELOW:g} point "
        "below expected is removed.",
    ])


def schema_extras(kind: str) -> tuple[dict, dict]:
    """Extra answer fields: (top-level properties, properties added to each transfer)."""
    ids = {"type": "array", "items": {"type": "string"}}
    if kind == "self":
        return {"updated_notes": {"type": "array", "items": {"type": "string"}}}, {}
    lessons = {"type": "object", "properties": {"keep": ids, "new": {"type": "array", "items": {"type": "string"}}},
               "required": ["keep", "new"], "additionalProperties": False}
    return {"lessons": lessons, "captain_lesson_ids": ids}, {"out_lesson_ids": ids, "in_lesson_ids": ids}


# --- checking the memory part of an answer ----------------------------------------------------

def _length_errors(texts: list[str]) -> list[Error]:
    errors = []
    if len(texts) > config.MEMORY_MAX_LESSONS:
        errors.append(Error("MEMORY_TOO_MANY", f"{len(texts)} notes/lessons; the maximum is {config.MEMORY_MAX_LESSONS}."))
    words = sum(len(t.split()) for t in texts)
    if words > config.MEMORY_MAX_WORDS:
        errors.append(Error("MEMORY_TOO_LONG", f"{words} words in total; the maximum is {config.MEMORY_MAX_WORDS}."))
    return errors


def check_answer(kind: str, answer, memory: dict) -> list[Error]:
    if not isinstance(answer, dict):
        return []   # the validator already reports NOT_AN_OBJECT
    if kind == "self":
        notes = answer.get("updated_notes")
        if not isinstance(notes, list) or not all(isinstance(n, str) for n in notes):
            return [Error("MEMORY_FORMAT", "updated_notes must be a list of texts.")]
        return _length_errors(notes)

    lessons = answer.get("lessons")
    if not isinstance(lessons, dict) or not isinstance(lessons.get("keep"), list) or not isinstance(lessons.get("new"), list):
        return [Error("MEMORY_FORMAT", 'lessons must look like {"keep": [...], "new": [...]}.')]
    active = {lesson["id"]: lesson for lesson in active_lessons(memory)}
    errors = []
    unknown = [i for i in lessons["keep"] if i not in active]
    if unknown:
        errors.append(Error("LESSON_UNKNOWN", f"Can't keep lessons that don't exist: {unknown}. Current: {sorted(active)}."))
    kept_texts = [active[i]["text"] for i in lessons["keep"] if i in active]
    errors += _length_errors(kept_texts + [t for t in lessons["new"] if isinstance(t, str)])

    cited = list(answer.get("captain_lesson_ids") or [])
    for t in answer.get("transfers") or []:
        if isinstance(t, dict):
            cited += list(t.get("out_lesson_ids") or []) + list(t.get("in_lesson_ids") or [])
    bad = sorted({c for c in cited if c not in active})
    if bad:
        errors.append(Error("LESSON_CITATION_UNKNOWN",
                            f"Cited lessons that aren't current lessons: {bad}. Current: {sorted(active)}."))
    return errors


# --- updating memory after an accepted answer ------------------------------------------------

def apply_answer(kind: str, answer: dict, memory: dict, gw: int, expected: dict[int, float]) -> dict:
    """New memory after an accepted decision. `expected` maps player id -> ep_next at decision time."""
    memory = deepcopy(memory)
    if kind == "self":
        memory["notes"] = list(answer["updated_notes"])
        return memory

    memory["removed_notices"] = []   # they have now been shown once
    # Remember which decisions cited which lessons; they are checked after the gameweek is scored.
    def cite(ids, decision, player):
        for lesson_id in ids or []:
            memory["pending"].append({"gw": gw, "lesson": lesson_id, "decision": decision, "player": player,
                                      "expected": expected.get(player, 0.0)})
    for t in answer.get("transfers") or []:
        cite(t.get("out_lesson_ids"), "sold", t["out"])
        cite(t.get("in_lesson_ids"), "bought", t["in"])
    cite(answer.get("captain_lesson_ids"), "captain", answer["captain"])

    keep = set(answer["lessons"]["keep"])
    for lesson in active_lessons(memory):
        if lesson["id"] not in keep:
            lesson["status"], lesson["ended_gw"] = "dropped_by_agent", gw
    for text in answer["lessons"]["new"]:
        memory["lessons"].append({"id": f"L{memory['next_id']}", "text": text, "created_gw": gw,
                                  "status": "active", "uses": []})
        memory["next_id"] += 1
    return memory


# --- checking lessons after a gameweek is scored (verified only) ------------------------------

def evaluate(memory: dict, gw: int, points: dict[int, int], csv_path: Path | None = None) -> dict:
    """Score the decisions made in gameweek `gw` and remove lessons that fail the rule."""
    memory = deepcopy(memory)
    lessons = {lesson["id"]: lesson for lesson in memory["lessons"]}
    still_pending = []
    for use in memory["pending"]:
        if use["gw"] != gw:
            still_pending.append(use)
            continue
        actual = points.get(use["player"], 0)
        value = (use["expected"] - actual) if use["decision"] == "sold" else (actual - use["expected"])
        record = {**use, "actual": actual, "value": round(value, 2)}
        lessons[use["lesson"]]["uses"].append(record)
        if csv_path is not None:
            append_csv(csv_path, {k: record[k] for k in EVALUATION_FIELDS}, EVALUATION_FIELDS)
    memory["pending"] = still_pending

    for lesson in active_lessons(memory):
        uses, average = lesson_record(lesson)
        if uses >= config.LESSON_MIN_USES and average < config.LESSON_REMOVE_BELOW:
            lesson["status"], lesson["ended_gw"] = "removed", gw
            reason = (f"{lesson['id']} (\"{lesson['text']}\") was removed after gameweek {gw}: the {uses} decisions "
                      f"that cited it averaged {average:+.1f} points vs expected (removal below "
                      f"{config.LESSON_REMOVE_BELOW:+.1f} after at least {config.LESSON_MIN_USES} uses).")
            memory["removed_notices"].append(reason)
    return memory
