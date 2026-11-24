"""F99th Live Operations v0.2.4-dev — stdlib-only, read-only localhost web app.

Public access is provided separately by an existing Tailscale Funnel to localhost:8765.
The app never accepts file uploads or changes DCS, SRS, or DCSServerBot settings.
"""
from __future__ import annotations

import argparse
import world_feed
import release_versions
import server_details
from live_details import red_authorized, red_access, public_status, clock_worker, internet_clock, dcs_version, srs_address
import csv
import io
import json
import math
import re
import zipfile
from functools import lru_cache
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
LIVEOPS_TELEMETRY = Path(r"C:\F99th\LiveOps\telemetry")
TELEMETRY_DIRS = (LIVEOPS_TELEMETRY, HERE / "telemetry")
MISSION_ROOTS = (Path(os.environ.get("F99TH_MISSION_ROOT", str(Path.home() / "Saved Games" / "DCS.dcs_serverrelease" / "Missions"))),)
STATUS_TTL = 8.0
_track_samples = {}
_track_mission = None
_track_lock = threading.Lock()


@lru_cache(maxsize=32)
def _archive_terrain(path: str, modified: int, size: int) -> str | None:
    # Read the mission member only. Never extract or execute mission Lua.
    try:
        with zipfile.ZipFile(path) as archive:
            member = archive.getinfo("mission")
            if member.file_size > 32_000_000:
                return None
            with archive.open(member) as stream:
                raw = stream.read(32_000_001).decode("utf-8-sig")
            matches = re.findall(r'(?:\[\s*["\']theatre["\']\s*\]|\btheatre)\s*=\s*["\']([A-Za-z0-9 _-]{1,80})["\']', raw)
            return matches[0] if matches and len(set(matches)) == 1 else None
    except (OSError, ValueError, KeyError, UnicodeError, zipfile.BadZipFile, RuntimeError):
        return None


def _mission_terrain(mission: str | None) -> str | None:
    if not mission:
        return None
    # Match the fresh active feed's exact basename, never the newest archive.
    candidates = []
    for root in MISSION_ROOTS:
        try:
            candidates.extend(p for p in root.rglob("*.miz") if p.stem.casefold() == mission.casefold())
        except OSError:
            continue
    if len(candidates) != 1:
        return None
    try:
        p = candidates[0]
        stat = p.stat()
        return _archive_terrain(str(p), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None


def _tracking(pilots: list, stamp: object) -> None:
    timestamp = _timestamp(stamp)
    if timestamp is None:
        return
    now = timestamp.timestamp()
    with _track_lock:
        keys = [(p["callsign"], p["coalition"], p["aircraft"]) for p in pilots]
        for p, key in zip(pilots, keys):
            if keys.count(key) != 1 or p["lat"] is None or p["lon"] is None:
                continue
            old = _track_samples.get(key)
            if old and now == old[0]:
                p["ground_speed_kt"] = p["ground_speed_kt"] if p["ground_speed_kt"] is not None else old[3]
                if p["ground_speed_kt"] is not None and p["speed_source"] is None:
                    p["speed_source"] = "position samples"
                continue
            derived = None
            if old and 1 <= now - old[0] <= PILOT_FRESH_SECONDS:
                lat1, lat2 = math.radians(old[1]), math.radians(p["lat"])
                dlat, dlon = lat2-lat1, math.radians(p["lon"]-old[2])
                a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
                meters = 6371008.8 * 2 * math.asin(math.sqrt(min(1, a)))
                speed = meters / (now-old[0]) * 1.943844492
                if speed <= 2000:
                    derived = round(speed, 1)
            if p["ground_speed_kt"] is None:
                p["ground_speed_kt"] = derived
                p["speed_source"] = "position samples" if derived is not None else None
            _track_samples[key] = (now, p["lat"], p["lon"], derived)
        for key in list(_track_samples):
            if key not in keys or now - _track_samples[key][0] > PILOT_FRESH_SECONDS:
                del _track_samples[key]

FRESH_SECONDS = 35
PILOT_FRESH_SECONDS = 25
_cache_lock = threading.Lock()
_cache: tuple[float, dict] = (0.0, {})


def _powershell(command: str, timeout: int = 8) -> str | None:
    if os.name != "nt":
        return None
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            text=True, capture_output=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _process_list() -> set[str] | None:
    if os.name != "nt":
        return None
    try:
        raw = subprocess.check_output(
            ["tasklist", "/fo", "csv", "/nh"],
            text=True, errors="replace", timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return {r[0].strip().lower() for r in csv.reader(io.StringIO(raw)) if r}
    except (OSError, subprocess.SubprocessError, IndexError):
        return None


def _bot_running() -> bool | None:
    raw = _powershell(
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -match 'run\\.py' -and "
        "($_.CommandLine -match 'dcssb' -or $_.CommandLine -match 'DCSServerBot') } | "
        "Select-Object -First 1 -ExpandProperty ProcessId"
    )
    return None if raw is None else bool(raw)


def _tcp_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.6):
            return True
    except OSError:
        return False


def _udp_bound(port: int) -> bool | None:
    # UDP cannot be "connected" using a TCP probe. Check a local bound UDP endpoint.
    raw = _powershell(
        f"Get-NetUDPEndpoint -LocalPort {port} -ErrorAction SilentlyContinue | "
        "Select-Object -First 1 -ExpandProperty LocalPort"
    )
    return None if raw is None else str(port) in raw.splitlines()


def _load_small_json(path: Path, max_bytes: int = 64_000) -> dict | None:
    try:
        if path.stat().st_size > max_bytes:
            return None
        with path.open("rb") as stream:
            raw = stream.read(max_bytes + 1)
        if len(raw) > max_bytes:
            return None
        obj = json.loads(raw.decode("utf-8-sig"))
        return obj if isinstance(obj, dict) else None
    except (OSError, ValueError, UnicodeError):
        return None


def _timestamp(raw: object) -> datetime | None:
    try:
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        if isinstance(raw, str) and raw:
            result = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return result if result.tzinfo else None
    except (OverflowError, OSError, ValueError):
        pass
    return None


def _fresh(raw: object, seconds: int) -> tuple[bool, int | None]:
    stamp = _timestamp(raw)
    if stamp is None:
        return False, None
    age = (datetime.now(timezone.utc) - stamp).total_seconds()
    return -30 <= age <= seconds, max(0, int(age))


def _clean_string(raw: object, limit: int = 110) -> str | None:
    if not isinstance(raw, str):
        return None
    result = "".join(ch for ch in raw if ch.isprintable()).strip()
    return result[:limit] if result else None


def _mission_telemetry() -> dict:
    # The existing project hook writes server_status.json in C:\F99th\LiveOps\telemetry.
    # A same-directory copy is supported for easy manual inspection / local testing.
    for folder in TELEMETRY_DIRS:
        path = folder / "server_status.json"
        obj = _load_small_json(path)
        if not obj:
            continue
        valid, age = _fresh(obj.get("stamp", obj.get("updated_at")), FRESH_SECONDS)
        if not valid:
            continue
        state = _clean_string(obj.get("mission_state"), 32)
        mission = _clean_string(obj.get("mission"))
        terrain = _clean_string(obj.get("terrain"), 80)
        if mission:
            mission = mission.replace("\\", "/").split("/")[-1]
            if mission.lower().endswith(".miz"):
                mission = mission[:-4]
        terrain = _mission_terrain(mission) or terrain
        count = obj.get("connected_players", obj.get("pilot_count"))
        count = count if type(count) is int and 0 <= count <= 200 else None
        elapsed = obj.get("mission_elapsed_seconds")
        elapsed = elapsed if type(elapsed) is int and 0 <= elapsed <= 86400 * 60 else None
        return {
            "connected": True, "mission": mission, "terrain": terrain,
            "pilot_count": count, "mission_state": state,
            "mission_elapsed_seconds": elapsed, "age_seconds": age,
        }
    return {
        "connected": False, "mission": None, "terrain": None,
        "pilot_count": None, "mission_state": None,
        "mission_elapsed_seconds": None, "age_seconds": None,
    }


def _num(raw: object, low: float | None = None, high: float | None = None) -> float | None:
    if type(raw) not in (float, int):
        return None
    n = float(raw)
    if not math.isfinite(n) or (low is not None and n < low) or (high is not None and n > high):
        return None
    return n


def _pilots_telemetry() -> dict:
    # This is ONLY a reader. It does not fabricate pilots or fetch admin data.
    for folder in TELEMETRY_DIRS:
        path = folder / "pilots.json"
        obj = _load_small_json(path, 150_000)
        if not obj:
            continue
        stamp = obj.get("stamp", obj.get("updated_at"))
        if stamp is None:
            try:
                stamp = path.stat().st_mtime
            except OSError:
                continue
        valid, age = _fresh(stamp, PILOT_FRESH_SECONDS)
        if not valid:
            continue
        entries = obj.get("pilots")
        if not isinstance(entries, list):
            continue
        pilots = []
        for item in entries[:200]:
            if not isinstance(item, dict):
                continue
            coalition = _clean_string(item.get("coalition"), 16) or "neutral"
            coalition = coalition.lower() if coalition.lower() in ("blue", "red") else "neutral"
            pilots.append({
                "callsign": _clean_string(item.get("callsign"), 64) or "Pilot",
                "aircraft": _clean_string(item.get("aircraft"), 64),
                "coalition": coalition,
                "lat": _num(item.get("lat"), -90, 90),
                "lon": _num(item.get("lon"), -180, 180),
                "altitude_ft": _num(item.get("altitude_ft"), -1000, 200000),
                "heading_deg": _num(item.get("heading_deg"), 0, 360),
                "ground_speed_kt": _num(item.get("ground_speed_kt"), 0, 2000),
                "speed_source": "telemetry" if _num(item.get("ground_speed_kt"), 0, 2000) is not None else None,
            })
        _tracking(pilots, stamp)
        return {"connected": True, "age_seconds": age, "pilots": pilots}
    with _track_lock:
        _track_samples.clear()
    return {"connected": False, "age_seconds": None, "pilots": []}


def _aircraft_telemetry(mission: str | None) -> dict:
    for folder in TELEMETRY_DIRS:
        obj = _load_small_json(folder / "mission_aircraft.json", 2_000_000)
        if not obj or obj.get("schema_version") != 1 or obj.get("full_scope") is not True:
            continue
        valid, age = _fresh(obj.get("stamp"), PILOT_FRESH_SECONDS)
        if not valid or not mission or obj.get("mission") != mission:
            continue
        entries = obj.get("aircraft")
        if not isinstance(entries, list):
            continue
        aircraft = []
        for item in entries[:2000]:
            if not isinstance(item, dict):
                continue
            lat, lon = _num(item.get("lat"), -90, 90), _num(item.get("lon"), -180, 180)
            if lat is None or lon is None:
                continue
            if item.get("is_player") is not True and item.get("airborne") is not True:
                continue
            aircraft.append({
                "callsign": _clean_string(item.get("callsign"), 64) or "Aircraft",
                "aircraft": _clean_string(item.get("aircraft"), 64),
                "coalition": item.get("coalition") if item.get("coalition") in ("blue", "red") else "neutral",
                "is_player": item.get("is_player") is True,
                "lat": lat, "lon": lon,
                "altitude_ft": _num(item.get("altitude_ft"), -1000, 200000),
                "heading_deg": _num(item.get("heading_deg"), 0, 360),
                "ground_speed_kt": _num(item.get("ground_speed_kt"), 0, 2000),
                "speed_source": "telemetry",
            })
        return {"connected": True, "age_seconds": age, "aircraft": aircraft}
    return {"connected": False, "age_seconds": None, "aircraft": []}


def _mission_conditions(mission):
    for folder in TELEMETRY_DIRS:
        obj = _load_small_json(folder / "mission_aircraft.json", 2_000_000)
        if not obj or not mission or obj.get("mission") != mission or not _fresh(obj.get("stamp"), PILOT_FRESH_SECONDS)[0]:
            continue
        return {"time_seconds": _num(obj.get("mission_time_seconds"), 0, 86400),
                "weather": _clean_string(obj.get("weather_summary"), 250)}
    return {"time_seconds": None, "weather": None}


def collect_status() -> dict:
    global _cache, _track_mission
    with _cache_lock:
        if time.monotonic() - _cache[0] < STATUS_TTL and _cache[1]:
            return _cache[1]
        processes = _process_list()
        dcs = ("dcs_server.exe" in processes or "dcs.exe" in processes) if processes is not None else None
        srs = any(name in processes for name in (
            "sr-server.exe", "srs-server-commandline.exe", "srs-server.exe"
        )) if processes is not None else None
        mission = _mission_telemetry()
        if mission.get("mission") != _track_mission:
            with _track_lock:
                _track_samples.clear()
            _track_mission = mission.get("mission")
        status = {
            "version": "0.2.4-dev", "server": "F99th3",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "checks": {
                "dcs_process": dcs, "dcs_game_port": _tcp_listening(10308),
                "srs_process": srs, "srs_udp_bound": _udp_bound(5002),
                "discord_bot": _bot_running(),
            },
            "telemetry": mission,
            "dcs_version": dcs_version(),
            "srs_address": srs_address(),
            "srs_tcp": _tcp_listening(5002),
            "conditions": _mission_conditions(mission.get("mission")),
            "services": server_details.services(MISSION_ROOTS[0].parent),
            "briefing": server_details.mission_details(mission.get("mission"), MISSION_ROOTS).get("briefing"),
            "aircraft": _aircraft_telemetry(mission.get("mission")),
            "roster": _pilots_telemetry(),
            "read_only": True,
        }
        _cache = (time.monotonic(), status)
        return status


ASSETS = {
    "/mgrs.js": ("mgrs.js", "text/javascript; charset=utf-8"),
    "/coordinates.js": ("coordinates.js", "text/javascript; charset=utf-8"),
    "/terrain-outlines.js": ("terrain-outlines.js", "text/javascript; charset=utf-8"),
    "/briefings": ("briefings.html", "text/html; charset=utf-8"),
    "/briefings.js": ("briefings.js", "text/javascript; charset=utf-8"),
    "/": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/assets/f99th-patch.jpg": ("assets/f99th-patch.jpg", "image/jpeg"),
    "/assets/serverops-bot.png": ("assets/serverops-bot.png", "image/png"),
}


class Handler(BaseHTTPRequestHandler):
    server_version = "F99thDashboard/0.2.4-dev"
    sys_version = ""

    def _headers(self, code: int, content_type: str, length: int) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; "
                         "script-src 'self'; "
                         "style-src 'self' 'unsafe-inline'; "
                         "connect-src 'self'; "
                         "img-src 'self' data: https://tile.openmaps.fr https://tile.openstreetmap.org https://basemaps.cartocdn.com; "
                         "font-src 'self' data:; "
                         "worker-src 'self'; child-src 'none'; "
                         "object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == '/api/releases':
            payload=json.dumps(release_versions.snapshot()).encode()
            self._headers(200,'application/json; charset=utf-8',len(payload));self.wfile.write(payload)
            return
        if path == '/api/map-config':
            # A domain-restricted browser tile key is intentionally public.
            key=os.environ.get('F99TH_CARTO_BASEMAP_KEY','').strip()
            if not key:
                try:
                    config_path=HERE/'map-config.json'
                    if config_path.stat().st_size<=4096:
                        config=json.loads(config_path.read_text(encoding='utf-8-sig'))
                        key=config.get('carto_basemap_key','') if isinstance(config,dict) else ''
                except (OSError,ValueError): pass
            if not isinstance(key,str) or not 8<=len(key)<=256 or any(ord(c)<33 for c in key): key=''
            payload=json.dumps({'carto_basemap_key':key}).encode()
            self._headers(200,'application/json; charset=utf-8',len(payload));self.wfile.write(payload)
            return
        authorized=False
        if path in ('/api/red-access','/api/status','/api/world'):
            authorized,retry=red_access.check(self.headers.get('X-Red-Password'))
            if retry:
                payload=b'Too many password attempts. Try again shortly.'
                self.send_response(429)
                self.send_header('Retry-After',str(retry))
                self.send_header('Content-Type','text/plain; charset=utf-8')
                self.send_header('Content-Length',str(len(payload)))
                self.send_header('Cache-Control','no-store')
                self.send_header('X-Content-Type-Options','nosniff')
                self.end_headers();self.wfile.write(payload)
                return
        if path == "/api/red-access":
            self._error(200 if authorized else 403, b"Access check")
            return
        if path == "/api/clock":
            payload = json.dumps(internet_clock()).encode()
            self._headers(200, "application/json", len(payload))
            self.wfile.write(payload)
            return
        if path in ("/api/status", "/api/world"):
            status = collect_status()
            if path == "/api/world":
                status = world_feed.combine(status, world_feed.current())
            payload = json.dumps(public_status(status, authorized), separators=(",", ":")).encode("utf-8")
            self._headers(200, "application/json; charset=utf-8", len(payload))
            self.wfile.write(payload)
            return
        if path == "/health":
            payload = b"ok\n"
            self._headers(200, "text/plain; charset=utf-8", len(payload))
            self.wfile.write(payload)
            return
        if path in ASSETS:
            name, content_type = ASSETS[path]
            try:
                payload = (HERE / name).read_bytes()
            except OSError:
                self._error(404, b"Asset not found")
                return
            self._headers(200, content_type, len(payload))
            self.wfile.write(payload)
            return
        self._error(404, b"Not found")

    def _error(self, status: int, payload: bytes) -> None:
        self._headers(status, "text/plain; charset=utf-8", len(payload))
        self.wfile.write(payload)

    def do_POST(self) -> None: self._error(405, b"Read-only dashboard")
    def do_PUT(self) -> None: self._error(405, b"Read-only dashboard")
    def do_DELETE(self) -> None: self._error(405, b"Read-only dashboard")

    def log_message(self, fmt: str, *args: object) -> None:
        # Keep URLs/IP addresses out of app logs.
        return


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="F99th Live Operations v0.2.4-dev")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--telemetry-dir", type=Path, help="Read only this telemetry directory")
    parser.add_argument("--mission-root", type=Path, help="Read-only mission archive search root")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if args.telemetry_dir:
        TELEMETRY_DIRS = (args.telemetry_dir.resolve(),)
    if args.mission_root:
        MISSION_ROOTS = (args.mission_root.resolve(),)
    threading.Thread(target=release_versions.poll, daemon=True).start()
    threading.Thread(target=clock_worker, daemon=True).start()
    threading.Thread(target=world_feed.poll, daemon=True).start()
    web = None
    try:
        web = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
        web.daemon_threads = True
        print(f"F99th Dashboard v0.2.4-dev — http://127.0.0.1:{args.port}")
        print("Existing Tailscale Funnel may forward HTTPS to this port.")
        print("Press Ctrl+C to stop.")
        web.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nF99th dashboard stopped.")
    except OSError as exc:
        print(f"Unable to start dashboard: {exc}")
        raise SystemExit(1)

    finally:
        if web is not None:
            web.server_close()
