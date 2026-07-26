# Decision index

- [ADR 0001: Use immutable snapshots and exact byte-span evidence](adr/0001-research-evidence-model.md)
- [ADR 0002: Keep sibling systems behind artifact/protocol seams](adr/0002-system-boundaries.md)
- [ADR 0003: Require explicit BYOK consent for bounded model assistance](adr/0003-explicit-byok-model-assistance.md)
- [ADR 0004: Audit restored databases before exclusive publication](adr/0004-staged-restore-audit-publication.md)
- [ADR 0005: Add targeted indexes for claim-scoped request fulfillment](adr/0005-targeted-fulfillment-indexing.md)
- [ADR 0006: Report operator remnants without removing them](adr/0006-operator-remnant-notices.md)
- [ADR 0007: Retract findings instead of blocking export forever](adr/0007-finding-retraction.md)

## Milestone 1 implementation decisions

- Linux/POSIX with Python 3.12–3.14 is the tested alpha boundary. FastAPI, Jinja2,
  stdlib `sqlite3`, and stdlib `argparse` keep the runtime small and avoid a
  JavaScript build chain. Other operating systems remain unverified.
- Migrations are explicit packaged SQL files with recorded checksums. An ORM is not
  required for the bounded schema and would not replace domain validation.
- Source locations are UTF-8 byte offsets, not code-point offsets or line numbers.
- Duplicate source bytes produce equal digests but distinct provenance registrations.
- User-supplied Markdown/HTML is displayed as escaped text; Milestone 1 does not need
  a rich renderer or sanitizer dependency.
- The fixed `research-brief.json` export is the one canonical agent packet. Version 2
  adds strict SQLite-independent parsing and verification, complete research and
  provenance preservation, and an explicit no-execute/no-approve/no-orchestrate/
  no-publish ownership boundary instead of creating a parallel format.
- Export digests cover the compact, sorted-key canonical semantic payload; the digest
  envelope itself is excluded to avoid circular hashing.
- Capability manifest schema v2 is additive: packet/export and optional CLI-only
  assistance support are advertised while sibling exchange, orchestration, experiment
  execution, approval authority, and the future shared run envelope remain explicitly
  unavailable.
- A future shared run envelope is separately versioned from packet content. Its
  artifact references bind schema version plus SHA-256, not paths or URLs, and its
  fields provide correlation metadata rather than authentication, authority, truth,
  approval, or guaranteed recovery.
- Existing databases and export targets are never overwritten by normal commands.
- Migrations are forward-only; recovery from an unwanted upgrade uses a verified
  standalone pre-upgrade backup and the prior binary, not an in-place downgrade.
- The project license is intentionally not selected here; licensing is a human legal
  decision and is not required to prove the vertical slice.

## Milestone 1.2 implementation decisions

- The existing `minerva.research-brief.v2` document remains the only packet format.
  Standalone tooling calls its canonical parser and verifier rather than introducing a
  second validation path.
- Packet intake is a Linux file-boundary adapter: it rejects parent segments, walks
  path components with descriptor-relative no-follow opens, pins and type-checks the
  final target with `O_PATH`, accepts only one stable regular file, enforces the 20 MiB
  limit before decoding, and parses only bytes captured from the pinned descriptor.
- `packet verify` and `packet inspect` are database-free, offline commands. Their
  compact JSON outputs are fixed-key and bounded; inspection exposes inventory and
  provenance/audit coverage, not stored research text, identifiers, URLs, or paths.
- Audit references must respect dependency order as well as coverage: a recorded
  mutation cannot precede the entities or evidence state it depends on.
- Untrusted sequence fields stop validation on the first invalid item; JSON
  object-width/nesting preflight and bounded error classification prevent hostile
  packets from multiplying validation errors into attacker-sized output or memory.
- Canonical digest verification establishes self-consistency only. Packet
  authenticity, source-byte revalidation, transport, signing, Athena/Icarus exchange,
  and any execution or approval authority remain future seams.

## Milestone 1.3 implementation decisions

- `minerva.research-request.v1` is an inert canonical selection contract, not an
  Athena adapter or shared run envelope. It contains only exact Minerva identifiers,
  complete-ledger selection, and requested output schema; its digest is
  self-consistency, not authentication or authority.
- `complete_claim_ledger` is the only policy. Its sorted active citation IDs are an
  exact freshness precondition, never a subset: fulfillment preserves every active
  stance and all withdrawn/supersession/status history needed by canonical v2.
- Fulfillment validates the request before database open and resolves mission, claim,
  ledger, and claim-scoped synthesis through one query-only read snapshot. It does not
  call the mutating/audited brief-export path.
- Fulfillment bounds cumulative SQLite virtual-machine work with a connection-local
  progress handler and maps only its own exhaustion interrupt to the existing
  `brief_work_limit` refusal. This schema-free hardening accepted possible false refusal
  on scan-heavy databases; migration 0003 has since supplied the targeted indexes
  (ADR 0005) while retaining the budget.
- Before full database text or snapshot content is returned to Python, claim-scoped
  synthesis preflights NUL-safe storage-byte lengths at every emitted string's exact
  packet multiplicity. UTF-8 is exact and UTF-16 uses a conservative two-to-one
  threshold; canonical serialization remains authoritative. SQLite still inspects the
  stored values, so this is a Python-materialization guard rather than an SQLite-memory
  limit.
- Claim-scoped output remains `minerva.research-brief.v2`; request/scope metadata does
  not fork or extend the packet schema. Minimal `minerva.research-result.v1` binds the
  request digest to exact output bytes. Consumers need that external binding to
  interpret selection completeness.
- Fixed request-result files use the existing exclusive no-follow writer and caught-
  error cleanup. No migration, identity/run, audit record, provider/model, network,
  transport, publication, messaging, execution, approval, or automatic adoption is
  added.

## Milestone 2B implementation decisions

- Model assistance is an optional CLI-only exception to the offline Milestone 1
  boundary, not a general integration or autonomous-research platform.
- Provider choice and model are explicit. Credentials are BYOK environment values,
  loaded only after the operator authorizes the exact preview digest.
- OpenAI and Anthropic are separate optional extras. Network/provider imports are
  restricted to one reviewed adapter file per provider.
- Exact active evidence is disclosed only after preview; model output is validated,
  ephemeral candidate `agent_inference` and never research state.
- Requested and terminal audit metadata bracket the external call but cannot be
  transactionally atomic with it. Timeouts have unknown provider outcomes and are not
  retried automatically.

## Milestone 1.4 implementation decisions

- Migration 0003 adds only two indexes: `idx_audit_event_entity` on
  `audit_events(event_type, entity_id)` and `idx_findings_claim` on
  `findings(mission_id, claim_id, created_at, id)`. Fulfillment cost becomes
  independent of unrelated audit history; the cumulative work budget, its
  `brief_work_limit` refusal, and the storage-byte preflight are unchanged.
- The claim-scoped `INDEXED BY` hints are repointed to `idx_findings_claim` in the
  same change, because SQLite ignores a better index while a hint names another.
  The hints stay so the chosen index is explicit at the call site and a missing
  migration fails at prepare time; they do not by themselves prevent a scan, so
  the plan is pinned by an `EXPLAIN QUERY PLAN` assertion in the tests.
- Determinism is unaffected: every order-sensitive read on the export and
  fulfillment paths orders by a unique key or key suffix, so no plan change can
  reorder canonical output.
- `connect()` never creates a database and never removes one. It opens a `mode=rw`
  URI built with `Path.as_uri()`, so a path containing `?` or `#` cannot address a
  different file, and a missing database is reported as `database_missing` (503)
  rather than being created and then rejected as `database_unready` (422).
- Fresh `initialize()` stages, migrates, audits, and publishes with an exclusive
  hard link, matching ADR 0004's restore pattern. Losing that race repeats
  initialization against the published database so concurrent init stays
  idempotent instead of destroying the winner's data.

## Wave-A hardening decisions

- `PRAGMA recursive_triggers = ON` is set per connection. Without it,
  `INSERT OR REPLACE` resolves a primary-key conflict with a delete that skips
  the BEFORE DELETE triggers, which was demonstrated to rewrite a recorded
  migration checksum in place.
- Backup applies the destination-sidecar refusal restore already had, so an
  unusable backup is refused at backup time rather than discovered at recovery.
- Restore no longer collapses migration-state failures into `backup_invalid`. An
  intact backup at another schema version reports the real code, because calling
  a good backup corrupt at recovery time is the worst possible moment for a
  false claim.
- The OpenAI adapter checks terminal status before refusal content. A refusal
  item on a failed or still-running response is an unknown outcome, not an
  observed refusal, and must not be audited as one.
- `ANTHROPIC_AUTH_TOKEN` fails closed. The pinned SDK ignores it when an
  explicit key is supplied; the supported range is `>=0.117,<1`, so this is
  version-independence rather than a fix for a live bypass.
- The security middleware allows only `http` (checked) and `lifespan`
  (delegated). A websocket handshake ignores CSP and the same-origin rules the
  middleware depends on, so it is closed rather than forwarded.
- Packet digest-mismatch classification is anchored to the root envelope
  validator and matched exactly. Identifiers are free-form text, so a substring
  test let a crafted packet choose its own rejection code.
- Text validation rejects strings that cannot encode as UTF-8, and the finding
  citation bound lives in the service rather than only the REST adapter.
- The static security gate additionally bans `os.posix_spawn`, `multiprocessing`,
  `ProcessPoolExecutor`, `webbrowser`, `ctypes`, and the asyncio DNS and socket
  helpers. Tests deny non-loopback sockets suite-wide instead of relying on
  convention.

- `doctor` reports remnants and never removes them. Notices are a separate
  channel from checks, so they never affect `DoctorReport.ok`, `/readyz`, or the
  `doctor` exit status: crash residue is housekeeping, not unreadiness. Notice
  text carries a count and no filename, because a staging remnant's name embeds
  the database filename.
- Partial export and fulfillment output directories remain undiscoverable by
  design. `brief_exports` stores digests rather than paths and `request fulfill`
  records nothing, so Minerva says it cannot locate that residue instead of
  offering a check that silently finds none.

## Finding retraction decisions (gate D-9)

- Retraction is to a finding what withdrawal is to an evidence card: an
  append-only record, never an edit or a delete. The finding, its citations, and
  its audit history all remain; synthesis stops carrying it.
- Minerva never auto-retracts a finding when cited evidence is withdrawn.
  Whether a withdrawal invalidates a finding is a research judgement, so the
  operator records it.
- The withdrawn-citation refusal applies to material findings only, matching PRD
  invariant 8. An assumption or unresolved question may keep an optional
  citation to withdrawn evidence; the packet marks that citation withdrawn so
  the state is visible rather than the document being refused.
- `minerva.research-brief.v2` is unchanged. A retracted finding is absent from
  the packet rather than flagged inside it, so the frozen fleet-facing contract,
  its canonical bytes, and its golden fixtures all stay put. Surfacing
  retraction history in a packet is a future v3 question, not this change.

## Retraction visibility and verification (plan 2, issues 1-2)

- Leaving a finding out of the brief is not the same as marking it retracted.
  D-9 shipped the database record and the synthesis exclusion but left every
  listing surface rendering a retracted finding exactly like an asserted one,
  which manufactures certainty by omission on the surface a human actually
  reads. `Finding` and `FindingRead` now carry `retracted`,
  `retraction_reason`, `retracted_at`, and `retracted_by`, mirroring the
  withdrawal fields already on `LedgerEntry`, and the web review page renders a
  RETRACTED badge with the reason.
- Findings are read through one left join on the mission-composite key rather
  than a follow-up query per row. `finding_retractions.finding_id` is UNIQUE, so
  the join cannot multiply rows or disturb cursor pagination.
- The set of append-only triggers doctor enforces is derived from the packaged
  migrations, not hand-listed. Migration 0004's two retraction triggers were
  missing from the hand-maintained set, so dropping them and deleting a
  retraction row left `doctor --deep` reporting a healthy database while the
  finding silently returned to synthesis. `_REQUIRED_TRIGGERS` remains as the
  declared floor - it catches a migration resource missing from the
  distribution, which a derived-only set would read as "nothing required" - and
  a test pins the two sets equal.
- Deep doctor reconciles every `finding_retractions` row against its
  `research.finding.retracted` audit event, exactly as it already did for
  evidence withdrawals. A deleted retraction now fails `material_audit_integrity`
  because its audit event is left dangling.
- Editing only a retraction's `reason` text is still not detectable by audit
  reconciliation, because the audit event carries the retraction id rather than
  the reason - the same shape as `evidence.card.withdrawn`. The defence there is
  the append-only trigger, which doctor now requires and fingerprints, so the
  edit cannot happen without first dropping a trigger that doctor reports.

## Index-pinning claims corrected (plan 2, issue 3)

- Four documents claimed `idx_audit_event_entity` was pinned with `INDEXED BY`
  and that a missing index would fail loudly. Measured directly on a fresh
  connection per statement, so no cached plan could mislead: the audit query
  names no hint, and dropping the index turns it into `SCAN audit_events`
  with no error at all. Only `idx_findings_claim` is hinted, and dropping it
  does raise `no such index` at preparation. The prose in ARCHITECTURE.md,
  ROADMAP.md, THREAT_MODEL.md, and ADR 0005's consequences now says which
  index gets which guarantee.
- `INDEXED BY` never forces a seek. With the index present but the equality
  predicate removed, the plan becomes
  `SCAN findings USING COVERING INDEX idx_findings_claim` plus a temp b-tree
  sort, silently. ADR 0005 already stated this correctly in its decision
  section; the summary documents contradicted it, and now do not.
- `test_targeted_fulfillment_indexes_are_present_and_selected` is therefore the
  only real control on index selection, and is named as such wherever the
  guarantee is described.
- **Migration 0003's header comment is left stale on purpose.** It repeats the
  overstatement, but `schema_migrations.checksum` is `sha256` over the whole
  migration file, comments included: editing it changes the digest (measured:
  `4622fe79...` to `09d38ed6...`) and every database already at schema 3 or
  higher would refuse to open with `migration_checksum_mismatch`. Correcting a
  comment is not worth breaking every existing installation. ADR 0005 carries
  the correction of record and says so explicitly.

## Reads no longer alter what they read (plan 2, issue 4)

- `PRAGMA journal_mode = WAL` rewrites the database header, and it ran on every
  connection including reads. Inspecting a delete-journal artifact with
  `doctor` therefore changed its bytes and its SHA-256, breaking the
  byte-stable-artifact provenance the product rests on. Write-path pragmas
  (`journal_mode`, `synchronous`) now run only on write paths.
- **`mode=ro` was measured and rejected.** It is the obvious fix and it breaks
  backup and restore. A read-only connection attaches the WAL index but cannot
  checkpoint or unlink `-wal`/`-shm` on close, so it leaves sidecars beside the
  database; the restore and backup guards refuse to publish over live sidecars,
  and seven tests failed accordingly. The mutation came from the pragma, not
  from the open mode, so dropping the pragma fixes the defect without weakening
  a guard. `read()` documents this so the next reader does not "improve" it
  back.
- Doctor's `wal` check now reports the journal mode stored in the file instead
  of the value the connection had just forced. A delete-journal artifact is
  honestly reported as not being in WAL, which is a real deviation worth
  surfacing rather than one doctor silently repaired.
- Doctor's `foreign_keys` check reported whether the inspection connection had
  enforcement switched on — always true, because `_connect` had just set it.
  `Database.integrity_check` now returns page integrity and foreign-key
  satisfaction separately, so `foreign_keys` means "the recorded references
  resolve", a property of the database. Both pragmas were already being run;
  only one of them was being reported.

## Publication durability (plan 2, issue 5)

- Publishing a file makes its contents durable but not the directory entry
  that names it: that entry stays in the page cache until the directory is
  synced. There was exactly one `fsync` in the whole source tree (the export
  file descriptor) and none in `core/`, so a crash right after a successful
  `minerva backup` could leave a committed `database.backup.created` audit row
  describing a file that no longer existed.
- The barrier lives in `_publish_private_database`, not at its three call
  sites. Initialization, backup, and restore all publish through that one
  `os.link`, so putting it there makes the guarantee structural rather than
  something each new caller must remember.
- **Ordering is the point.** The directory is synced before the operation
  records that it happened — before the `brief_exports` transaction on export,
  before returning success on fulfillment. A durable audit row can then never
  outlive the artifact it describes. The regressions assert that ordering, not
  merely that an fsync occurred.
- `fsync` failures propagate rather than being suppressed. A filesystem that
  cannot sync a directory cannot support the durability the operation is about
  to claim, and Minerva does not report a success it cannot stand behind.
- **This was verified structurally, not by simulating power loss.** The tests
  prove the sync happens and happens before the success is recorded; they do
  not prove behaviour across a real crash, and SECURITY.md states the limits:
  no multi-file export atomicity, no coverage of SQLite's own write path, and
  no defence against hardware that acknowledges `fsync` without persisting.

## Backup refuses only what it should (plan 2, issue 6)

- `backup_to` gated on the whole `DoctorReport` and mapped every failure to
  `database_invalid` ("The database failed validation and cannot be backed
  up"). Measured, that one message covered three different situations: a
  genuinely corrupt database, an intact one whose schema was merely out of
  date, and an intact one with loose permissions or a non-WAL journal mode.
  Only the first is a reason to refuse a copy.
- **Outdated schema now reports `database_migration_required`**, matching what
  `restore_from` already did. Permitting the backup outright would be the more
  operator-friendly answer, but running deep doctor against an older schema is
  not meaningful — the required-trigger set is derived from the packaged
  migrations, so a schema-3 database legitimately lacks migration 0004's
  triggers — and a weaker "raw copy" validation tier belongs with decision gate
  D-11, which already covers restoring pre-upgrade backups. The honest refusal
  ships now; the capability stays gated.
- **Configuration problems no longer block a backup.** `permissions` and `wal`
  are listed in `doctor.BACKUP_ADVISORY_CHECKS`: a loose-permission or
  delete-journal database is exactly the one an operator most wants to copy
  before touching anything, and `doctor` reports both conditions on the copy
  too, so proceeding conceals nothing. Membership is a short allowlist, so a
  future check blocks backups until someone decides otherwise.
- **This slice also repairs a regression slice 9 introduced.** Making doctor
  report the real journal mode meant a delete-journal database began failing
  the `wal` check, which `backup_to` then turned into `database_invalid`.
  Before slice 9 that database was silently converted to WAL and backed up.
  Neither behaviour was right; a backup now succeeds and alters nothing.
- **A backup no longer rewrites its own source.** `backup_to` read through a
  write connection, which forced `journal_mode = WAL` and rewrote the header of
  the database being copied. It now reads through the same non-mutating
  connection every other read path uses.

## Oversized is a work limit, never tampering (plan 2, issue 7)

- The mission-wide branch of `_preflight_synthesis` bounded record counts,
  reference counts, and snapshot bytes but never emitted text, unlike the
  claim-scoped branch. Record and snapshot counts do not bound emitted text:
  one evidence quote may be 100,000 bytes and many cards may quote the same
  small snapshot, so a mission can hold far more packet text than snapshot
  bytes. Measured: 215 cards quoting one 99,001-byte range produced 21.3 MB of
  quote text against 99 KB of snapshots and passed the preflight.
- The oversize then surfaced at serialization, where `_require_packet_size`
  raised a bare `ValueError` that a blanket `except ValueError` reported as
  `packet_integrity_invalid` — a tamper alarm for a completely intact database,
  and one that wedged mission-wide export permanently. It now refuses at the
  preflight with `brief_work_limit`, before any snapshot BLOB is materialized.
- **The accounting is a deliberate lower bound.** It sums the unbounded
  free-text columns (quotes, statements, uncertainty, falsification criteria,
  status reasons, question text, snapshot labels) and ignores identifiers,
  timestamps, and JSON structure. A lower bound can only refuse a mission whose
  output genuinely exceeds the cap, never one that would have fit.
- `ResearchPacketTooLargeError` subclasses `ValueError`, so every consumer-side
  handler behaves identically while a producer can distinguish "too large" from
  "malformed". The serializer guard remains as a backstop for a mission whose
  canonical bytes exceed the cap by less than the lower bound could see, and it
  now maps to `brief_work_limit` too.
- The UTF-8/UTF-16 storage factor is now one shared helper
  (`_storage_bytes_per_output_byte`) instead of being spelled out in the
  claim-scoped branch only, so the two branches cannot drift on it.

## The claim-scoped boundary is documented, not changed (plan 2, issue 8)

- Reproduced: a mission-level finding (`claim_id` NULL) that cites the target
  claim's own evidence is omitted from a claim-scoped packet, along with its
  uncertainty and any mission-level unresolved question, while the packet still
  carries the cited card. Mission-wide: 2 findings + 1 unresolved question + 2
  uncertainties; claim-scoped: 1 + 0 + 1, with the card present either way.
- **This is the documented rule, not a defect.** ADR 0002 already says a
  claim-scoped packet retains the closure the canonical verifier requires and
  that "unrelated mission entities are omitted", and PRD invariant 16 already
  says the packet carries no selection marker, with the request/result binding
  supplying that meaning. PRD invariant 16 now states the finding-scope rule
  explicitly, because the behaviour reads like a bug: an empty statement array
  means "none for this claim", not "none in this mission".
- `test_claim_scoped_packet_omits_mission_level_statements_by_design` pins it,
  so the boundary cannot move silently in either direction.
- **Including intersecting mission-level statements was considered and
  rejected, on a technical blocker rather than taste.** `_validate_findings`
  requires every finding's citations to be present in the packet. A
  mission-level finding may cite cards from several claims, so including it
  would force those other claims' cards into a claim-scoped packet —
  contradicting "unrelated mission entities are omitted" and dragging the
  packet toward mission-wide. Restricting inclusion to findings whose citations
  lie entirely within the target ledger would still silently drop the rest,
  which moves the ambiguity rather than removing it.
- Recorded as a `minerva.research-brief.v3` question, on the same terms as ADR
  0007's retraction-in-packet deferral: it needs a consumer that actually wants
  mission-level context in a claim-scoped packet, and a selection rule that
  survives the citation-closure requirement. No consumer exists today.
