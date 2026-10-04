"""Local-only dashboard with allowlisted actions and same-origin write protection."""
import argparse
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from .cli import ROOT,probe,save
from .forward import Forward,safe_error,now


class App:
    def __init__(self,root):
        self.root=root;self.forward=Forward(root);self.token=secrets.token_urlsafe(32)
        self.probing=False;self.probe_error=None;self.lock=threading.Lock()

    def status(self):
        file=self.root/'artifacts/probe.json'
        return dict(forward=self.forward.snapshot(),permissions=json.loads(file.read_text()) if file.exists() else {},
            probing=self.probing,probe_error=self.probe_error,orders_enabled=False,
            reports=sorted(p.parent.name for p in (self.root/'artifacts/forward').glob('*/report.md'))[-20:])

    def action(self,action,data):
        if action=='probe':
            with self.lock:
                if self.probing:raise ValueError('PROBE_ALREADY_RUNNING')
                self.probing=True;self.probe_error=None
            def work():
                try:probe(self.root)
                except Exception as exc:self.probe_error=safe_error(exc)
                finally:self.probing=False
            threading.Thread(target=work,daemon=True).start()
        elif action=='start':
            # Permission check is never inferred from an account opening.
            file=self.root/'artifacts/probe.json'
            record=json.loads(file.read_text()) if file.exists() else {}
            item=record.get('products',{}).get(data.get('product'),{})
            if not item.get('snapshot') or not item.get('history'):raise ValueError('CHECK_MARKET_PERMISSIONS_FIRST')
            if (now()-__import__('pandas').Timestamp(record['at_utc'])).total_seconds()>600:raise ValueError('RECHECK_PERMISSIONS_REQUIRED')
            self.forward.start(data)
        elif action=='pause':self.forward.pause()
        elif action=='resume':self.forward.resume()
        elif action=='choose':
            if data.get('option') not in ['KEEP_FROZEN','QUALIFY_DATA_AND_COSTS','REGISTER_ENTRY_STUDY']:raise ValueError('OPTION_INVALID')
            self.forward.event('USER_OPTIMIZATION_CHOICE',option=data['option'])
            # Choice records intent only; frozen strategy does not silently change.
        else:raise ValueError('ACTION_INVALID')


def handler(app,port):
    origin=f'http://127.0.0.1:{port}'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def respond(self,status,body,content='application/json'):
            encoded=body.encode('utf-8') if isinstance(body,str) else json.dumps(body,allow_nan=False).encode('utf-8')
            self.send_response(status);self.send_header('Content-Type',content+'; charset=utf-8')
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
            self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)
        def valid_host(self):return self.headers.get('Host')==f'127.0.0.1:{port}'
        def do_GET(self):
            if not self.valid_host():return self.respond(403,dict(error='HOST_DENIED'))
            if self.path=='/':
                html=Path(__file__).with_name('dashboard.html').read_text(encoding='utf-8').replace('__TOKEN__',app.token)
                return self.respond(200,html,'text/html')
            if self.path=='/status':return self.respond(200,app.status())
            if self.path.startswith('/report/'):
                date=self.path.removeprefix('/report/')
                import re
                if re.fullmatch(r'\d{4}-\d{2}-\d{2}',date):
                    file=app.root/'artifacts/forward'/date/'report.md'
                    if file.exists():return self.respond(200,file.read_text(encoding='utf-8'),'text/markdown')
            return self.respond(404,dict(error='NOT_FOUND'))
        def do_POST(self):
            if not self.valid_host() or self.headers.get('Origin')!=origin or self.headers.get('X-CSRF-Token')!=app.token:
                return self.respond(403,dict(error='ORIGIN_OR_TOKEN_DENIED'))
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=4096 or self.headers.get('Content-Type')!='application/json':raise ValueError('INVALID_REQUEST')
                if self.path!='/action':return self.respond(404,dict(error='NOT_FOUND'))
                data=json.loads(self.rfile.read(length))
                if not isinstance(data,dict):raise ValueError('INVALID_REQUEST')
                app.action(data.pop('action',''),data)
                return self.respond(200,dict(ok=True))
            except Exception as exc:return self.respond(400,dict(error=safe_error(exc)))
    return Handler


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT);parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args();app=App(args.root.resolve())
    server=ThreadingHTTPServer(('127.0.0.1',args.port),handler(app,args.port))
    print(f'ES/MES dashboard: http://127.0.0.1:{args.port}',flush=True)
    try:server.serve_forever()
    finally:app.forward.stop_event.set();server.server_close()


if __name__=='__main__':main()
