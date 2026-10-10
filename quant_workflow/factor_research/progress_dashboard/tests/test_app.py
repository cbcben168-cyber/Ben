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
        assert "Futu Quant 因子研究进度看板" in page.text
        health = client.get("/api/health").json()
        assert health["orders_enabled"] is False
        assert health["host_scope"] == "127.0.0.1-only"
        payload = client.get("/api/dashboard").json()
        assert payload["factors"][0]["development_stage"] == "SPECIFIED"
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
        page = client.get("/")
        assert "research_verdict" in page.text
        assert "功能验收" in page.text
