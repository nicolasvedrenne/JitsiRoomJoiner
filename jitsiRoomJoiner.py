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
    now = datetime.now(tzlocal()).isoformat(timespec="seconds")
    print(f"[{now}] {message}", file=sys.stderr, flush=True)


def log_environment() -> None:
    wayland = os.environ.get("WAYLAND_DISPLAY", "")
    display = os.environ.get("DISPLAY", "")
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "")
    log(f"Env WAYLAND_DISPLAY={wayland!r} DISPLAY={display!r} XDG_RUNTIME_DIR={runtime_dir!r}")


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


def firefox_pattern(profile: str) -> str:
    return f"{os.path.basename(FIREFOX)}.*-P {profile}"


def firefox_running(profile: str) -> bool:
    pattern = firefox_pattern(profile)
    proc = subprocess.run(
        ["pgrep", "-f", pattern],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc.returncode == 0


def cleanup_stale_lock() -> None:
    if not os.path.exists(LOCKFILE):
        return
    if firefox_running(PROFILE):
        return
    try:
        os.remove(LOCKFILE)
        log("Lockfile supprimé (aucun processus Firefox détecté).")
    except OSError as exc:  # noqa: BLE001
        log(f"Impossible de supprimer le lockfile {LOCKFILE}: {exc}")


def stop_meeting():
    pattern = firefox_pattern(PROFILE)
    if firefox_running(PROFILE):
        subprocess.run(["pkill", "-f", pattern], check=False)
        log("Firefox arrêté.")

    if os.path.exists(LOCKFILE):
        try:
            os.remove(LOCKFILE)
            log("Lockfile supprimé.")
        except OSError as exc:  # noqa: BLE001
            log(f"Impossible de supprimer le lockfile {LOCKFILE}: {exc}")


def launch_meeting(url: str):
    cleanup_stale_lock()

    # Avoid relaunching if already on the same URL
    if os.path.exists(LOCKFILE):
        try:
            with open(LOCKFILE, "r", encoding="utf-8") as fh:
                current = fh.read().strip()
        except OSError:
            current = ""
        if current == url:
            log("Déjà connecté sur cette réunion, rien à faire.")
            return
        stop_meeting()

    try:
        with open(LOCKFILE, "w", encoding="utf-8") as fh:
            fh.write(url)
    except OSError as exc:  # noqa: BLE001
        log(f"Impossible d'écrire le lockfile {LOCKFILE}: {exc}")
        return

    cmd = [
        FIREFOX,
        "-P",
        PROFILE,
        "--no-remote",
        "--new-instance",
        "--kiosk",
        url,
    ]
    log(f"Lancement Firefox: {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        log(f"Firefox introuvable: {exc}")
        stop_meeting()
        return
    except OSError as exc:  # noqa: BLE001
        log(f"Echec de démarrage de Firefox: {exc}")
        stop_meeting()
        return

    try:
        _, stderr_output = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        if proc.stderr:
            proc.stderr.close()
        log("Firefox semble démarré (processus toujours en cours après 5s).")
        return

    stderr_text = ""
    if stderr_output:
        stderr_text = stderr_output.decode("utf-8", errors="replace").strip()

    if proc.returncode != 0:
        log(f"Firefox s'est arrêté immédiatement (code {proc.returncode}).")
        if stderr_text:
            log(f"stderr Firefox: {stderr_text}")
        stop_meeting()
    else:
        if stderr_text:
            log(f"Firefox a renvoyé un code 0 immédiatement. stderr: {stderr_text}")
        stop_meeting()


def main():
    if not ICS_SOURCE:
        log("Configurez ICS_URL avant d'executer le script.")
        sys.exit(1)

    now = datetime.now(tzlocal())

    log_environment()
    cleanup_stale_lock()

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
