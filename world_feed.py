"""Bounded private relay reader and combined map data. No control endpoints."""
import os
import copy
import json
import math
import threading
import time
from datetime import datetime, timezone
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

PA_URL = os.environ.get('F99TH_PA_RELAY_URL', '').strip()
MAX_AGE = 25
_lock = threading.Lock()
_raw = None
_received = 0

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def recent(value, now):
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return stamp.tzinfo is not None and -5 <= now-stamp.timestamp() <= MAX_AGE
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False

def number(value, low, high):
    if type(value) not in (int,float): return None
    return value if math.isfinite(value) and low <= value <= high else None

def text(value, limit=120):
    return ''.join(c for c in value if c.isprintable())[:limit] if isinstance(value,str) else None

def sanitize(raw, now=None):
    now = time.time() if now is None else now
    result={'live':False,'status_live':False,'server':'PennsyServer','pilots':[], 'mission':None,'mission_state':None,'connected_players':None,'age_seconds':None,'aircraft_live':False,'aircraft':[],'aircraft_age_seconds':None}
    if not isinstance(raw,dict) or raw.get('server') != 'PennsyServer': return result
    if raw.get('live') is True and recent(raw.get('last_update'),now) and isinstance(raw.get('pilots'),list):
        result['live']=True
        result['age_seconds']=max(0,int(now-datetime.fromisoformat(raw['last_update'].replace('Z','+00:00')).timestamp()))
        for p in raw['pilots'][:200]:
            if not isinstance(p,dict): continue
            result['pilots'].append({'site':'pennsylvania','is_player':True,
                'callsign':text(p.get('callsign'),64) or 'Pilot', 'aircraft':text(p.get('aircraft'),64),
                'coalition':p.get('coalition') if p.get('coalition') in ('blue','red') else 'neutral',
                'lat':number(p.get('lat'),-90,90),'lon':number(p.get('lon'),-180,180),
                'altitude_ft':number(p.get('altitude_ft'),-1000,200000),'heading_deg':number(p.get('heading_deg'),0,360),
                'ground_speed_kt':number(p.get('ground_speed_kt'),0,2000),'speed_source':'telemetry'})
    if raw.get('status_live') is True and recent(raw.get('status_last_update'),now):
        result.update(status_live=True,mission=text(raw.get('mission')),mission_state=text(raw.get('mission_state'),32),connected_players=number(raw.get('connected_players'),0,200))
    if recent(raw.get('details_updated'), now):
        services = raw.get('services') if isinstance(raw.get('services'),dict) else {}
        result['services'] = {k:text(services.get(k),120) for k in ('dcs_version','srs_version','srs_address')}
        result['services']['srs_port'] = number(services.get('srs_port'),1,65535)
        result['services']['srs_listening'] = services.get('srs_listening') if type(services.get('srs_listening')) is bool else None
    if result['status_live']:
        if (raw.get('aircraft_live') is True and result['mission']
                and raw.get('aircraft_mission') == result['mission']
                and recent(raw.get('aircraft_last_update'),now)
                and isinstance(raw.get('aircraft'),list)):
            result['aircraft_live']=True
            result['aircraft_age_seconds']=max(0,int(now-datetime.fromisoformat(raw['aircraft_last_update'].replace('Z','+00:00')).timestamp()))
            for p in raw['aircraft'][:2000]:
                if not isinstance(p,dict) or type(p.get('is_player')) is not bool: continue
                if not p['is_player'] and p.get('airborne') is not True: continue
                lat,lon=number(p.get('lat'),-90,90),number(p.get('lon'),-180,180)
                if lat is None or lon is None: continue
                result['aircraft'].append({'site':'pennsylvania','is_player':p['is_player'],'airborne':p.get('airborne') is True,
                    'callsign':text(p.get('callsign'),64) or ('Pilot' if p['is_player'] else 'AI'),
                    'aircraft':text(p.get('aircraft'),64),'coalition':p.get('coalition') if p.get('coalition') in ('blue','red') else 'neutral',
                    'lat':lat,'lon':lon,'altitude_ft':number(p.get('altitude_ft'),-1000,200000),
                    'heading_deg':number(p.get('heading_deg'),0,360),'ground_speed_kt':number(p.get('ground_speed_kt'),0,2000),'speed_source':'telemetry'})
        result['terrain'] = text(raw.get('terrain'),80)
        result['mission_elapsed_seconds'] = number(raw.get('mission_elapsed_seconds'),0,31536000)
        result['briefing'] = raw.get('briefing')[:24000] if isinstance(raw.get('briefing'),str) else None
        conditions = raw.get('conditions') if isinstance(raw.get('conditions'),dict) else {}
        result['conditions'] = {'time_seconds':number(conditions.get('time_seconds'),0,86400),'weather':text(conditions.get('weather'),250)}
        result['status_age_seconds'] = max(0,int(now-datetime.fromisoformat(raw['status_last_update'].replace('Z','+00:00')).timestamp()))
    return result

def poll():
    global _raw,_received
    if not PA_URL:
        return
    opener=build_opener(ProxyHandler({}),NoRedirect())
    while True:
        raw=None
        try:
            with opener.open(Request(PA_URL,headers={'Accept':'application/json'}),timeout=2) as response:
                data=response.read(2000001)
            if len(data)<=2000000: raw=json.loads(data)
        except (OSError,ValueError,TypeError): pass
        with _lock: _raw=raw;_received=time.monotonic()
        time.sleep(5)

def current():
    with _lock:
        raw=copy.deepcopy(_raw) if time.monotonic()-_received<=MAX_AGE else None
    return sanitize(raw)

def combine(local, pa):
    result=copy.deepcopy(local)
    ga_roster=local.get('roster',{})
    ga_aircraft=local.get('aircraft',{})
    pilots=[dict(p,site='georgia') for p in ga_roster.get('pilots',[]) if ga_roster.get('connected')]
    pilots.extend(pa['pilots'] if pa['live'] else [])
    ga_positions=ga_aircraft.get('aircraft',[]) if ga_aircraft.get('connected') else ga_roster.get('pilots',[]) if ga_roster.get('connected') else []
    positions=[dict(p,site='georgia') for p in ga_positions]
    positions.extend(pa['aircraft'] if pa.get('aircraft_live') else pa['pilots'] if pa['live'] else [])
    result['roster']={'connected':bool(ga_roster.get('connected') or pa['live']),'pilots':pilots,'age_seconds':None,
        'site_ages':{'georgia':ga_roster.get('age_seconds') if ga_roster.get('connected') else None,'pennsylvania':pa.get('age_seconds') if pa['live'] else None}}
    result['aircraft']={'connected':bool(ga_aircraft.get('connected') or ga_roster.get('connected') or pa['live'] or pa.get('aircraft_live')),'aircraft':positions,'age_seconds':None}
    # Metadata only: no second copy of unfiltered aircraft can leak red positions.
    result['servers']={'georgia':{'live':bool(ga_roster.get('connected') or ga_aircraft.get('connected')),**local.get('telemetry',{}), 'services':local.get('services',{}), 'conditions':local.get('conditions',{}), 'briefing':local.get('briefing')},
        'pennsylvania':{k:v for k,v in pa.items() if k not in ('pilots','aircraft')}}
    return result
