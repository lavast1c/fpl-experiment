"""Phone alerts (notify.py): sent only when a topic is set, and never stop a run. No real network."""

import pytest
import requests

from experiment import notify


class FakeResponse:
    def raise_for_status(self):
        pass


@pytest.fixture(autouse=True)
def no_env_file(monkeypatch):
    monkeypatch.setattr(notify, "load_dotenv", lambda path: None)


def test_without_a_topic_nothing_is_sent(monkeypatch):
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: pytest.fail("an alert was sent"))
    notify.send("FPL experiment", "Gameweek 8 scored.")


def test_an_alert_goes_to_the_topic(monkeypatch):
    sent = {}

    def fake_post(url, data, headers, timeout):
        sent.update(url=url, data=data, headers=headers)
        return FakeResponse()

    monkeypatch.setenv("NTFY_TOPIC", "made-up-topic")
    monkeypatch.setattr(requests, "post", fake_post)
    notify.send("FPL experiment: problem", "The picks failed: no internet.", problem=True)
    assert sent["url"] == "https://ntfy.sh/made-up-topic"
    assert sent["data"] == "The picks failed: no internet.".encode("utf-8")
    assert sent["headers"]["Title"] == "FPL experiment: problem"
    assert sent["headers"]["Priority"] == "high"


def test_a_failed_alert_does_not_stop_the_run(monkeypatch, capsys):
    def offline(*args, **kwargs):
        raise requests.ConnectionError("no internet")

    monkeypatch.setenv("NTFY_TOPIC", "made-up-topic")
    monkeypatch.setattr(requests, "post", offline)
    notify.send("FPL experiment", "Gameweek 8 scored.")
    assert "could not be sent" in capsys.readouterr().out
