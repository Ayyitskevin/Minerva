"""FastAPI application factory and server-rendered review surface."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Request
from fastapi import Path as ApiPath
from fastapi.responses import JSONResponse, RedirectResponse
from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from minerva import __version__
from minerva.api.errors import install_exception_handlers
from minerva.api.models import ReadyCheckRead
from minerva.api.routes import MAX_REQUEST_BODY_BYTES, create_api_router
from minerva.core.db import Database
from minerva.core.doctor import run_doctor
from minerva.core.errors import MinervaError
from minerva.evidence.service import EvidenceService
from minerva.research.service import ResearchService
from minerva.sources.service import SourceService
from minerva.synthesis.service import SynthesisService
from minerva.web.security import LocalSecurityMiddleware

_WebId = Annotated[str, ApiPath(min_length=1, max_length=100)]


def _templates() -> Jinja2Templates:
    environment = Environment(
        loader=PackageLoader("minerva.web", "templates"),
        autoescape=select_autoescape(
            enabled_extensions=("html", "htm", "xml"),
            default_for_string=True,
            default=True,
        ),
        undefined=StrictUndefined,
        enable_async=False,
    )
    return Jinja2Templates(env=environment)


def create_app(db_path: str | Path, testing: bool = False) -> FastAPI:
    """Create a loopback-only Minerva app without initializing or migrating its database."""

    database = Database(Path(db_path))
    research = ResearchService(database)
    sources = SourceService(database)
    evidence = EvidenceService(database)
    synthesis = SynthesisService(database)
    templates = _templates()

    app = FastAPI(
        title="Minerva",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
    )
    app.state.database = database
    install_exception_handlers(app)
    app.include_router(create_api_router(database))
    app.mount(
        "/static",
        StaticFiles(packages=[("minerva.web", "static")]),
        name="static",
    )

    @app.get("/healthz", include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    def readiness() -> JSONResponse:
        try:
            report = run_doctor(database, deep=False)
            checks = [
                ReadyCheckRead(
                    name=item.name,
                    ok=item.ok,
                    message=item.message,
                ).model_dump(mode="json")
                for item in report.checks
            ]
            ready = report.ok
        except (MinervaError, OSError, sqlite3.Error):
            ready = False
            checks = [
                ReadyCheckRead(
                    name="database",
                    ok=False,
                    message="Database readiness validation failed safely.",
                ).model_dump(mode="json")
            ]
        return JSONResponse(
            {
                "status": "ready" if ready else "not_ready",
                "checks": checks,
            },
            status_code=200 if ready else 503,
        )

    @app.get("/", include_in_schema=False)
    def index() -> RedirectResponse:
        return RedirectResponse("/missions", status_code=303)

    @app.get("/missions", include_in_schema=False)
    def mission_list(request: Request) -> Response:
        return templates.TemplateResponse(
            request,
            "missions.html",
            {
                "missions": research.list_missions(),
                "page_title": "Research missions",
            },
        )

    @app.get("/missions/{mission_id}", include_in_schema=False)
    def mission_detail(request: Request, mission_id: _WebId) -> Response:
        with database.read() as connection:
            context = {
                "mission": research.get_mission(mission_id, connection=connection),
                "questions": research.list_questions(mission_id, connection=connection),
                "claims": research.list_claims(mission_id, connection=connection),
                "sources": sources.list_snapshots(mission_id, connection=connection),
                "findings": research.list_findings(mission_id, connection=connection),
                "page_title": "Mission review",
            }
        return templates.TemplateResponse(
            request,
            "mission_detail.html",
            context,
        )

    @app.get("/claims/{claim_id}", include_in_schema=False)
    def claim_detail(request: Request, claim_id: _WebId) -> Response:
        with database.read() as connection:
            claim = research.get_claim(claim_id, connection=connection)
            ledger = evidence.ledger_for_claim(claim_id, connection=connection)
            snapshots = {
                entry.evidence.snapshot_id: sources.get_snapshot(
                    entry.evidence.snapshot_id,
                    connection=connection,
                )
                for entry in ledger
            }
        return templates.TemplateResponse(
            request,
            "claim_detail.html",
            {
                "claim": claim,
                "ledger": ledger,
                "snapshots": snapshots,
                "page_title": "Claim evidence ledger",
            },
        )

    @app.get("/missions/{mission_id}/brief", include_in_schema=False)
    def brief_preview(request: Request, mission_id: _WebId) -> Response:
        mission = research.get_mission(mission_id)
        artifacts = synthesis.build_brief(mission_id)
        return templates.TemplateResponse(
            request,
            "brief_preview.html",
            {
                "mission": mission,
                "export_digest": artifacts.export_digest,
                "markdown": artifacts.markdown.decode("utf-8", errors="strict"),
                "page_title": "Research brief preview",
            },
        )

    @app.get("/missions/{mission_id}/brief/markdown", include_in_schema=False)
    def brief_markdown_download(mission_id: _WebId) -> Response:
        artifacts = synthesis.build_brief(mission_id)
        return Response(
            content=artifacts.markdown,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="research-brief.md"'},
        )

    @app.get("/missions/{mission_id}/brief/json", include_in_schema=False)
    def brief_json_download(mission_id: _WebId) -> Response:
        artifacts = synthesis.build_brief(mission_id)
        return Response(
            content=artifacts.json,
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="research-brief.json"'},
        )

    app.add_middleware(
        LocalSecurityMiddleware,
        max_request_body_bytes=MAX_REQUEST_BODY_BYTES,
        allowed_test_hosts=("testserver",) if testing else (),
    )
    return app
