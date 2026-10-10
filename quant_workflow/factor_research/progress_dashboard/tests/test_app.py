from pathlib import Path

from fastapi.testclient import TestClient

from quant_workflow.factor_research.progress_dashboard.app import create_app


def test_dashboard_page_health_and_initial_api(tmp_path):
    app = create_app(
        database_path=tmp_path / "app.sqlite3",
        watch_dirs=[tmp_path / "downloads"],
        inbox_dir=tmp_path / "inbox",
        enable_watcher=False,
    )
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "Futu 因子研究看板" in page.text
        assert "因子表现比较" in page.text
        assert "高级资料" in page.text
        assert 'data-horizon="15"' in page.text
        assert 'data-horizon="30"' in page.text
        assert 'data-horizon="60"' in page.text
        health = client.get("/api/health").json()
        assert health["orders_enabled"] is False
        assert health["host_scope"] == "127.0.0.1-only"
        payload = client.get("/api/dashboard").json()
        assert payload["factors"][0]["development_stage"] == "SPECIFIED"
        assert payload["factors"][0]["conclusion_zh"] == "未测试"
        assert payload["summary"]["planned_factors"] == 6
        assert payload["summary"]["registered_factors"] == 1
        assert payload["comparison"]["ranking_ready"] is False
        assert "PLAN_CATALOG_INCOMPLETE" in payload["comparison"]["reason_codes"]
        assert payload["service"]["status"] == "已暂停"


def test_fixture_upload_uses_test_database_only(tmp_path, runlog_fixture):
    app = create_app(
        database_path=tmp_path / "test-only.sqlite3",
        watch_dirs=[tmp_path / "downloads"],
        inbox_dir=tmp_path / "inbox",
        enable_watcher=False,
        allow_fixtures=True,
    )
    with TestClient(app) as client:
        with runlog_fixture.open("rb") as handle:
            response = client.post("/api/import", files={"file": (runlog_fixture.name, handle, "text/csv")})
        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "VALIDATED"
        dashboard = client.get("/api/dashboard").json()
        assert len(dashboard["runs"]) == 1
        source = client.get(f"/api/source-files/{result['file_sha256']}")
        assert source.status_code == 200
        assert b"FUTU_FACTOR_V1" in source.content


def test_source_endpoint_rejects_path_like_identifier(tmp_path):
    app = create_app(
        database_path=tmp_path / "app.sqlite3",
        inbox_dir=tmp_path / "inbox",
        enable_watcher=False,
    )
    with TestClient(app) as client:
        assert client.get("/api/source-files/not-a-sha").status_code == 400


def test_legacy_functional_upload_is_visible_in_api_and_page(tmp_path, legacy_runlog_fixture):
    app = create_app(
        database_path=tmp_path / "legacy.sqlite3",
        watch_dirs=[tmp_path / "downloads"],
        inbox_dir=tmp_path / "inbox",
        enable_watcher=False,
    )
    with TestClient(app) as client:
        with legacy_runlog_fixture.open("rb") as handle:
            response = client.post(
                "/api/import",
                files={"file": (legacy_runlog_fixture.name, handle, "text/csv")},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "VALIDATED"
        dashboard = client.get("/api/dashboard").json()
        assert dashboard["runs"][0]["research_verdict"] == "FUNCTIONAL_VALIDATION_PASS"
        assert dashboard["factors"][0]["edge_status"] == "INSUFFICIENT_EVIDENCE"
        assert dashboard["factors"][0]["conclusion_zh"] == "证据不足"
        page = client.get("/")
        assert "有证据的有效因子" in page.text
        assert "高历史均值不等于找到 Edge" in page.text


def test_horizon_switching_and_invalid_window(tmp_path, runlog_fixture):
    app = create_app(
        database_path=tmp_path / "windows.sqlite3",
        watch_dirs=[tmp_path / "downloads"],
        inbox_dir=tmp_path / "inbox",
        enable_watcher=False,
        allow_fixtures=True,
    )
    with TestClient(app) as client:
        with runlog_fixture.open("rb") as handle:
            assert client.post(
                "/api/import", files={"file": (runlog_fixture.name, handle, "text/csv")}
            ).status_code == 200
        expected = {15: 0.01, 30: -0.01, 60: 0.02}
        for horizon, mean_return in expected.items():
            response = client.get(f"/api/dashboard?horizon_minutes={horizon}")
            assert response.status_code == 200
            comparison = response.json()["comparison"]
            assert comparison["horizon_minutes"] == horizon
            assert comparison["rows"][0]["pass_mean_return"] == mean_return
        assert client.get("/api/dashboard?horizon_minutes=45").status_code == 422
        assert client.get(
            "/api/factors/SPY_F001_CLOSE_GT_EMA20?horizon_minutes=45"
        ).status_code == 422


def test_import_failure_has_chinese_reason_and_preserves_raw_code(tmp_path):
    app = create_app(
        database_path=tmp_path / "errors.sqlite3",
        inbox_dir=tmp_path / "inbox",
        enable_watcher=False,
    )
    bad = tmp_path / "RunLog_bad.csv"
    bad.write_text('time,message\n1,"FUTU_FACTOR_V9|{}"\n', encoding="utf-8")
    with TestClient(app) as client, bad.open("rb") as handle:
        response = client.post("/api/import", files={"file": (bad.name, handle, "text/csv")})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "INVALID"
    assert payload["error_info"]["raw_error"] == "UNSUPPORTED_MARKER_VERSION"
    assert "不支持" in payload["error_info"]["message_zh"]
