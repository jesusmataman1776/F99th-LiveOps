"""PennsyServer -> Georgia: read-only F99th DCS telemetry over Tailscale.

Installation target: PennsyServer (NOT Georgia).
Requires Python 3.10+; uses only the standard library.
Listens on Pennsylvania's Tailscale IPv4, not its public/LAN interfaces.
Only Georgia's Tailscale IPv4 may read the endpoint.
No DCS/SRS/DCSServerBot administration or credentials are exposed.
"""
from __future__ import annotations

import argparse
import server_details
import json
import math
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DEFAULT_BIND = "127.0.0.1"  # PennsyServer tailnet address
DEFAULT_ALLOWED_PEER = "127.0.0.1"  # Georgia master tailnet address
PORT = 8766
TELEMETRY_DIR = Path(r"C:\F99th\LiveOps\telemetry")
FRESH_SECONDS = 20
SAVED_GAMES = None


def as_number(value):
    if isinstance(value, bool): return None
    try:
        num = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return num if math.isfinite(num) else None


def as_text(value, max_len):
    return value[:max_len] if isinstance(value, str) else None


def fresh_json(path, max_bytes=300_000):
    try:
        stat = path.stat()
        age = time.time() - stat.st_mtime
        if not 0 <= age <= FRESH_SECONDS:
            return None, None, None
        if stat.st_size > max_bytes:
            return None, None, None
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            return None, None, None
        modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
        return raw, modified, round(age, 1)
    except (OSError, TypeError, ValueError):
        return None, None, None


def get_feed(telemetry_dir):
    output = {
        "server": "PennsyServer", "live": False, "pilots": [],
        "last_update": None, "age_seconds": None,
        "status_live": False, "status_last_update": None, "mission": None, "mission_state": None,
        "connected_players": None, "mission_elapsed_seconds": None,
        "aircraft_live": False, "aircraft": [], "aircraft_last_update": None,
        "aircraft_mission": None,
    }
    pilots, modified, age = fresh_json(telemetry_dir / "pilots.json")
    if isinstance(pilots, dict) and isinstance(pilots.get("pilots"), list):
        output["live"] = True  # An empty but fresh roster is still operational.
        output["last_update"] = modified
        output["age_seconds"] = age
        for p in pilots["pilots"][:200]:
            if not isinstance(p, dict):
                continue
            lat, lon = as_number(p.get("lat")), as_number(p.get("lon"))
            output["pilots"].append({
                "callsign": as_text(p.get("callsign"), 80) or "",
                "coalition": p.get("coalition") if p.get("coalition") in ("blue", "red") else "neutral",
                "aircraft": as_text(p.get("aircraft"), 80) or "",
                "lat": lat if lat is not None and -90 <= lat <= 90 else None,
                "lon": lon if lon is not None and -180 <= lon <= 180 else None,
                "altitude_ft": as_number(p.get("altitude_ft")),
                "heading_deg": as_number(p.get("heading_deg")),
                "flight_status": as_text(p.get("flight_status"), 30),
            })
    state, state_modified, _ = fresh_json(telemetry_dir / "server_status.json")
    if isinstance(state, dict):
        output["status_live"] = True
        output["status_last_update"] = state_modified
        output["mission"] = as_text(state.get("mission"), 120)
        output["mission_state"] = as_text(state.get("mission_state"), 30)
        count = as_number(state.get("connected_players"))
        if count is not None and 0 <= count <= 1000 and count.is_integer():
            output["connected_players"] = int(count)
        elapsed = as_number(state.get("mission_elapsed_seconds"))
        if elapsed is not None and 0 <= elapsed <= 365 * 24 * 3600:
            output["mission_elapsed_seconds"] = round(elapsed)
    snapshot, _, _ = fresh_json(telemetry_dir/'mission_aircraft.json', 2_000_000)
    stamp = snapshot.get('stamp') if snapshot else None
    if (snapshot and type(stamp) in (int,float) and math.isfinite(stamp)
            and -5 <= time.time()-stamp <= FRESH_SECONDS
            and output['status_live'] and output['mission']
            and snapshot.get('mission') == output['mission']
            and snapshot.get('schema_version') == 1 and snapshot.get('full_scope') is True
            and isinstance(snapshot.get('aircraft'),list)):
        output.update(aircraft_live=True,aircraft_mission=output['mission'],
                      aircraft_last_update=datetime.fromtimestamp(stamp,timezone.utc).isoformat())
        for aircraft in snapshot['aircraft'][:2000]:
            if not isinstance(aircraft,dict) or type(aircraft.get('is_player')) is not bool: continue
            if not aircraft['is_player'] and aircraft.get('airborne') is not True: continue
            # Only telemetry fields; never forward arbitrary hook data.
            item={k:as_text(aircraft.get(k),80) for k in ('callsign','aircraft','coalition')}
            item.update(is_player=aircraft['is_player'],airborne=aircraft.get('airborne') is True)
            for key in ('lat','lon','altitude_ft','heading_deg','ground_speed_kt'):
                item[key]=as_number(aircraft.get(key))
            output['aircraft'].append(item)
        output['conditions']={'time_seconds':as_number(snapshot.get('mission_time_seconds')),
                              'weather':as_text(snapshot.get('weather_summary'),250)}
    if SAVED_GAMES:
        output['services'] = server_details.services(SAVED_GAMES)
        output['details_updated'] = datetime.now(timezone.utc).isoformat()
        if output['status_live']:
            output.update(server_details.mission_details(output['mission'], [SAVED_GAMES/'Missions']))
    return output


def create_handler(telemetry_dir, allowed_clients):
    class Handler(BaseHTTPRequestHandler):
        server_version = "F99thTelemetry/1.0"

        def do_GET(self):
            # Defense in depth: Windows firewall MUST independently restrict
            # TCP 8766 to the authorized dashboard peer.
            if self.client_address[0] not in allowed_clients:
                self.send_error(403, "Forbidden")
                return
            if self.path not in ("/api/pilots", "/health"):
                self.send_error(404, "Not found")
                return
            if self.path == "/health":
                response = {"service": "PennsyServer telemetry", "ready": True}
            else:
                response = get_feed(telemetry_dir)
            encoded = json.dumps(response, ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, fmt, *args):
            # Only limited request metadata; no payloads or credentials.
            print('[F99th telemetry]', self.address_string(), fmt % args)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', default=DEFAULT_BIND,
                        help='Bind interface (default: loopback)')
    parser.add_argument('--allow-client', default=DEFAULT_ALLOWED_PEER,
                        help='Only this source IPv4 is allowed (default: loopback)')
    parser.add_argument('--telemetry', type=Path, default=TELEMETRY_DIR,
                        help='Directory written by Pennsylvania DCS Lua hooks')
    parser.add_argument('--port', type=int, default=PORT)
    parser.add_argument("--saved-games", type=Path)
    args = parser.parse_args()
    global SAVED_GAMES
    SAVED_GAMES = args.saved_games
    handler = create_handler(args.telemetry, {args.allow_client, args.bind})
    server = ThreadingHTTPServer((args.bind, args.port), handler)
    print(f'F99th Pennsylvania telemetry: {args.bind}:{args.port} -> {args.telemetry}')
    print(f'Allowed remote client: {args.allow_client}')
    print('Read-only service. Never forward TCP 8766 on the Xfinity router.')
    try:
        server.serve_forever(poll_interval=0.4)
    except KeyboardInterrupt:
        print('Shutdown requested.')
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
