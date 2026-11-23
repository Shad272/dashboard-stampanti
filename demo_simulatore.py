"""Dashboard stampanti - versione dimostrativa con stampanti simulate.

Uso: doppio clic su DEMO_SIMULATORE.cmd (Windows) oppure, da questa cartella,
     python3 demo_simulatore.py
Si apre http://127.0.0.1:8767. Per fermarla chiudi la finestra o premi Ctrl+C.

Il programma della dashboard non viene modificato. Questo file:
- avvia sul PC (127.0.0.1) dieci stampanti finte che rispondono come stampanti
  SNMP vere, con livelli e contatori che cambiano mentre la guardi;
- devia le letture SNMP verso le stampanti finte: nessun pacchetto va in rete,
  anche se in stampanti.json scrivi indirizzi diversi;
- disattiva le email di avviso, che nella versione dimostrativa non partono mai.
"""
import logging
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import server as app  # noqa: E402  (il programma originale)
import notifiche  # noqa: E402

INIZIO = time.monotonic()
MIB = app.MIB
HR = '1.3.6.1.2.1.25.3.'

# Codici della Printer MIB (RFC 3805)
TONER, SCARTO, CARTUCCIA_INCHIOSTRO, FOTORICETTORE, FUSORE, KIT = 3, 4, 6, 9, 15, 18
CONSUMATO, RACCOLTA = 3, 4
PERCENTO, IMPRESSIONI = 19, 7
IN_FUNZIONE, AVVISO = 2, 3
ALTRO, IN_ATTESA, IN_STAMPA = 1, 3, 4


def minuti():
    return (time.monotonic() - INIZIO) / 60


def cresce(base, al_minuto):
    """Contatore di pagine che aumenta mentre la demo resta aperta."""
    return int(base + al_minuto * minuti())


def cala(inizio, al_minuto, minimo=1):
    """Livello che scende mentre la demo resta aperta."""
    return max(minimo, int(round(inizio - al_minuto * minuti())))


def base(modello, matricola, stato):
    return {'1.3.6.1.2.1.1.1.0': modello + ' (stampante simulata)',
            MIB + '5.1.1.17.1': matricola, HR + '5.1.1.1': stato}


def materiali(*voci):
    """voci: (nome, tipo, classe, unita, massimo, livello)."""
    t = {}
    for i, (nome, tipo, classe, unita, massimo, livello) in enumerate(voci, 1):
        s = '.1.' + str(i)
        t.update({MIB + '11.1.1.4' + s: classe, MIB + '11.1.1.5' + s: tipo, MIB + '11.1.1.6' + s: nome,
                  MIB + '11.1.1.7' + s: unita, MIB + '11.1.1.8' + s: massimo, MIB + '11.1.1.9' + s: livello})
    return t


def vassoi(*voci):
    """voci: (nome, capacita in fogli, livello, formato, tipo, colore)."""
    t = {}
    for i, (nome, capacita, livello, formato, tipo, colore) in enumerate(voci, 1):
        s = '.1.' + str(i)
        t.update({MIB + '8.2.1.13' + s: nome, MIB + '8.2.1.18' + s: nome, MIB + '8.2.1.8' + s: 8,
                  MIB + '8.2.1.9' + s: capacita, MIB + '8.2.1.10' + s: livello,
                  MIB + '8.2.1.12' + s: formato, MIB + '8.2.1.21' + s: tipo, MIB + '8.2.1.22' + s: colore})
    return t


def contatori(*valori):
    t = {}
    for i, valore in enumerate(valori, 1):
        t.update({MIB + '10.2.1.3.1.' + str(i): IMPRESSIONI, MIB + '10.2.1.4.1.' + str(i): valore})
    return t


def dispositivi(*voci):
    t = {}
    for i, (nome, stato) in enumerate(voci, 1):
        t.update({HR + '2.1.3.' + str(i): nome, HR + '2.1.5.' + str(i): stato})
    return t


def elenco(radice, *testi):
    return {radice + '.1.' + str(i): testo for i, testo in enumerate(testi, 1)}


def avvisi(*testi):
    return elenco(MIB + '18.1.1.8', *testi)


def display(*testi):
    return elenco(MIB + '16.5.1.2', *testi)


A4 = ('iso-a4', 'stationery', 'white')
A3 = ('iso-a3', 'stationery', 'white')


def canon_colore(modello, matricola, nero, ciano, magenta, giallo, scarto, stato=IN_ATTESA):
    return (base(modello, matricola, stato)
            | materiali(('Toner nero', TONER, CONSUMATO, PERCENTO, 100, nero),
                        ('Toner ciano', TONER, CONSUMATO, PERCENTO, 100, ciano),
                        ('Toner magenta', TONER, CONSUMATO, PERCENTO, 100, magenta),
                        ('Toner giallo', TONER, CONSUMATO, PERCENTO, 100, giallo),
                        ('Contenitore toner di scarto', SCARTO, RACCOLTA, PERCENTO, 100, scarto))
            | dispositivi((modello + ' stampante', IN_FUNZIONE), (modello + ' scanner', IN_FUNZIONE)))


# Ogni stampante e' una funzione: i valori vengono ricalcolati a ogni lettura.
def biblioteca():        # colori misti, stampa in corso, tre contatori
    return (canon_colore('Canon iR-ADV C5850', 'DEMO-C5850-01', 76, 54, cala(41, .2), 63, 70, IN_STAMPA)
            | contatori(cresce(84210, 6), cresce(51377, 4), cresce(32833, 2))
            | vassoi(('Cassetto 1', 550, 410, *A4), ('Cassetto 2', 550, 120, *A4), ('Cassetto 3', 550, 550, *A3))
            | display('Stampa in corso'))


def protocollo():        # toner ciano quasi finito con avviso
    return (canon_colore('Canon iR-ADV C3826', 'DEMO-C3826-02', 48, cala(14, .1), 52, 66, 35)
            | contatori(cresce(40112, 3), cresce(18904, 1))
            | vassoi(('Cassetto 1', 550, 260, *A4), ('Cassetto 2', 550, 300, *A3))
            | avvisi('Toner ciano in esaurimento. Preparare una cartuccia di ricambio.')
            | display('Pronta', 'Toner ciano in esaurimento'))


def edilizia():          # inchiostro con livello sconosciuto e testina "presente"
    return (base('HP PageWide Color 755', 'DEMO-PW755-03', IN_ATTESA)
            | materiali(('Cartuccia inchiostro nero', CARTUCCIA_INCHIOSTRO, CONSUMATO, PERCENTO, 100, -2),
                        ('Cartuccia inchiostro ciano', CARTUCCIA_INCHIOSTRO, CONSUMATO, PERCENTO, 100, 71),
                        ('Cartuccia inchiostro magenta', CARTUCCIA_INCHIOSTRO, CONSUMATO, PERCENTO, 100, 69),
                        ('Cartuccia inchiostro giallo', CARTUCCIA_INCHIOSTRO, CONSUMATO, PERCENTO, 100, 22),
                        ('Testina di stampa', KIT, CONSUMATO, PERCENTO, 100, -3))
            | contatori(cresce(22654, 2))
            | vassoi(('Vassoio 2', 500, 350, *A4), ('Vassoio 3', 500, 500, *A3)))


def segreteria():        # risponde solo in SNMPv1: la dashboard ripiega da v2c a v1
    return (base('HP PageWide Color 755', 'DEMO-PW755-04', IN_ATTESA)
            | materiali(('Cartuccia inchiostro nero', CARTUCCIA_INCHIOSTRO, CONSUMATO, PERCENTO, 100, 88),
                        ('Cartuccia inchiostro ciano', CARTUCCIA_INCHIOSTRO, CONSUMATO, PERCENTO, 100, 64),
                        ('Cartuccia inchiostro magenta', CARTUCCIA_INCHIOSTRO, CONSUMATO, PERCENTO, 100, 59),
                        ('Cartuccia inchiostro giallo', CARTUCCIA_INCHIOSTRO, CONSUMATO, PERCENTO, 100, 91))
            | contatori(cresce(9876, 1)))


def tributi():           # toner nero che scende sotto la soglia del 20% dopo pochi minuti
    return (base('HP LaserJet MFP E73030', 'DEMO-E73030-06', IN_STAMPA)
            | materiali(('Cartuccia toner nero', TONER, CONSUMATO, PERCENTO, 100, cala(23, 1)),
                        ('Kit di manutenzione', KIT, CONSUMATO, PERCENTO, 100, 35))
            | contatori(cresce(61540, 8))
            | vassoi(('Vassoio 1', 100, -3, *A4), ('Vassoio 2', 520, 380, *A4))
            | dispositivi(('HP LaserJet MFP E73030', IN_FUNZIONE)))


def polizia():           # risponde solo all'inizio, poi tace: resta l'ultima lettura valida
    return (canon_colore('Canon iR-ADV C5850', 'DEMO-C5850-07', 33, 57, 61, 49, 52)
            | contatori(cresce(70321, 3)))


def servizi_sociali():   # carta inceppata: avviso, messaggio sul display, dispositivo in avviso
    t = (canon_colore('Canon iR-ADV C5850', 'DEMO-C5850-08', 67, 45, 72, 38, 81, ALTRO)
         | contatori(cresce(55009, 0))
         | vassoi(('Cassetto 1', 550, 200, *A4), ('Cassetto 2', 550, 90, *A4))
         | avvisi('Inceppamento carta nel cassetto 2.')
         | display('Rimuovere la carta inceppata nel cassetto 2.'))
    t[HR + '2.1.5.1'] = AVVISO
    return t


def anagrafe():          # fotoricettore quasi esaurito: da qui si apre il modulo di richiesta
    return (base('Xerox VersaLink B7030 MFP', 'DEMO-B7030-09', IN_ATTESA)
            | materiali(('Toner nero', TONER, CONSUMATO, PERCENTO, 100, 58),
                        ('Drum Cartridge (fotoricettore)', FOTORICETTORE, CONSUMATO, PERCENTO, 100, cala(12, .1)),
                        ('Fuser', FUSORE, CONSUMATO, PERCENTO, 100, -3))
            | contatori(cresce(123456, 4))
            | vassoi(('Vassoio 1', 520, 312, *A4), ('Vassoio 2', 520, 0, *A4), ('Vassoio 3', 520, -3, *A3),
                     ('Bypass', 100, -3, *A4))
            | dispositivi(('Xerox VersaLink B7030 stampante', IN_FUNZIONE), ('Scanner', IN_FUNZIONE))
            | avvisi('016-424 Device is in low power mode. No action is required.',
                     'Drum Cartridge is near end of life. Order a replacement.')
            | display('Risparmio energetico'))


def ragioneria():        # due contatori: il modulo lascia il contatore da compilare
    return (base('Xerox VersaLink B7030 MFP', 'DEMO-B7030-10', IN_ATTESA)
            | materiali(('Toner nero', TONER, CONSUMATO, PERCENTO, 100, 81),
                        ('Drum Cartridge (fotoricettore)', FOTORICETTORE, CONSUMATO, PERCENTO, 100, 64),
                        ('Fuser', FUSORE, CONSUMATO, PERCENTO, 100, -3))
            | contatori(cresce(98302, 3), cresce(4120, 1))
            | vassoi(('Vassoio 1', 520, 500, *A4), ('Vassoio 2', 520, 150, *A3))
            | dispositivi(('Xerox VersaLink B7030 stampante', IN_FUNZIONE), ('Scanner', IN_FUNZIONE))
            | display('Pronta'))


# codice stampante -> (valori, versioni SNMP accettate, secondi dopo cui smette di rispondere)
SIMULATE = {
    'ST-001': (biblioteca, (0, 1), None),
    'ST-002': (protocollo, (0, 1), None),
    'ST-003': (edilizia, (0, 1), None),
    'ST-004': (segreteria, (0,), None),
    # ST-005 non ha simulatore: e' spenta o irraggiungibile
    'ST-006': (tributi, (0, 1), None),
    'ST-007': (polizia, (0, 1), 20),
    'ST-008': (servizi_sociali, (0, 1), None),
    'ST-009': (anagrafe, (0, 1), None),
    'ST-010': (ragioneria, (0, 1), None),
}


class StampanteFinta:
    """Risponde a GET e GETNEXT come una stampante SNMP, solo sull'indirizzo locale."""

    def __init__(self, valori=None, versioni=(0, 1), smette_dopo=None):
        self.valori, self.versioni, self.smette_dopo = valori, set(versioni), smette_dopo
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('127.0.0.1', 0))
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self.ascolta, daemon=True).start()

    def ascolta(self):
        while True:
            try:
                raw, mittente = self.sock.recvfrom(65535)
            except OSError:
                return
            if self.valori is None:
                continue  # stampante spenta: nessuna risposta
            if self.smette_dopo is not None and time.monotonic() - INIZIO > self.smette_dopo:
                continue  # ha smesso di rispondere (spenta o in risparmio energetico)
            try:
                risposta = self.rispondi(raw)
            except Exception:
                continue
            if risposta:
                self.sock.sendto(risposta, mittente)

    def rispondi(self, raw):
        esterno = app.children(app.unpack(raw)[1])
        pdu = app.children(esterno[2][1])
        versione = app.scalar(*esterno[0])
        if versione not in self.versioni:
            return None
        richiesto = app.decode_oid(app.children(app.children(pdu[3][1])[0][1])[0][1])
        valori = self.valori()
        chiave = lambda oid: tuple(map(int, oid.split('.')))
        if esterno[2][0] == 0xA1:  # GETNEXT
            successivi = [k for k in valori if chiave(k) > chiave(richiesto)]
            oid = min(successivi, key=chiave) if successivi else richiesto
            valore = valori[oid] if successivi else None
        else:  # GET
            oid, valore = richiesto, valori.get(richiesto)
        codificato = (app.integer(valore) if isinstance(valore, int)
                      else app.tlv(4, valore.encode()) if isinstance(valore, str) else app.tlv(0x82, b''))
        vb = app.tlv(0x30, app.oid_encode(oid) + codificato)
        return app.tlv(0x30, app.integer(versione) + app.tlv(4, esterno[1][1])
                       + app.tlv(0xA2, app.integer(app.scalar(*pdu[0])) + app.integer(0) + app.integer(0) + app.tlv(0x30, vb)))


def prepara():
    config = app.load_config()
    spenta = StampanteFinta()
    porte = {}
    for p in config['printers']:
        valori, versioni, smette = SIMULATE.get(p['id'], (None, (0, 1), None))
        porte[p.get('ip')] = StampanteFinta(valori, versioni, smette).port if valori else spenta.port
    vera = app.Snmp

    def snmp_simulato(host, community, *args, **kwargs):
        kwargs.pop('port', None)
        return vera('127.0.0.1', community, *args, port=porte.get(host, spenta.port), **kwargs)

    app.Snmp = snmp_simulato
    notifiche.process = lambda printers: 'Versione dimostrativa: le email di avviso sono disattivate.'
    notifiche.send_test = lambda: (False, "Versione dimostrativa: l'invio delle email e' disattivato.")
    return config


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    config = prepara()
    print('\nDASHBOARD STAMPANTI - VERSIONE DIMOSTRATIVA')
    print(str(len(config['printers'])) + ' stampanti configurate, tutte simulate su questo PC: nessuna lettura in rete.')
    print('Indirizzo: http://127.0.0.1:8767')
    print('Lascia aperta questa finestra. Per terminare chiudila o premi Ctrl+C.\n')
    app.main()
