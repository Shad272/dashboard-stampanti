"""Dashboard locale; Python 3.10+, nessuna dipendenza esterna. Solo SNMP GET/GETNEXT."""
import concurrent.futures
import datetime as dt
import ipaddress
import json
import secrets
import socket
import threading
import time
import webbrowser
import argparse
import logging
import notifiche
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
MIB = '1.3.6.1.2.1.43.'

def tlv(tag, payload):
    n = len(payload)
    size = bytes([n]) if n < 128 else bytes([128 + (n.bit_length()+7)//8]) + n.to_bytes((n.bit_length()+7)//8, 'big')
    return bytes([tag]) + size + payload

def integer(n):
    return tlv(2, n.to_bytes(max(1, (n.bit_length()+8)//8), 'big', signed=True))

def base128(n):
    parts = [n & 127]
    n >>= 7
    while n:
        parts.insert(0, (n & 127) | 128)
        n >>= 7
    return bytes(parts)

def oid_encode(value):
    nums = [int(v) for v in value.split('.')]
    return tlv(6, base128(nums[0]*40+nums[1]) + b''.join(base128(n) for n in nums[2:]))

def decode_oid(raw):
    nums, n = [], 0
    for b in raw:
        n = (n << 7) | (b & 127)
        if not b & 128:
            nums.append(n)
            n = 0
    if not nums or raw[-1] & 128:
        raise ValueError('OID non valido')
    first = nums.pop(0)
    return '.'.join(map(str, [min(first//40, 2), first-40*min(first//40, 2)] + nums))

def unpack(data, offset=0):
    if offset+2 > len(data):
        raise ValueError('Pacchetto SNMP incompleto')
    tag, n = data[offset], data[offset+1]
    offset += 2
    if n & 128:
        length_bytes = n & 127
        if not length_bytes or length_bytes > 4 or offset+length_bytes > len(data):
            raise ValueError('Lunghezza SNMP non valida')
        n = int.from_bytes(data[offset:offset+length_bytes], 'big')
        offset += length_bytes
    if offset+n > len(data):
        raise ValueError('Risposta SNMP troncata')
    return tag, data[offset:offset+n], offset+n

def children(raw):
    result, pos = [], 0
    while pos < len(raw):
        tag, value, pos = unpack(raw, pos)
        result.append((tag, value))
    return result

def scalar(tag, raw):
    if tag == 2:
        return int.from_bytes(raw, 'big', signed=True)
    if tag in (0x41, 0x42, 0x43, 0x46):
        return int.from_bytes(raw, 'big')
    if tag == 4:
        return raw.decode('utf-8', errors='replace').strip('\x00 ')
    if tag == 6:
        return decode_oid(raw)
    return None

class Snmp:
    def __init__(self, host, community, timeout=1.5, port=161, budget=22):
        self.host, self.community, self.timeout, self.port = host, community.encode(), timeout, port
        self.deadline = time.monotonic()+budget
        self.version = 1  # BER: 0 = SNMPv1, 1 = SNMPv2c

    def request(self, oid, next_oid=False):
        remaining = self.deadline-time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Tempo massimo di lettura SNMP superato')
        rid = secrets.randbelow(2**30)+1
        varbind = tlv(0x30, oid_encode(oid)+tlv(5, b''))
        pdu = tlv(0xA1 if next_oid else 0xA0, integer(rid)+integer(0)+integer(0)+tlv(0x30, varbind))
        packet = tlv(0x30, integer(self.version)+tlv(4, self.community)+pdu)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect((self.host, self.port))
            for attempt in range(2):
                remaining = self.deadline-time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Tempo massimo di lettura SNMP superato')
                sock.settimeout(min(self.timeout, remaining))
                try:
                    sock.send(packet)
                    response = sock.recv(65535)
                    break
                except socket.timeout:
                    if attempt == 1:
                        raise
        tag, raw, _ = unpack(response)
        outer = children(raw)
        if tag != 0x30 or len(outer) != 3 or outer[2][0] != 0xA2:
            raise ValueError('Risposta SNMP inattesa')
        p = children(outer[2][1])
        if scalar(*p[0]) != rid or outer[1][1] != self.community or scalar(*outer[0]) != self.version:
            raise ValueError('Risposta SNMP non corrispondente')
        if scalar(*p[1]):
            if self.version == 0 and next_oid and scalar(*p[1]) == 2:
                return oid, None, 0x82  # SNMPv1: noSuchName a fine MIB
            raise ValueError('Errore SNMP: '+str(scalar(*p[1])))
        variables = children(p[3][1])
        pair = children(variables[0][1])
        return decode_oid(pair[0][1]), scalar(*pair[1]), pair[1][0]

    def walk(self, root, limit=256):
        current, result = root, {}
        for _ in range(limit):
            oid, value, tag = self.request(current, True)
            if not oid.startswith(root+'.') or tag in (0x80, 0x81, 0x82):
                return result
            if tuple(map(int, oid.split('.'))) <= tuple(map(int, current.split('.'))):
                raise ValueError('La stampante restituisce OID non progressivi')
            result[oid[len(root)+1:]] = value
            current = oid
        raise ValueError('Tabella SNMP troppo lunga: lettura non completata')

def table_rows(values):
    result = {}
    for suffix, value in values.items():
        column, _, index = suffix.partition('.')
        result.setdefault(index, {})[int(column)] = value
    return result

def supply(row, index):
    level, maximum, unit = row.get(9), row.get(8), row.get(7)
    percent = None
    if isinstance(level, int) and level >= 0:
        if unit == 19 and level <= 100:
            percent = level
        elif isinstance(maximum, int) and maximum > 0 and level <= maximum:
            percent = round(100*level/maximum)
    status = {-1:'Altro', -2:'Livello sconosciuto', -3:'Materiale presente; quantità sconosciuta'}.get(level, '')
    return {'id':index, 'name':row.get(6) or 'Consumabile '+index, 'level':level,
            'maximum':maximum, 'unit':unit, 'percent':percent, 'detail':status,
            'class':row.get(4), 'type':row.get(5), 'receptacle':row.get(4)==4}

def utcnow():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def printer_extra(client, result):
    """Dettagli per tutte le marche tramite Printer-MIB e Host Resources MIB."""
    result['trays'], result['devices'], result['console'] = [], [], []
    def column(root):
        try:
            return client.walk(root,128)
        except (OSError, ValueError, TimeoutError) as exc:
            result['warnings'].append('Dettagli non disponibili per '+root+' ('+type(exc).__name__+').')
            return {}
    cols={c:column(MIB+'8.2.1.'+str(c)) for c in (13,18,8,9,10,12,21,22)}
    indices=set().union(*(v.keys() for v in cols.values()))
    for index in sorted(indices):
        v={c:entries.get(index) for c,entries in cols.items()}
        level,maximum=v[10],v[9]
        percent=None
        if isinstance(level,int) and level>=0 and isinstance(maximum,int) and maximum>0 and level<=maximum:
            percent=round(100*level/maximum)
        detail='Carta presente; quantità non disponibile' if level==-3 else 'Vuoto' if level==0 else 'Quantità non disponibile' if not isinstance(level,int) or level<0 else str(level)+(' fogli' if v[8]==8 else ' unità')
        result['trays'].append({'id':index,'name':v[13] or v[18] or 'Vassoio '+index,'description':v[18],
            'media':v[12], 'media_type':v[21], 'media_color':v[22], 'level':level,'capacity':maximum,
            'unit':v[8], 'percent':percent,'detail':detail})
    names=column('1.3.6.1.2.1.25.3.2.1.3')
    statuses=column('1.3.6.1.2.1.25.3.2.1.5')
    for index,name in names.items():
        result['devices'].append({'name':name,'status':{1:'Altro',2:'In funzione',3:'Avviso',4:'In test',5:'Non disponibile'}.get(statuses.get(index),'—')})
    result['console']=[v for v in column(MIB+'16.5.1.2').values() if isinstance(v,str) and v.strip()]
    result['informational_alerts']=[a for a in result['alerts'] if any(code in a for code in ('016-424','016-425')) and 'no action' in a.lower() and any(mode in a.lower() for mode in ('low power','sleep mode'))] if 'xerox' in (result.get('model') or '').lower() else []

def collect(printer, config):
    result = {k:printer.get(k) for k in ('id','name','ip','model','serial','web')}
    result.update({'attempted_at':utcnow(), 'ok':False, 'supplies':[], 'alerts':[], 'counters':[], 'warnings':[]})
    if not printer.get('ip'):
        result['error'] = 'IP da configurare in stampanti.json'
        return result
    preferred = str(printer.get('snmp_version','auto')).lower()
    versions = [0] if preferred == '1' else [1] if preferred in ('2','2c') else [1,0]
    result['diagnostic_attempts'] = []
    for version in versions:
        client = Snmp(printer['ip'], printer.get('community', config.get('community','public')))
        client.version = version
        try:
            _, description, tag = client.request('1.3.6.1.2.1.1.1.0')
            if tag != 4:
                raise ValueError('sysDescr non disponibile')
            result['description'] = description
            result['protocol'] = 'SNMPv1' if version == 0 else 'SNMPv2c'
            break
        except (OSError, ValueError, TimeoutError) as exc:
            result['diagnostic_attempts'].append({'protocol':'SNMPv1' if version==0 else 'SNMPv2c','error':type(exc).__name__})
    else:
        result['error'] = 'Nessuna risposta SNMP valida. Verificare community di lettura, versione SNMP e blocco SNMP in modalità riposo.'
        return result
    result['ok'] = True
    for label, root in [('serial',MIB+'5.1.1.17'), ('supplies',MIB+'11.1.1'),
                        ('alerts',MIB+'18.1.1.8'), ('counters',MIB+'10.2.1'),
                        ('status','1.3.6.1.2.1.25.3.5.1.1')]:
        try:
            values = client.walk(root, 512 if label=='supplies' else 128)
            if label == 'serial':
                serials = [v for v in values.values() if isinstance(v,str) and v.strip()]
                if serials:
                    result['serial'] = serials[0]
            elif label == 'supplies':
                result['supplies'] = [supply(row,index) for index,row in table_rows(values).items()]
            elif label == 'alerts':
                result['alerts'] = list(dict.fromkeys(str(v) for v in values.values() if v))
            elif label == 'counters':
                result['counters'] = [{'id':i,'value':row[4], 'unit':row.get(3)} for i,row in table_rows(values).items() if isinstance(row.get(4),int)]
            else:
                result['status'] = list(dict.fromkeys({1:'Altro',2:'Sconosciuto',3:'In attesa',4:'Stampa in corso',5:'Riscaldamento'}.get(v,'Sconosciuto') for v in values.values()))
        except (OSError, ValueError, TimeoutError) as exc:
            result['warnings'].append('Lettura '+label+' non disponibile ('+type(exc).__name__+').')
    printer_extra(client,result)
    result['read_at'] = utcnow()
    return result

def load_config(path=ROOT/'stampanti.json'):
    conf = json.loads(path.read_text(encoding='utf-8-sig'))
    conf['interval_seconds'] = max(30, int(conf.get('interval_seconds',60)))
    ids = set()
    for p in conf['printers']:
        if p['id'] in ids:
            raise ValueError('Codice stampante duplicato')
        ids.add(p['id'])
        if p.get('ip'):
            ip = ipaddress.ip_address(p['ip'])
            if ip.version != 4 or not ip.is_private or ip.is_loopback or ip.is_multicast or ip.is_unspecified:
                raise ValueError('Sono ammessi solo IP IPv4 privati delle stampanti')
    return conf

class Monitor:
    def __init__(self, config):
        self.config, self.lock, self.event = config, threading.Lock(), threading.Event()
        self.stopped = False
        self.state = {'refreshing':False,'last_cycle':None,'next_cycle':None,'printers':[],'interval_seconds':config['interval_seconds'],'configured_count':len(config['printers'])}
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=10)

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.state))

    def cycle(self):
        with self.lock:
            self.state['refreshing'] = True
        jobs = {self.pool.submit(collect,p,self.config):p for p in self.config['printers']}
        results = {}
        for future in concurrent.futures.as_completed(jobs):
            p = jobs[future]
            try:
                item = future.result()
            except Exception as exc:
                item = {'id':p['id'],'name':p['name'],'ip':p.get('ip'),'ok':False,'error':'Lettura fallita: '+type(exc).__name__}
            with self.lock:
                previous = next((v for v in self.state['printers'] if v['id']==p['id']),None)
            if not item['ok'] and previous:
                old = previous.get('last_good') or (previous if previous.get('ok') else None)
                if old:
                    item['last_good'] = {k:v for k,v in old.items() if k != 'last_good'}
            results[p['id']] = item
            with self.lock:
                current = {v['id']:v for v in self.state['printers']}
                current[p['id']] = item
                self.state['printers'] = [current[p['id']] for p in self.config['printers'] if p['id'] in current]
        notification_status = notifiche.process(list(results.values()))
        with self.lock:
            self.state.update(refreshing=False,last_cycle=utcnow(),next_cycle=time.time()+self.config['interval_seconds'], notifiche=notification_status)

    def run(self):
        while not self.stopped:
            self.event.clear()
            self.cycle()
            self.event.wait(self.config['interval_seconds'])

class Handler(BaseHTTPRequestHandler):
    def allowed(self):
        host = self.headers.get('Host','')
        return host in ('127.0.0.1:8767','localhost:8767')

    def reply(self, status, body, mime='application/json; charset=utf-8'):
        self.send_response(status)
        self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.allowed():
            return self.reply(403,b'{}')
        if self.path in ('/','/index.html'):
            return self.reply(200,(ROOT/'index.html').read_bytes(),'text/html; charset=utf-8')
        if urlsplit(self.path).path == '/richiesta-fotorecettore':
            return self.reply(200,(ROOT/'Richiesta_Fotorecettore_Anagrafe.html').read_bytes(),'text/html; charset=utf-8')
        if self.path == '/api/status':
            return self.reply(200,json.dumps(self.server.monitor.snapshot(),ensure_ascii=False).encode())
        if self.path == '/api/health':
            return self.reply(200,b'{"app":"dashboard-stampanti","version":6}')
        return self.reply(404,b'{}')

    def do_POST(self):
        if not self.allowed() or self.headers.get('Origin') not in ('http://127.0.0.1:8767','http://localhost:8767'):
            return self.reply(403,b'{}')
        if self.path == '/api/test-email':
            ok, message = notifiche.send_test()
            return self.reply(200 if ok else 400, json.dumps({'ok':ok,'message':message},ensure_ascii=False).encode('utf-8'))
        if self.path == '/api/stop':
            self.reply(202,b'{"stopping":true}')
            self.server.monitor.stopped = True
            self.server.monitor.event.set()
            threading.Thread(target=self.server.shutdown,daemon=True).start()
            return
        if self.path != '/api/refresh':
            return self.reply(404,b'{}')
        self.server.monitor.event.set()
        return self.reply(202,b'{"accepted":true}')

    def log_message(self, fmt, *args):
        pass

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    config = load_config()
    server = ThreadingHTTPServer(('127.0.0.1',8767),Handler)
    server.monitor = Monitor(config)
    threading.Thread(target=server.monitor.run,daemon=True).start()
    logging.info('Dashboard avviata su http://127.0.0.1:8767')
    if not args.no_browser:
        webbrowser.open('http://127.0.0.1:8767')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.monitor.stopped = True
        server.monitor.event.set()
        server.server_close()
        server.monitor.pool.shutdown(wait=False,cancel_futures=True)

if __name__ == '__main__':
    from logging.handlers import RotatingFileHandler
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',handlers=[RotatingFileHandler(ROOT/'dashboard.log',maxBytes=1000000,backupCount=2,encoding='utf-8')])
    try:
        main()
    except Exception:
        logging.exception('Avvio o esecuzione fallita')
