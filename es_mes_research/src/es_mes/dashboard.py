"""Local-only dashboard with allowlisted actions and same-origin write protection."""
import argparse
import json
import secrets
import threading
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
            date=data.get('session_date') or now().tz_convert('America/New_York').strftime('%Y-%m-%d')
            project(self.root,self.forward.snapshot(),date)  # Validate date before storing intent.
            with self.lock:
                file=self.root/'state/dashboard_choices.json'
                choices=json.loads(file.read_text(encoding='utf-8')) if file.exists() else {}
                choices[date]=dict(option=data['option'],selected_at_utc=now().isoformat())
                save(file,choices)
            self.forward.event('USER_OPTIMIZATION_CHOICE',option=data['option'],reviewed_session_date=date)
            # Choice records intent only; frozen strategy does not silently change.
        else:raise ValueError('ACTION_INVALID')



from contextlib import asynccontextmanager
import asyncio
from typing import Literal
from fastapi import FastAPI,Request
from fastapi.responses import HTMLResponse,JSONResponse,StreamingResponse,FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,ConfigDict,StrictInt
from .dashboard_data import project


class Action(BaseModel):
    model_config=ConfigDict(extra="forbid",allow_inf_nan=False)
    action: Literal['probe','start','pause','resume','choose']
    product: Literal['ES','MES'] | None=None
    contract: str | None=None
    expires_on: str | None=None
    timezone: Literal['America/New_York','America/Chicago'] | None=None
    fee: float | None=None
    slip: StrictInt | None=None
    option: Literal['KEEP_FROZEN','QUALIFY_DATA_AND_COSTS','REGISTER_ENTRY_STUDY'] | None=None
    session_date: str | None=None


def create_api(root=ROOT,port=8765):
    service=App(Path(root));origin=f'http://127.0.0.1:{port}'
    @asynccontextmanager
    async def lifespan(api):
        yield
        service.forward.stop_event.set()
    api=FastAPI(title='ES/MES Research',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
    api.state.service=service
    @api.middleware('http')
    async def guard(request:Request,call_next):
        if request.headers.get('host')!=f'127.0.0.1:{port}':return JSONResponse({'error':'HOST_DENIED'},403)
        if request.headers.get('origin') not in [None,origin]:return JSONResponse({'error':'ORIGIN_DENIED'},403)
        if request.method=='POST':
            if request.headers.get('origin')!=origin or request.headers.get('x-csrf-token')!=service.token:
                return JSONResponse({'error':'ORIGIN_OR_TOKEN_DENIED'},403)
            try:length=int(request.headers.get('content-length','0'))
            except ValueError:length=0
            if not 0<length<=4096 or request.headers.get('content-type')!='application/json':return JSONResponse({'error':'INVALID_REQUEST'},400)
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'"
        return response
    @api.get('/')
    def index():return HTMLResponse(Path(__file__).with_name('dashboard.html').read_text(encoding='utf-8'))
    @api.get('/session')
    def session():return dict(token=service.token)
    @api.get('/status')
    def status():return service.status()
    def payload(date):return dict(**service.status(),view=project(service.root,service.forward.snapshot(),date))
    @api.get('/api/dashboard')
    def dashboard(date:str|None=None):
        try:return payload(date)
        except Exception as exc:return JSONResponse({'error':safe_error(exc)},400)
    @api.get('/api/stream')
    async def stream(request:Request,date:str|None=None):
        try:payload(date)
        except Exception as exc:return JSONResponse({'error':safe_error(exc)},400)
        async def updates():
            while not await request.is_disconnected():
                result=await asyncio.to_thread(payload,date)
                yield 'data: '+json.dumps(result,allow_nan=False)+'\n\n'
                await asyncio.sleep(1)
        return StreamingResponse(updates(),media_type='text/event-stream',headers={'X-Accel-Buffering':'no'})
    @api.post('/action')
    def action(body:Action):
        data=body.model_dump(exclude_none=True);command=data.pop('action')
        try:service.action(command,data);return dict(ok=True)
        except Exception as exc:return JSONResponse({'error':safe_error(exc)},400)
    @api.get('/download/{date}/{kind}')
    def download(date:str,kind:Literal['report','trades','bars','events']):
        try:view=project(service.root,service.forward.snapshot(),date)
        except Exception:return JSONResponse({'error':'INVALID_SESSION_DATE'},400)
        if kind=='trades':
            import pandas as pd
            columns=['id','product','contract','direction','quantity','entry_time','entry_price','exit_time','exit_price','stop','target','fee_usd','slippage_ticks','net_usd','status','reason','execution']
            csv=pd.DataFrame(view['trades'],columns=columns).to_csv(index=False)
            return StreamingResponse(iter([csv]),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="{date}_trades.csv"'})
        file=service.root/'artifacts/forward'/date/({'report':'report.md','bars':'completed_bars.csv','events':'events.jsonl'}[kind])
        if not file.exists():return JSONResponse({'error':'NO_DATA_YET'},404)
        return FileResponse(file,filename=date+'_'+file.name)
    api.mount('/assets',StaticFiles(directory=Path(__file__).with_name('web')),name='assets')
    return api


def main():
    import uvicorn
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT);parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    uvicorn.run(create_api(args.root.resolve(),args.port),host='127.0.0.1',port=args.port,workers=1,log_level='warning')


if __name__=='__main__':main()
