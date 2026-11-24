# F99th Live Ops

The F99th Live Ops dashboard displays DCS mission status, briefings, pilot positions and aircraft tracks. Georgia runs the dashboard. An optional private relay supplies Pennsylvania telemetry.

## Install on Windows

1. Install Python 3.10 or later. Copy the repository contents to `C:\F99th\Dashboard`. On an existing installation, back up the dashboard and retain its local configuration.
2. Create `C:\F99th\LiveOps\telemetry` on each DCS host. Copy the three Lua files from `hooks` to the active dedicated-server profile under `Saved Games\<DCS profile>\Scripts\Hooks`. Restart DCS at the next maintenance window. Confirm that the JSON files update during a mission.
3. On Georgia, run `py -3 C:\F99th\Dashboard\app.py --port 8765`. Open `http://127.0.0.1:8765/`. To start the map manually from the desktop, run `Launcher\Install-F99thLiveOpsShortcut.ps1` once, then use **F99th LiveOps Map**. Keep its console open.
4. For existing Tailscale Funnel installations, check that the HTTPS route forwards to local TCP 8765. Verify the local map before testing the public URL.

## Site configuration

- **Missions.** Set `F99TH_MISSION_ROOT` to the directory that contains the active mission archives if the server uses a custom profile.
- **Pennsylvania relay.** On Pennsylvania, run `py -3 relay\pennsy_feed.py --bind <PA-tailnet-IP> --allow-client <GA-tailnet-IP> --port 8766 --saved-games "<DCS profile path>"`. Replace both addresses and the profile path. Limit inbound TCP 8766 to Georgia on the private network. On Georgia set `F99TH_PA_RELAY_URL` to `http://<PA-tailnet-IP>:8766/api/pilots` before starting the dashboard.
- **Red coalition access.** Set `F99TH_RED_PASSWORD_SHA256` locally to the 64-character SHA-256 hex digest of the site password. Red access stays locked until configured.
- **Map tiles.** The tactical basemap accepts a domain-restricted browser key through `F99TH_CARTO_BASEMAP_KEY`. The map serves this key to browsers. Use a key intended for browser access.

## File register

| Files | Function |
| --- | --- |
| app.py, live_details.py, server_details.py, release_versions.py | Serve the dashboard and read local status, mission details and release information. |
| world_feed.py, relay/ | Read and combine Pennsylvania telemetry with the Georgia feed. |
| index.html, app.js, style.css | Render the map, service indicators and aircraft filters. |
| briefings.html, briefings.js | Display current mission briefings. |
| coordinates.js, mgrs.js, terrain-outlines.js | Format coordinates and draw terrain boundaries. See the included MGRS license files. |
| hooks/ | Export DCS status, pilot roster and aircraft telemetry. |
| assets/, Launcher/ | Supply dashboard graphics, the desktop icon and manual startup scripts. |

