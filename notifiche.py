"""Avvisi tramite Outlook classico già aperto nella sessione Windows."""
import json
import logging
import base64
import subprocess
import os
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = ROOT / 'notifiche_stato.json'

def ensure_outlook():
    """Controlla l'istanza Outlook esistente senza aprire finestre."""
    if os.name != 'nt': return False
    script = r"""
$ErrorActionPreference = 'Stop'
try { $null = [Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application'); exit 0 } catch { exit 1 }
"""
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    try:
        result = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',encoded],
          stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10,
          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        return result.returncode == 0
    except (OSError,subprocess.TimeoutExpired): return False

def send_outlook(subject, body):
    """Usa l'istanza Outlook classico già aperta nello stesso utente Windows."""
    if os.name != 'nt':
        raise RuntimeError('Disponibile solo su Windows con Outlook classico aperto')
    script = r"""
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
$payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
$outlook = [Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application')
$mail = $outlook.CreateItem(0)
$mail.To = 'ced@comune-di-esempio.example'
$mail.Subject = [string]$payload.subject
$mail.Body = [string]$payload.body
$mail.Send()
"""
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    result = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',encoded],
        input=json.dumps({'subject':subject,'body':body},ensure_ascii=False), encoding='utf-8',
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:
        raise RuntimeError('Outlook non disponibile o invio bloccato')

def send_test():
    try:
        send_outlook('Test notifiche - Dashboard stampanti',
            'Questa è una email di prova della dashboard stampanti.\nNon riguarda un componente in esaurimento.')
        return True, 'Richiesta inviata a Outlook. Controlla Posta inviata e la casella ced@comune-di-esempio.example.'
    except Exception as exc:
        logging.warning('Test Outlook fallito: %s',type(exc).__name__)
        return False, 'Invio non riuscito: apri Outlook classico con lo stesso utente Windows e verifica eventuali richieste di sicurezza.'

def process(printers):
    try:
        if not ensure_outlook(): return 'Outlook non disponibile: apri Outlook classico. Il programma riprovera al prossimo controllo.'
        recipient = 'ced@comune-di-esempio.example'
        threshold = 20
        sent = json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}
        dirty = False
        for printer in printers:
            if not printer.get('ok'): continue
            for supply in printer.get('supplies', []):
                percent = supply.get('percent')
                if not isinstance(percent,(int,float)) or isinstance(percent,bool): continue
                key = json.dumps([printer.get('id'), supply.get('id')], ensure_ascii=False)
                if percent > threshold:
                    if key in sent:
                        del sent[key]; dirty = True
                    continue
                if key in sent: continue
                name = supply.get('name') or 'Componente'
                msg = EmailMessage()
                msg['To'] = recipient
                msg['Subject'] = 'Stampante: consumabile in esaurimento - ' + str(printer.get('name') or '—')
                kind = 'spazio residuo nel contenitore' if supply.get('receptacle') else 'livello residuo'
                msg.set_content('\n'.join(['Avviso automatico: consumabile da controllare.', '',
                  'Ufficio/stampante: '+str(printer.get('name') or '—'),
                  'Modello: '+str(printer.get('model') or '—'), 'Matricola: '+str(printer.get('serial') or '—'),
                  'IP: '+str(printer.get('ip') or '—'), 'Codice inventario: '+str(printer.get('id') or '—'),
                  'Componente: '+str(name), f'Stato: {percent}% ({kind})',
                  'Soglia avviso: '+str(threshold)+'%', 'Lettura: '+str(printer.get('read_at') or '—'),
                  'Pagina stampante: '+str(printer.get('web') or '—'), '',
                  'Verificare il componente e procedere secondo la procedura dell’ufficio.']))
                send_outlook(str(msg['Subject']), msg.get_content())
                sent[key] = {'component':name,'percent':percent}
                tmp = STATE.with_suffix('.tmp'); tmp.write_text(json.dumps(sent,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(STATE)
                dirty = False
        if dirty:
            tmp = STATE.with_suffix('.tmp'); tmp.write_text(json.dumps(sent,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(STATE)
        return 'Configurato con Outlook classico: avvisi a '+recipient+' per livelli fino al '+str(threshold)+'%; tieni Outlook aperto.'
    except Exception as exc:
        logging.warning('Notifiche email non disponibili: %s',type(exc).__name__)
        return 'Errore invio: verifica che Outlook classico sia aperto e controlla eventuali richieste di sicurezza.'
