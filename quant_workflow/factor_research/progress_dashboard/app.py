from __future__ import annotations

from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from .db import Database
from .ingest import FolderWatcher, Importer, MAX_FILE_BYTES, sha256_file


HERE = Path(__file__).resolve().parent


def _default_data_dir() -> Path:
    return HERE / "data"


def _default_downloads() -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Downloads"


def create_app(
    *,
    database_path: Path | None = None,
    watch_dirs: list[Path] | None = None,
    inbox_dir: Path | None = None,
    enable_watcher: bool = True,
    allow_fixtures: bool = False,
    poll_seconds: float = 2.0,
) -> FastAPI:
    data_dir = _default_data_dir()
    database_path = Path(
        database_path
        or os.environ.get("FUTU_FACTOR_DB", data_dir / "factor_progress_v1.sqlite3")
    )
    inbox_dir = Path(inbox_dir or os.environ.get("FUTU_FACTOR_INBOX", data_dir / "inbox"))
    configured_watch = os.environ.get("FUTU_FACTOR_WATCH_DIR")
    watch_dirs = watch_dirs or [Path(configured_watch) if configured_watch else _default_downloads(), inbox_dir]
    inbox_dir.mkdir(parents=True, exist_ok=True)

    database = Database(database_path)
    database.initialize()
    importer = Importer(database, allow_fixtures=allow_fixtures)
    watcher = FolderWatcher(importer, watch_dirs, poll_seconds=poll_seconds, stable_checks=2)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if enable_watcher:
            watcher.start()
        try:
            yield
        finally:
            watcher.stop()

    application = FastAPI(
        title="Futu Quant 因子研究进度看板",
        version="1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    application.state.database = database
    application.state.importer = importer
    application.state.watcher = watcher
    application.state.inbox_dir = inbox_dir

    @application.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse((HERE / "templates" / "index.html").read_text(encoding="utf-8"))

    @application.get("/api/health")
    def health() -> dict:
        return {
            "ok": True,
            "service": "futu-factor-progress-dashboard",
            "watching": watcher.running,
            "host_scope": "127.0.0.1-only",
            "orders_enabled": False,
        }

    @application.get("/api/dashboard")
    def dashboard() -> dict:
        snapshot = database.dashboard_snapshot()
        snapshot["service"] = {
            "watching": watcher.running,
            "status": "正在监控" if watcher.running else "已暂停",
            "last_error": watcher.last_error,
            "watch_dirs": [str(path) for path in watcher.folders],
            "poll_seconds": watcher.poll_seconds,
            "orders_enabled": False,
        }
        return snapshot

    @application.get("/api/factors/{factor_id}")
    def factor_detail(factor_id: str) -> dict:
        detail = database.factor_detail(factor_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="factor not found")
        return detail

    @application.post("/api/import")
    async def upload_csv(file: UploadFile = File(...)) -> dict:
        if not file.filename or not file.filename.lower().endswith(".csv"):
            raise HTTPException(status_code=400, detail="only CSV files are accepted")
        content = await file.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail="file exceeds 50 MiB")
        digest = hashlib.sha256(content).hexdigest()
        target = inbox_dir / f"RunLog_upload_{digest[:16]}.csv"
        if not target.exists():
            target.write_bytes(content)
        result = importer.import_file(target)
        return {**result, "saved_as": target.name}

    @application.get("/api/source-files/{file_sha256}")
    def source_file(file_sha256: str) -> FileResponse:
        if not re_full_sha256(file_sha256):
            raise HTTPException(status_code=400, detail="invalid sha256")
        path = database.source_path(file_sha256)
        if path is None or not path.is_file():
            raise HTTPException(status_code=404, detail="source file not found")
        if sha256_file(path) != file_sha256:
            raise HTTPException(status_code=409, detail="source file changed after import")
        return FileResponse(path, filename=path.name, media_type="text/csv")

    return application


def re_full_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
