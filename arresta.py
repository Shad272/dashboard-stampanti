"""Arresta soltanto il servizio della dashboard stampanti locale."""
import json
import time
import urllib.request
import sys
URL = 'http://127.0.0.1:8767'
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def health():
    try:
        with OPENER.open(URL+'/api/health',timeout=2) as r:
            return json.load(r).get('app') == 'dashboard-stampanti'
    except (OSError, ValueError):
        return False
try:
    if not health():
        print('La dashboard stampanti non risponde sulla porta 8767: potrebbe gia essere arrestata.')
    else:
        req=urllib.request.Request(URL+'/api/stop',method='POST',headers={'Origin':URL})
        with OPENER.open(req,timeout=5) as r:
            if r.status != 202: raise RuntimeError('Richiesta di arresto non accettata')
        deadline=time.monotonic()+8
        while health() and time.monotonic()<deadline: time.sleep(.2)
        if health(): raise RuntimeError('Il server non si e arrestato entro 8 secondi')
        print('Dashboard stampanti arrestata. Outlook rimane aperto.')
except Exception as exc:
    print('Errore durante arresto: '+str(exc))
    sys.exit(1)
