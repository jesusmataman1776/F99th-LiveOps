"""Read-only hourly checks of the publishers' stable releases."""
import copy
import json
import re
import threading
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen

SOURCES = {
    'dcs': 'https://www.digitalcombatsimulator.com/en/news/changelog/',
    'srs': 'https://api.github.com/repos/ciribob/DCS-SimpleRadioStandalone/releases/latest',
    'bot': 'https://api.github.com/repos/Special-K-s-Flightsim-Bots/DCSServerBot/releases/latest',
}
LINKS = {
    'dcs': SOURCES['dcs'],
    'srs': 'https://github.com/ciribob/DCS-SimpleRadioStandalone/releases/latest',
    'bot': 'https://github.com/Special-K-s-Flightsim-Bots/DCSServerBot/releases/latest',
}
_lock = threading.Lock()
_state = {key: {'version': None, 'checked_at': None, 'stale': True, 'source': LINKS[key]} for key in SOURCES}

def parse_version(key, text):
    if key == 'dcs':
        match = re.search(r'\bDCS\s+(\d+\.\d+\.\d+\.\d+)\b', text)
        version = match.group(1) if match else ''
    else:
        data = json.loads(text)
        if data.get('draft') or data.get('prerelease'):
            raise ValueError('Not a stable release')
        version = data.get('tag_name', '').removeprefix('v')
    if not re.fullmatch(r'\d{1,3}(?:\.\d{1,6}){3}', version):
        raise ValueError('Release version missing')
    return version

def snapshot():
    with _lock:
        return copy.deepcopy(_state)

def refresh():
    for key, url in SOURCES.items():
        try:
            request = Request(url, headers={'User-Agent': 'F99th-LiveOps/1.0', 'Accept': 'text/html' if key == 'dcs' else 'application/json'})
            with urlopen(request, timeout=12) as response:
                body = response.read(2_000_001)
            if len(body) > 2_000_000:
                raise ValueError('Response too large')
            version = parse_version(key, body.decode('utf-8'))
            with _lock:
                _state[key].update(version=version, checked_at=datetime.now(timezone.utc).isoformat(), stale=False)
        except Exception:
            with _lock:
                _state[key]['stale'] = True

def poll():
    while True:
        refresh()
        time.sleep(3600)
