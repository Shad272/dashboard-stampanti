"""Test senza collegamenti alle stampanti: python -m unittest -v test_dashboard.py"""
import http.client
import json
import socket
import threading
import unittest
from importlib.machinery import SourceFileLoader
from importlib.util import spec_from_loader,module_from_spec
from unittest.mock import patch
import server as app

class FakePrinter:
    def __init__(self):
        self.sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        self.sock.bind(('127.0.0.1',0))
        self.port=self.sock.getsockname()[1]
        self.sock.settimeout(.1)
        self.stop=False
        self.level=30
        self.supported_versions={0,1}
        self.thread=threading.Thread(target=self.run,daemon=True)
        self.thread.start()

    def values(self):
        return {'1.3.6.1.2.1.1.1.0':'Simulatore test',app.MIB+'5.1.1.17.1':'TEST123',
            app.MIB+'11.1.1.4.1.1':3,app.MIB+'11.1.1.5.1.1':3,
            app.MIB+'11.1.1.6.1.1':'Toner ciano',app.MIB+'11.1.1.7.1.1':19,
            app.MIB+'11.1.1.8.1.1':100,app.MIB+'11.1.1.9.1.1':self.level,
            app.MIB+'18.1.1.8.1.1':'Carta assente',app.MIB+'10.2.1.3.1.1':7,
            app.MIB+'10.2.1.4.1.1':12345,'1.3.6.1.2.1.25.3.5.1.1.1':3}

    def run(self):
        while not self.stop:
            try:
                raw,peer=self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            outer=app.children(app.unpack(raw)[1]);pdu=app.children(outer[2][1])
            if app.scalar(*outer[0]) not in self.supported_versions:
                continue
            varbind=app.children(app.children(pdu[3][1])[0][1]);oid=app.decode_oid(varbind[0][1])
            values=self.values()
            if outer[2][0]==0xA1:
                keys=sorted(values,key=lambda x:tuple(map(int,x.split('.'))))
                oid=next((k for k in keys if tuple(map(int,k.split('.')))>tuple(map(int,oid.split('.')))),oid)
                value=values.get(oid) if oid in keys and oid!=app.decode_oid(varbind[0][1]) else None
            else:
                value=values.get(oid)
            encoded=app.integer(value) if isinstance(value,int) else app.tlv(4,value.encode()) if isinstance(value,str) else app.tlv(0x82,b'')
            vb=app.tlv(0x30,app.oid_encode(oid)+encoded)
            response=app.tlv(0x30,app.integer(app.scalar(*outer[0]))+app.tlv(4,outer[1][1])+app.tlv(0xA2,app.integer(app.scalar(*pdu[0]))+app.integer(0)+app.integer(0)+app.tlv(0x30,vb)))
            self.sock.sendto(response,peer)

    def close(self):
        self.stop=True;self.thread.join(1);self.sock.close()

class Tests(unittest.TestCase):
    def test_silent_launcher(self):
        loader=SourceFileLoader('silent_launcher',str(app.ROOT/'launcher.pyw'))
        spec=spec_from_loader(loader.name,loader)
        launcher=module_from_spec(spec);loader.exec_module(launcher)
        with patch.object(launcher,'start_server') as start, patch.object(launcher,'open_dashboard') as browser, patch.object(launcher.sys,'argv',['launcher.pyw','--background']):
            launcher.main();start.assert_called_once();browser.assert_not_called()
        with patch.object(launcher,'start_server') as start, patch.object(launcher,'open_dashboard') as browser, patch.object(launcher.sys,'argv',['launcher.pyw','--url','stampanti-locali://apri']):
            launcher.main();start.assert_called_once();browser.assert_called_once_with()
        with patch.object(launcher,'find_chrome',return_value=app.ROOT/'chrome.exe'),patch.object(launcher.subprocess,'Popen') as process,patch.object(launcher.webbrowser,'open') as default_browser:
            launcher.open_dashboard()
            self.assertEqual(process.call_args.args[0],[str(app.ROOT/'chrome.exe'),'--new-tab',launcher.URL])
            default_browser.assert_not_called()
        with patch.object(launcher,'health',return_value=True),patch.object(launcher.subprocess,'Popen') as process:
            launcher.start_server();process.assert_not_called()
        with patch.object(launcher,'health',side_effect=[False,True]),patch.object(launcher.socket,'socket') as sock,patch.object(launcher.subprocess,'Popen') as process:
            sock.return_value.__enter__.return_value.connect_ex.return_value=1
            launcher.start_server()
            self.assertIn('--no-browser',process.call_args.args[0])
            self.assertEqual(process.call_args.kwargs['stdin'],launcher.subprocess.DEVNULL)
    def test_codec(self):
        for oid in ['1.3.6.1.2.1.43.11.1.1.9.1.1','2.999.5000.1']:
            self.assertEqual(app.decode_oid(app.unpack(app.oid_encode(oid))[1]),oid)
        for n in [-3,-2,-1,0,127,128,12345,2**30]:
            t,v,_=app.unpack(app.integer(n));self.assertEqual(app.scalar(t,v),n)
        with self.assertRaises(ValueError):app.unpack(b'\x30\x82\x01')

    def test_snmp_live_change(self):
        fake=FakePrinter()
        try:
            client=app.Snmp('127.0.0.1','public',port=fake.port)
            self.assertEqual(client.request('1.3.6.1.2.1.1.1.0')[1],'Simulatore test')
            table=app.table_rows(client.walk(app.MIB+'11.1.1'))
            self.assertEqual(app.supply(table['1.1'],'1.1')['percent'],30)
            fake.level=9
            table=app.table_rows(client.walk(app.MIB+'11.1.1'))
            self.assertEqual(app.supply(table['1.1'],'1.1')['percent'],9)
            real=app.Snmp
            with patch.object(app,'Snmp',side_effect=lambda host,community:real('127.0.0.1',community,port=fake.port)):
                result=app.collect({'id':'T','name':'Test','ip':'192.168.1.2'},{})
            self.assertTrue(result['ok']);self.assertEqual(result['serial'],'TEST123')
            self.assertEqual(result['counters'][0]['value'],12345)
            self.assertEqual(result['alerts'],['Carta assente'])
            self.assertFalse(result['warnings'])
            self.assertIn('trays',result)
            self.assertIn('devices',result)
        finally:fake.close()

    def test_unknown_and_receptacle(self):
        for n in [-1,-2,-3]:
            self.assertIsNone(app.supply({9:n,8:100,7:19},'x')['percent'])
        self.assertEqual(app.supply({9:25,8:200,7:7},'x')['percent'],12)
        self.assertTrue(app.supply({4:4},'x')['receptacle'])

    def test_v1_only_and_auto_fallback(self):
        fake=FakePrinter();fake.supported_versions={0}
        real=app.Snmp
        try:
            with patch.object(app,'Snmp',side_effect=lambda host,community:real('127.0.0.1',community,port=fake.port,timeout=.05)):
                result=app.collect({'id':'T','name':'Canon test','ip':'192.168.1.2'},{})
            self.assertTrue(result['ok'])
            self.assertEqual(result['protocol'],'SNMPv1')
            self.assertEqual(result['supplies'][0]['percent'],30)
            self.assertEqual(result['diagnostic_attempts'][0]['protocol'],'SNMPv2c')
        finally:fake.close()

    def test_stale_reading(self):
        m=app.Monitor({'printers':[{'id':'T'}],'interval_seconds':60})
        try:
            with patch.object(app,'collect',return_value={'id':'T','ok':True,'read_at':'before','supplies':[{'percent':60}]}):m.cycle()
            with patch.object(app,'collect',return_value={'id':'T','ok':False,'error':'timeout'}):m.cycle()
            item=m.snapshot()['printers'][0]
            self.assertFalse(item['ok']);self.assertEqual(item['last_good']['read_at'],'before')
        finally:m.pool.shutdown()

    def test_xerox_extended_tables(self):
        values={app.MIB+'8.2.1.13':{'1.1':'Vassoio 1','1.2':'Bypass'},
            app.MIB+'8.2.1.8':{'1.1':8,'1.2':8},app.MIB+'8.2.1.9':{'1.1':500,'1.2':100},
            app.MIB+'8.2.1.10':{'1.1':250,'1.2':-3},app.MIB+'8.2.1.12':{'1.1':'iso-a4'},
            '1.3.6.1.2.1.25.3.2.1.3':{'2':'Scanner'},'1.3.6.1.2.1.25.3.2.1.5':{'2':2},
            app.MIB+'16.5.1.2':{'1.1':'Pronta'}}
        class Client:
            def walk(self,root,limit):return values.get(root,{})
        result={'model':'Xerox B7030','warnings':[],'alerts':['016-424 Device is in low power mode. No action is required.','Riordina fotorecettore']}
        app.printer_extra(Client(),result)
        self.assertEqual(result['trays'][0]['percent'],50)
        self.assertEqual(result['trays'][0]['media'],'iso-a4')
        self.assertIsNone(result['trays'][1]['percent'])
        self.assertIn('Carta presente',result['trays'][1]['detail'])
        self.assertEqual(result['devices'][0]['status'],'In funzione')
        self.assertEqual(result['console'],['Pronta'])
        self.assertEqual(len(result['informational_alerts']),1)
        for model in ('Canon C5850','HP PageWide 755'):
            other={'model':model,'warnings':[],'alerts':[]}
            app.printer_extra(Client(),other)
            self.assertEqual(other['trays'][0]['percent'],50)
            self.assertEqual(other['devices'][0]['name'],'Scanner')
        empty={'warnings':[],'alerts':[]}
        values.clear();app.printer_extra(Client(),empty)
        self.assertEqual(empty['trays'],[])
        self.assertEqual(empty['devices'],[])

    def test_http_and_origin(self):
        httpd=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        httpd.monitor=app.Monitor({'printers':[],'interval_seconds':60})
        thread=threading.Thread(target=httpd.serve_forever,daemon=True);thread.start()
        conn=http.client.HTTPConnection('127.0.0.1',httpd.server_port)
        try:
            conn.request('GET','/',headers={'Host':'127.0.0.1:8767'})
            response=conn.getresponse();self.assertEqual(response.status,200);self.assertIn(b'Le tue stampanti',response.read())
            conn.request('GET','/api/status',headers={'Host':'127.0.0.1:8767'})
            response=conn.getresponse();self.assertEqual(json.loads(response.read())['configured_count'],0)
            conn.request('GET','/api/health',headers={'Host':'127.0.0.1:8767'})
            response=conn.getresponse();self.assertEqual(json.loads(response.read())['app'],'dashboard-stampanti')
            conn.request('GET','/richiesta-fotorecettore?counter=123456',headers={'Host':'127.0.0.1:8767'})
            response=conn.getresponse();self.assertEqual(response.status,200)
            form=response.read();self.assertIn(b'DEMO-B7030-09',form);self.assertIn(b'richieste@fornitore-di-esempio.example',form)
            self.assertIn("img-src 'self' data:",response.getheader('Content-Security-Policy'))
            conn.request('POST','/api/refresh',headers={'Host':'127.0.0.1:8767','Origin':'https://example.com'})
            response=conn.getresponse();self.assertEqual(response.status,403);response.read()
            conn.request('POST','/api/refresh',headers={'Host':'127.0.0.1:8767','Origin':'http://127.0.0.1:8767'})
            response=conn.getresponse();self.assertEqual(response.status,202);response.read()
            conn.request('GET','/api/status',headers={'Host':'untrusted.example'})
            response=conn.getresponse();self.assertEqual(response.status,403);response.read()
            conn.request('POST','/api/stop',headers={'Host':'127.0.0.1:8767','Origin':'http://127.0.0.1:8767'})
            response=conn.getresponse();self.assertEqual(response.status,202);response.read()
            self.assertTrue(httpd.monitor.stopped)
        finally:conn.close();httpd.shutdown();httpd.server_close();thread.join();httpd.monitor.pool.shutdown()

if __name__=='__main__':unittest.main()
