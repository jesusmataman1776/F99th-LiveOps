"""Read-only service metadata, mission conditions, and internet clock."""
import copy
import hashlib
import hmac
import json
import os
import math
from collections import deque
import re
import threading
import time
import urllib.request
from email.utils import parsedate_to_datetime
from pathlib import Path

RED_DIGEST = os.environ.get('F99TH_RED_PASSWORD_SHA256', "").lower()
if RED_DIGEST and not re.fullmatch(r'[0-9a-f]{64}',RED_DIGEST):
    raise ValueError('F99TH_RED_PASSWORD_SHA256 must be a SHA-256 hex digest')
_clock = None
_clock_lock = threading.Lock()

def red_authorized(password):
    return bool(RED_DIGEST) and isinstance(password, str) and len(password)<=256 and hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(), RED_DIGEST)

class RedAccessLimiter:
    """Shared limit across all endpoints; do not trust spoofable forwarded IPs.

    Funnel connections arrive over loopback. A global failed-attempt budget
    bounds guesses without pretending that loopback identifies a visitor.
    Anonymous public reads do not use the budget.
    """
    def __init__(self, limit=10, window=60, clock=time.monotonic):
        self.limit,self.window,self.clock=limit,window,clock
        self.failures=deque()
        self.lock=threading.Lock()

    def check(self,password):
        if password is None: return False,0
        with self.lock:
            now=self.clock()
            while self.failures and now-self.failures[0]>=self.window: self.failures.popleft()
            if len(self.failures)>=self.limit:
                return False,max(1,math.ceil(self.window-(now-self.failures[0])))
            authorized=red_authorized(password)
            if not authorized: self.failures.append(now)
            return authorized,0

red_access = RedAccessLimiter()

def public_status(status, authorized=False):
    result=copy.deepcopy(status)
    if not authorized:
        for section, key in (("aircraft","aircraft"),("roster","pilots")):
            if section in result:
                result[section][key]=[p for p in result[section].get(key,[]) if p.get("coalition")!="red"]
    result["red_unlocked"]=authorized
    return result

def clock_worker():
    global _clock
    while True:
        try:
            with urllib.request.urlopen(urllib.request.Request("https://www.google.com/generate_204", headers={"User-Agent":"F99thDashboard/0.2.4"}), timeout=8) as response:
                stamp=parsedate_to_datetime(response.headers["Date"]).timestamp()
            with _clock_lock: _clock=(stamp,time.monotonic())
        except (OSError, ValueError, TypeError, KeyError): pass
        time.sleep(300)

def internet_clock():
    with _clock_lock:
        if _clock is None: return {"synced":False,"utc_ms":None}
        age=time.monotonic()-_clock[1]
        return {"synced":age<900,"utc_ms":(_clock[0]+age)*1000,"source":"Google HTTPS Date","age_seconds":int(age)}

def dcs_version():
    try:
        with (Path.home() / r"Saved Games\DCS.dcs_serverrelease\Logs\dcs.log").open(encoding="utf-8",errors="replace") as f:
            match=re.search(r"DCS/(\d+(?:\.\d+){2,4})",f.read(16000))
        if match: return match.group(1)
    except OSError: pass
    return None

def srs_address():
    try:
        text=(Path.home() / r"Saved Games\DCS.dcs_serverrelease\Scripts\Hooks\DCS-SRS-AutoConnectGameGUI.lua").read_text(encoding="utf-8-sig")
        host=re.search(r'^SRSAuto\.SERVER_SRS_HOST\s*=\s*"([A-Za-z0-9.-]+)"',text,re.M)
        port=re.search(r'^SRSAuto\.SERVER_SRS_PORT\s*=\s*"(\d+)"',text,re.M)
        if host and port: return host[1]+":"+port[1]
    except OSError: pass
    return None
