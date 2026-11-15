"""Authenticated loopback ingestion. Public ingress is deliberately absent."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json


def server(store,token,port=8532,simulation=False):
    if not isinstance(token,str) or len(token)<32: raise ValueError('RECEIVER_TOKEN_REQUIRED')
    if port in (8501,8506,8527): raise ValueError('PROTECTED_PORT')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass  # Never put tokens, URLs or payloads in access logs.
        def reply(self,status,value):
            body=json.dumps(value,ensure_ascii=False).encode()
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def do_GET(self):
            self.reply(200 if self.path=='/health' else 404,dict(service='V23C_RESEARCH_RECEIVER',loopback_only=True))
        def do_POST(self):
            self.connection.settimeout(3)
            if self.path!='/v23c/events': return self.reply(404,dict(error='NOT_FOUND'))
            if not hmac.compare_digest(self.headers.get('Authorization','').encode('utf-8'), ('Bearer '+token).encode('utf-8')):
                return self.reply(401,dict(error='UNAUTHORIZED'))
            try: size=int(self.headers.get('Content-Length','0'))
            except ValueError: size=0
            if not 0<size<=16384: return self.reply(413,dict(error='BODY_SIZE'))
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                return self.reply(415,dict(error='JSON_REQUIRED'))
            try:
                def unique(pairs):
                    result={}
                    for k,v in pairs:
                        if k in result: raise ValueError('DUPLICATE_JSON_FIELD')
                        result[k]=v
                    return result
                payload=json.loads(self.rfile.read(size).decode('utf-8'),object_pairs_hook=unique)
                result=store.ingest(payload,simulation=simulation)
                self.reply(200,dict(id=result['id'],duplicate=result['duplicate'],quality=result['quality'],trading_eligible=False))
            except (ValueError,UnicodeError,TimeoutError) as exc:
                code=str(exc)
                if not code.replace('_','').isalnum() or len(code)>64: code='INVALID_MESSAGE'
                self.reply(400,dict(error=code))
            except Exception:
                self.reply(503,dict(error='STORE_UNAVAILABLE'))
    return ThreadingHTTPServer(('127.0.0.1',port),Handler)
