"""Phone alerts about the automatic runs (automation.py), through the free ntfy service (ntfy.sh).

The project owner's computer has Windows notifications switched off, so alerts go to the ntfy app on
their phone instead (METHODS.md, 2026-10-27). Each alert is posted to https://ntfy.sh/<topic>, where
the topic is a long random name kept in .env (NTFY_TOPIC). Anyone who knew the name could read the
alerts, but they only say what the public repository shows anyway. Without a topic, or if anything
goes wrong, the alert is only printed: an alert never stops a run.
"""

import os

import requests
from dotenv import load_dotenv

from . import config

MAX_CHARS = 1000   # ntfy turns long messages into attachments; alerts are a sentence or two


def send(title: str, text: str, problem: bool = False) -> bool:
    """Send one alert; True if ntfy accepted it."""
    print(f"  alert: {title}: {text}")
    load_dotenv(config.PROJECT_ROOT / ".env")
    topic = os.getenv("NTFY_TOPIC", "")
    if not topic:
        return False
    headers = {"Title": title, "Click": config.WEBSITE_URL, "Tags": "warning" if problem else "soccer"}
    if problem:
        headers["Priority"] = "high"
    try:
        response = requests.post(f"{config.NTFY_SERVER}/{topic}", data=text[:MAX_CHARS].encode("utf-8"),
                                 headers=headers, timeout=30)
        response.raise_for_status()
        return True
    except requests.RequestException as error:
        print(f"  (the alert could not be sent: {error})")
        return False
