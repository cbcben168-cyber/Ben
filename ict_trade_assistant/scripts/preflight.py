"""Local read-only market preflight. Emits sanitized quote health only."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desk.provider import Provider

p = Provider()
try:
    data = p.fetch('US.SPY')
    report = dict(health=data['health'], errors=data['errors'], minute_rows=len(data['minute']),
                  daily_rows=len(data['daily']),
                  minute_pagination_complete=data.get('minute_pagination_complete'),
                  daily_pagination_complete=data.get('daily_pagination_complete'))
    path = Path(__file__).resolve().parents[1]/'data'/'preflight.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, default=str))
finally:
    p.close()
