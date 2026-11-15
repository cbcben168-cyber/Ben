"""Local V23C research receiver; no tunnel, broker, or automatic order routing."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8532)
    parser.add_argument('--db',default=str(ROOT/'data/v23c/signals.sqlite3'))
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--simulation',action='store_true',help='Label every received event as isolated simulation')
    args=parser.parse_args()
    if args.port in (8501,8506,8527) or not 1024<=args.port<=65535:
        parser.error('PROTECTED_OR_INVALID_PORT')
    if args.check:
        print(json.dumps(dict(loopback_only=True,port=args.port,db=str(Path(args.db).resolve()),
                              public_ingress=False,phone_delivery_verified=False)))
        return 0
    # Only the one receiver-specific secret is read; .env is never printed.
    token=None
    envfile=ROOT/'.env'
    if envfile.is_file():
        for line in envfile.read_text(encoding='utf-8-sig').splitlines():
            if line.startswith('ICT_V23C_RECEIVER_TOKEN='):
                token=line.split('=',1)[1].strip().strip('\"\'')
    if not token or len(token)<32: parser.error('请在本工作树.env配置ICT_V23C_RECEIVER_TOKEN（至少32字符）；禁止把密钥写进Pine或提交Git。')
    from desk.v23c_receiver import server
    from desk.v23c_signals import SignalStore
    http=server(SignalStore(args.db),token,args.port,args.simulation)
    print('V23C loopback receiver ready; research only',flush=True)
    try: http.serve_forever()
    except KeyboardInterrupt: pass
    finally: http.server_close()
    return 0


if __name__=='__main__':
    raise SystemExit(main())
