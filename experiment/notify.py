"""Pop-up messages on the computer that runs the experiment (automation.py).

Windows only: a standard Windows notification, shown through Windows PowerShell so nothing extra
needs installing. On other systems, and if anything goes wrong, the message is only printed.
"""

import os
import subprocess
import sys

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# The text arrives in environment variables and is escaped before it goes into the notification's XML.
TOAST_SCRIPT = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$title = [Security.SecurityElement]::Escape($env:FPL_POPUP_TITLE)
$text = [Security.SecurityElement]::Escape($env:FPL_POPUP_TEXT)
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$title</text><text>$text</text></binding></visual></toast>")
# Windows PowerShell's own app id, so the notification needs no registered app of its own.
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show((New-Object Windows.UI.Notifications.ToastNotification $xml))
"""


def popup(title: str, text: str) -> None:
    print(f"  pop-up: {title}: {text}")
    if sys.platform != "win32":
        return
    env = {**os.environ, "FPL_POPUP_TITLE": title, "FPL_POPUP_TEXT": text}
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", TOAST_SCRIPT],
                       env=env, capture_output=True, timeout=60, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as error:
        print(f"  (the pop-up could not be shown: {error})")
