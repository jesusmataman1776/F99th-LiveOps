"""Read-only metadata. Mission Lua is read as text, never executed or extracted."""
import json
import os
import re
import socket
import subprocess
import time
import zipfile
from pathlib import Path
from functools import lru_cache

def lua_string(source, key):
    match = re.search(r'\[\s*"' + re.escape(key) + r'"\s*\]\s*=\s*("(?:\\.|[^"\\])*"|\[(=*)\[.*?\]\2\])', source, re.S)
    if not match: return None
    value = match[1]
    if value.startswith('['):
        n = len(match[2]) + 2
        return value[n:-n].lstrip('\r\n')
    # Decode only Lua string escapes; leave Unicode intact.
    return re.sub(r'\\(\r?\n|[nrt"\\]|\d{1,3})', lambda m: {'n':'\n','r':'\r','t':'\t','"':'"','\\':'\\','\n':'\n','\r\n':'\n'}.get(m[1], chr(int(m[1])) if m[1].isdigit() else m[1]), value[1:-1])

@lru_cache(maxsize=16)
def archive_details(path, modified, size):
    try:
        with zipfile.ZipFile(path) as archive:
            def read(name):
                member = archive.getinfo(name)
                if member.file_size > 32_000_000: raise ValueError('Oversized mission member')
                return archive.read(member).decode('utf-8-sig')
            mission = read('mission')
            brief = lua_string(mission, 'descriptionText')
            if brief and brief.startswith('DictKey_'):
                brief = lua_string(read('l10n/DEFAULT/dictionary'), brief)
            return {'terrain': lua_string(mission, 'theatre'), 'briefing': (brief or '')[:24000] or None}
    except (OSError, ValueError, KeyError, UnicodeError, zipfile.BadZipFile, RuntimeError):
        return {'terrain': None, 'briefing': None}

def mission_details(mission, roots):
    if not isinstance(mission, str) or not mission: return {}
    try:
        matches = [p for root in roots for p in Path(root).rglob('*.miz') if p.stem.casefold() == mission.casefold()]
        if len(matches) != 1: return {}
        p = matches[0]; stat = p.stat()
        return archive_details(str(p), stat.st_mtime_ns, stat.st_size)
    except OSError: return {}

_services_cache = {}

def running_bot_version():
    override = os.environ.get('F99TH_DCSSB_LOG')
    root = Path(r'C:\F99th\DCSServerBot')
    filename = f'dcssb-{socket.gethostname().lower()}.log'
    candidates = (Path(override),) if override else (
        root / 'DCSServerBot' / 'logs' / filename,
        root / 'logs' / filename,
    )
    for log in candidates:
        try:
            if time.time() - log.stat().st_mtime > 300:
                continue
        except OSError:
            continue
        # A long-running bot may have rotated its startup line out of the active log.
        for path in (log, *(log.with_name(f'{log.name}.{n}') for n in range(1, 6))):
            try:
                with path.open(encoding='utf-8', errors='replace') as stream:
                    header = stream.read(16_000)
                match = re.search(r'\bDCSServerBot v(\d{1,3}(?:\.\d{1,6}){3}) starting up', header)
                if match:
                    return match[1]
            except OSError:
                continue
    return None

def services(saved_games):
    saved_games = Path(saved_games)
    key = str(saved_games)
    cached = _services_cache.get(key)
    if cached and time.monotonic()-cached[0] < 30: return dict(cached[1])
    result = {'dcs_version': None, 'srs_version': None, 'srs_address': None, 'srs_port': None,
              'srs_listening': None, 'bot_version': running_bot_version()}
    try:
        with (saved_games/'Logs/dcs.log').open(encoding='utf-8', errors='replace') as f:
            match = re.search(r'DCS/(\d+(?:\.\d+){2,4})', f.read(16000))
        if match: result['dcs_version'] = match[1]
    except OSError: pass
    try:
        hook = (saved_games/'Scripts/Hooks/DCS-SRS-AutoConnectGameGUI.lua').read_text(encoding='utf-8-sig')
        host = re.search(r'^SRSAuto\.SERVER_SRS_HOST\s*=\s*"([A-Za-z0-9.-]+)"', hook, re.M)
        port = re.search(r'^SRSAuto\.SERVER_SRS_PORT\s*=\s*"(\d+)"', hook, re.M)
        if host and port and 0 < int(port[1]) < 65536:
            result.update(srs_address=host[1]+':'+port[1], srs_port=int(port[1]))
    except OSError: pass
    # Executable metadata and actual local listening sockets, not a guessed version.
    command = "$p=Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('SRS-Server.exe','SR-Server.exe','SRS-Server-CommandLine.exe') } | Select-Object -First 1; if($p){$v=(Get-Item -LiteralPath $p.ExecutablePath).VersionInfo.FileVersion; $ports=@(Get-NetTCPConnection -State Listen -OwningProcess $p.ProcessId -ErrorAction SilentlyContinue | Select-Object -ExpandProperty LocalPort -Unique); @{version=$v;ports=$ports} | ConvertTo-Json -Compress}"
    try:
        run = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command], capture_output=True, text=True, timeout=8, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        info = json.loads(run.stdout)
        result['srs_version'] = str(info.get('version') or '')[:80] or None
        ports = info.get('ports', [])
        if result['srs_port'] is None and len(ports) == 1: result['srs_port'] = ports[0]
        if result['srs_port'] is not None: result['srs_listening'] = result['srs_port'] in ports
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired): pass
    if result['srs_version'] is None:
        try:
            command = r"$p=Get-Item -LiteralPath 'C:\Program Files\DCS-SimpleRadio-Standalone\Server\SRS-Server.exe' -ErrorAction Stop; $p.VersionInfo.FileVersion"
            run = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],capture_output=True,text=True,timeout=5,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if run.returncode == 0: result['srs_version'] = run.stdout.strip()[:80] or None
        except (OSError, subprocess.TimeoutExpired): pass
    if result['srs_listening'] is None and result['srs_port'] is not None:
        try:
            with socket.create_connection(('127.0.0.1',result['srs_port']), timeout=.4):
                result['srs_listening'] = True
        except OSError: pass
    _services_cache[key] = (time.monotonic(), result)
    return dict(result)
