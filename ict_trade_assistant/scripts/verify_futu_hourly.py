"""Build a new verified archive from immutable captured raw files."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desk.futu_hourly import verify_hourly


def verify(capture, output):
    output.mkdir(parents=True, exist_ok=False)
    original = (capture/'manifest.json').read_bytes()
    manifest = json.loads(original)
    manifest['raw_capture_manifest_sha256'] = hashlib.sha256(original).hexdigest()
    manifest['verification_contract'] = 'V046_END_LABEL_OHLC_DAY_RECONCILIATION_V1'
    for symbol, entry in manifest['symbols'].items():
        name = symbol.removeprefix('US.')+'.json'
        blob = (capture/name).read_bytes()
        if hashlib.sha256(blob).hexdigest() != entry['sha256']:
            raise ValueError('原始捕获SHA256不匹配')
        (output/name).write_bytes(blob)
        try:
            meta, frame = verify_hourly(json.loads(blob))
            manifest['symbols'][symbol] = dict(status='PASS', sha256=entry['sha256'], verification=meta)
        except (ValueError, KeyError, TypeError) as exc:
            manifest['symbols'][symbol] = dict(status='UNAVAILABLE', sha256=entry['sha256'], reason=str(exc))
        print(symbol, manifest['symbols'][symbol]['status'], flush=True)
    (output/'raw-capture-manifest.json').write_bytes(original)
    for name, sha in manifest.get('boundary_probes', {}).items():
        if hashlib.sha256((capture/name).read_bytes()).hexdigest() != sha:
            raise ValueError('边界探针SHA256不匹配')
        shutil.copyfile(capture/name, output/name)
    (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    verify(args.capture, args.output)
