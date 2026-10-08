from pathlib import Path

import pytest

from quant_workflow.factor_research.progress_dashboard.db import canonical_strategy_hash


HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "fixtures" / "RunLog_TEST_FIXTURE_F001.csv"
STRATEGY = HERE.parents[3] / "factor_research" / "spy_factor_v1" / "SPY_FACTOR_RESEARCH_V1.py"


@pytest.fixture
def runlog_fixture(tmp_path):
    content = TEMPLATE.read_text(encoding="utf-8")
    content = content.replace(
        "a4189f867d94a34a8852aead81c6f122ecb3258704407b45d6201d643863cba2",
        canonical_strategy_hash(STRATEGY),
    )
    path = tmp_path / "RunLog_TEST_FIXTURE_F001.csv"
    path.write_text(content, encoding="utf-8")
    return path
