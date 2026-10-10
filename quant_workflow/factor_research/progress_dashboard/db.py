from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from .stats import compute_statistics, compute_train_analysis, histogram


FACTOR_ID = "SPY_F001_CLOSE_GT_EMA20"
HORIZONS = (15, 30, 60)
BATCH_FACTOR_CATALOG = (
    (
        "SPY_F001_CLOSE_GT_EMA20",
        "C[0] > EMA20[0]",
        "F001-C1-BATCH-V1",
    ),
    (
        "SPY_F002_EMA20_RISING_3",
        "EMA20[0] > EMA20[3]",
        "F002-C1-BATCH-V1",
    ),
    (
        "SPY_F003_CLOSE_CROSS_ABOVE_EMA20",
        "C[-1] <= EMA20[-1] and C[0] > EMA20[0]",
        "F003-C1-BATCH-V1",
    ),
    (
        "SPY_F004_CLOSE_BREAKS_PRIOR_5_HIGH",
        "C[0] > max(H[-1],...,H[-5])",
        "F004-C1-BATCH-V1",
    ),
    (
        "SPY_F005_THREE_CLOSE_MOMENTUM",
        "C[-2] < C[-1] < C[0]",
        "F005-C1-BATCH-V1",
    ),
    (
        "SPY_F006_STRONG_BULL_BODY",
        "C[0] > O[0] and (C[0]-O[0])/(H[0]-L[0]) > 0.60",
        "F006-C1-BATCH-V1",
    ),
)
TRAIN_FACTOR_PARAMETER_VERSIONS = {
    factor_id: parameter_version.replace("-V1", "-TRAIN-V1")
    for factor_id, _, parameter_version in BATCH_FACTOR_CATALOG
}
PARTITION_PRIORITY = {"FUNCTIONAL_VALIDATION": 1, "TRAIN": 2, "VALIDATION": 3, "OOS": 4}
SUPPORTED_EDGE_STATUSES = {
    "VALIDATION_SUPPORTED",
    "OOS_SUPPORTED",
    "INDEPENDENT_VALIDATION_SUPPORTED",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_strategy_hash(path: Path) -> str:
    source = path.read_text(encoding="utf-8")
    normalized, count = re.subn(
        r'(self\.strategy_hash = ")[0-9a-f]{64}(".*)',
        r"\g<1>" + ("0" * 64) + r"\g<2>",
        source,
        count=1,
    )
    if count != 1:
        raise ValueError("strategy hash declaration is missing or malformed")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def normalized_source_hash(path: Path) -> str:
    source = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


class Database:
    def __init__(self, path: Path, strategy_path: Path | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        repo_root = Path(__file__).resolve().parents[3]
        self.strategy_path = strategy_path or (
            repo_root / "factor_research" / "spy_factor_v1" / "SPY_FACTOR_RESEARCH_V1.py"
        )
        self.legacy_strategy_path = (
            repo_root / "factor_research" / "spy_factor_v1" / "SPY_FACTOR_RESEARCH_V1_LEGACY.py"
        )
        self.train_strategy_path = (
            repo_root / "factor_research" / "spy_factor_v1" / "SPY_FACTOR_RESEARCH_TRAIN_V1.py"
        )
        self.batch_strategy_path = (
            repo_root
            / "factor_research"
            / "spy_factor_batch_v1"
            / "SPY_SIX_FACTOR_BATCH_V1.py"
        )
        self.batch_train_strategy_path = (
            repo_root
            / "factor_research"
            / "spy_factor_batch_v1"
            / "SPY_SIX_FACTOR_BATCH_TRAIN_V1.py"
        )

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def initialize(self) -> None:
        schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
        with self.connect() as connection:
            connection.executescript(schema)
            self._migrate(connection)
            self._seed(connection)

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        run_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(research_runs)").fetchall()
        }
        if "research_verdict" not in run_columns:
            connection.execute(
                "ALTER TABLE research_runs ADD COLUMN research_verdict TEXT NOT NULL DEFAULT 'NOT_ASSESSED'"
            )
        if "version_binding_status" not in run_columns:
            connection.execute(
                "ALTER TABLE research_runs ADD COLUMN version_binding_status TEXT NOT NULL DEFAULT 'EMBEDDED_HASH'"
            )
        source_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(source_files)").fetchall()
        }
        if "system_log_start_local" not in source_columns:
            connection.execute(
                "ALTER TABLE source_files ADD COLUMN system_log_start_local TEXT"
            )
        if "system_log_end_local" not in source_columns:
            connection.execute(
                "ALTER TABLE source_files ADD COLUMN system_log_end_local TEXT"
            )

    def _seed(self, connection: sqlite3.Connection) -> None:
        now = utc_now()
        strategy_hash = canonical_strategy_hash(self.strategy_path)
        legacy_hash = normalized_source_hash(self.legacy_strategy_path)
        train_hash = canonical_strategy_hash(self.train_strategy_path)
        batch_hash = canonical_strategy_hash(self.batch_strategy_path)
        batch_train_hash = canonical_strategy_hash(self.batch_train_strategy_path)
        factor_values = (
            FACTOR_ID,
            "close(select=2) > ema20(select=2)",
            "US.SPY",
            "5m",
            json.dumps([15, 30, 60]),
            "SPECIFIED",
            "INDETERMINATE",
            "NOT_TESTED",
            1,
            "六因子批量代码已就绪；尚未完成真实富途 S0 批量功能回测",
            "在富途运行 SPY_SIX_FACTOR_BATCH_V1.py 并导出完整 RunLog CSV",
            now,
            now,
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO factors (
                factor_id, formula, symbol, bar_size, horizons_json,
                development_stage, data_gate, edge_status, code_present,
                blocking_reason, next_action, created_at_utc, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            factor_values,
        )
        for factor_id, formula, _ in BATCH_FACTOR_CATALOG:
            connection.execute(
                """
                INSERT OR IGNORE INTO factors (
                    factor_id, formula, symbol, bar_size, horizons_json,
                    development_stage, data_gate, edge_status, code_present,
                    blocking_reason, next_action, created_at_utc, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    factor_id,
                    formula,
                    "US.SPY",
                    "5m",
                    json.dumps([15, 30, 60]),
                    "SPECIFIED",
                    "INDETERMINATE",
                    "NOT_TESTED",
                    1,
                    "六因子批量代码已就绪；尚未完成真实富途 S0 批量功能回测",
                    "在富途运行 SPY_SIX_FACTOR_BATCH_V1.py 并导出完整 RunLog CSV",
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE factors
                SET code_present=1,
                    blocking_reason=?,
                    next_action=?,
                    updated_at_utc=?
                WHERE factor_id=?
                  AND NOT EXISTS (
                      SELECT 1
                      FROM research_runs r
                      JOIN factor_versions v ON v.version_id=r.version_id
                      WHERE v.factor_id=factors.factor_id
                        AND v.strategy_version IN (
                            'FUTU_BATCH_FACTORS_V1', 'FUTU_BATCH_FACTORS_TRAIN_V1'
                        )
                        AND r.run_status='VALIDATED'
                  )
                """,
                (
                    "六因子批量代码已就绪；尚未完成真实富途 S0 批量功能回测",
                    "在富途运行 SPY_SIX_FACTOR_BATCH_V1.py 并导出完整 RunLog CSV",
                    now,
                    factor_id,
                ),
            )
        connection.execute("UPDATE factor_versions SET active=0 WHERE factor_id=?", (FACTOR_ID,))
        versions = [
            (
                "SPY_FACTOR_RESEARCH_V1_LEGACY",
                legacy_hash,
                "F001-FUNCTIONAL-20260928-20261006",
                0,
            ),
            ("SPY_FACTOR_RESEARCH_V1.1", strategy_hash, "F001-P1", 0),
            (
                "SPY_FACTOR_RESEARCH_TRAIN_V1",
                train_hash,
                "F001-TRAIN-20251001-20260630",
                1,
            ),
        ]
        for version in versions:
            connection.execute(
                """
                INSERT INTO factor_versions (
                    factor_id, strategy_version, strategy_hash, parameter_version,
                    active, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(factor_id, strategy_version, strategy_hash, parameter_version)
                DO UPDATE SET active=excluded.active
                """,
                (FACTOR_ID, *version, now),
            )
        for factor_id, _, _ in BATCH_FACTOR_CATALOG:
            connection.execute(
                "UPDATE factor_versions SET active=0 WHERE factor_id=?", (factor_id,)
            )
        for factor_id, _, parameter_version in BATCH_FACTOR_CATALOG:
            connection.execute(
                """
                INSERT INTO factor_versions (
                    factor_id, strategy_version, strategy_hash, parameter_version,
                    active, created_at_utc
                ) VALUES (?, ?, ?, ?, 0, ?)
                ON CONFLICT(factor_id, strategy_version, strategy_hash, parameter_version)
                DO UPDATE SET active=excluded.active
                """,
                (
                    factor_id,
                    "FUTU_BATCH_FACTORS_V1",
                    batch_hash,
                    parameter_version,
                    now,
                ),
            )
        for factor_id, _, _ in BATCH_FACTOR_CATALOG:
            connection.execute(
                """
                INSERT INTO factor_versions (
                    factor_id, strategy_version, strategy_hash, parameter_version,
                    active, created_at_utc
                ) VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(factor_id, strategy_version, strategy_hash, parameter_version)
                DO UPDATE SET active=excluded.active
                """,
                (
                    factor_id,
                    "FUTU_BATCH_FACTORS_TRAIN_V1",
                    batch_train_hash,
                    TRAIN_FACTOR_PARAMETER_VERSIONS[factor_id],
                    now,
                ),
            )
        gates = [
            (
                "GATE5B_TIMING_SPY_5M_SELECT2",
                FACTOR_ID,
                "US.SPY",
                "5m",
                "TIME_LEAK",
                "PASS",
                "Gate5B-2026-10-08",
                "仅限 09:30/09:31/09:35、SPY、RTH、select=2 样本；不外推为普遍无未来泄漏",
            ),
            (
                "OHLC_SPY_1M_5M_V131",
                FACTOR_ID,
                "US.SPY",
                "1m/5m",
                "OHLC",
                "PASS",
                "V1.3.1-7-samples",
                "七个样本及 2026-10-06 完整日价格聚合一致；不代表全历史区间",
            ),
            (
                "EMA20_INTRADAY_RECURSION",
                FACTOR_ID,
                "US.SPY",
                "5m",
                "EMA",
                "PASS",
                "Gate5-12-of-12",
                "以上一平台 EMA 为种子，当日递推 12/12 一致",
            ),
            (
                "EMA20_ABSOLUTE_HISTORY",
                FACTOR_ID,
                "US.SPY",
                "5m",
                "EMA",
                "INDETERMINATE",
                "Gate5-absolute-history",
                "更早历史、预热与平台绝对 EMA 状态尚未验证",
            ),
            (
                "GATE5C_VOLUME_NATIVE_VS_1M",
                None,
                "US.SPY",
                "1m/5m",
                "VOLUME",
                "FAIL",
                "Gate5C-78-of-78",
                "原生 5m Volume 与 5×1m 聚合 78/78 不精确相等；成交量因子受限",
            ),
            (
                "QQQ_PLATFORM_FACTOR_RUN",
                None,
                "US.QQQ",
                "5m",
                "SYMBOL_TIMEFRAME",
                "NOT_TESTED",
                "initial-state-v1",
                "QQQ 尚未进行平台因子回测",
            ),
        ]
        for gate in gates:
            connection.execute(
                """
                INSERT OR IGNORE INTO data_gate_evidence (
                    gate_id, factor_id, symbol, bar_size, dimension, status,
                    evidence_version, scope_note, source_path, source_sha256,
                    observed_at_utc, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                gate
                + (
                    "quant_workflow/validation/gate5_opend_20261006/REPORT.md",
                    None,
                    "2026-10-08T15:26:35.856005Z",
                    now,
                ),
            )
        validated_runs = connection.execute(
            """
            SELECT COUNT(*)
            FROM research_runs r
            JOIN factor_versions v ON v.version_id=r.version_id
            WHERE v.factor_id=? AND v.strategy_version='FUTU_BATCH_FACTORS_V1'
              AND r.run_status='VALIDATED'
            """,
            (FACTOR_ID,),
        ).fetchone()[0]
        if not validated_runs:
            self._upsert_issue(
                connection,
                issue_key="TODO:C1_BATCH:WAITING_EXPORT",
                kind="TODO",
                severity="INFO",
                issue_code="WAITING_EXPORT",
                message="F001–F006 批量代码已定义，但尚无正式六因子批量回测 CSV。",
                next_action="运行 SPY_SIX_FACTOR_BATCH_V1.py 后导出 RunLog_*.csv 到看板 inbox。",
                factor_id=FACTOR_ID,
            )
        else:
            connection.execute(
                """
                UPDATE issues SET status='RESOLVED', resolved_at_utc=?, last_seen_utc=?
                WHERE issue_key='TODO:C1_BATCH:WAITING_EXPORT'
                """,
                (now, now),
            )
        connection.execute(
            """
            UPDATE issues SET status='RESOLVED', resolved_at_utc=?, last_seen_utc=?
            WHERE issue_key='TODO:F001:WAITING_EXPORT' AND status='OPEN'
            """,
            (now, now),
        )
        self._upsert_issue(
            connection,
            issue_key="TODO:QQQ:NOT_TESTED",
            kind="TODO",
            severity="INFO",
            issue_code="QQQ_NOT_TESTED",
            message="QQQ 尚未进行平台因子回测。",
            next_action="F001/SPY 闭环稳定后再使用同一数据结构测试 QQQ。",
        )

    def set_state(self, key: str, value: str | None) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO app_state (state_key, state_value, updated_at_utc)
                VALUES (?, ?, ?)
                ON CONFLICT(state_key) DO UPDATE SET
                    state_value=excluded.state_value,
                    updated_at_utc=excluded.updated_at_utc
                """,
                (key, value, now),
            )

    def record_source(
        self,
        *,
        path: Path,
        file_sha256: str,
        size_bytes: int,
        mtime_ns: int,
        classification: str = "PENDING",
        import_status: str = "WAITING_STABLE",
    ) -> None:
        now = utc_now()
        normalized = str(path.resolve())
        with self.connect() as connection:
            previous = connection.execute(
                """
                SELECT file_sha256 FROM file_observations
                WHERE normalized_path = ?
                ORDER BY last_seen_utc DESC LIMIT 1
                """,
                (normalized,),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO source_files (
                    file_sha256, canonical_path, size_bytes, mtime_ns,
                    first_seen_utc, last_seen_utc, classification, import_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_sha256) DO UPDATE SET last_seen_utc=excluded.last_seen_utc
                """,
                (
                    file_sha256,
                    normalized,
                    size_bytes,
                    mtime_ns,
                    now,
                    now,
                    classification,
                    import_status,
                ),
            )
            connection.execute(
                """
                INSERT INTO file_observations (
                    normalized_path, file_sha256, size_bytes, mtime_ns,
                    first_seen_utc, last_seen_utc
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(normalized_path, file_sha256, mtime_ns)
                DO UPDATE SET last_seen_utc=excluded.last_seen_utc
                """,
                (normalized, file_sha256, size_bytes, mtime_ns, now, now),
            )
            if previous and previous["file_sha256"] != file_sha256:
                self._upsert_issue(
                    connection,
                    issue_key=f"FILE_CHANGED:{hashlib.sha256(normalized.encode()).hexdigest()[:20]}:{file_sha256}",
                    kind="ANOMALY",
                    severity="WARNING",
                    issue_code="SOURCE_PATH_CONTENT_CHANGED",
                    message=f"同一路径出现新内容版本：{path.name}",
                    next_action="核对这是重新导出的跑次还是写入中途版本；旧审计记录已保留。",
                    file_sha256=file_sha256,
                )

    def update_source(self, file_sha256: str, **fields: Any) -> None:
        allowed = {
            "encoding",
            "marker_version",
            "classification",
            "import_status",
            "rows_total",
            "rows_marked",
            "parse_success_rate",
            "error_text",
            "canonical_path",
            "system_log_start_local",
            "system_log_end_local",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unsupported source fields: {sorted(unknown)}")
        fields["last_seen_utc"] = utc_now()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [file_sha256]
        with self.connect() as connection:
            connection.execute(
                f"UPDATE source_files SET {assignments} WHERE file_sha256 = ?", values
            )

    def add_issue(self, **values: Any) -> None:
        with self.connect() as connection:
            self._upsert_issue(connection, **values)

    def _upsert_issue(
        self,
        connection: sqlite3.Connection,
        *,
        issue_key: str,
        kind: str,
        severity: str,
        issue_code: str,
        message: str,
        next_action: str | None = None,
        factor_id: str | None = None,
        run_instance_id: str | None = None,
        file_sha256: str | None = None,
    ) -> None:
        now = utc_now()
        connection.execute(
            """
            INSERT INTO issues (
                issue_key, kind, severity, status, issue_code, factor_id,
                run_instance_id, file_sha256, message, next_action,
                first_seen_utc, last_seen_utc
            ) VALUES (?, ?, ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(issue_key) DO UPDATE SET
                severity=excluded.severity,
                status='OPEN',
                message=excluded.message,
                next_action=excluded.next_action,
                last_seen_utc=excluded.last_seen_utc,
                resolved_at_utc=NULL
            """,
            (
                issue_key,
                kind,
                severity,
                issue_code,
                factor_id,
                run_instance_id,
                file_sha256,
                message,
                next_action,
                now,
                now,
            ),
        )

    def import_runs(
        self, file_sha256: str, runs: list[dict[str, Any]]
    ) -> tuple[str, list[str]]:
        expected_factor_ids = {item[0] for item in BATCH_FACTOR_CATALOG}
        if len(runs) != len(expected_factor_ids) or {
            run.get("factor_id") for run in runs
        } != expected_factor_ids:
            self.add_issue(
                issue_key=f"BATCH:{file_sha256}:FACTOR_SET_MISMATCH",
                kind="ANOMALY",
                severity="ERROR",
                issue_code="BATCH_FACTOR_SET_MISMATCH",
                message="六因子批次没有完整包含冻结的 F001–F006 集合，整批拒绝。",
                next_action="使用未修改的 SPY_SIX_FACTOR_BATCH_V1.py 重新运行并导出完整 CSV。",
                file_sha256=file_sha256,
            )
            return "INVALID", []
        run_instance_ids = [
            hashlib.sha256(f"{file_sha256}|{run['run_id']}".encode("utf-8")).hexdigest()
            for run in runs
        ]
        with self.connect() as connection:
            existing = {
                row["run_instance_id"]
                for row in connection.execute(
                    "SELECT run_instance_id FROM research_runs WHERE file_sha256=?",
                    (file_sha256,),
                ).fetchall()
            }
            expected = set(run_instance_ids)
            if existing == expected:
                return "DUPLICATE", run_instance_ids
            if existing:
                self._upsert_issue(
                    connection,
                    issue_key=f"BATCH:{file_sha256}:PARTIAL_STATE",
                    kind="ANOMALY",
                    severity="ERROR",
                    issue_code="PARTIAL_BATCH_STATE",
                    message="数据库中已存在该 CSV 的部分逻辑跑次；为防止不完整排行，整批停止。",
                    next_action="保留数据库和原始 CSV，交由 Codex 审核事务状态，不要手工补行。",
                    file_sha256=file_sha256,
                )
                connection.execute(
                    "UPDATE source_files SET import_status='INVALID', error_text=? WHERE file_sha256=?",
                    ("PARTIAL_BATCH_STATE", file_sha256),
                )
                return "INVALID", []
            for run in runs:
                version = connection.execute(
                    """
                    SELECT version_id FROM factor_versions
                    WHERE factor_id=? AND strategy_version=? AND strategy_hash=?
                      AND parameter_version=?
                    """,
                    (
                        run["factor_id"],
                        run["strategy_version"],
                        run["strategy_hash"],
                        run["parameter_version"],
                    ),
                ).fetchone()
                if version is None:
                    self._upsert_issue(
                        connection,
                        issue_key=f"BATCH:{file_sha256}:VERSION_MISMATCH",
                        kind="ANOMALY",
                        severity="ERROR",
                        issue_code="VERSION_MISMATCH",
                        message="批次中至少一个因子的版本、策略哈希或参数版本未登记，整批拒绝。",
                        next_action="核对冻结的 C1 六因子文件与看板版本，不要部分导入。",
                        factor_id=run["factor_id"],
                        file_sha256=file_sha256,
                    )
                    connection.execute(
                        "UPDATE source_files SET import_status='INVALID', error_text=? WHERE file_sha256=?",
                        ("VERSION_MISMATCH", file_sha256),
                    )
                    return "INVALID", []
            statuses: list[str] = []
            imported_ids: list[str] = []
            for run in runs:
                status, run_instance_id = self.import_run(
                    file_sha256, run, connection=connection
                )
                statuses.append(status)
                imported_ids.append(run_instance_id)
            status = (
                "INVALID"
                if "INVALID" in statuses
                else "INCOMPLETE"
                if "INCOMPLETE" in statuses
                else "VALIDATED"
            )
            return status, imported_ids

    def import_run(
        self,
        file_sha256: str,
        run: dict[str, Any],
        *,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[str, str]:
        now = utc_now()
        run_instance_id = hashlib.sha256(
            f"{file_sha256}|{run['run_id']}".encode("utf-8")
        ).hexdigest()
        coverage_key = hashlib.sha256(
            "|".join(
                [
                    run["factor_id"],
                    run["parameter_version"],
                    run.get("study_start_et") or "UNKNOWN",
                    run.get("study_end_et") or "UNKNOWN",
                    run["symbol"],
                    run["timeframe"],
                ]
            ).encode("utf-8")
        ).hexdigest()
        signals = run["signals"]
        labels = run["labels"]
        completeness = min(1.0, len(labels) / (len(signals) * 3)) if signals else 0.0
        connection_context = self.connect() if connection is None else nullcontext(connection)
        with connection_context as connection:
            version = connection.execute(
                """
                SELECT version_id FROM factor_versions
                WHERE factor_id = ? AND strategy_version = ? AND strategy_hash = ?
                  AND parameter_version = ?
                """,
                (
                    run["factor_id"],
                    run["strategy_version"],
                    run["strategy_hash"],
                    run["parameter_version"],
                ),
            ).fetchone()
            if not version:
                self._upsert_issue(
                    connection,
                    issue_key=f"VERSION_MISMATCH:{file_sha256}:{run['run_id']}",
                    kind="ANOMALY",
                    severity="ERROR",
                    issue_code="VERSION_MISMATCH",
                    message="日志策略版本/hash/参数版本未登记，未导入研究结果。",
                    next_action="核对因子文件版本，不要根据文件名推断或绕过版本门槛。",
                    factor_id=run.get("factor_id"),
                    file_sha256=file_sha256,
                )
                connection.execute(
                    "UPDATE source_files SET import_status='INVALID', error_text=? WHERE file_sha256=?",
                    ("VERSION_MISMATCH", file_sha256),
                )
                return "INVALID", run_instance_id

            existing = connection.execute(
                "SELECT run_instance_id FROM research_runs WHERE run_instance_id = ?",
                (run_instance_id,),
            ).fetchone()
            if existing:
                return "DUPLICATE", run_instance_id

            duplicate_coverage = connection.execute(
                "SELECT run_instance_id FROM research_runs WHERE coverage_key = ? LIMIT 1",
                (coverage_key,),
            ).fetchone()
            actual_times = [item["signal_time_et"] for item in signals]
            connection.execute(
                """
                INSERT INTO research_runs (
                    run_instance_id, declared_run_id, version_id, file_sha256,
                    run_status, research_verdict, version_binding_status,
                    study_partition, settings_start_et, settings_end_et,
                    actual_start_et, actual_end_et, timezone, session, symbol,
                    timeframe, select_value, signal_count, label_count,
                    completeness, coverage_key, imported_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_instance_id,
                    run["run_id"],
                    version["version_id"],
                    file_sha256,
                    run["run_status"],
                    run.get("research_verdict", "NOT_ASSESSED"),
                    run.get("version_binding_status", "EMBEDDED_HASH"),
                    run["study_partition"],
                    run.get("study_start_et"),
                    run.get("study_end_et"),
                    min(actual_times) if actual_times else None,
                    max(actual_times) if actual_times else None,
                    run["timezone"],
                    run["session"],
                    run["symbol"],
                    run["timeframe"],
                    int(run["select"]),
                    len(signals),
                    len(labels),
                    completeness,
                    coverage_key,
                    now,
                ),
            )
            for item in signals:
                connection.execute(
                    """
                    INSERT INTO signals (
                        run_instance_id, signal_id, signal_time_et, signal_time_utc,
                        signal_close, factor_value, factor_numeric
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_instance_id,
                        item["signal_id"],
                        item["signal_time_et"],
                        item["signal_time_utc"],
                        float(item["signal_close"]),
                        item["factor_value"],
                        item.get("factor_numeric"),
                    ),
                )
            for item in labels:
                connection.execute(
                    """
                    INSERT INTO labels (
                        run_instance_id, signal_id, horizon_bars, horizon_minutes,
                        target_time_et, target_time_utc, target_close, forward_return
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_instance_id,
                        item["signal_id"],
                        int(item["horizon_bars"]),
                        int(item["horizon_minutes"]),
                        item["target_time_et"],
                        item["target_time_utc"],
                        float(item["target_close"]),
                        float(item["forward_return"]),
                    ),
                )
            for row in compute_statistics(signals, labels):
                connection.execute(
                    """
                    INSERT INTO run_statistics (
                        run_instance_id, horizon_minutes, cohort, n, mean_return,
                        median_return, positive_rate, baseline_mean, edge_bps
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (run_instance_id, *row.values()),
                )
            if run["study_partition"] == "TRAIN" and run["run_status"] == "VALIDATED":
                for analysis in compute_train_analysis(
                    signals,
                    labels,
                    seed_key=run_instance_id,
                ):
                    connection.execute(
                        """
                        INSERT INTO run_analyses (
                            run_instance_id, horizon_minutes, analysis_version,
                            analysis_json, created_at_utc
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            run_instance_id,
                            int(analysis["horizon_minutes"]),
                            analysis["analysis_version"],
                            json.dumps(analysis, ensure_ascii=False, sort_keys=True),
                            now,
                        ),
                    )
            warmup_audit = run.get("warmup_audit")
            if warmup_audit:
                connection.execute(
                    """
                    INSERT INTO run_audits (
                        run_instance_id, audit_type, status, payload_json, created_at_utc
                    ) VALUES (?, 'EMA20_WARMUP', ?, ?, ?)
                    """,
                    (
                        run_instance_id,
                        str(warmup_audit.get("status", "UNKNOWN")),
                        json.dumps(warmup_audit, ensure_ascii=False, sort_keys=True),
                        now,
                    ),
                )
            for issue in run.get("issues", []):
                self._upsert_issue(
                    connection,
                    issue_key=f"RUN:{run_instance_id}:{issue['code']}",
                    kind="ANOMALY",
                    severity=issue.get("severity", "WARNING"),
                    issue_code=issue["code"],
                    message=issue["message"],
                    next_action=issue.get("next_action"),
                    factor_id=run["factor_id"],
                    run_instance_id=run_instance_id,
                    file_sha256=file_sha256,
                )
            if duplicate_coverage:
                self._upsert_issue(
                    connection,
                    issue_key=f"RUN:{run_instance_id}:REPEATED_COVERAGE",
                    kind="ANOMALY",
                    severity="WARNING",
                    issue_code="REPEATED_COVERAGE",
                    message="相同参数版本和覆盖区间已有其他跑次；本跑次单独存档，不累计为独立样本。",
                    next_action="逐次比较差异，不合并原始样本量。",
                    factor_id=run["factor_id"],
                    run_instance_id=run_instance_id,
                    file_sha256=file_sha256,
                )
            verdict = run.get("research_verdict", "NOT_ASSESSED")
            if verdict == "FUNCTIONAL_VALIDATION_PASS":
                stage = "PLATFORM_VALIDATED"
                edge_status = "INSUFFICIENT_EVIDENCE"
                blocking_reason = "仅完成六因子功能验证；未执行 TRAIN/VALIDATION/OOS，不构成 Edge"
                next_action = "核对 S0 六因子事件与 F001 历史口径后，再运行冻结的 S1 TRAIN 区间"
            elif verdict == "TRAIN_DATA_VALIDATED":
                stage = "HISTORICAL_RUN"
                edge_status = "INSUFFICIENT_EVIDENCE"
                blocking_reason = "TRAIN 已导入但 VALIDATION/OOS 尚未执行；重叠事件不能视为独立样本"
                next_action = "完成预注册 TRAIN 统计审核后，另行批准是否进入 VALIDATION"
            elif verdict == "VALIDATION_DATA_VALIDATED":
                stage = "VALIDATION"
                edge_status = "INSUFFICIENT_EVIDENCE"
                blocking_reason = "Validation 数据已导入，但交易化规则和最终 OOS 尚未完成"
                next_action = "冻结候选、成交与成本规则后，另行批准最终 OOS"
            elif verdict == "OOS_DATA_VALIDATED":
                stage = "OOS"
                edge_status = "INSUFFICIENT_EVIDENCE"
                blocking_reason = "OOS 数据已导入；仍需按预注册准则独立审核，不能自动宣称 Edge"
                next_action = "审核 OOS、成本和稳健性证据后人工决定是否进入 Forward"
            else:
                stage = "SPECIFIED"
                edge_status = "NOT_TESTED"
                blocking_reason = "日志尚未通过完整性验证"
                next_action = "处理导入异常并重新导出完整日志"
            connection.execute(
                """
                UPDATE factors SET development_stage=?, edge_status=?, blocking_reason=?,
                    next_action=?, updated_at_utc=?
                WHERE factor_id=?
                """,
                (
                    stage,
                    edge_status,
                    blocking_reason,
                    next_action,
                    now,
                    run["factor_id"],
                ),
            )
            if (
                run["run_status"] == "VALIDATED"
                and run.get("version_binding_status") == "BATCH_DEFINITION_HASH"
            ):
                connection.execute(
                    """
                    UPDATE issues SET status='RESOLVED', resolved_at_utc=?, last_seen_utc=?
                    WHERE issue_key='TODO:C1_BATCH:WAITING_EXPORT'
                    """,
                    (now, now),
                )
            connection.execute(
                """
                    UPDATE source_files SET classification=?, import_status=?,
                    error_text=NULL, last_seen_utc=? WHERE file_sha256=?
                    """,
                (
                    "FACTOR_BATCH"
                    if run.get("version_binding_status") == "BATCH_DEFINITION_HASH"
                    else "FACTOR_RUN",
                    run["run_status"],
                    now,
                    file_sha256,
                ),
            )
            connection.execute(
                """
                INSERT INTO app_state (state_key, state_value, updated_at_utc)
                VALUES ('last_import_file', ?, ?)
                ON CONFLICT(state_key) DO UPDATE SET
                    state_value=excluded.state_value, updated_at_utc=excluded.updated_at_utc
                """,
                (file_sha256, now),
            )
        return run["run_status"], run_instance_id

    @staticmethod
    def _rows(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
        return [dict(row) for row in rows]

    def _run_window_metrics(
        self,
        connection: sqlite3.Connection,
        run_instance_id: str,
        horizon_minutes: int,
        *,
        include_analysis: bool = False,
    ) -> dict[str, Any]:
        statistics = self._rows(
            connection.execute(
                """
                SELECT * FROM run_statistics
                WHERE run_instance_id=? AND horizon_minutes=?
                ORDER BY cohort
                """,
                (run_instance_id, horizon_minutes),
            ).fetchall()
        )
        by_cohort = {row["cohort"]: row for row in statistics}
        baseline = by_cohort.get("ALL", {})
        passed = by_cohort.get("PASS", {})
        failed = by_cohort.get("FAIL", {})
        coverage = connection.execute(
            """
            SELECT COUNT(DISTINCT substr(s.signal_time_et, 1, 10)) AS trading_days,
                   MIN(substr(s.signal_time_et, 1, 10)) AS first_day,
                   MAX(substr(s.signal_time_et, 1, 10)) AS last_day
            FROM labels l
            JOIN signals s ON s.run_instance_id=l.run_instance_id
                AND s.signal_id=l.signal_id
            WHERE l.run_instance_id=? AND l.horizon_minutes=?
            """,
            (run_instance_id, horizon_minutes),
        ).fetchone()
        stability = connection.execute(
            """
            WITH daily AS (
                SELECT substr(s.signal_time_et, 1, 10) AS trading_day,
                       s.factor_value AS cohort,
                       AVG(l.forward_return) AS mean_return
                FROM labels l
                JOIN signals s ON s.run_instance_id=l.run_instance_id
                    AND s.signal_id=l.signal_id
                WHERE l.run_instance_id=? AND l.horizon_minutes=?
                GROUP BY trading_day, cohort
            ), paired AS (
                SELECT p.trading_day, p.mean_return AS pass_mean, f.mean_return AS fail_mean
                FROM daily p
                JOIN daily f ON f.trading_day=p.trading_day
                WHERE p.cohort='PASS' AND f.cohort='FAIL'
            )
            SELECT COUNT(*) AS eligible_days,
                   COALESCE(SUM(CASE WHEN pass_mean > fail_mean THEN 1 ELSE 0 END), 0)
                       AS better_days
            FROM paired
            """,
            (run_instance_id, horizon_minutes),
        ).fetchone()
        monthly_rows = self._rows(
            connection.execute(
                """
                SELECT substr(s.signal_time_et, 1, 7) AS month,
                       s.factor_value AS cohort,
                       COUNT(*) AS n,
                       AVG(l.forward_return) AS mean_return
                FROM labels l
                JOIN signals s ON s.run_instance_id=l.run_instance_id
                    AND s.signal_id=l.signal_id
                WHERE l.run_instance_id=? AND l.horizon_minutes=?
                GROUP BY month, cohort
                ORDER BY month, cohort
                """,
                (run_instance_id, horizon_minutes),
            ).fetchall()
        )
        months: dict[str, dict[str, Any]] = {}
        for item in monthly_rows:
            month = months.setdefault(
                item["month"],
                {
                    "month": item["month"],
                    "pass_n": 0,
                    "fail_n": 0,
                    "pass_mean_return": None,
                    "fail_mean_return": None,
                    "pass_fail_diff_bps": None,
                },
            )
            key = item["cohort"].lower()
            month[f"{key}_n"] = item["n"]
            month[f"{key}_mean_return"] = item["mean_return"]
        for month in months.values():
            if month["pass_mean_return"] is not None and month["fail_mean_return"] is not None:
                month["pass_fail_diff_bps"] = (
                    month["pass_mean_return"] - month["fail_mean_return"]
                ) * 10000
        analysis_row = None
        audit_row = None
        if include_analysis:
            analysis_row = connection.execute(
                """
                SELECT analysis_json FROM run_analyses
                WHERE run_instance_id=? AND horizon_minutes=?
                ORDER BY created_at_utc DESC LIMIT 1
                """,
                (run_instance_id, horizon_minutes),
            ).fetchone()
            audit_row = connection.execute(
                """
                SELECT status, payload_json FROM run_audits
                WHERE run_instance_id=? AND audit_type='EMA20_WARMUP'
                """,
                (run_instance_id,),
            ).fetchone()
        pass_mean = passed.get("mean_return")
        fail_mean = failed.get("mean_return")
        eligible_days = int(stability["eligible_days"] or 0)
        better_days = int(stability["better_days"] or 0)
        return {
            "horizon_minutes": horizon_minutes,
            "pass_mean_return": pass_mean,
            "fail_mean_return": fail_mean,
            "pass_fail_diff_bps": (
                (pass_mean - fail_mean) * 10000
                if pass_mean is not None and fail_mean is not None
                else None
            ),
            "baseline_mean_return": baseline.get("mean_return"),
            "pass_edge_vs_baseline_bps": passed.get("edge_bps"),
            "pass_n": int(passed.get("n") or 0),
            "fail_n": int(failed.get("n") or 0),
            "positive_rate": passed.get("positive_rate"),
            "coverage_trading_days": int(coverage["trading_days"] or 0),
            "coverage_first_day": coverage["first_day"],
            "coverage_last_day": coverage["last_day"],
            "stable_better_days": better_days,
            "stable_eligible_days": eligible_days,
            "daily_stability": better_days / eligible_days if eligible_days else None,
            "monthly": list(months.values()),
            "train_analysis": json.loads(analysis_row["analysis_json"]) if analysis_row else None,
            "warmup_audit": (
                {
                    "status": audit_row["status"],
                    "payload": json.loads(audit_row["payload_json"]),
                }
                if audit_row
                else None
            ),
        }

    def _comparison_snapshot(
        self,
        connection: sqlite3.Connection,
        factors: list[dict[str, Any]],
        horizon_minutes: int,
        planned_factor_count: int,
    ) -> dict[str, Any]:
        candidate_runs = self._rows(
            connection.execute(
                """
                SELECT r.*, v.factor_id, s.marker_version
                FROM research_runs r
                JOIN factor_versions v ON v.version_id=r.version_id
                JOIN source_files s ON s.file_sha256=r.file_sha256
                WHERE r.run_status='VALIDATED'
                ORDER BY r.imported_at_utc DESC
                """
            ).fetchall()
        )
        selected_runs: dict[str, dict[str, Any]] = {}
        completed_partitions: dict[str, set[str]] = {}
        for run in candidate_runs:
            completed_partitions.setdefault(run["factor_id"], set()).add(run["study_partition"])
            current = selected_runs.get(run["factor_id"])
            if current is None or PARTITION_PRIORITY.get(run["study_partition"], 0) > PARTITION_PRIORITY.get(
                current["study_partition"], 0
            ):
                selected_runs[run["factor_id"]] = run

        rows: list[dict[str, Any]] = []
        for factor in factors:
            run = selected_runs.get(factor["factor_id"])
            row: dict[str, Any] = {
                "rank": None,
                "factor_id": factor["factor_id"],
                "formula": factor["formula"],
                "data_gate": factor["data_gate"],
                "run_instance_id": run["run_instance_id"] if run else None,
                "declared_run_id": run["declared_run_id"] if run else None,
                "study_partition": run["study_partition"] if run else None,
                "completed_partitions": sorted(completed_partitions.get(factor["factor_id"], set())),
                "comparison_scope": None,
            }
            if run:
                row.update(self._run_window_metrics(connection, run["run_instance_id"], horizon_minutes))
                row["comparison_scope"] = {
                    "symbol": run["symbol"],
                    "timeframe": run["timeframe"],
                    "study_partition": run["study_partition"],
                    "settings_start_et": run["settings_start_et"],
                    "settings_end_et": run["settings_end_et"],
                    "timezone": run["timezone"],
                    "session": run["session"],
                    "data_gate": factor["data_gate"],
                    "marker_version": run["marker_version"],
                    "return_definition": "close_to_close",
                }
            else:
                row.update(
                    {
                        "horizon_minutes": horizon_minutes,
                        "pass_mean_return": None,
                        "fail_mean_return": None,
                        "pass_fail_diff_bps": None,
                        "baseline_mean_return": None,
                        "pass_edge_vs_baseline_bps": None,
                        "pass_n": 0,
                        "fail_n": 0,
                        "positive_rate": None,
                        "coverage_trading_days": 0,
                        "coverage_first_day": None,
                        "coverage_last_day": None,
                        "stable_better_days": 0,
                        "stable_eligible_days": 0,
                        "daily_stability": None,
                        "monthly": [],
                        "train_analysis": None,
                        "warmup_audit": None,
                    }
                )
            rows.append(row)

        reason_codes: list[str] = []
        if len(factors) != planned_factor_count:
            reason_codes.append("PLAN_CATALOG_INCOMPLETE")
        if len(factors) < 2:
            reason_codes.append("FEWER_THAN_TWO_FACTORS")
        if any(row["pass_mean_return"] is None or row["fail_mean_return"] is None for row in rows):
            reason_codes.append("MISSING_ELIGIBLE_RUN")
        if any(factor["data_gate"] != "PASS" for factor in factors):
            reason_codes.append("DATA_GATE_NOT_PASS")
        scope_tokens = {
            json.dumps(row["comparison_scope"], ensure_ascii=False, sort_keys=True)
            for row in rows
            if row["comparison_scope"] is not None
        }
        if len(factors) > 1 and (
            len(scope_tokens) != 1 or any(row["comparison_scope"] is None for row in rows)
        ):
            reason_codes.append("COMPARISON_SCOPE_MISMATCH")

        reason_codes = list(dict.fromkeys(reason_codes))
        ranking_ready = not reason_codes
        if ranking_ready:
            rows.sort(key=lambda item: item["pass_fail_diff_bps"], reverse=True)
            for rank, row in enumerate(rows, start=1):
                row["rank"] = rank
        else:
            rows.sort(key=lambda item: item["factor_id"])
        return {
            "horizon_minutes": horizon_minutes,
            "ranking_ready": ranking_ready,
            "reason_codes": reason_codes,
            "rows": rows,
            "return_unit": "percent",
            "difference_unit": "bp",
        }

    def dashboard_snapshot(
        self, horizon_minutes: int = 15, planned_factor_count: int | None = None
    ) -> dict[str, Any]:
        if horizon_minutes not in HORIZONS:
            raise ValueError("unsupported horizon")
        with self.connect() as connection:
            factors = self._rows(
                connection.execute(
                    """
                    SELECT f.*, fv.strategy_version, fv.strategy_hash, fv.parameter_version,
                        (SELECT COUNT(*) FROM research_runs r
                         JOIN factor_versions v ON v.version_id=r.version_id
                         WHERE v.factor_id=f.factor_id) AS run_count,
                        (SELECT COUNT(*) FROM research_runs r
                         JOIN factor_versions v ON v.version_id=r.version_id
                         WHERE v.factor_id=f.factor_id AND r.run_status='VALIDATED') AS valid_run_count,
                        (SELECT MAX(r.imported_at_utc) FROM research_runs r
                         JOIN factor_versions v ON v.version_id=r.version_id
                         WHERE v.factor_id=f.factor_id) AS latest_run_utc,
                        (SELECT r.research_verdict FROM research_runs r
                         JOIN factor_versions v ON v.version_id=r.version_id
                         WHERE v.factor_id=f.factor_id
                         ORDER BY r.imported_at_utc DESC LIMIT 1) AS latest_verdict
                    FROM factors f
                    LEFT JOIN factor_versions fv ON fv.factor_id=f.factor_id AND fv.active=1
                    ORDER BY f.factor_id
                    """
                ).fetchall()
            )
            runs = self._rows(
                connection.execute(
                    """
                    SELECT r.*, v.factor_id, v.strategy_version, v.strategy_hash,
                        v.parameter_version, s.canonical_path, s.marker_version,
                        s.system_log_start_local, s.system_log_end_local
                    FROM research_runs r
                    JOIN factor_versions v ON v.version_id=r.version_id
                    JOIN source_files s ON s.file_sha256=r.file_sha256
                    ORDER BY r.imported_at_utc DESC LIMIT 100
                    """
                ).fetchall()
            )
            gates = self._rows(
                connection.execute(
                    "SELECT * FROM data_gate_evidence ORDER BY symbol, dimension, gate_id"
                ).fetchall()
            )
            issues = self._rows(
                connection.execute(
                    """
                    SELECT * FROM issues
                    ORDER BY CASE status WHEN 'OPEN' THEN 0 ELSE 1 END,
                             last_seen_utc DESC
                    LIMIT 200
                    """
                ).fetchall()
            )
            imports = self._rows(
                connection.execute(
                    "SELECT * FROM source_files ORDER BY last_seen_utc DESC LIMIT 100"
                ).fetchall()
            )
            states = {
                row["state_key"]: row["state_value"]
                for row in connection.execute("SELECT * FROM app_state").fetchall()
            }
            planned_count = max(planned_factor_count or len(factors), len(factors))
            comparison = self._comparison_snapshot(
                connection, factors, horizon_minutes, planned_count
            )
        validated_partitions = {
            (item["factor_id"], item["study_partition"])
            for item in runs
            if item["run_status"] == "VALIDATED"
        }
        summary = {
            "candidate_factors": len(factors),
            "planned_factors": planned_count,
            "planned_factor_source": "C1 六因子计划；可由 FUTU_FACTOR_PLANNED_COUNT 覆盖",
            "registered_factors": len(factors),
            "code_written": sum(int(item["code_present"]) for item in factors),
            "first_backtest_done": sum(int(item["valid_run_count"] > 0) for item in factors),
            "functional_backtest_done": len(
                {factor_id for factor_id, part in validated_partitions if part == "FUNCTIONAL_VALIDATION"}
            ),
            "long_train_done": len(
                {factor_id for factor_id, part in validated_partitions if part == "TRAIN"}
            ),
            "validation_done": len(
                {factor_id for factor_id, part in validated_partitions if part == "VALIDATION"}
            ),
            "oos_done": len(
                {factor_id for factor_id, part in validated_partitions if part == "OOS"}
            ),
            "evidence_supported": sum(
                item["edge_status"] in SUPPORTED_EDGE_STATUSES for item in factors
            ),
            "data_qualified": sum(item["data_gate"] == "PASS" for item in factors),
            "oos_supported": sum(item["edge_status"] == "OOS_SUPPORTED" for item in factors),
            "rejected": sum(item["development_stage"] == "REJECTED" for item in factors),
            "waiting_export": sum(
                item["issue_code"] == "WAITING_EXPORT" and item["status"] == "OPEN"
                for item in issues
            ),
            "import_anomalies": sum(
                item["kind"] == "ANOMALY" and item["status"] == "OPEN" for item in issues
            ),
            "latest_data_utc": max(
                [item["last_seen_utc"] for item in imports]
                + [item["updated_at_utc"] for item in factors]
                + [None],
                key=lambda value: value or "",
            ),
            "next_action": next(
                (item["next_action"] for item in factors if item.get("next_action")),
                "等待新的验收记录或回测 CSV。",
            ),
        }
        return {
            "summary": summary,
            "comparison": comparison,
            "factors": factors,
            "runs": runs,
            "gates": gates,
            "issues": issues,
            "imports": imports,
            "app_state": states,
        }

    def factor_detail(
        self, factor_id: str, horizon_minutes: int = 15
    ) -> dict[str, Any] | None:
        if horizon_minutes not in HORIZONS:
            raise ValueError("unsupported horizon")
        snapshot = self.dashboard_snapshot(horizon_minutes=horizon_minutes)
        factor = next((item for item in snapshot["factors"] if item["factor_id"] == factor_id), None)
        if factor is None:
            return None
        runs = [item for item in snapshot["runs"] if item["factor_id"] == factor_id]
        with self.connect() as connection:
            for run in runs:
                run["statistics"] = self._rows(
                    connection.execute(
                        """
                        SELECT * FROM run_statistics WHERE run_instance_id=?
                        ORDER BY horizon_minutes, cohort
                        """,
                        (run["run_instance_id"],),
                    ).fetchall()
                )
                distributions: dict[str, list[dict]] = {}
                for horizon in (15, 30, 60):
                    for cohort in ("ALL", "PASS", "FAIL"):
                        values = [
                            row["forward_return"]
                            for row in connection.execute(
                                """
                                SELECT l.forward_return FROM labels l
                                JOIN signals s ON s.run_instance_id=l.run_instance_id
                                    AND s.signal_id=l.signal_id
                                WHERE l.run_instance_id=? AND l.horizon_minutes=?
                                  AND (?='ALL' OR s.factor_value=?)
                                """,
                                (run["run_instance_id"], horizon, cohort, cohort),
                            ).fetchall()
                        ]
                        distributions[f"{horizon}_{cohort}"] = histogram(values)
                run["distributions"] = distributions
                run["selected_window"] = self._run_window_metrics(
                    connection,
                    run["run_instance_id"],
                    horizon_minutes,
                    include_analysis=True,
                )
        return {
            "factor": factor,
            "horizon_minutes": horizon_minutes,
            "runs": runs,
            "gates": [
                item
                for item in snapshot["gates"]
                if item["factor_id"] in (None, factor_id) and item["symbol"] in (factor["symbol"], "US.QQQ")
            ],
            "issues": [
                item for item in snapshot["issues"] if item["factor_id"] in (None, factor_id)
            ],
            "market_environment_note": "尚无经验证的市场环境标签，当前不生成环境优劣结论。",
            "limitations": [
                "条件收益为 close-to-close 研究统计，不是可执行交易 PnL。",
                "相邻信号和持有窗口可能重叠，样本并非完全独立。",
                "只有明确完成 Validation/OOS 后，才可升级独立验证结论。",
            ],
        }

    def source_path(self, file_sha256: str) -> Path | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT canonical_path FROM source_files WHERE file_sha256=?",
                (file_sha256,),
            ).fetchone()
        return Path(row["canonical_path"]) if row else None
