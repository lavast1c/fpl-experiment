"""The fetch rules from the brief: cache, per-gameweek cap, allowed endpoints, no cookies."""

from datetime import datetime, timedelta, timezone

import pytest

from experiment import config, fetch
from experiment.files import read_csv

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class FakeHttp:
    """Stands in for requests.get and records every call."""

    def __init__(self, data):
        self.data = data
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.data)


@pytest.fixture(autouse=True)
def reset_rate_limit():
    fetch._last_request_at = None


def test_download_then_cache_hit(tmp_path):
    http = FakeHttp([{"id": 1}])
    first = fetch.get("fixtures/", 9, raw_dir=tmp_path, http_get=http, sleep=lambda s: None, now=NOW)
    second = fetch.get("fixtures/", 9, raw_dir=tmp_path, http_get=http, sleep=lambda s: None,
                       now=NOW + timedelta(hours=1))
    assert first == second == [{"id": 1}]
    assert len(http.calls) == 1  # second call came from the cache
    assert len(fetch.cached_files(tmp_path, 9, "fixtures/")) == 1
    log = read_csv(tmp_path / "fetch_log.csv")
    assert log[0]["endpoint"] == "fixtures/" and log[0]["gw"] == "9"


def test_stale_cache_downloads_again(tmp_path):
    http = FakeHttp([])
    fetch.get("fixtures/", 9, raw_dir=tmp_path, http_get=http, sleep=lambda s: None, now=NOW)
    fetch.get("fixtures/", 9, raw_dir=tmp_path, http_get=http, sleep=lambda s: None,
              now=NOW + timedelta(hours=7))
    assert len(http.calls) == 2


def test_cap_blocks_extra_downloads(tmp_path):
    http = FakeHttp([])
    for i in range(config.MAX_FETCHES_PER_GAMEWEEK):
        fetch.get("fixtures/", 9, raw_dir=tmp_path, http_get=http, sleep=lambda s: None,
                  now=NOW + timedelta(hours=7 * i))
    with pytest.raises(fetch.FetchCapReached):
        fetch.get("fixtures/", 9, raw_dir=tmp_path, http_get=http, sleep=lambda s: None,
                  now=NOW + timedelta(days=3))
    # --force allows it, with a warning
    fetch.get("fixtures/", 9, raw_dir=tmp_path, http_get=http, sleep=lambda s: None,
              now=NOW + timedelta(days=4), force=True)
    assert len(http.calls) == config.MAX_FETCHES_PER_GAMEWEEK + 1


def test_no_cookies_or_auth_sent(tmp_path):
    http = FakeHttp({})
    fetch.get("event-status/", 9, raw_dir=tmp_path, http_get=http, sleep=lambda s: None, now=NOW)
    url, kwargs = http.calls[0]
    assert url == config.API_BASE + "event-status/"
    assert "cookies" not in kwargs and "auth" not in kwargs
    assert set(kwargs["headers"]) == {"User-Agent", "Accept"}


def test_only_allowed_endpoints(tmp_path):
    http = FakeHttp({})
    with pytest.raises(ValueError):
        fetch.get("entry/123/history/", 9, raw_dir=tmp_path, http_get=http, sleep=lambda s: None, now=NOW)
    assert http.calls == []


def test_waits_between_requests(tmp_path):
    http = FakeHttp({})
    waits = []
    fetch.get("fixtures/", 9, raw_dir=tmp_path, http_get=http, sleep=waits.append, now=NOW)
    fetch.get("event-status/", 9, raw_dir=tmp_path, http_get=http, sleep=waits.append, now=NOW)
    assert len(waits) == 1 and 0 < waits[0] <= config.REQUEST_DELAY_SECONDS


def test_bootstrap_filed_under_decision_gameweek(tmp_path, bootstrap):
    http = FakeHttp(bootstrap)
    data, gw = fetch.get_bootstrap(raw_dir=tmp_path, http_get=http, sleep=lambda s: None, now=NOW)
    assert gw == 9
    assert fetch.latest_bootstrap(tmp_path)[1] == 9
    again, _ = fetch.get_bootstrap(raw_dir=tmp_path, http_get=http, sleep=lambda s: None,
                                   now=NOW + timedelta(hours=1))
    assert again == data and len(http.calls) == 1
