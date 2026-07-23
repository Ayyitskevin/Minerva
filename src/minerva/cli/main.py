"""Argparse console adapter for Minerva's shared services."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

from minerva.assist.models import ModelProvider
from minerva.assist.service import AssistanceService
from minerva.cli._common import EXIT_OPERATIONAL, Outcome, run_safely
from minerva.cli.credentials import load_provider_credential, resolve_provider_selection
from minerva.core.audit import list_audit_events
from minerva.core.db import Database
from minerva.core.doctor import run_doctor
from minerva.core.errors import SecurityBoundaryError
from minerva.core.operations import OperationsService
from minerva.core.types import IdentityContext, local_identity
from minerva.evidence.models import EvidenceStance
from minerva.evidence.service import EvidenceService
from minerva.integrations.research_packet_file import (
    load_research_packet,
    packet_inspection_report,
    packet_verification_report,
)
from minerva.integrations.research_request_file import (
    load_research_request,
    request_verification_report,
)
from minerva.research.models import ClaimStatus, FindingStatus, StatementKind
from minerva.research.service import ResearchService
from minerva.sources.service import SourceService
from minerva.synthesis.request_fulfillment import ResearchRequestFulfillmentService
from minerva.synthesis.service import SynthesisService

CommandHandler = Callable[[argparse.Namespace], Outcome]


def _database(args: argparse.Namespace) -> Database:
    return Database(cast(Path, args.db))


def _identity(purpose: str) -> IdentityContext:
    return local_identity(purpose=purpose)


def _command_result(name: str, value: object) -> Outcome:
    return Outcome({name: value})


def _claim_with_ledger(database: Database, claim_id: str) -> Outcome:
    research = ResearchService(database)
    evidence = EvidenceService(database)
    with database.read() as connection:
        claim = research.get_claim(claim_id, connection=connection)
        ledger = evidence.ledger_for_claim(claim_id, connection=connection)
    return Outcome({"claim": claim, "evidence_ledger": ledger})


def _cmd_init(args: argparse.Namespace) -> Outcome:
    database = _database(args)
    version = OperationsService(database).initialize(
        identity=_identity("cli:init"),
        refuse_existing=cast(bool, args.refuse_existing),
    )
    return Outcome({"status": "initialized", "schema_version": version})


def _cmd_mission_create(args: argparse.Namespace) -> Outcome:
    mission = ResearchService(_database(args)).create_mission(
        title=cast(str, args.title),
        objective=cast(str, args.objective),
        identity=_identity("cli:mission-create"),
    )
    return _command_result("mission", mission)


def _cmd_mission_list(args: argparse.Namespace) -> Outcome:
    missions = ResearchService(_database(args)).list_missions(limit=cast(int, args.limit))
    return _command_result("missions", missions)


def _cmd_mission_show(args: argparse.Namespace) -> Outcome:
    database = _database(args)
    mission_id = cast(str, args.mission)
    research = ResearchService(database)
    sources = SourceService(database)
    with database.read() as connection:
        result = {
            "mission": research.get_mission(mission_id, connection=connection),
            "questions": research.list_questions(mission_id, connection=connection),
            "claims": research.list_claims(mission_id, connection=connection),
            "findings": research.list_findings(mission_id, connection=connection),
            "source_snapshots": sources.list_snapshots(mission_id, connection=connection),
        }
    return Outcome(result)


def _cmd_question_add(args: argparse.Namespace) -> Outcome:
    question = ResearchService(_database(args)).add_question(
        mission_id=cast(str, args.mission),
        text=cast(str, args.text),
        identity=_identity("cli:question-add"),
    )
    return _command_result("question", question)


def _cmd_claim_add(args: argparse.Namespace) -> Outcome:
    claim = ResearchService(_database(args)).add_claim(
        mission_id=cast(str, args.mission),
        question_id=cast(str, args.question),
        statement=cast(str, args.statement),
        falsification_criteria=cast(str, args.falsification_criteria),
        identity=_identity("cli:claim-add"),
    )
    return _command_result("claim", claim)


def _cmd_claim_show(args: argparse.Namespace) -> Outcome:
    return _claim_with_ledger(_database(args), cast(str, args.claim))


def _cmd_claim_status(args: argparse.Namespace) -> Outcome:
    claim = ResearchService(_database(args)).set_claim_status(
        claim_id=cast(str, args.claim),
        status=ClaimStatus(cast(str, args.status)),
        reason=cast(str, args.reason),
        expected_version=cast(int, args.expected_version),
        identity=_identity("cli:claim-status"),
    )
    return _command_result("claim", claim)


def _cmd_source_import(args: argparse.Namespace) -> Outcome:
    snapshot = SourceService(_database(args)).import_file(
        mission_id=cast(str, args.mission),
        root=cast(Path, args.root),
        relative_path=cast(str, args.file),
        media_type=cast(str, args.media_type),
        url_metadata=cast(str | None, args.url_metadata),
        identity=_identity("cli:source-import"),
    )
    return _command_result("snapshot", snapshot)


def _cmd_source_show(args: argparse.Namespace) -> Outcome:
    snapshot = SourceService(_database(args)).read_snapshot(cast(str, args.snapshot))
    payload: dict[str, object] = {"snapshot": snapshot.metadata}
    if not cast(bool, args.metadata_only):
        payload["text"] = snapshot.content.decode("utf-8", errors="strict")
    return Outcome(payload)


def _cmd_evidence_add(args: argparse.Namespace) -> Outcome:
    evidence = EvidenceService(_database(args)).add_evidence(
        mission_id=cast(str, args.mission),
        claim_id=cast(str, args.claim),
        snapshot_id=cast(str, args.snapshot),
        start_byte=cast(int, args.start),
        end_byte=cast(int, args.end),
        quote=cast(str, args.quote),
        stance=EvidenceStance(cast(str, args.stance)),
        supersedes_evidence_id=cast(str | None, args.supersedes),
        identity=_identity("cli:evidence-add"),
    )
    return _command_result("evidence", evidence)


def _cmd_evidence_withdraw(args: argparse.Namespace) -> Outcome:
    withdrawal_id = EvidenceService(_database(args)).withdraw_evidence(
        evidence_id=cast(str, args.evidence),
        reason=cast(str, args.reason),
        identity=_identity("cli:evidence-withdraw"),
    )
    return Outcome({"status": "withdrawn", "withdrawal_id": withdrawal_id})


def _cmd_finding_add(args: argparse.Namespace) -> Outcome:
    finding = ResearchService(_database(args)).add_finding(
        mission_id=cast(str, args.mission),
        claim_id=cast(str | None, args.claim),
        statement=cast(str, args.statement),
        statement_kind=StatementKind(cast(str, args.statement_kind)),
        status=FindingStatus(cast(str, args.status)),
        uncertainty=cast(str, args.uncertainty),
        evidence_ids=tuple(cast(list[str], args.evidence)),
        identity=_identity("cli:finding-add"),
    )
    return _command_result("finding", finding)


def _cmd_brief_preview(args: argparse.Namespace) -> Outcome:
    artifacts = SynthesisService(_database(args)).build_brief(cast(str, args.mission))
    return Outcome(
        {
            "export_digest": artifacts.export_digest,
            "markdown_sha256": artifacts.markdown_sha256,
            "json_sha256": artifacts.json_sha256,
            "brief": artifacts.payload,
            "markdown": artifacts.markdown.decode("utf-8"),
        }
    )


def _cmd_brief_export(args: argparse.Namespace) -> Outcome:
    result = SynthesisService(_database(args)).export_brief(
        mission_id=cast(str, args.mission),
        output_dir=cast(Path, args.output_dir),
        identity=_identity("cli:brief-export"),
    )
    return Outcome(
        {
            "export_id": result.export_id,
            "export_digest": result.export_digest,
            "markdown_sha256": result.markdown_sha256,
            "json_sha256": result.json_sha256,
            "files": [result.markdown_path.name, result.json_path.name],
        }
    )


def _cmd_packet_verify(args: argparse.Namespace) -> Outcome:
    document = load_research_packet(cast(Path, args.input))
    return Outcome(packet_verification_report(document))


def _cmd_packet_inspect(args: argparse.Namespace) -> Outcome:
    document = load_research_packet(cast(Path, args.input))
    return Outcome(packet_inspection_report(document))


def _cmd_request_verify(args: argparse.Namespace) -> Outcome:
    document = load_research_request(cast(Path, args.input))
    return Outcome(request_verification_report(document))


def _cmd_request_fulfill(args: argparse.Namespace) -> Outcome:
    document = load_research_request(cast(Path, args.input))
    result = ResearchRequestFulfillmentService(_database(args)).fulfill(
        request=document,
        output_dir=cast(Path, args.output_dir),
    )
    return Outcome(
        {
            "schema_version": result.schema_version,
            "status": result.status,
            "request_digest": result.request_digest,
            "output_artifact": {
                "schema_version": result.output_schema_version,
                "sha256": result.output_sha256,
            },
        }
    )


def _cmd_audit_list(args: argparse.Namespace) -> Outcome:
    database = _database(args)
    with database.read() as connection:
        events = list_audit_events(
            connection,
            mission_id=cast(str | None, args.mission),
            limit=cast(int, args.limit),
            after_sequence=cast(int, args.after_sequence),
        )
    return _command_result("audit_events", events)


def _cmd_doctor(args: argparse.Namespace) -> Outcome:
    report = run_doctor(_database(args), deep=cast(bool, args.deep))
    return Outcome({"doctor": report}, 0 if report.ok else EXIT_OPERATIONAL)


def _cmd_backup(args: argparse.Namespace) -> Outcome:
    OperationsService(_database(args)).backup(
        target=cast(Path, args.output),
        identity=_identity("cli:backup"),
    )
    return Outcome({"status": "backup_created"})


def _cmd_restore(args: argparse.Namespace) -> Outcome:
    database = OperationsService.restore(
        backup=cast(Path, args.backup),
        target=cast(Path, args.db),
        identity=_identity("cli:restore"),
    )
    return Outcome({"status": "restored", "schema_version": database.schema_version()})


def _cmd_assist_finding_candidates(args: argparse.Namespace) -> Outcome:
    selection = resolve_provider_selection(
        provider=cast(str | None, args.provider),
        model=cast(str | None, args.model),
    )
    service = AssistanceService(_database(args))
    preview = service.preview_finding_candidates(
        claim_id=cast(str, args.claim),
        selection=selection,
        max_candidates=cast(int, args.max_candidates),
        max_output_tokens=cast(int, args.max_output_tokens),
    )
    confirmed = cast(bool, args.confirm_external_send)
    expected_digest = cast(str | None, args.expected_request_sha256)
    if not confirmed:
        if expected_digest is not None:
            raise SecurityBoundaryError(
                "assistant_confirmation_invalid",
                "A request digest may only be supplied with explicit external-send confirmation.",
            )
        return Outcome(
            {
                "mode": "preview",
                "network_called": False,
                "credential_environment_variable": (
                    selection.provider.credential_environment_variable
                ),
                "preview": preview,
                "authorization": (
                    "Re-run with --confirm-external-send and the exact "
                    "--expected-request-sha256 value after reviewing context_json."
                ),
            }
        )
    if expected_digest is None:
        raise SecurityBoundaryError(
            "assistant_authorization_required",
            "External send requires the exact request digest from a fresh preview.",
        )

    timeout_seconds = cast(float, args.timeout_seconds)
    service.authorize_finding_candidate_request(
        preview=preview,
        expected_request_sha256=expected_digest,
        timeout_seconds=timeout_seconds,
    )
    from minerva.integrations.ai import candidate_provider

    provider = candidate_provider(selection.provider)
    credential = load_provider_credential(selection.provider)
    result = service.generate_finding_candidates(
        preview=preview,
        expected_request_sha256=expected_digest,
        provider=provider,
        credential=credential,
        timeout_seconds=timeout_seconds,
        identity=_identity("cli:assist-finding-candidates"),
    )
    return Outcome({"mode": "completed", "network_called": True, "result": result})


def _cmd_serve(args: argparse.Namespace) -> Outcome:
    database_path = cast(Path, args.db)
    Database(database_path).schema_version()
    import uvicorn

    from minerva.web.app import create_app

    uvicorn.run(
        create_app(database_path),
        host=cast(str, args.host),
        port=cast(int, args.port),
    )
    return Outcome({"status": "server_stopped"})


def _loopback_host(value: str) -> str:
    if value != "127.0.0.1":
        raise argparse.ArgumentTypeError("serve host must be 127.0.0.1")
    return value


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be an integer") from error
    if not 1 <= port <= 65_535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _add_database(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", required=True, type=Path, help="local Minerva SQLite database")


def _set_handler(parser: argparse.ArgumentParser, handler: CommandHandler) -> None:
    parser.set_defaults(_handler=handler)


def _add_claim_lookup(parser: argparse.ArgumentParser) -> None:
    _add_database(parser)
    parser.add_argument("--claim", required=True)
    _set_handler(parser, _cmd_claim_show)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="minerva",
        description="Local-first, provenance-first research laboratory.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    init_parser = commands.add_parser("init", help="initialize or migrate a database")
    _add_database(init_parser)
    init_parser.add_argument("--refuse-existing", action="store_true")
    _set_handler(init_parser, _cmd_init)

    mission_parser = commands.add_parser("mission", help="manage research missions")
    mission_commands = mission_parser.add_subparsers(dest="mission_command", required=True)
    mission_create = mission_commands.add_parser("create")
    _add_database(mission_create)
    mission_create.add_argument("--title", required=True)
    mission_create.add_argument("--objective", required=True)
    _set_handler(mission_create, _cmd_mission_create)
    mission_list = mission_commands.add_parser("list")
    _add_database(mission_list)
    mission_list.add_argument("--limit", type=int, default=100)
    _set_handler(mission_list, _cmd_mission_list)
    mission_show = mission_commands.add_parser("show")
    _add_database(mission_show)
    mission_show.add_argument("--mission", required=True)
    _set_handler(mission_show, _cmd_mission_show)

    question_parser = commands.add_parser("question", help="manage research questions")
    question_commands = question_parser.add_subparsers(dest="question_command", required=True)
    question_add = question_commands.add_parser("add")
    _add_database(question_add)
    question_add.add_argument("--mission", required=True)
    question_add.add_argument("--text", required=True)
    _set_handler(question_add, _cmd_question_add)

    claim_parser = commands.add_parser("claim", help="manage falsifiable claims")
    claim_commands = claim_parser.add_subparsers(dest="claim_command", required=True)
    claim_add = claim_commands.add_parser("add")
    _add_database(claim_add)
    claim_add.add_argument("--mission", required=True)
    claim_add.add_argument("--question", required=True)
    claim_add.add_argument("--statement", required=True)
    claim_add.add_argument("--falsification-criteria", required=True)
    _set_handler(claim_add, _cmd_claim_add)
    _add_claim_lookup(claim_commands.add_parser("show"))
    _add_claim_lookup(claim_commands.add_parser("ledger"))
    claim_status = claim_commands.add_parser("status")
    _add_database(claim_status)
    claim_status.add_argument("--claim", required=True)
    claim_status.add_argument(
        "--status", required=True, choices=[item.value for item in ClaimStatus]
    )
    claim_status.add_argument("--reason", required=True)
    claim_status.add_argument("--expected-version", required=True, type=int)
    _set_handler(claim_status, _cmd_claim_status)

    source_parser = commands.add_parser("source", help="import and inspect immutable snapshots")
    source_commands = source_parser.add_subparsers(dest="source_command", required=True)
    source_import = source_commands.add_parser("import")
    _add_database(source_import)
    source_import.add_argument("--mission", required=True)
    source_import.add_argument("--root", required=True, type=Path)
    source_import.add_argument("--file", required=True)
    source_import.add_argument("--media-type", default="text/plain")
    source_import.add_argument("--url-metadata")
    _set_handler(source_import, _cmd_source_import)
    source_show = source_commands.add_parser("show")
    _add_database(source_show)
    source_show.add_argument("--snapshot", required=True)
    source_show.add_argument("--metadata-only", action="store_true")
    _set_handler(source_show, _cmd_source_show)

    evidence_parser = commands.add_parser("evidence", help="manage exact evidence cards")
    evidence_commands = evidence_parser.add_subparsers(dest="evidence_command", required=True)
    evidence_add = evidence_commands.add_parser("add")
    _add_database(evidence_add)
    evidence_add.add_argument("--mission", required=True)
    evidence_add.add_argument("--claim", required=True)
    evidence_add.add_argument("--snapshot", required=True)
    evidence_add.add_argument("--start", required=True, type=int)
    evidence_add.add_argument("--end", required=True, type=int)
    evidence_add.add_argument("--quote", required=True)
    evidence_add.add_argument(
        "--stance",
        required=True,
        choices=[item.value for item in EvidenceStance],
    )
    evidence_add.add_argument("--supersedes")
    _set_handler(evidence_add, _cmd_evidence_add)
    evidence_withdraw = evidence_commands.add_parser("withdraw")
    _add_database(evidence_withdraw)
    evidence_withdraw.add_argument("--evidence", required=True)
    evidence_withdraw.add_argument("--reason", required=True)
    _set_handler(evidence_withdraw, _cmd_evidence_withdraw)

    finding_parser = commands.add_parser("finding", help="record labeled findings")
    finding_commands = finding_parser.add_subparsers(dest="finding_command", required=True)
    finding_add = finding_commands.add_parser("add")
    _add_database(finding_add)
    finding_add.add_argument("--mission", required=True)
    finding_add.add_argument("--claim")
    finding_add.add_argument("--statement", required=True)
    finding_add.add_argument(
        "--kind",
        "--statement-kind",
        dest="statement_kind",
        required=True,
        choices=[item.value for item in StatementKind],
    )
    finding_add.add_argument(
        "--status",
        required=True,
        choices=[item.value for item in FindingStatus],
    )
    finding_add.add_argument("--uncertainty", default="")
    finding_add.add_argument("--evidence", action="append", default=[])
    _set_handler(finding_add, _cmd_finding_add)

    brief_parser = commands.add_parser("brief", help="preview or export a research brief")
    brief_commands = brief_parser.add_subparsers(dest="brief_command", required=True)
    brief_preview = brief_commands.add_parser("preview")
    _add_database(brief_preview)
    brief_preview.add_argument("--mission", required=True)
    _set_handler(brief_preview, _cmd_brief_preview)
    brief_export = brief_commands.add_parser("export")
    _add_database(brief_export)
    brief_export.add_argument("--mission", required=True)
    brief_export.add_argument("--output-dir", required=True, type=Path)
    _set_handler(brief_export, _cmd_brief_export)

    packet_parser = commands.add_parser(
        "packet",
        help="verify or inspect a standalone research packet",
    )
    packet_commands = packet_parser.add_subparsers(dest="packet_command", required=True)
    packet_verify = packet_commands.add_parser(
        "verify",
        help="verify one canonical research packet without a database",
    )
    packet_verify.add_argument("--input", required=True, type=Path)
    _set_handler(packet_verify, _cmd_packet_verify)
    packet_inspect = packet_commands.add_parser(
        "inspect",
        help="show bounded metadata for one verified research packet",
    )
    packet_inspect.add_argument("--input", required=True, type=Path)
    _set_handler(packet_inspect, _cmd_packet_inspect)

    request_parser = commands.add_parser(
        "request",
        help="verify or fulfill an offline research request",
    )
    request_commands = request_parser.add_subparsers(dest="request_command", required=True)
    request_verify = request_commands.add_parser(
        "verify",
        help="verify one canonical research request without a database",
    )
    request_verify.add_argument("--input", required=True, type=Path)
    _set_handler(request_verify, _cmd_request_verify)
    request_fulfill = request_commands.add_parser(
        "fulfill",
        help="write a claim-scoped canonical brief without mutating research state",
    )
    _add_database(request_fulfill)
    request_fulfill.add_argument("--input", required=True, type=Path)
    request_fulfill.add_argument("--output-dir", required=True, type=Path)
    _set_handler(request_fulfill, _cmd_request_fulfill)

    audit_parser = commands.add_parser("audit", help="inspect append-only audit events")
    audit_commands = audit_parser.add_subparsers(dest="audit_command", required=True)
    audit_list = audit_commands.add_parser("list")
    _add_database(audit_list)
    audit_list.add_argument("--mission")
    audit_list.add_argument("--limit", type=int, default=100)
    audit_list.add_argument("--after-sequence", type=int, default=0)
    _set_handler(audit_list, _cmd_audit_list)

    doctor_parser = commands.add_parser("doctor", help="validate local database integrity")
    _add_database(doctor_parser)
    doctor_parser.add_argument("--deep", action="store_true")
    _set_handler(doctor_parser, _cmd_doctor)

    backup_parser = commands.add_parser("backup", help="create a non-overwriting backup")
    _add_database(backup_parser)
    backup_parser.add_argument("--output", required=True, type=Path)
    _set_handler(backup_parser, _cmd_backup)

    restore_parser = commands.add_parser("restore", help="restore into a new database")
    _add_database(restore_parser)
    restore_parser.add_argument("--backup", required=True, type=Path)
    _set_handler(restore_parser, _cmd_restore)

    assist_parser = commands.add_parser(
        "assist",
        help="preview or explicitly invoke optional external model assistance",
    )
    assist_commands = assist_parser.add_subparsers(dest="assist_command", required=True)
    finding_candidates = assist_commands.add_parser(
        "finding-candidates",
        help="draft candidate agent inferences from one claim's active evidence",
    )
    _add_database(finding_candidates)
    finding_candidates.add_argument("--claim", required=True)
    finding_candidates.add_argument(
        "--provider",
        choices=[item.value for item in ModelProvider],
        help="provider override; otherwise MINERVA_AI_PROVIDER is required",
    )
    finding_candidates.add_argument(
        "--model",
        help="model override; otherwise MINERVA_AI_MODEL is required",
    )
    finding_candidates.add_argument("--max-candidates", type=int, default=3)
    finding_candidates.add_argument("--max-output-tokens", type=int, default=1_200)
    finding_candidates.add_argument("--timeout-seconds", type=float, default=60.0)
    finding_candidates.add_argument("--confirm-external-send", action="store_true")
    finding_candidates.add_argument("--expected-request-sha256")
    _set_handler(finding_candidates, _cmd_assist_finding_candidates)

    serve_parser = commands.add_parser("serve", help="start the loopback review server")
    _add_database(serve_parser)
    serve_parser.add_argument("--host", type=_loopback_host, default="127.0.0.1")
    serve_parser.add_argument("--port", type=_port, default=8765)
    _set_handler(serve_parser, _cmd_serve)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = cast(CommandHandler, args._handler)
    return run_safely(lambda: handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
