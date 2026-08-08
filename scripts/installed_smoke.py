"""Install Minerva's wheel into a temporary venv and smoke-test it off-checkout."""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path

PROVIDER_EXTRA_CASES = (
    ("ai-openai", ("openai",)),
    ("ai-anthropic", ("anthropic",)),
    ("ai", ("anthropic", "openai")),
)


class SmokeError(RuntimeError):
    """Raised when the installed artifact fails its smoke contract."""


def _run_checked(command: Sequence[str], *, cwd: Path, environment: dict[str, str]) -> str:
    result = subprocess.run(  # noqa: S603 - executable paths are resolved inside the temp venv.
        list(command),
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        if len(detail) > 2_000:
            detail = f"{detail[:2_000]}..."
        raise SmokeError(f"command failed with exit {result.returncode}: {detail}")
    return result.stdout.strip()


def _json_object(document: str, *, label: str) -> dict[str, object]:
    try:
        value = json.loads(document)
    except json.JSONDecodeError as error:
        raise SmokeError(f"{label} returned malformed JSON") from error
    if not isinstance(value, dict):
        raise SmokeError(f"{label} did not return a JSON object")
    return value


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _installed_database_state(
    python: Path,
    database_path: Path,
    *,
    cwd: Path,
    environment: dict[str, str],
) -> tuple[str, str]:
    state_probe = """
import json
import sys
from hashlib import sha256
from pathlib import Path

from minerva.core.db import Database

database = Database(Path(sys.argv[1]))
with database.read() as connection:
    dump = tuple(connection.iterdump())
encoded = json.dumps(
    dump,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
    allow_nan=False,
).encode("utf-8")
print(sha256(encoded).hexdigest())
""".strip()
    dump_sha256 = _run_checked(
        [str(python), "-c", state_probe, str(database_path)],
        cwd=cwd,
        environment=environment,
    )
    return sha256(database_path.read_bytes()).hexdigest(), dump_sha256


def _single_wheel(dist_directory: Path) -> Path:
    resolved_directory = dist_directory.resolve()
    if not resolved_directory.is_dir():
        raise SmokeError(f"distribution directory does not exist: {resolved_directory}")
    wheels = sorted(resolved_directory.glob("*.whl"))
    if len(wheels) != 1:
        raise SmokeError(f"expected exactly one wheel, found {len(wheels)}")
    return wheels[0].resolve(strict=True)


def _uv_tooling(checkout: Path) -> tuple[Path, Path]:
    uv_command = shutil.which("uv")
    if uv_command is None:
        raise SmokeError("uv is required to provision the locked installed-smoke environment")
    lockfile = checkout / "uv.lock"
    if not lockfile.is_file():
        raise SmokeError(f"installed smoke requires the project lockfile: {lockfile}")
    return Path(uv_command).resolve(strict=True), lockfile


def _venv_executable(venv_root: Path, name: str) -> Path:
    bin_directory = venv_root / ("Scripts" if os.name == "nt" else "bin")
    suffix = ".exe" if os.name == "nt" else ""
    executable = bin_directory / f"{name}{suffix}"
    if not executable.is_file():
        raise SmokeError(f"installed environment is missing expected executable {name!r}")
    return executable.resolve()


def _provision_locked_environment(
    *,
    uv_command: Path,
    checkout: Path,
    wheel: Path,
    venv_root: Path,
    cwd: Path,
    environment: dict[str, str],
    extra: str | None,
) -> Path:
    venv.EnvBuilder(with_pip=False, system_site_packages=False, clear=True).create(venv_root)
    python = _venv_executable(venv_root, "python")
    requirements = venv_root.with_name(f"{venv_root.name}-requirements.txt")
    extra_arguments = [] if extra is None else ["--extra", extra]

    _run_checked(
        [
            str(uv_command),
            "export",
            "--project",
            str(checkout),
            "--frozen",
            *extra_arguments,
            "--no-emit-project",
            "--no-hashes",
            "--output-file",
            str(requirements),
            "--offline",
        ],
        cwd=cwd,
        environment=environment,
    )
    if not requirements.is_file() or not requirements.read_text(encoding="utf-8").strip():
        raise SmokeError("uv exported an empty locked dependency set")

    try:
        _run_checked(
            [
                str(uv_command),
                "pip",
                "install",
                "--python",
                str(python),
                "--requirement",
                str(requirements),
                "--offline",
            ],
            cwd=cwd,
            environment=environment,
        )
    except SmokeError as pip_error:
        sync_environment = environment.copy()
        sync_environment["UV_PROJECT_ENVIRONMENT"] = str(venv_root)
        try:
            _run_checked(
                [
                    str(uv_command),
                    "sync",
                    "--project",
                    str(checkout),
                    "--frozen",
                    *extra_arguments,
                    "--no-install-project",
                    "--offline",
                ],
                cwd=cwd,
                environment=sync_environment,
            )
        except SmokeError as sync_error:
            extra_label = "base dependencies" if extra is None else f"extra {extra!r}"
            raise SmokeError(
                f"unable to provision locked {extra_label} offline; "
                f"export install failed: {pip_error}; lock sync failed: {sync_error}"
            ) from sync_error

    _run_checked(
        [
            str(uv_command),
            "pip",
            "install",
            "--python",
            str(python),
            "--no-deps",
            "--offline",
            str(wheel),
        ],
        cwd=cwd,
        environment=environment,
    )
    _run_checked(
        [str(uv_command), "pip", "check", "--python", str(python)],
        cwd=cwd,
        environment=environment,
    )
    return python


def smoke_wheel(dist_directory: Path) -> Path:
    """Install and exercise the sole wheel in *dist_directory* outside the checkout."""
    wheel = _single_wheel(dist_directory)
    checkout = Path(__file__).resolve().parents[1]
    uv_command, _lockfile = _uv_tooling(checkout)

    with tempfile.TemporaryDirectory(prefix="minerva-installed-smoke-") as temporary:
        temporary_root = Path(temporary).resolve()
        smoke_directory = temporary_root / "outside-checkout"
        smoke_directory.mkdir()
        if smoke_directory.is_relative_to(checkout):
            raise SmokeError("temporary smoke directory unexpectedly resides inside the checkout")

        environment = os.environ.copy()
        for variable in (
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_BASE_URL",
            "MINERVA_AI_MODEL",
            "MINERVA_AI_PROVIDER",
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "PYTHONPATH",
        ):
            environment.pop(variable, None)
        environment.update(
            {
                "PYTHONDONTWRITEBYTECODE": "1",
                "UV_NO_PROGRESS": "1",
            }
        )

        venv_root = temporary_root / "venv-base"
        python = _provision_locked_environment(
            uv_command=uv_command,
            checkout=checkout,
            wheel=wheel,
            venv_root=venv_root,
            cwd=smoke_directory,
            environment=environment,
            extra=None,
        )

        probe = (
            "from importlib.metadata import version; "
            "from pathlib import Path; "
            "import minerva; "
            "from minerva.lens import LensService; "
            "from minerva.lineage import ClaimLineageService; "
            "from minerva.review import ClaimReviewService; "
            "from minerva.research_queue import MissionResearchQueueService; "
            "print(version('minerva-research')); "
            "print(Path(minerva.__file__).resolve())"
        )
        probe_output = _run_checked(
            [str(python), "-c", probe], cwd=smoke_directory, environment=environment
        )
        output_lines = probe_output.splitlines()
        if len(output_lines) != 2 or not output_lines[0]:
            raise SmokeError("installed package probe returned an unexpected result")
        imported_path = Path(output_lines[1]).resolve()
        if not imported_path.is_relative_to(venv_root):
            raise SmokeError("package import did not resolve to the temporary wheel installation")
        sdk_probe = """
from importlib.util import find_spec

unexpected = [name for name in ("anthropic", "openai") if find_spec(name) is not None]
if unexpected:
    raise RuntimeError(f"provider SDKs leaked into base installation: {unexpected}")
""".strip()
        _run_checked([str(python), "-c", sdk_probe], cwd=smoke_directory, environment=environment)

        minerva_command = _venv_executable(venv_root, "minerva")
        demo_command = _venv_executable(venv_root, "minerva-demo")
        for command in (minerva_command, demo_command):
            _run_checked([str(command), "--help"], cwd=smoke_directory, environment=environment)

        demo_database = smoke_directory / "demo.db"
        export_directory = smoke_directory / "demo-export"
        demo = _json_object(
            _run_checked(
                [
                    str(demo_command),
                    "--db",
                    str(demo_database),
                    "--export-dir",
                    str(export_directory),
                ],
                cwd=smoke_directory,
                environment=environment,
            ),
            label="installed demo",
        )
        if demo.get("status") != "demo_created":
            raise SmokeError("installed demo did not report successful creation")
        mission_id = demo.get("mission_id")
        if not isinstance(mission_id, str):
            raise SmokeError("installed demo did not return a mission identifier")

        lens_arguments = [
            str(minerva_command),
            "lens",
            "search",
            "--db",
            str(demo_database),
            "--mission",
            mission_id,
            "--query",
            "runtime",
            "--limit",
            "3",
        ]
        lens_output = _run_checked(
            lens_arguments,
            cwd=smoke_directory,
            environment=environment,
        )
        if lens_output != _run_checked(
            lens_arguments,
            cwd=smoke_directory,
            environment=environment,
        ):
            raise SmokeError("installed Lens search is not byte-deterministic")
        lens_envelope = _json_object(lens_output, label="installed Lens search")
        lens = lens_envelope.get("lens")
        if not isinstance(lens, dict):
            raise SmokeError("installed Lens search omitted its retrieval receipt")
        candidates = lens.get("candidates")
        semantic_boundary = lens.get("semantic_boundary")
        if (
            lens.get("schema_version") != "minerva.lens-search.v1"
            or lens.get("kind") != "candidate_context_search"
            or lens.get("mission_id") != mission_id
            or lens.get("algorithm") != "bounded-unicode-line-lexical"
            or not isinstance(lens.get("query_sha256"), str)
            or len(lens["query_sha256"]) != 64
            or not isinstance(lens.get("snapshot_set_sha256"), str)
            or len(lens["snapshot_set_sha256"]) != 64
            or not isinstance(lens.get("retrieval_receipt_sha256"), str)
            or len(lens["retrieval_receipt_sha256"]) != 64
            or not isinstance(candidates, list)
            or not candidates
            or not isinstance(semantic_boundary, dict)
            or semantic_boundary.get("candidate_context_only") is not True
            or semantic_boundary.get("creates_evidence") is not False
            or semantic_boundary.get("persists_agent_inference") is not False
        ):
            raise SmokeError("installed Lens retrieval receipt is invalid")
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            raise SmokeError("installed Lens candidate context is invalid")
        snapshot_id = candidate.get("snapshot_id")
        quote = candidate.get("quote")
        start_byte = candidate.get("start_byte")
        end_byte = candidate.get("end_byte")
        quote_utf8_base64 = candidate.get("quote_utf8_base64")
        if (
            candidate.get("kind") != "candidate_context"
            or candidate.get("mission_id") != mission_id
            or not isinstance(snapshot_id, str)
            or not isinstance(quote, str)
            or not isinstance(start_byte, int)
            or not isinstance(end_byte, int)
            or not isinstance(quote_utf8_base64, str)
        ):
            raise SmokeError("installed Lens candidate provenance is incomplete")
        shown = _json_object(
            _run_checked(
                [
                    str(minerva_command),
                    "source",
                    "show",
                    "--db",
                    str(demo_database),
                    "--snapshot",
                    snapshot_id,
                ],
                cwd=smoke_directory,
                environment=environment,
            ),
            label="installed Lens snapshot round trip",
        )
        source_text = shown.get("text")
        if (
            not isinstance(source_text, str)
            or source_text.encode()[start_byte:end_byte] != quote.encode()
            or base64.b64decode(quote_utf8_base64, validate=True) != quote.encode()
        ):
            raise SmokeError("installed Lens byte span does not round trip")
        claim_ids = demo.get("claim_ids")
        if not isinstance(claim_ids, list) or not claim_ids:
            raise SmokeError("installed demo did not return claim identifiers")
        demo_claim_ids = tuple(item for item in claim_ids if isinstance(item, str))
        if len(demo_claim_ids) != len(claim_ids):
            raise SmokeError("installed demo returned an invalid claim identifier")
        claim_id = demo_claim_ids[0]

        queue_state_before = _installed_database_state(
            python,
            demo_database,
            cwd=smoke_directory,
            environment=environment,
        )
        mission_queue_arguments = [
            str(minerva_command),
            "mission",
            "queue",
            "--db",
            str(demo_database),
            "--mission",
            mission_id,
        ]
        mission_queue_output = _run_checked(
            mission_queue_arguments,
            cwd=smoke_directory,
            environment=environment,
        )
        if mission_queue_output != _run_checked(
            mission_queue_arguments,
            cwd=smoke_directory,
            environment=environment,
        ):
            raise SmokeError("installed Mission Research Queue is not byte-deterministic")
        queue_state_after = _installed_database_state(
            python,
            demo_database,
            cwd=smoke_directory,
            environment=environment,
        )
        if queue_state_before != queue_state_after:
            raise SmokeError("installed Mission Research Queue changed database state")

        mission_queue_envelope = _json_object(
            mission_queue_output,
            label="installed Mission Research Queue",
        )
        mission_queue = mission_queue_envelope.get("mission_research_queue")
        if not isinstance(mission_queue, dict):
            raise SmokeError("installed Mission Research Queue omitted its receipt")
        reviewed_claims = mission_queue.get("reviewed_claims")
        queue_items = mission_queue.get("items")
        reason_catalog = mission_queue.get("reason_catalog")
        reason_counts = mission_queue.get("reason_counts")
        queue_work = mission_queue.get("work")
        queue_boundary = mission_queue.get("semantic_boundary")
        queue_receipt = mission_queue.get("queue_receipt_sha256")
        if (
            mission_queue.get("schema_version") != "minerva.mission-research-queue.v1"
            or mission_queue.get("kind") != "mission_research_queue"
            or mission_queue.get("algorithm") != "claim-review-cue-aggregation"
            or mission_queue.get("algorithm_version") != "1"
            or mission_queue.get("scope") != "mission_claim_review_cues_v1"
            or mission_queue.get("completion_policy") != "complete_or_refuse"
            or mission_queue.get("complete") is not True
            or mission_queue.get("truncated") is not False
            or mission_queue.get("mission_id") != mission_id
            or mission_queue.get("sequence_semantics") != "deterministic_display_order_not_priority"
            or mission_queue.get("ordering")
            != [
                "reviewed_claims:claim_created_at_ascending_then_claim_id_ascending",
                "items:reviewed_claim_order_then_claim_review_cue_catalog_order",
            ]
            or not isinstance(reviewed_claims, list)
            or not isinstance(queue_items, list)
            or not isinstance(reason_catalog, list)
            or not isinstance(reason_counts, list)
            or not isinstance(queue_work, dict)
            or not isinstance(queue_boundary, dict)
            or not isinstance(queue_receipt, str)
            or len(queue_receipt) != 64
            or not isinstance(mission_queue.get("claim_set_sha256"), str)
            or len(mission_queue["claim_set_sha256"]) != 64
            or not isinstance(mission_queue.get("claim_review_set_sha256"), str)
            or len(mission_queue["claim_review_set_sha256"]) != 64
            or not isinstance(mission_queue.get("item_set_sha256"), str)
            or len(mission_queue["item_set_sha256"]) != 64
        ):
            raise SmokeError("installed Mission Research Queue receipt is invalid")

        reviewed_claim_documents = [item for item in reviewed_claims if isinstance(item, dict)]
        queue_item_documents = [item for item in queue_items if isinstance(item, dict)]
        reason_documents = [item for item in reason_catalog if isinstance(item, dict)]
        reason_count_documents = [item for item in reason_counts if isinstance(item, dict)]
        if (
            len(reviewed_claim_documents) != len(reviewed_claims)
            or len(queue_item_documents) != len(queue_items)
            or len(reason_documents) != len(reason_catalog)
            or len(reason_count_documents) != len(reason_counts)
        ):
            raise SmokeError("installed Mission Research Queue contains an invalid row")

        catalog_position_by_code: dict[str, int] = {}
        catalog_codes: list[str] = []
        for expected_position, reason in enumerate(reason_documents, start=1):
            code = reason.get("code")
            if (
                reason.get("catalog_position") != expected_position
                or not isinstance(code, str)
                or code in catalog_position_by_code
                or not isinstance(reason.get("category"), str)
                or not isinstance(reason.get("explanation"), str)
            ):
                raise SmokeError("installed Mission Research Queue reason catalog is invalid")
            catalog_position_by_code[code] = expected_position
            catalog_codes.append(code)

        summary_by_claim: dict[str, dict[object, object]] = {}
        summary_order: dict[str, int] = {}
        claim_sort_keys: list[tuple[str, str]] = []
        for expected_sequence, summary in enumerate(reviewed_claim_documents, start=1):
            queue_claim_id = summary.get("claim_id")
            claim_created_at = summary.get("claim_created_at")
            if (
                summary.get("sequence") != expected_sequence
                or not isinstance(queue_claim_id, str)
                or queue_claim_id in summary_by_claim
                or not isinstance(summary.get("question_id"), str)
                or not isinstance(summary.get("claim_statement"), str)
                or not isinstance(claim_created_at, str)
                or not isinstance(summary.get("reason_codes"), list)
                or not isinstance(summary.get("item_count"), int)
                or not isinstance(summary.get("review_receipt_sha256"), str)
                or len(summary["review_receipt_sha256"]) != 64
            ):
                raise SmokeError("installed Mission Research Queue claim summary is invalid")
            summary_by_claim[queue_claim_id] = summary
            summary_order[queue_claim_id] = expected_sequence
            claim_sort_keys.append((claim_created_at, queue_claim_id))
        if (
            set(summary_by_claim) != set(demo_claim_ids)
            or len(summary_by_claim) != len(demo_claim_ids)
            or claim_sort_keys != sorted(claim_sort_keys)
        ):
            raise SmokeError("installed Mission Research Queue claim coverage is invalid")

        items_by_claim: dict[str, list[dict[object, object]]] = {
            queue_claim_id: [] for queue_claim_id in summary_by_claim
        }
        item_order_keys: list[tuple[int, int]] = []
        seen_item_labels: set[tuple[str, str]] = set()
        for expected_sequence, item in enumerate(queue_item_documents, start=1):
            queue_claim_id = item.get("claim_id")
            reason_code = item.get("reason_code")
            record_ids = item.get("record_ids")
            if (
                item.get("sequence") != expected_sequence
                or item.get("kind") != "structural_review_cue"
                or not isinstance(queue_claim_id, str)
                or queue_claim_id not in summary_by_claim
                or not isinstance(reason_code, str)
                or reason_code not in catalog_position_by_code
                or (queue_claim_id, reason_code) in seen_item_labels
                or not isinstance(item.get("question_id"), str)
                or not isinstance(item.get("reason_category"), str)
                or not isinstance(item.get("explanation"), str)
                or not isinstance(record_ids, list)
                or not all(isinstance(record_id, str) for record_id in record_ids)
                or not isinstance(item.get("source_review_receipt_sha256"), str)
                or len(item["source_review_receipt_sha256"]) != 64
            ):
                raise SmokeError("installed Mission Research Queue item is invalid")
            seen_item_labels.add((queue_claim_id, reason_code))
            items_by_claim[queue_claim_id].append(item)
            item_order_keys.append(
                (summary_order[queue_claim_id], catalog_position_by_code[reason_code])
            )
        if item_order_keys != sorted(item_order_keys):
            raise SmokeError("installed Mission Research Queue item order is invalid")

        for queue_claim_id, summary in summary_by_claim.items():
            claim_items = items_by_claim[queue_claim_id]
            projected_codes = [item["reason_code"] for item in claim_items]
            if (
                summary.get("reason_codes") != projected_codes
                or summary.get("item_count") != len(claim_items)
                or not projected_codes
                or any(
                    item.get("source_review_receipt_sha256") != summary.get("review_receipt_sha256")
                    for item in claim_items
                )
            ):
                raise SmokeError("installed Mission Research Queue cue projection is invalid")

        item_code_counts = {
            code: sum(item.get("reason_code") == code for item in queue_item_documents)
            for code in catalog_codes
        }
        if [item.get("code") for item in reason_count_documents] != catalog_codes or any(
            not isinstance(item.get("code"), str)
            or item.get("count") != item_code_counts[item["code"]]
            for item in reason_count_documents
        ):
            raise SmokeError("installed Mission Research Queue reason counts are invalid")
        if (
            queue_work.get("reviewed_claim_count") != len(reviewed_claim_documents)
            or queue_work.get("item_count") != len(queue_item_documents)
            or not isinstance(queue_work.get("evidence_card_count"), int)
            or queue_work["evidence_card_count"] < 0
            or not isinstance(queue_work.get("distinct_evidence_quote_bytes"), int)
            or queue_work["distinct_evidence_quote_bytes"] < 0
            or not isinstance(mission_queue.get("bounds"), dict)
            or queue_work["distinct_evidence_quote_bytes"]
            > mission_queue["bounds"].get("max_distinct_evidence_quote_bytes", -1)
            or queue_work.get("canonical_output_bytes") != len(_canonical_bytes(mission_queue))
        ):
            raise SmokeError("installed Mission Research Queue work receipt is invalid")

        common_frame = {
            "algorithm": "claim-review-cue-aggregation",
            "algorithm_version": "1",
            "scope": "mission_claim_review_cues_v1",
            "mission_id": mission_id,
        }
        claim_frame = {
            "schema_version": "minerva.mission-research-queue-claims.v1",
            **common_frame,
            "claims": [
                {
                    "sequence": summary["sequence"],
                    "claim_id": summary["claim_id"],
                    "question_id": summary["question_id"],
                    "claim_statement": summary["claim_statement"],
                    "recorded_status": summary["recorded_status"],
                    "recorded_status_version": summary["recorded_status_version"],
                    "claim_created_at": summary["claim_created_at"],
                }
                for summary in reviewed_claim_documents
            ],
        }
        review_frame = {
            "schema_version": "minerva.mission-research-queue-claim-reviews.v1",
            **common_frame,
            "claim_reviews": [
                {
                    "sequence": summary["sequence"],
                    "claim_id": summary["claim_id"],
                    "reason_codes": summary["reason_codes"],
                    "item_count": summary["item_count"],
                    "review_receipt_sha256": summary["review_receipt_sha256"],
                }
                for summary in reviewed_claim_documents
            ],
        }
        item_frame = {
            "schema_version": "minerva.mission-research-queue-items.v1",
            **common_frame,
            "items": queue_item_documents,
        }
        if (
            mission_queue.get("claim_set_sha256")
            != sha256(_canonical_bytes(claim_frame)).hexdigest()
            or mission_queue.get("claim_review_set_sha256")
            != sha256(_canonical_bytes(review_frame)).hexdigest()
            or mission_queue.get("item_set_sha256")
            != sha256(_canonical_bytes(item_frame)).hexdigest()
        ):
            raise SmokeError("installed Mission Research Queue subreceipt digest is invalid")
        queue_receipt_payload = dict(mission_queue)
        queue_receipt_payload.pop("queue_receipt_sha256")
        if queue_receipt != sha256(_canonical_bytes(queue_receipt_payload)).hexdigest():
            raise SmokeError("installed Mission Research Queue receipt digest does not verify")

        if (
            queue_boundary.get("read_only") is not True
            or queue_boundary.get("structural_review_index_only") is not True
            or queue_boundary.get("current_claim_review_taxonomy_guarantees_a_cue") is not True
            or queue_boundary.get("item_presence_means_action_required") is not False
            or queue_boundary.get("item_presence_means_open_or_unresolved") is not False
            or queue_boundary.get("item_order_is_priority_or_severity") is not False
            or queue_boundary.get("assigns_work") is not False
            or queue_boundary.get("records_completion_or_deferral") is not False
            or queue_boundary.get("determines_truth") is not False
            or queue_boundary.get("calculates_confidence") is not False
            or queue_boundary.get("recommends_or_alters_claim_status") is not False
            or queue_boundary.get("creates_or_changes_research_state") is not False
            or queue_boundary.get("writes_audit_event_or_export") is not False
            or queue_boundary.get("modifies_source_or_snapshot_bytes") is not False
            or queue_boundary.get("invokes_claim_lineage") is not False
            or queue_boundary.get("invokes_model_provider") is not False
            or queue_boundary.get("invokes_network") is not False
            or queue_boundary.get("exposes_external_agent_protocol") is not False
        ):
            raise SmokeError("installed Mission Research Queue semantic boundary is invalid")

        claim_review_arguments = [
            str(minerva_command),
            "claim",
            "review",
            "--db",
            str(demo_database),
            "--mission",
            mission_id,
            "--claim",
            claim_id,
        ]
        claim_review_output = _run_checked(
            claim_review_arguments,
            cwd=smoke_directory,
            environment=environment,
        )
        if claim_review_output != _run_checked(
            claim_review_arguments,
            cwd=smoke_directory,
            environment=environment,
        ):
            raise SmokeError("installed Claim Review is not byte-deterministic")
        claim_review_envelope = _json_object(
            claim_review_output,
            label="installed Claim Review",
        )
        claim_review = claim_review_envelope.get("claim_review")
        if not isinstance(claim_review, dict):
            raise SmokeError("installed Claim Review omitted its review receipt")
        review_receipt = claim_review.get("review_receipt_sha256")
        review_boundary = claim_review.get("semantic_boundary")
        if (
            claim_review.get("schema_version") != "minerva.claim-review.v1"
            or claim_review.get("kind") != "evidence_gap_and_retraction_impact"
            or claim_review.get("algorithm") != "structural-ledger-review"
            or claim_review.get("algorithm_version") != "1"
            or claim_review.get("completion_policy") != "complete_or_refuse"
            or claim_review.get("complete") is not True
            or claim_review.get("truncated") is not False
            or claim_review.get("mission_id") != mission_id
            or claim_review.get("claim_id") != claim_id
            or not isinstance(review_receipt, str)
            or len(review_receipt) != 64
            or not isinstance(review_boundary, dict)
            or review_boundary.get("read_only") is not True
            or review_boundary.get("structural_observations_only") is not True
            or review_boundary.get("determines_truth") is not False
            or review_boundary.get("calculates_confidence") is not False
            or review_boundary.get("alters_claim_status") is not False
            or review_boundary.get("creates_or_withdraws_evidence") is not False
            or review_boundary.get("writes_audit_event") is not False
            or review_boundary.get("invokes_model_provider") is not False
            or review_boundary.get("invokes_network") is not False
        ):
            raise SmokeError("installed Claim Review receipt or semantic boundary is invalid")
        review_receipt_payload = dict(claim_review)
        review_receipt_payload.pop("review_receipt_sha256")
        expected_review_receipt = sha256(
            json.dumps(
                review_receipt_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        if review_receipt != expected_review_receipt:
            raise SmokeError("installed Claim Review receipt digest does not verify")

        claim_lineage_arguments = [
            str(minerva_command),
            "claim",
            "lineage",
            "--db",
            str(demo_database),
            "--mission",
            mission_id,
            "--claim",
            claim_id,
        ]
        claim_lineage_output = _run_checked(
            claim_lineage_arguments,
            cwd=smoke_directory,
            environment=environment,
        )
        if claim_lineage_output != _run_checked(
            claim_lineage_arguments,
            cwd=smoke_directory,
            environment=environment,
        ):
            raise SmokeError("installed Claim Lineage is not byte-deterministic")
        claim_lineage_envelope = _json_object(
            claim_lineage_output,
            label="installed Claim Lineage",
        )
        claim_lineage = claim_lineage_envelope.get("claim_lineage")
        if not isinstance(claim_lineage, dict):
            raise SmokeError("installed Claim Lineage omitted its lineage receipt")
        lineage_nodes = claim_lineage.get("nodes")
        lineage_edges = claim_lineage.get("edges")
        lineage_receipt = claim_lineage.get("lineage_receipt_sha256")
        lineage_boundary = claim_lineage.get("semantic_boundary")
        if (
            claim_lineage.get("schema_version") != "minerva.claim-lineage.v1"
            or claim_lineage.get("kind") != "claim_lineage_graph"
            or claim_lineage.get("algorithm") != "structural-ledger-lineage"
            or claim_lineage.get("algorithm_version") != "1"
            or claim_lineage.get("scope") != "claim_owned_closure_v1"
            or claim_lineage.get("completion_policy") != "complete_or_refuse"
            or claim_lineage.get("complete") is not True
            or claim_lineage.get("truncated") is not False
            or claim_lineage.get("mission_id") != mission_id
            or claim_lineage.get("claim_id") != claim_id
            or claim_lineage.get("root_node_id") != claim_id
            or not isinstance(lineage_receipt, str)
            or len(lineage_receipt) != 64
            or not isinstance(claim_lineage.get("node_set_sha256"), str)
            or len(claim_lineage["node_set_sha256"]) != 64
            or not isinstance(claim_lineage.get("edge_set_sha256"), str)
            or len(claim_lineage["edge_set_sha256"]) != 64
            or not isinstance(claim_lineage.get("snapshot_set_sha256"), str)
            or len(claim_lineage["snapshot_set_sha256"]) != 64
            or not isinstance(lineage_nodes, list)
            or not lineage_nodes
            or not isinstance(lineage_edges, list)
            or not lineage_edges
            or not isinstance(lineage_boundary, dict)
            or lineage_boundary.get("read_only") is not True
            or lineage_boundary.get("structural_topology_only") is not True
            or lineage_boundary.get("complete_claim_owned_scope") is not True
            or lineage_boundary.get("determines_truth") is not False
            or lineage_boundary.get("calculates_confidence") is not False
            or lineage_boundary.get("recommends_or_alters_claim_status") is not False
            or lineage_boundary.get("creates_or_changes_research_state") is not False
            or lineage_boundary.get("writes_audit_event_or_export") is not False
            or lineage_boundary.get("modifies_source_or_snapshot_bytes") is not False
            or lineage_boundary.get("invokes_model_provider") is not False
            or lineage_boundary.get("invokes_network") is not False
        ):
            raise SmokeError("installed Claim Lineage receipt or semantic boundary is invalid")
        lineage_receipt_payload = dict(claim_lineage)
        lineage_receipt_payload.pop("lineage_receipt_sha256")
        expected_lineage_receipt = sha256(
            json.dumps(
                lineage_receipt_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        if lineage_receipt != expected_lineage_receipt:
            raise SmokeError("installed Claim Lineage receipt digest does not verify")

        if not all(isinstance(node, dict) for node in lineage_nodes):
            raise SmokeError("installed Claim Lineage contains an invalid node")
        lineage_node_ids = [node.get("node_id") for node in lineage_nodes]
        if (
            any(not isinstance(node_id, str) for node_id in lineage_node_ids)
            or len(set(lineage_node_ids)) != len(lineage_node_ids)
            or claim_id not in lineage_node_ids
        ):
            raise SmokeError("installed Claim Lineage node identities are invalid")
        if not all(isinstance(edge, dict) for edge in lineage_edges):
            raise SmokeError("installed Claim Lineage contains an invalid edge")
        lineage_node_id_set = set(lineage_node_ids)
        if any(
            not isinstance(edge.get("relation"), str)
            or edge.get("source_node_id") not in lineage_node_id_set
            or edge.get("target_node_id") not in lineage_node_id_set
            for edge in lineage_edges
        ):
            raise SmokeError("installed Claim Lineage contains a dangling graph edge")

        lineage_evidence_nodes = [node for node in lineage_nodes if node.get("kind") == "evidence"]
        if not lineage_evidence_nodes:
            raise SmokeError("installed Claim Lineage omitted target-claim evidence")
        lineage_evidence = lineage_evidence_nodes[0].get("payload")
        if not isinstance(lineage_evidence, dict):
            raise SmokeError("installed Claim Lineage evidence payload is invalid")
        lineage_snapshot_id = lineage_evidence.get("snapshot_id")
        lineage_start = lineage_evidence.get("start_byte")
        lineage_end = lineage_evidence.get("end_byte")
        lineage_quote = lineage_evidence.get("quote")
        lineage_quote_base64 = lineage_evidence.get("quote_utf8_base64")
        if (
            not isinstance(lineage_snapshot_id, str)
            or not isinstance(lineage_start, int)
            or not isinstance(lineage_end, int)
            or lineage_start < 0
            or lineage_end <= lineage_start
            or not isinstance(lineage_quote, str)
            or not isinstance(lineage_quote_base64, str)
        ):
            raise SmokeError("installed Claim Lineage evidence provenance is incomplete")
        lineage_source = _json_object(
            _run_checked(
                [
                    str(minerva_command),
                    "source",
                    "show",
                    "--db",
                    str(demo_database),
                    "--snapshot",
                    lineage_snapshot_id,
                ],
                cwd=smoke_directory,
                environment=environment,
            ),
            label="installed Claim Lineage snapshot round trip",
        )
        lineage_source_text = lineage_source.get("text")
        lineage_quote_bytes = lineage_quote.encode("utf-8")
        if (
            not isinstance(lineage_source_text, str)
            or lineage_source_text.encode("utf-8")[lineage_start:lineage_end] != lineage_quote_bytes
            or base64.b64decode(lineage_quote_base64, validate=True) != lineage_quote_bytes
            or lineage_evidence.get("quote_byte_length") != len(lineage_quote_bytes)
            or lineage_evidence.get("quote_sha256") != sha256(lineage_quote_bytes).hexdigest()
        ):
            raise SmokeError("installed Claim Lineage evidence byte span does not round trip")

        evidence_ids = demo.get("evidence_ids")
        if (
            not isinstance(evidence_ids, list)
            or len(evidence_ids) < 2
            or not all(isinstance(item, str) for item in evidence_ids[:2])
        ):
            raise SmokeError("installed demo did not return target-claim evidence identifiers")
        active_citation_ids = sorted(evidence_ids[:2])
        assistant_preview = _json_object(
            _run_checked(
                [
                    str(minerva_command),
                    "assist",
                    "finding-candidates",
                    "--db",
                    str(demo_database),
                    "--claim",
                    claim_id,
                    "--provider",
                    "openai",
                    "--model",
                    "test-model-1",
                ],
                cwd=smoke_directory,
                environment=environment,
            ),
            label="installed assistant preview",
        )
        if assistant_preview.get("mode") != "preview":
            raise SmokeError("installed assistant did not return preview mode")
        if assistant_preview.get("network_called") is not False:
            raise SmokeError("installed assistant preview reported a network call")
        preview_document = assistant_preview.get("preview")
        if not isinstance(preview_document, dict):
            raise SmokeError("installed assistant preview omitted its request document")
        request_sha256 = preview_document.get("request_sha256")
        if not isinstance(request_sha256, str) or len(request_sha256) != 64:
            raise SmokeError("installed assistant preview omitted its request digest")

        preview = _json_object(
            _run_checked(
                [
                    str(minerva_command),
                    "brief",
                    "preview",
                    "--db",
                    str(demo_database),
                    "--mission",
                    mission_id,
                ],
                cwd=smoke_directory,
                environment=environment,
            ),
            label="installed brief preview",
        )
        markdown_path = export_directory / "research-brief.md"
        json_path = export_directory / "research-brief.json"
        markdown = markdown_path.read_bytes()
        json_bytes = json_path.read_bytes()
        brief = _json_object(json_bytes.decode("utf-8", errors="strict"), label="brief export")
        if brief.get("export_digest") != demo.get("export_digest"):
            raise SmokeError("installed demo and JSON export digests disagree")
        if preview.get("markdown_sha256") != sha256(markdown).hexdigest():
            raise SmokeError("installed Markdown export digest is invalid")
        if preview.get("json_sha256") != sha256(json_bytes).hexdigest():
            raise SmokeError("installed JSON export digest is invalid")
        if preview.get("export_digest") != demo.get("export_digest"):
            raise SmokeError("installed preview and demo export digests disagree")

        packet_verify_output = _run_checked(
            [
                str(minerva_command),
                "packet",
                "verify",
                "--input",
                str(json_path),
            ],
            cwd=smoke_directory,
            environment=environment,
        )
        packet_verify = _json_object(packet_verify_output, label="installed packet verify")
        if (
            packet_verify.get("status") != "verified"
            or packet_verify.get("schema_version") != "minerva.research-brief.v2"
            or packet_verify.get("export_digest") != demo.get("export_digest")
        ):
            raise SmokeError("installed packet verification returned an invalid result")

        packet_inspect_output = _run_checked(
            [
                str(minerva_command),
                "packet",
                "inspect",
                "--input",
                str(json_path),
            ],
            cwd=smoke_directory,
            environment=environment,
        )
        packet_inspect = _json_object(packet_inspect_output, label="installed packet inspect")
        expected_counts = {
            "missions": 1,
            "questions": 1,
            "claims": 2,
            "citations": 4,
            "active_citations": 4,
            "withdrawn_citations": 0,
            "evidence_stances": {
                "supports": 2,
                "opposes": 2,
                "context": 0,
                "inconclusive": 0,
            },
            "findings": 1,
            "assumptions": 1,
            "unresolved_questions": 1,
            "uncertainties": 3,
            "sources": 4,
        }
        ownership = packet_inspect.get("ownership")
        integrity = packet_inspect.get("integrity")
        if (
            packet_inspect.get("status") != "verified"
            or packet_inspect.get("export_digest") != demo.get("export_digest")
            or packet_inspect.get("counts") != expected_counts
            or not isinstance(ownership, dict)
            or ownership.get("researches") is not True
            or any(
                ownership.get(capability) is not False
                for capability in ("executes", "approves", "orchestrates", "publishes")
            )
            or not isinstance(integrity, dict)
            or integrity.get("digest_verified") is not True
            or integrity.get("authenticity") != "not_established"
            or len(packet_inspect_output) >= 2_000
        ):
            raise SmokeError("installed packet inspection returned an invalid result")

        request_path = smoke_directory / "research-request.json"
        request_builder = """
import sys
from pathlib import Path

from minerva.integrations.research_request import (
    build_research_request,
    serialize_research_request,
)

document = build_research_request(
    mission_id=sys.argv[2],
    claim_id=sys.argv[3],
    expected_active_citation_ids=tuple(sys.argv[4:]),
)
Path(sys.argv[1]).write_bytes(serialize_research_request(document))
""".strip()
        _run_checked(
            [
                str(python),
                "-c",
                request_builder,
                str(request_path),
                mission_id,
                claim_id,
                *active_citation_ids,
            ],
            cwd=smoke_directory,
            environment=environment,
        )
        request_verify = _json_object(
            _run_checked(
                [str(minerva_command), "request", "verify", "--input", str(request_path)],
                cwd=smoke_directory,
                environment=environment,
            ),
            label="installed request verify",
        )
        selection = request_verify.get("evidence_selection")
        if (
            request_verify.get("status") != "verified"
            or request_verify.get("schema_version") != "minerva.research-request.v1"
            or request_verify.get("requested_output_schema") != "minerva.research-brief.v2"
            or not isinstance(request_verify.get("request_digest"), str)
            or not isinstance(selection, dict)
            or selection.get("policy") != "complete_claim_ledger"
            or selection.get("expected_active_citation_count") != 2
        ):
            raise SmokeError("installed request verification returned an invalid result")

        request_output = smoke_directory / "request-result"
        fulfillment = _json_object(
            _run_checked(
                [
                    str(minerva_command),
                    "request",
                    "fulfill",
                    "--db",
                    str(demo_database),
                    "--input",
                    str(request_path),
                    "--output-dir",
                    str(request_output),
                ],
                cwd=smoke_directory,
                environment=environment,
            ),
            label="installed request fulfill",
        )
        produced_names = sorted(path.name for path in request_output.iterdir())
        if produced_names != ["research-brief.json", "research-result.json"]:
            raise SmokeError("installed request fulfillment wrote unexpected files")
        fulfilled_brief_path = request_output / "research-brief.json"
        fulfilled_brief_bytes = fulfilled_brief_path.read_bytes()
        result_manifest = _json_object(
            (request_output / "research-result.json").read_text(encoding="utf-8"),
            label="installed research result",
        )
        if fulfillment != result_manifest:
            raise SmokeError("installed fulfillment output and result manifest disagree")
        output_artifact = result_manifest.get("output_artifact")
        if (
            result_manifest.get("schema_version") != "minerva.research-result.v1"
            or result_manifest.get("status") != "fulfilled"
            or result_manifest.get("request_digest") != request_verify.get("request_digest")
            or not isinstance(output_artifact, dict)
            or output_artifact.get("schema_version") != "minerva.research-brief.v2"
            or output_artifact.get("sha256") != sha256(fulfilled_brief_bytes).hexdigest()
        ):
            raise SmokeError("installed research result manifest is invalid")
        fulfilled_packet = _json_object(
            _run_checked(
                [
                    str(minerva_command),
                    "packet",
                    "verify",
                    "--input",
                    str(fulfilled_brief_path),
                ],
                cwd=smoke_directory,
                environment=environment,
            ),
            label="installed fulfilled packet verify",
        )
        if (
            fulfilled_packet.get("status") != "verified"
            or fulfilled_packet.get("schema_version") != "minerva.research-brief.v2"
        ):
            raise SmokeError("installed fulfilled packet verification failed")

        doctor = _json_object(
            _run_checked(
                [
                    str(minerva_command),
                    "doctor",
                    "--db",
                    str(demo_database),
                    "--deep",
                ],
                cwd=smoke_directory,
                environment=environment,
            ),
            label="installed doctor",
        )
        doctor_report = doctor.get("doctor")
        if not isinstance(doctor_report, dict) or doctor_report.get("ok") is not True:
            raise SmokeError("installed deep doctor did not report a healthy database")

        web_probe = """
import asyncio
import json
import sys
from pathlib import Path

from minerva.web.app import create_app

async def get(app, path):
    messages = []
    request_delivered = False

    async def receive():
        nonlocal request_delivered
        if request_delivered:
            return {"type": "http.disconnect"}
        request_delivered = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"testserver")],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        },
        receive,
        send,
    )
    status = next(
        message["status"] for message in messages if message["type"] == "http.response.start"
    )
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return status, body

database = Path(sys.argv[1])
mission_id = sys.argv[2]
claim_id = sys.argv[3]
routes = (
    "/readyz",
    "/missions",
    f"/missions/{mission_id}",
    f"/claims/{claim_id}",
    f"/missions/{mission_id}/brief",
    "/static/style.css",
)
app = create_app(database, testing=True)

async def main():
    for route in routes:
        status, body = await get(app, route)
        if status != 200:
            raise RuntimeError(f"installed web route {route} returned {status}")
        if route == "/static/style.css" and not body:
            raise RuntimeError("installed static CSS is empty")

    capability_status, capability_body = await get(app, "/api/v1/capabilities")
    if capability_status != 200:
        raise RuntimeError(
            f"installed capability manifest returned {capability_status}"
        )
    try:
        capabilities = json.loads(capability_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("installed capability manifest returned malformed JSON") from error
    if not isinstance(capabilities, dict):
        raise RuntimeError("installed capability manifest did not return an object")

    advertised = capabilities.get("capabilities")
    unavailable = capabilities.get("unavailable")
    limits = capabilities.get("limits")
    if (
        capabilities.get("schema_version") != "minerva.capabilities.v2"
        or capabilities.get("api_version") != "v1"
        or capabilities.get("local_only") is not False
        or capabilities.get("loopback_only") is not True
        or capabilities.get("external_egress") != "disabled_by_default_cli_only"
        or capabilities.get("supported_external_providers") != ["openai", "anthropic"]
        or capabilities.get("identity_boundary") != "local_os_user"
        or capabilities.get("citation_scheme") != "utf8-byte-offset-v1"
        or capabilities.get("brief_schema_version") != "minerva.research-brief.v2"
        or capabilities.get("research_request_schema_version")
        != "minerva.research-request.v1"
        or not isinstance(advertised, list)
        or "brief.export.markdown_json" not in advertised
        or "research.packet.v2.canonical" not in advertised
        or "research.request.v1.canonical" not in advertised
        or "research.request.v1.verify.cli" not in advertised
        or "research.request.v1.fulfill.cli" not in advertised
        or "research.result.v1.canonical" not in advertised
        or "assist.finding_candidates.preview.cli" not in advertised
        or "assist.finding_candidates.invoke.cli.byok.optional" not in advertised
        or not isinstance(unavailable, list)
        or "network.fetch" not in unavailable
        or "model.invoke.api" not in unavailable
        or "model.invoke.web" not in unavailable
        or "model.output.auto_adopt" not in unavailable
        or "provider.credential.persist" not in unavailable
        or "sibling_artifact_exchange" not in unavailable
        or "shared_run_envelope" not in unavailable
        or "orchestration" not in unavailable
        or "experiment_execution" not in unavailable
        or "approval_authority" not in unavailable
        or not isinstance(limits, dict)
        or limits.get("research_request_bytes") != 65_536
        or limits.get("assistant_context_bytes") != 65_536
        or limits.get("assistant_evidence_cards") != 50
        or limits.get("assistant_candidates") != 3
    ):
        raise RuntimeError("installed capability manifest is incomplete or untruthful")

asyncio.run(main())
""".strip()
        _run_checked(
            [str(python), "-c", web_probe, str(demo_database), mission_id, claim_id],
            cwd=smoke_directory,
            environment=environment,
        )

        provider_probe = """
import socket
import sys
from importlib.util import find_spec

def deny_network(*_args, **_kwargs):
    raise RuntimeError("provider adapter construction attempted network access")

socket.create_connection = deny_network
socket.getaddrinfo = deny_network

from minerva.assist.models import ModelProvider
from minerva.integrations.ai import candidate_provider

expected = frozenset(sys.argv[1:])
for module in ("anthropic", "openai"):
    present = find_spec(module) is not None
    if present != (module in expected):
        raise RuntimeError(
            f"provider SDK presence mismatch for {module}: present={present}, expected={expected}"
        )

for name in sorted(expected):
    provider = ModelProvider(name)
    adapter = candidate_provider(provider)
    if adapter.provider is not provider:
        raise RuntimeError(f"constructed adapter reports the wrong provider for {name}")
""".strip()
        for extra, expected_providers in PROVIDER_EXTRA_CASES:
            extra_python = _provision_locked_environment(
                uv_command=uv_command,
                checkout=checkout,
                wheel=wheel,
                venv_root=temporary_root / f"venv-{extra}",
                cwd=smoke_directory,
                environment=environment,
                extra=extra,
            )
            _run_checked(
                [str(extra_python), "-c", provider_probe, *expected_providers],
                cwd=smoke_directory,
                environment=environment,
            )

    return wheel


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist_directory", type=Path, help="directory containing one wheel")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        wheel = smoke_wheel(args.dist_directory)
    except (OSError, SmokeError) as exc:
        print(f"installed-wheel smoke failed: {exc}", file=sys.stderr)
        return 1
    print(f"installed-wheel smoke passed: {wheel.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
