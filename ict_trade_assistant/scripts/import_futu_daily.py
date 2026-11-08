"""Validate a complete capture and write only a new, independent Futu archive."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from capture_futu_daily import SYMBOLS
from desk.futu_daily import FutuDailyArchive, verify_payload


def main(directory, database):
    directory, database = Path(directory), Path(database)
    manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    if manifest['format'] != 'FUTU_DAILY_CAPTURE_V1' or set(manifest['files']) != {s+'.json' for s in SYMBOLS}:
        raise ValueError('必须是完整23只证券的独立Futu数据包')
    payloads = []
    for ticker in SYMBOLS:
        encoded = (directory/(ticker+'.json')).read_bytes()
        if hashlib.sha256(encoded).hexdigest() != manifest['files'][ticker+'.json']:
            raise ValueError('供应商原始文件SHA256不匹配')
        payload = json.loads(encoded)
        if payload.get('symbol') != 'US.'+ticker:
            raise ValueError('文件名与证券不一致')
        checked = verify_payload(payload)
        if checked['bars'] != 90 or (checked['first'],checked['last']) != ('2026-07-02','2026-11-06'):
            raise ValueError('必须是已批准区间的90根连续日K')
        payloads.append(payload)
    archive = FutuDailyArchive(database) if database.exists() else FutuDailyArchive.create(database)
    results = [archive.import_payload(p) for p in payloads]
    print(json.dumps(dict(database=str(database.resolve()), added=sum(r['added'] for r in results),
                          symbols=results), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--database', type=Path, required=True)
    args = parser.parse_args()
    main(args.capture, args.database)
