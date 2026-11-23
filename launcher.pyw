"""Avvio silenzioso Windows, avvio su richiesta e collegamento browser."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
import shutil

ROOT=Path(__file__).resolve().parent
URL='http://127.0.0.1:8767'
OPENER=urllib.request.build_opener(urllib.request.ProxyHandler({}))

def find_chrome():
    candidates=[]
    if os.name=='nt':
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
            for view in (winreg.KEY_WOW64_64KEY,winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(hive,r'Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe',0,winreg.KEY_READ|view) as key:
                        candidates.append(Path(os.path.expandvars(winreg.QueryValueEx(key,None)[0].strip('"'))))
                except OSError:
                    pass
    for variable in ('LOCALAPPDATA','PROGRAMFILES','PROGRAMFILES(X86)'):
        folder=os.environ.get(variable)
        if folder:candidates.append(Path(folder)/'Google'/'Chrome'/'Application'/'chrome.exe')
    on_path=shutil.which('chrome.exe') or shutil.which('google-chrome')
    if on_path:candidates.append(Path(on_path))
    return next((p for p in candidates if p.is_file()),None)

def open_dashboard():
    chrome=find_chrome()
    if chrome:
        subprocess.Popen([str(chrome),'--new-tab',URL],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0)
    elif os.name=='nt':
        raise RuntimeError('Google Chrome non trovato. Installa Chrome oppure verifica il percorso di chrome.exe. Nessun altro browser e stato aperto.')
    else:
        webbrowser.open(URL)

def health():
    try:
        with OPENER.open(URL+'/api/health',timeout=.5) as r:
            data=json.load(r)
        return data.get('app')=='dashboard-stampanti'
    except (OSError,ValueError):
        return False

def stop_server():
    if not health():
        print('La dashboard stampanti non risponde sulla porta 8767: potrebbe essere gia arrestata.')
        return
    req=urllib.request.Request(URL+'/api/stop',method='POST',headers={'Origin':URL})
    with OPENER.open(req,timeout=5) as response:
        if response.status != 202: raise RuntimeError('Il server non ha accettato la richiesta di arresto.')
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        if not health():
            print('Dashboard stampanti arrestata. Outlook rimane aperto.')
            return
        time.sleep(.2)
    raise RuntimeError('La dashboard non si e arrestata entro 8 secondi. Riprova.')

def start_server():
    if health():return
    with socket.socket() as s:
        if s.connect_ex(('127.0.0.1',8767))==0:
            raise RuntimeError('La porta 8767 e occupata: chiudi la vecchia versione della dashboard e riprova.')
    executable=Path(sys.executable)
    windowed=executable.with_name('pythonw.exe')
    if os.name=='nt' and windowed.exists():executable=windowed
    with open(ROOT/'avvio.log','a',encoding='utf-8') as log:
        process=subprocess.Popen([str(executable),str(ROOT/'server.py'),'--no-browser'],cwd=ROOT,
            stdin=subprocess.DEVNULL,stdout=log,stderr=log,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0)
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        if health():return
        if process.poll() is not None:break
        time.sleep(.15)
    raise RuntimeError('Il server non si e avviato. Controlla dashboard.log e avvio.log nella cartella del programma.')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--background',action='store_true')
    parser.add_argument('--no-outlook',action='store_true')
    parser.add_argument('--stop',action='store_true')
    parser.add_argument('--url',default='')
    args=parser.parse_args()
    handle=None
    try:
        if os.name=='nt':
            from ctypes import wintypes
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
            kernel.CreateMutexW.restype=wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
            kernel.ReleaseMutex.argtypes=[wintypes.HANDLE]
            kernel.CloseHandle.argtypes=[wintypes.HANDLE]
            handle=kernel.CreateMutexW(None,False,'Local\\DashboardStampantiLauncherV6')
            if not handle:raise OSError('Impossibile creare il blocco di avvio')
            if kernel.WaitForSingleObject(handle,20000) not in (0,0x80):
                kernel.CloseHandle(handle);handle=None
                raise RuntimeError('Un altro avvio e in corso. Riprova tra qualche secondo.')
        if args.stop:
            stop_server();return
        start_server()
        if args.background and not args.no_outlook and os.name=='nt':
            helper=ROOT/'Outlook_CED.ps1'
            subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File',str(helper),'-Mode','Startup'],
                cwd=ROOT,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if not args.background:open_dashboard()
    except Exception as exc:
        with open(ROOT/'avvio.log','a',encoding='utf-8') as log:log.write(time.strftime('%Y-%m-%d %H:%M:%S')+' '+repr(exc)+'\n')
        if args.stop:
            print('Errore durante l arresto: '+str(exc))
        elif not args.background and os.name=='nt':ctypes.windll.user32.MessageBoxW(None,str(exc),'Dashboard stampanti',0x10)
        raise SystemExit(1)
    finally:
        if handle:
            kernel.ReleaseMutex(handle);kernel.CloseHandle(handle)

if __name__=='__main__':main()
