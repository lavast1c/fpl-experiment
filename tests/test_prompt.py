"""The weekly prompt: every placeholder is filled, and text an agent wrote can't change the template."""

import pytest

from experiment import prompt
from experiment.rules import load_rules
from experiment.team import TeamState


def build(memory_section=""):
    return prompt.build_prompt(TeamState("test"), {}, load_rules(), 9, "2026-10-31 11:00", "PLAYER TABLE",
                               memory_section, "self")


def test_every_placeholder_is_filled():
    text = build()
    assert "{{" not in text
    assert "PLAYER TABLE" in text and "gameweek 9" in text.lower()


def test_a_note_with_curly_brackets_is_kept_as_written():
    # An agent's own note goes into the prompt word for word: no error, and no player table pasted into it.
    note = "- watch {{players}} and {{ odd brackets"
    text = build(note)
    assert note in text
    assert text.count("PLAYER TABLE") == 1


def test_an_unknown_placeholder_in_the_template_is_an_error(monkeypatch):
    monkeypatch.setattr(prompt, "load_template", lambda name: "{{gameweek}} {{nothing_fills_this}}")
    with pytest.raises(ValueError, match="nothing_fills_this"):
        build()
