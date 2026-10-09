import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import viewer
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'diagnostics'))
import quick_latency


class ViewerTests(unittest.TestCase):
    def test_static_runtime_reload_missing_config_and_port_conflict(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);dist=root/'dist';dist.mkdir();(dist/'index.html').write_text('Viewer fixture')
            private=root/'client.json'
            server=viewer.make_server(private,dist,0)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            def get(path,host=None):
                conn=http.client.HTTPConnection('127.0.0.1',server.server_port)
                conn.request('GET',path,headers={'Host':host or f'127.0.0.1:{server.server_port}'})
                response=conn.getresponse();data=response.read();conn.close();return response.status,data
            try:
                self.assertEqual(get('/')[0],200);self.assertEqual(get('/config.json')[0],409)
                c={'turn':{'signalingServer':'example.invalid','signalingPort':50239,'mediaServer':'172.17.0.6','mediaPort':47998,
                    'iceServerConfiguration':{'iceTransportPolicy':'relay','iceServers':[{'urls':'turn:example.invalid:27645?transport=tcp','username':'fixture','credential':'fixture'}]},'remote_key':'exclude'}}
                private.write_text(json.dumps(c))
                code,data=get('/config.json?transport=turn');self.assertEqual(code,200);self.assertNotIn(b'remote_key',data)
                self.assertEqual(json.loads(get('/transports.json')[1]),{'transports':['turn']})
                self.assertEqual(get('/config.json?transport=relay')[0],409)
                self.assertEqual(get('/config.json','attacker.invalid')[0],403)
                with self.assertRaises(OSError):viewer.make_server(private,dist,server.server_port)
                private.write_text('invalid');self.assertEqual(get('/config.json')[0],409)
            finally:server.shutdown();server.server_close();thread.join()

    def test_private_config_symlinks_not_served(self):
        if os.name=='nt':self.skipTest('symlink privileges vary on Windows')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);dist=root/'dist';dist.mkdir();private=root/'secret.json';private.write_text('private')
            (dist/'leak.json').symlink_to(private)
            server=viewer.make_server(private,dist,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                conn=http.client.HTTPConnection('127.0.0.1',server.server_port);conn.request('GET','/leak.json')
                response=conn.getresponse();self.assertEqual(response.status,404);response.read();conn.close()
            finally:server.shutdown();server.server_close();thread.join()

    def test_latency_quantiles_exclude_response_after_timeout(self):
        rows=[{'operation_id':i,'status':status,'latency_ms':latency} for i,status,latency in
              [(1,'response',100),(2,'timeout',None),(3,'response',1800),(4,'response',120)]]
        result=quick_latency.summarize(rows,[])
        self.assertEqual(result['responses'],3);self.assertEqual(result['latency_samples'],2)
        self.assertEqual(result['excluded_after_timeout'],1);self.assertEqual(result['latency_ms']['median'],110)


if __name__=='__main__':unittest.main()
