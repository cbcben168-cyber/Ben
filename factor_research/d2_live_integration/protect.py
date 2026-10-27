"""Hash protected evidence only; never execute old or B code."""
from pathlib import Path
import json
from core import encoded, file_sha, write_once
from live_entry import HERE, ROOT


def paths():
    prior = json.loads((ROOT/'factor_research/spy_ticker_orderbook_d2_03/PROTECTED_BEFORE.json').read_bytes())
    selected = {Path(p) for p in prior if '/.git' not in p.replace('\\', '/')}
    for name in ('spy_ticker_orderbook_d2', 'spy_ticker_orderbook_d2_03',
                 'spy_ticker_orderbook_d2_20261027_03', 'FUTU_7DAY_FINALIZATION_20261025_01',
                 'a4_weekend_20261024'):
        selected.update(p for p in (ROOT/'factor_research'/name).rglob('*') if p.is_file())
    return sorted(selected)


if __name__ == '__main__':
    before = HERE/'PROTECTED_BEFORE.json'
    if not before.exists():
        values = {str(p): file_sha(p) for p in paths()}
        write_once(before, encoded(values))
        print(json.dumps({'protected_files': len(values)}))
    else:
        values = json.loads(before.read_bytes())
        changed = [p for p,h in values.items() if not Path(p).is_file() or file_sha(p) != h]
        write_once(HERE/'PROTECTED_AFTER.json', encoded({'checked': len(values), 'changed': changed,
            'all_unchanged': not changed, 'git_metadata_excluded': 'authorized A branch/fetch only'}))
        print(json.dumps({'checked': len(values), 'changed': len(changed)}))
        raise SystemExit(bool(changed))
