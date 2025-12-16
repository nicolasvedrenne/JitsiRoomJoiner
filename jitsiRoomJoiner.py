#!/usr/bin/env python3
import os
import subprocess
import sys
from datetime import datetime
from typing import Optional
from urllib.parse import quote

import requests
from dateutil.tz import tzlocal
from icalendar import Calendar

FIREFOX = os.environ.get("FIREFOX_BIN", "/usr/bin/firefox")
PROFILE = os.environ.get("FIREFOX_PROFILE", "meetingroom")
LOCKFILE = os.environ.get("JITSI_LOCKFILE", "/tmp/jitsi_meeting.lock")
ICS_SOURCE = os.environ.get("ICS_URL")
REQUEST_TIMEOUT = float(os.environ.get("ICS_TIMEOUT", "20"))
VISIO_BASE = os.environ.get("VISIO_BASE")
DISPLAY_NAME = os.environ.get("DISPLAY_NAME", "JitsiRoomJoiner")


def log(message: str) -> None:
    print(message, file=sys.stderr)


def normalize_dt(value) -> Optional[datetime]:
    """Return a timezone-aware datetime in local tz or None."""
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=tzlocal())
    return value.astimezone(tzlocal())


def get_datetime(event, field: str) -> Optional[datetime]:
    raw = event.get(field)
    if raw is None:
        return None
    raw = getattr(raw, "dt", raw)
    return normalize_dt(raw)

def extract_url(event) -> Optional[str]:
    conf_id = event.get("x-conference-id") or event.get("X-CONFERENCE-ID")
    if conf_id:
        return f'{VISIO_BASE}{conf_id}#userInfo.displayName="{quote(DISPLAY_NAME)}"&config.prejoinConfig.enabled=false&config.startWithAudioMuted=false&config.startWithVideoMuted=false'
    return None


def read_calendar(source: str) -> Calendar:
    if source.startswith("http"):
        resp = requests.get(source, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.content
    else:
        with open(source, "rb") as fh:
            data = fh.read()
    return Calendar.from_ical(data)


def find_active_event(cal: Calendar, now: datetime):
    events = []
    for ev in cal.walk("VEVENT"):
        start = get_datetime(ev, "dtstart")
        end = get_datetime(ev, "dtend")
        if not start or not end:
            continue
        events.append((start, end, ev))

    events.sort(key=lambda item: item[0])

    for start, end, ev in events:
        if start <= now < end:
            return ev
    return None


def stop_meeting():
    if not os.path.exists(LOCKFILE):
        return
    try:
        os.remove(LOCKFILE)
    except OSError:
        pass

    pattern = f"{os.path.basename(FIREFOX)}.*-P {PROFILE}"
    subprocess.run(["pkill", "-f", pattern], check=False)


def launch_meeting(url: str):
    # Avoid relaunching if already on the same URL
    if os.path.exists(LOCKFILE):
        try:
            with open(LOCKFILE, "r", encoding="utf-8") as fh:
                current = fh.read().strip()
        except OSError:
            current = ""
        if current == url:
            return
        stop_meeting()

    with open(LOCKFILE, "w", encoding="utf-8") as fh:
        fh.write(url)

    subprocess.Popen(
        [
            FIREFOX,
            "-P",
            PROFILE,
            "--kiosk",
            url,
        ]
    )


def main():
    if not ICS_SOURCE:
        log("Configurez ICS_URL avant d'executer le script.")
        sys.exit(1)

    now = datetime.now(tzlocal())

    try:
        cal = read_calendar(ICS_SOURCE)
    except Exception as exc:  # noqa: BLE001 - surface the actual problem
        log(f"Impossible de lire le calendrier ({exc}).")
        stop_meeting()
        sys.exit(1)

    event = find_active_event(cal, now)
    if not event:
        log(f"Pas d\'event en cours.")
        stop_meeting()
        return

    url = extract_url(event)
    if not url:
        log("Aucun lien detecte pour l'evenement en cours.")
        stop_meeting()
        return

    log(f"Connexion à la réunion: {url}")
    launch_meeting(url)


if __name__ == "__main__":
    main()
