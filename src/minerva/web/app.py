"""FastAPI application factory and server-rendered review surface."""

from __future__ import annotations

import secrets
import sqlite3
from pathlib import Path
from typing import Annotated, Final

from fastapi import FastAPI, Request
from fastapi import Path as ApiPath
from fastapi.responses import JSONResponse, RedirectResponse
from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from minerva import __version__
from minerva.api.errors import install_exception_handlers
from minerva.api.models import HealthRead, ReadinessRead, ReadyCheckRead
from minerva.api.routes import MAX_REQUEST_BODY_BYTES, create_api_router
from minerva.assist.adoption import AdoptionService
from minerva.core.db import Database
from minerva.core.doctor import run_doctor
from minerva.core.errors import MinervaError, NotFoundError
from minerva.core.types import local_identity
from minerva.evidence.service import EvidenceService
from minerva.lineage import ClaimLineageService
from minerva.research.models import ClaimStatus, FindingStatus, StatementKind
from minerva.research.service import ResearchService
from minerva.research_queue import MissionResearchQueueService
from minerva.review import ClaimReviewService
from minerva.sources.service import SourceService
from minerva.synthesis.service import SynthesisService
from minerva.web.forms import (
    add_csrf_cookie,
    csrf_token_for_request,
    form_enum,
    form_evidence_ids,
    form_identifier,
    optional_form_identifier,
    positive_form_integer,
    read_strict_form,
)
from minerva.web.security import CsrfProtector, LocalSecurityMiddleware

_WebId = Annotated[str, ApiPath(min_length=1, max_length=100)]

WEB_MISSION_PAGE_SIZE: Final = 100
"""How many missions the review surface renders at once.

The page is deliberately single-page: this is a restrained review surface, and
adding cursor navigation would mean either coupling it to the REST layer's
cursor encoding or growing a second one. What it must not do is present a capped
list as the whole set, so the template says how many it is showing and whether
more exist, and points at the surfaces that can page.
"""


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
    adoption = AdoptionService(database)
    queue = MissionResearchQueueService(database)
    review = ClaimReviewService(database)
    lineage = ClaimLineageService(database)
    templates = _templates()
    csrf = CsrfProtector(secrets.token_bytes(32))

    app = FastAPI(
        title="Minerva",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
    )
    app.state.database = database
    app.state.csrf = csrf
    install_exception_handlers(app)
    app.include_router(create_api_router(database))
    app.mount(
        "/static",
        StaticFiles(packages=[("minerva.web", "static")]),
        name="static",
    )

    @app.get("/healthz", include_in_schema=False)
    def health() -> dict[str, str]:
        return HealthRead(status="ok").model_dump(mode="json")

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
            ReadinessRead.model_validate(
                {
                    "status": "ready" if ready else "not_ready",
                    "checks": checks,
                }
            ).model_dump(mode="json"),
            status_code=200 if ready else 503,
        )

    @app.get("/", include_in_schema=False)
    def index() -> RedirectResponse:
        return RedirectResponse("/missions", status_code=303)

    @app.get("/missions", include_in_schema=False)
    def mission_list(request: Request) -> Response:
        # `page_missions` fetches one extra row and reports whether it existed,
        # so "more missions exist" is exact rather than the `len == limit`
        # guess, which would claim more whenever a mission count landed
        # exactly on the page size.
        missions, next_position = research.page_missions(limit=WEB_MISSION_PAGE_SIZE)
        return templates.TemplateResponse(
            request,
            "missions.html",
            {
                "missions": missions,
                "mission_page_size": WEB_MISSION_PAGE_SIZE,
                "more_missions_exist": next_position is not None,
                "page_title": "Research missions",
            },
        )

    @app.get("/missions/{mission_id}", include_in_schema=False)
    def mission_detail(request: Request, mission_id: _WebId) -> Response:
        with database.read() as connection:
            research_queue = queue.build_queue(
                mission_id=mission_id,
                connection=connection,
            )
            context = {
                "mission": research.get_mission(mission_id, connection=connection),
                "mission_audit_sequence": research.get_mission_audit_sequence(
                    mission_id,
                    connection=connection,
                ),
                "questions": research.list_questions(mission_id, connection=connection),
                "claims": research.list_claims(mission_id, connection=connection),
                "sources": sources.list_snapshots(mission_id, connection=connection),
                "findings": research.list_findings(mission_id, connection=connection),
                "agent_inferences": adoption.list_inferences(mission_id, connection=connection),
                "research_queue": research_queue,
                "claim_statuses": tuple(ClaimStatus),
                "finding_statuses": tuple(FindingStatus),
                "statement_kinds": tuple(StatementKind),
                "page_title": "Mission cockpit",
            }
        csrf_token, issue_cookie = csrf_token_for_request(request, csrf)
        context["csrf_token"] = csrf_token
        response = templates.TemplateResponse(
            request,
            "mission_detail.html",
            context,
        )
        if issue_cookie:
            add_csrf_cookie(
                response,
                request=request,
                csrf=csrf,
                token=csrf_token,
            )
        return response

    @app.post("/missions/{mission_id}/claims", include_in_schema=False)
    async def mission_claim_create(request: Request, mission_id: _WebId) -> RedirectResponse:
        fields = await read_strict_form(
            request,
            csrf=csrf,
            required_fields={
                "question_id",
                "statement",
                "falsification_criteria",
                "expected_mission_audit_sequence",
            },
        )
        research.add_claim(
            mission_id=mission_id,
            question_id=form_identifier(fields["question_id"]),
            statement=fields["statement"],
            falsification_criteria=fields["falsification_criteria"],
            identity=local_identity(purpose="web:claim-add"),
            expected_mission_audit_sequence=positive_form_integer(
                fields["expected_mission_audit_sequence"]
            ),
        )
        return RedirectResponse(
            request.url_for("mission_detail", mission_id=mission_id),
            status_code=303,
        )

    @app.post(
        "/missions/{mission_id}/claims/{claim_id}/status",
        include_in_schema=False,
    )
    async def mission_claim_status(
        request: Request,
        mission_id: _WebId,
        claim_id: _WebId,
    ) -> RedirectResponse:
        fields = await read_strict_form(
            request,
            csrf=csrf,
            required_fields={"status", "reason", "expected_version"},
        )
        claim = research.get_claim(claim_id)
        if claim.mission_id != mission_id:
            raise NotFoundError("claim_not_found")
        research.set_claim_status(
            claim_id=claim_id,
            status=form_enum(ClaimStatus, fields["status"]),
            reason=fields["reason"],
            expected_version=positive_form_integer(fields["expected_version"]),
            identity=local_identity(purpose="web:claim-status"),
        )
        return RedirectResponse(
            request.url_for("mission_detail", mission_id=mission_id),
            status_code=303,
        )

    @app.post("/missions/{mission_id}/findings", include_in_schema=False)
    async def mission_finding_create(request: Request, mission_id: _WebId) -> RedirectResponse:
        fields = await read_strict_form(
            request,
            csrf=csrf,
            required_fields={
                "claim_id",
                "statement",
                "statement_kind",
                "status",
                "uncertainty",
                "evidence_ids",
                "expected_mission_audit_sequence",
            },
        )
        research.add_finding(
            mission_id=mission_id,
            claim_id=optional_form_identifier(fields["claim_id"]),
            statement=fields["statement"],
            statement_kind=form_enum(StatementKind, fields["statement_kind"]),
            status=form_enum(FindingStatus, fields["status"]),
            uncertainty=fields["uncertainty"],
            evidence_ids=form_evidence_ids(fields["evidence_ids"]),
            identity=local_identity(purpose="web:finding-add"),
            expected_mission_audit_sequence=positive_form_integer(
                fields["expected_mission_audit_sequence"]
            ),
        )
        return RedirectResponse(
            request.url_for("mission_detail", mission_id=mission_id),
            status_code=303,
        )

    @app.get("/missions/{mission_id}/queue", include_in_schema=False)
    def mission_queue_view(request: Request, mission_id: _WebId) -> Response:
        result = queue.build_queue(mission_id=mission_id)
        return templates.TemplateResponse(
            request,
            "mission_queue.html",
            {
                "queue": result,
                "page_title": "Mission structural review",
            },
        )

    @app.get("/claims/{claim_id}", include_in_schema=False)
    def claim_detail(request: Request, claim_id: _WebId) -> Response:
        with database.read() as connection:
            claim = research.get_claim(claim_id, connection=connection)
            ledger = evidence.ledger_for_claim(claim_id, connection=connection)
            inferences = adoption.list_inferences_for_claim(claim_id, connection=connection)
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
                "agent_inferences": inferences,
                "page_title": "Claim evidence ledger",
            },
        )

    @app.get("/missions/{mission_id}/claims/{claim_id}/review", include_in_schema=False)
    def claim_review_view(request: Request, mission_id: _WebId, claim_id: _WebId) -> Response:
        result = review.review_claim(mission_id=mission_id, claim_id=claim_id)
        return templates.TemplateResponse(
            request,
            "claim_review.html",
            {
                "review": result,
                "page_title": "Claim structural review",
            },
        )

    @app.get("/missions/{mission_id}/claims/{claim_id}/lineage", include_in_schema=False)
    def claim_lineage_view(request: Request, mission_id: _WebId, claim_id: _WebId) -> Response:
        result = lineage.build_graph(mission_id=mission_id, claim_id=claim_id)
        return templates.TemplateResponse(
            request,
            "claim_lineage.html",
            {
                "lineage": result,
                "page_title": "Claim provenance lineage",
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
