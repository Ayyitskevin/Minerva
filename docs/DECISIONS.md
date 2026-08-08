# Decision index

- [ADR 0001: Use immutable snapshots and exact byte-span evidence](adr/0001-research-evidence-model.md)
- [ADR 0002: Keep sibling systems behind artifact/protocol seams](adr/0002-system-boundaries.md)
- [ADR 0003: Require explicit BYOK consent for bounded model assistance](adr/0003-explicit-byok-model-assistance.md)
- [ADR 0004: Audit restored databases before exclusive publication](adr/0004-staged-restore-audit-publication.md)
- [ADR 0005: Add targeted indexes for claim-scoped request fulfillment](adr/0005-targeted-fulfillment-indexing.md)
- [ADR 0006: Report operator remnants without removing them](adr/0006-operator-remnant-notices.md)
- [ADR 0007: Retract findings instead of blocking export forever](adr/0007-finding-retraction.md)
- [ADR 0008: Persist human-adopted agent inferences as a separate labeled record](adr/0008-persisted-agent-inferences.md)
- [ADR 0009: External principals and signed request attribution](adr/0009-external-principals-and-request-attribution.md) — **Proposed (gate D-2)**
- [ADR 0010: The Athena coordination adapter seam](adr/0010-athena-coordination-adapter-seam.md) — **Proposed (gate D-2)**
- [Workspace research-memory season](#workspace-research-memory-season-decision-0-2026-08-20) — **Accepted 2026-08-20 (Decision 0)**
- [Lens v1: narrow local candidate retrieval](#lens-v1-narrow-local-candidate-retrieval) — **Accepted 2026-08-08; broad D-6 remains closed**

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

## The review surface says what it is showing (plan 2, issue 9)

- `/missions` called `list_missions()` with no argument, taking its default
  `limit=100`, and `missions.html` had no count, banner, or pagination
  affordance. Measured with 105 missions: 100 cards rendered, "Mission 104"
  absent, and no string anywhere disclosing that anything was hidden — while
  the REST route on the same data returned a `next_cursor`. A human review
  surface silently presenting a capped list as the whole set is the same
  false-completeness class as the retraction and oversize slices.
- The route now uses `page_missions`, which fetches one extra row and reports
  whether it existed. That makes "more exist" **exact**. A
  `len(missions) == limit` heuristic would have claimed more missions existed
  whenever a count landed exactly on the page size, and a surface built to stop
  overstating completeness must not start overstating truncation instead.
- **The page stays single-page on purpose.** Cursor navigation would mean
  either coupling the review surface to the REST layer's cursor encoding or
  growing a second one, and this is a deliberately restrained GET-only surface.
  What it owed the reviewer was honesty about the cap, not navigation. The
  banner names `minerva mission list` and `/api/v1/missions` as the surfaces
  that do page, so nothing is unreachable — only differently reached.

## The suite now delivers what it claims (plan 2, issue 10)

Three places where the test suite asserted a stronger guarantee than the code
behind it provided. Each was reproduced against the real fixture or script
before being changed.

- **The outbound-network guard covered two entry points, not "any socket".**
  `deny_outbound_network` patched only `connect` and `create_connection` while
  its docstring promised to fail any test opening a non-loopback socket.
  Measured against the real fixture: `connect_ex` to 127.0.0.2 reached the OS
  and UDP `sendto` delivered its bytes, both silently. It now guards `connect`,
  `connect_ex`, `create_connection`, `sendto`, and `sendmsg`, and the docstring
  names them so the two stay in step. A test that forgot to inject a provider
  fake could otherwise have reached the network from a machine holding real
  credentials.
- **Alias tracking ignored unpacking.** `_bind_alias` returned early for any
  non-`ast.Name` target, so `(runner,) = (os.system,)`, `[runner] = [...]`,
  `first, runner = 1, os.system`, and `*rest, runner = [...]` all evaded MIN002
  while the tested `runner = os.system` form was caught. `_unpacked_bindings`
  now pairs targets with values positionally, including around a single starred
  target, where names before it pair from the front and names after it from the
  back. When the pairing is not knowable it binds `None`, clearing the name
  rather than guessing: a wrong alias is worse than none, because it would flag
  innocent code.
- **MIN003 had no test witness.** The rule the threat model names as the
  prohibition on dynamic code execution was enforced only by the tool running
  clean over a repository that happens not to call `eval`. It now has cases for
  `eval`, `exec`, `compile`, and an aliased `eval`. These are new witnesses for
  behaviour that already worked, not a fix.
- **The coverage floor now includes the static gate.**
  `scripts/static_security_check.py` enforces threat-model prohibitions, so its
  detection branches belong under the floor. `verify_dist.py` and
  `installed_smoke.py` are omitted **deliberately**: both are exercised end to
  end by their own gate commands against a built distribution, so measuring
  them under pytest would report how little pytest calls them rather than how
  well they are tested. Including all of `scripts/` unfiltered put the total at
  exactly 85.0%, which would have made the floor flap on any small change.

## The low sweep (plan 2, issue 11)

Five small refusals that were each wrong in a different way, plus two
documentation corrections. Every one was reproduced against real code before
being changed, and each regression was checked to fail on the pre-fix source.

- **Creation was stricter than export for assumptions.** `add_finding` passed
  `allow_withdrawn=False` for every statement kind, so an assumption citing
  already-withdrawn evidence was refused `citation_withdrawn`. PRD invariant 8
  and ADR 0007 scope that refusal to *material* findings: an assumption may keep
  an optional citation to withdrawn evidence, which the packet marks as
  withdrawn. The old behaviour was not even a stronger guarantee — the same end
  state reached by withdrawing the evidence *after* creating the assumption
  exported fine. The flag now derives from `statement_kind.requires_citation`,
  so one predicate governs both ends.
- **A float citation offset escaped as a raw `TypeError`.** Every range
  comparison in `add_evidence` passes for a float, and the failure surfaced
  deeper in the write path when the snapshot was sliced. A CLI caller never saw
  it because argparse types the argument, but a direct service caller got an
  unmapped exception instead of a domain refusal. The offsets are now
  type-checked up front, `bool` excluded first because it is an `int` subclass.
- **Error-code ordering let a flag decide what the problem was.** `initialize`
  checked `refuse_existing` before the unsafe-path rule, and `Path.exists()`
  follows symlinks — so the identical filesystem state reported `database_exists`
  or `database_symlink` depending only on the caller's flag. The symlink rule now
  runs first: a symlinked database path is categorically unusable, not merely
  occupied.
- **The request digest classifier was unanchored.** The reader matched the
  mismatch sentence anywhere in any validation error, so a non-root error that
  happened to carry the sentinel could claim `request_digest_mismatch`. It now
  matches the packet reader: `value_error`, empty `loc`, exact message against
  the named `REQUEST_DIGEST_MISMATCH_MESSAGE` constant. Today every request field
  is pattern-constrained so nothing can carry that text — this closes the class,
  not a live hole.
- **The identity-header denylist was an arbitrary subset.** It listed
  `x-forwarded-user` but not `x-forwarded-email`, and missed Google IAP, Azure
  EasyAuth, Kong, and Cloudflare Access entirely. Seven names and two vendor
  prefixes were added, and matching is now case-normalised. This is defence in
  depth and is documented as such: `local_identity` derives the actor from
  `getpass.getuser()` and no code path reads an actor from a header, so accepting
  one of these would have granted nothing. Refusing them makes a misconfigured
  deployment fail loudly instead of appearing to work.
- **Two documents understated their own scope.** `docs/PRD.md` and
  `docs/THREAT_MODEL.md` were titled "Milestones 1 through 1.4 and 2B" after
  Milestone 1.5 (finding retraction, D-9) shipped. Retitling the threat model
  would have claimed coverage its body did not have, so it also gained the
  retraction row and invariant. The invariant states what the code does rather
  than the tidier thing: finding reads return a retracted finding marked with its
  reason, timestamp, and actor, while synthesis *excludes* it from the brief.
  Both are true and they are not the same rule.
- **The capability manifest omitted two shipped verbs.**
  `research.packet.v2.verify.cli` and `research.packet.v2.inspect.cli` back real
  `minerva packet verify` / `minerva packet inspect` commands. This is an
  additive change to `minerva.capabilities.v2`: it makes the manifest more
  truthful without removing or altering an existing entry, so a consumer pinning
  the previous set sees new names, never a missing one.

Three issue 11 items are **not** done and are not implied by the above:
migration-runner TOCTOU (F2-CORE-5), a golden-fixture regeneration script
(F2-TESTS-4), and the README CLI verb reference (F4-CLI-UNDOC).

## Finishing the low sweep (plan 2, issue 11, items 8-10)

The three items slice 16 left open. Each was reproduced before being changed.

- **A concurrent upgrade reported a broken migration.** Two processes opening
  the same out-of-date database both compute the pending set, one wins the write
  lock and commits, and the loser replays migrations that are already durable —
  failing on an already-existing table and surfacing as `migration_failed`. That
  reads as database corruption for what is a benign race with the intended end
  state. Measured on a v3 database with migration 0004 packaged: one upgrader
  succeeded, the other raised `migration_failed`, and the database was fine at
  v4 the whole time.

  The lock cannot be taken any earlier. `executescript` implicitly commits, so
  the `BEGIN IMMEDIATE` guarding the migrations has to live *inside* the script
  — the pre-lock classification is unavoidable. What changed is what happens
  when the replay fails: the pending set is derived again with the lock actually
  held, and an empty result means another writer did the work and there is
  nothing left to do.

- **The loser of a mixed-version race was blamed on the migration.** Found while
  building the reproduction above, not from the plan. When the winner is a
  *newer* build, the older one's replay fails and the honest code is
  `database_too_new` — the database really is newer than that installation
  understands. It was reporting `migration_failed`. Deriving the pending set
  again runs the whole classification rather than a bespoke equality check, so
  the accurate code comes out on its own. The pre-lock and post-failure paths
  now share `_classify_migrations`, which is why they cannot disagree.

  A **partial** concurrent upgrade — another writer applying some of several
  pending migrations — deliberately still reports `migration_failed`. Applying
  the remainder is impossible without releasing the lock, and retrying inside
  the call would be a loop whose bound depends on other processes. The
  operator's next attempt sees the smaller pending set and succeeds; that is
  pinned by a test so the narrowness is a decision rather than an oversight.

- **Golden fixtures had no regeneration procedure.**
  `scripts/regenerate_golden_fixtures.py` rebuilds both from a deterministic
  scenario. It **defaults to checking**, not writing: it reports whether the
  checked-in bytes still match and exits non-zero with a field-level diff if
  they do not. `--write` is explicit and prints the diff first.

  The script re-declares its scenario instead of importing the suite's. Sharing
  the code would make the two equal by construction and prove nothing; a test
  compares the script's output against the checked-in bytes, so the script, the
  suite's `_populate_brief`, and the fixtures are pinned to each other and
  cannot diverge silently. It is not added to the gate list — the byte equality
  it would assert is already asserted by the suite, and a gate that can rewrite
  its own expectation is the wrong shape for a gate.

  The standing rule is restated in the module docstring: regenerating is never
  how a failing golden gets fixed. A fixture that stops matching means either
  the contract changed on purpose or something broke, and rewriting it makes
  that question unanswerable.

- **The README had no complete verb list.** Three verbs — `mission list`,
  `claim ledger`, `brief preview` — appeared nowhere, and six more existed only
  in passing prose. Correcting slice 16's PR note: `packet verify` and `packet
  inspect` were *not* among the undocumented ones; both had worked examples.
  Sixteen subcommands also had no `help=` at all, so `minerva mission --help`
  listed bare names. Both are fixed, and the README table quotes the same
  sentences `--help` prints.

  `test_readme_command_reference_covers_every_cli_verb` compares the table
  against the parser rather than a hand-written list, so a new subcommand fails
  the suite until it is documented. The reference also states what is absent by
  contract — no verb deletes a mission, claim, snapshot, citation, finding, or
  audit event — with a test holding that claim.

Issue 11 is now complete. Issue 12 is the last Phase 0C item.

## The last Phase 0C slice (plan 2, issue 12)

- **Ctrl-C during a provider call left the invocation open forever.** The
  interrupt handling caught `MinervaError` and `Exception`, and
  `KeyboardInterrupt` is neither — it is a `BaseException`. So the likeliest
  interruption of all, on the one operation that can run for a full timeout with
  the operator watching it, produced a requested event with no terminal one, and
  `doctor` counted that invocation as unfinished permanently. Reproduced for both
  `KeyboardInterrupt` and `SystemExit`.

  The recorded outcome is `outcome_unknown`, not `failed`. The request had
  already left the machine, so the provider may have processed and charged for
  it; that is exactly the claim a timeout makes, and the only honest one
  available. The interrupt is re-raised **unchanged** — converting it into a
  `MinervaError` would stop Ctrl-C from ending the process, which is worse than
  an unmatched audit pair.

  Recording is best effort on this path only. A second Ctrl-C or a busy database
  while writing that row must not replace the operator's interrupt with a
  database error, which would both hide the interrupt and look like corruption.
  When the write cannot happen the invocation stays unmatched — the state the
  threat model already documents and `doctor`'s `unfinished_assistance` notice
  already reports. A test drives that path and asserts doctor still counts it.

- **Two readers had four identical helpers between them.** `research_packet.py`
  and `research_request.py` each carried their own canonical-JSON writer, strict
  loader, and bounded-shape check. They were byte-identical apart from one noun,
  which is the shape that drifts silently: a fix applied to one reader and not
  the other changes what the two contracts accept without either looking wrong.
  F-SEC-1 and F2-INTEGRATIONS-1 were both instances of exactly that divergence.
  They now come from `integrations/canonical_json.py`.

  **The noun is a parameter, not a constant.** Both file readers classify on
  `str(error).startswith(f"{subject} JSON ")` to produce `packet_too_complex` or
  `request_too_complex`, so collapsing the messages would have silently changed
  which error code an oversized document gets. Deliberately swapping the packet's
  subject fails two existing tests, so that wiring is already pinned and needed no
  new test.

  **Not everything that calls `json.dumps(sort_keys=True)` was consolidated.**
  `api/routes.py` builds ASCII-only cursor tokens, `cli/_common.py` writes to a
  stream after coercing values, and `core/audit.py`, `core/doctor.py`, and
  `sources/integrity.py` serialize a single field for comparison. Those differ in
  ways that matter; collapsing them would be consolidation for its own sake. The
  golden fixtures are byte-identical across the change, which is what proves the
  consolidation changed no behaviour.

- **The coverage floor is now 88%, and it is a ratchet.** The suite measures
  90.00% on 3.12 and 3.13 — identically — so 88 leaves two points of headroom:
  enough that an ordinary change cannot make the gate flap, tight enough that
  five points can no longer disappear unnoticed. `CONTRIBUTING.md` records the
  rule that the floor is never lowered to make a red gate green.

- **The release runbook and `v0.2.0a1` tag both exist.** Kevin chose the
  pre-release tag that exactly matches `pyproject.toml`, preserving `v0.2.0` for
  a later product decision. `CONTRIBUTING.md` carries the release procedure and
  commit-attribution convention, and `CHANGELOG.md` records the observed gate
  evidence. The annotated GitHub tag peels to merge commit `b162573`; it is never
  moved or deleted.

- **Python 3.14 is verified on a released interpreter.** The original development
  machine exposed only `3.14.0rc2`, where the pinned pydantic failed before the
  suite could run. CI later passed on released 3.14.6, and the clean release-tag
  verification repeated all eleven gates locally on Python 3.14.6: 689 tests and
  90.00% branch coverage. The rc-only failure remains an environment mismatch,
  not a Minerva defect.

Phase 0C is complete. Everything remaining is gated on a decision from Kevin.

## Two claims nothing enforced (post-Phase-0C verification)

Phase 0C closed every issue plan 2 named, and everything beyond it is gated. So
rather than start gated work, the tree was checked against its own claims the way
plan 2 checked the state file before trusting it. Structure held — schema 4, 15
tables, 14 indexes, 30 triggers, exactly as documented; the demo builds and
`doctor --deep` passes all eleven checks with zero notices. Two claims did not.

- **Two contract constants were wired to nothing.** `SOURCE_DIGEST_ALGORITHM` and
  `EXPORT_DIGEST_ALGORITHM` sat beside `CITATION_SCHEME` in `research_packet.py`
  looking like the source of truth for the packet's integrity block, while the
  emitter in `synthesis/service.py` carried its own string literals — and
  imported `CITATION_SCHEME` from that same module, which is what made the
  inconsistency easy to miss. Measured: corrupting both constants to obvious
  nonsense left all 689 tests passing. A maintainer changing them would have
  believed they changed the contract, and nothing would have happened.

  They are now `Literal`-annotated, matching the pattern
  `RESEARCH_REQUEST_SCHEMA_VERSION` already established, and the emitter
  references them. Both layers now catch a wrong value: corrupting them fails 40
  tests at runtime, and mypy rejects the assignment outright. The golden fixtures
  are byte-identical, so this changed no output.

- **The manifest test named truthfulness and checked a dict.**
  `test_capability_manifest_is_versioned_and_truthful` pins the whole document,
  which catches an unintended change but not an untrue one. Measured: advertising
  `research.nonexistent.v9.teleport.cli` — a capability naming a verb that does
  not exist — passed it. `minerva.capabilities.v2` is what a consumer reads to
  decide what Minerva can do, so an entry naming nothing is a false statement to
  that consumer, and this was the surface slice 16 had just added two entries to.

  A second test now holds the `.cli` entries to a declared correspondence
  between capability and CLI verb. Both directions fail: a `.cli` capability
  missing from the table, and a table entry naming a verb absent from the parser.
  Both branches were verified by breaking each in turn.

All six CLI-backed capabilities were confirmed to map to real verbs before the
test was written, so this enforces a property that already held rather than
fixing a live falsehood. That distinction is the point — the manifest was true
and unguarded, and it is the guard that was missing.

## Persisted agent inferences (gate D-1)

Kevin's directive of 2026-07-30 opened gate D-1 and accepted ADR 0008. The four
open questions resolved as follows; each remains reversible by Kevin at review
time.

- **`minerva.research-brief.v2` canonical bytes are unchanged.** Inferences
  appear in the Markdown brief in their own clearly labeled section, so two
  exports of the same mission diverge: the packet omits live content the
  Markdown carries. That divergence is real and is documented here and in the
  ADR rather than hidden; the `v3` packet question is deferred to the first
  consumer-facing packet revision (the D-2 era), when a version bump will be
  forced anyway. This is the smallest reviewed change to the highest-integrity
  surface and preserves the golden fixtures and the offline verifier contract.
- **Promotion into a finding is explicit and never automatic.**
  `finding add --from-inference <id>` creates the human finding and records an
  append-only promotion link in the same atomic transaction. The link is a
  fourth table, `agent_inference_promotions`, because the `BEFORE UPDATE`
  triggers correctly forbid setting a link column after insert.
  `UNIQUE(inference_id)` permits one promotion per inference. The finding is
  the human's assertion; the inference remains as provenance.
- **`doctor` verifies inference citation integrity**, symmetric with findings,
  at the cost of another deep-check query.
- **The CLI verb is `assist adopt`**, keeping the assistance surface together
  per ADR 0003's boundary. Adoption stays CLI-only; no API or web adoption
  path is added.

Non-negotiables carried from the ADR: migration 0005 ships the retraction table
and the reading-surface visibility in the same change (the D-9 lesson);
adoption revalidates every citation against the live record, rescans the text
for secret patterns, and is idempotent by unique constraint on
`(request_sha256, candidate_index, claim_id)`; inferences never influence claim
status, never count toward anything, and can never be cited by a finding as
evidence.

## CLI-only correction verbs and the manifest taxonomy (gate D-10)

Kevin's directive of 2026-07-30 opened gate D-10 and accepted Plan 2's
recommendation: record the boundary now, defer the endpoint.

- **Evidence withdrawal is deliberately CLI-only.** `minerva evidence withdraw`
  is the only withdrawal surface; there is no REST, web, or packet-driven
  withdrawal path. This is a boundary decision, not an unbuilt feature: a
  correction verb changes the research record, and the only actor Minerva
  recognizes today is the local OS user behind the CLI. The REST withdrawal
  endpoint stays deferred until gate D-2 creates the first real protocol
  consumer with an authenticated principal to answer for the correction.
- **Finding retraction is the same boundary.** `minerva finding retract`
  shipped in Milestone 1.5 as a CLI-only correction verb (see the D-9 section
  above) and is recorded here as the same deliberate shape.
- **The capability manifest now says so.** `minerva.capabilities.v2` gains
  `evidence.withdraw.cli` and `finding.retract.cli`, so a consumer reading the
  manifest can discover the symmetric correction vocabulary and see that it is
  CLI-only rather than absent. This is additive: no entry is removed or
  altered, so a consumer pinning the previous set sees new names, never a
  missing one — the same rule the F5-CAP-PACKET-CLI fix established for the
  packet-CLI entries. The `.cli` taxonomy is now truthful in both directions:
  every advertised `.cli` entry names a verb that exists (pinned by
  `test_capability_manifest_cli_entries_name_verbs_that_exist`), and every
  capability a protocol consumer could expect that is CLI-only — the correction
  verbs and the packet, request, and assistance surfaces — is labeled `.cli`.
  Operator-only tooling (`init`, `doctor`, `backup`, `restore`, `audit list`,
  `serve`, `demo`) is deliberately not advertised at all: the manifest answers
  what a consumer can ask Minerva to do, not how an operator maintains it.

## Staged migration during restore (gate D-11)

Kevin's directive of 2026-07-30 opened gate D-11 and accepted Plan 2's
recommendation, recorded as the second amendment to ADR 0004.

- **Restoring a pre-upgrade backup no longer requires the prior binary.**
  `restore_from` accepts an intact backup at any older recorded schema version
  and runs the forward-only migration chain on the private staged copy — never
  the live database — inside the existing audited staging pipeline. Deep
  doctor then validates the migrated staging state, and only then does
  exclusive publication happen. A backup this installation cannot reconcile at
  all (unmanaged, newer, or checksum-mismatched) is still refused before
  staging, with the same codes as before; only genuine corruption reports
  `backup_invalid`.
- **Fail-closed semantics are unchanged.** A failed staged migration, a failed
  audit callback, or a failed deep validation abandons the staged copy and
  leaves the destination and the live database untouched; publication still
  never overwrites and never removes a public replacement.
- **The audit trail is provenance-correct about the migration.** The
  migration, a new `database.migrated` event
  (`from_schema_version` → `to_schema_version`), and the existing
  `database.restored` event commit in one transaction on the staged copy, which
  is the database that gets published. The restored database therefore carries
  its own honest history: the backup's original events, then the restore run's
  events showing that the record was migrated forward during this restore and
  by how much. A same-version restore records no `database.migrated` event, and
  `minerva init` upgrades of a live database are unchanged and record none
  either — the event exists only where the migration happened inside restore.
- **Rollback doctrine is unchanged.** Migrations remain forward-only with
  recorded checksums; there is still no in-place downgrade, so rolling back to
  an older version still means restoring the verified pre-upgrade backup with
  the prior binary into a new path. What closed is the asymmetric gap: moving
  *forward* from a pre-upgrade backup no longer needs the old binary.

## Withdrawal after adoption is state, not corruption (plan 3, issue 3)

Two documented first-class verbs used in sequence — adopt an inference, then
withdraw a card it cites — produced a clean-looking export, a deep-doctor
failure, and a refused backup, with nothing on any surface pointing at the
remedy. That is honest use reading as tampering, and it is the same class of
defect as D-9's: the record was right and the reading surfaces were not.

- **The Markdown brief marks a withdrawn inference citation inline**, using the
  marker the citation-resolution section has always used
  (`**[evd_…]** **WITHDRAWN**`). An adopted inference is model-drafted text; it
  must not out-assert a human finding by rendering a withdrawn citation as
  though it still stood. This is Markdown only. The canonical
  `minerva.research-brief.v2` payload never carried inferences and still does
  not, so the golden fixtures are byte-identical across this change.
- **`inference_integrity` now verifies inference citations with
  `allow_withdrawn=True`.** This narrows ADR 0008's "symmetric with findings"
  resolution of its third open question, and the asymmetry is the point: a
  material finding may not rest on withdrawn evidence, because a finding is the
  operator's own assertion about the claim. An inference asserts nothing — it
  cannot influence claim status and counts toward nothing — so a withdrawal
  behind it is a fact to display, not an integrity failure to refuse on. D-9's
  rule that Minerva never auto-retracts on the operator's behalf means the
  inference stays until a human retracts it, and until then the correct
  behaviour is to say so, visibly.
- **What still fails is unchanged.** A citation that is missing, tampered with,
  or scoped to a different claim still fails `inference_integrity`, and
  adoption still refuses to adopt a candidate citing already-withdrawn evidence
  (`allow_withdrawn=False` at the adoption boundary). Only the post-adoption
  withdrawal case moved.
- **Backups are no longer blocked by it.** `BACKUP_ADVISORY_CHECKS` is
  unchanged and still a short allowlist: `inference_integrity` remains a check
  that blocks a backup when it fails. It simply no longer fails for a database
  that is telling the truth — which is exactly the database an operator most
  wants a copy of before correcting anything.

## An unwired security primitive is a false affordance (plan 3, issue 6)

`CsrfProtector` in `web/security.py` was fully implemented, exported, and
tested — signed double-submit tokens, `HttpOnly`/`SameSite=Strict` cookie,
constant-time comparison — and wired into nothing. The review server has no
unsafe form: every route is a GET, and the only mutation surfaces are the CLI
and the loopback REST API, which is not cookie-authenticated and so is not the
threat CSRF answers.

It is deleted. A reader auditing the web boundary saw a CSRF defense in the
module and its tests passing, and the honest reading of that is "this
application defends its forms," which was not true of anything. Unused
security code also rots quietly: it is never exercised against the routes it
would protect, so the day someone wires it up, its assumptions are years old.

Re-add it with the first unsafe form, from the git history rather than from
scratch — `git log -- src/minerva/web/security.py` keeps the implementation and
its tests intact, and re-adding it against a real route is the only way its
correctness can actually be verified. Nothing about the boundary changed:
`LocalSecurityMiddleware` still enforces loopback hosts, origin checks, body
limits, and the strict header set, and no route gained or lost a defense.

This closes plan 2's F2-SURFACES-4.

## Workspace research-memory season (Decision 0, 2026-08-20)

Kevin recorded Decision 0 on 2026-08-20: this season optimizes Minerva as the
fleet's research-memory on mickey rather than opening gate D-2, productizing an
MCP/agent protocol, or parking the repository.

What this accepts:

- Identity stays the local-first provenance laboratory. The governing rule is
  unchanged. PRD invariants and accepted ADRs are not rewritten.
- Daily use is the season's optimization: a Grok-seat clone, recovery of the
  unpublished Lens/review stack after rebase onto current `main`, one persistent
  local SQLite database, loopback review, and a documented same-OS-user CLI
  loop for filing evidence.
- Gate D-2 remains closed. Athena still cannot hold a keypair. A signature
  still attests only to the extent the verifier could not have produced it, and
  a server-held key still attests a deployment, never an agent.
- Same-OS-user CLI access to one local database is the existing trust model. It
  is not D-2, not multi-user authorization, and not a remote bind.

What this does not authorize:

- MCP, Tailscale or reverse-proxy bind, packet `v3`, a PROV-O/RO-Crate
  exporter, extra providers, vector search, URL fetching, Icarus exchange
  (D-3), or a read-only agent protocol (D-5).
- Creating the persistent database, shipping systemd, or merging Lens. Those
  are later phases that still need their own review and the eleven gates.
- Editing another seat's clone or writing Minerva state into ORACLE.

The written form is [VISION.md](VISION.md) and [WORKSPACE.md](WORKSPACE.md).

## Lens v1: narrow local candidate retrieval

The repository owner's 2026-08-08 directive authorizes one deliberately narrow
exception to the otherwise closed D-6 retrieval/ingestion gate: deterministic,
model-free lexical search over immutable snapshots already imported into one
Minerva mission.

- **Search returns leads, not research state.** The public object is
  `candidate_context` with `unassessed` stance and `candidate_only` evidence
  status. It is not an `EvidenceCard`, finding, claim update, confidence value,
  or persisted inference. Moving useful bytes into the record remains a
  separate explicit evidence operation with normal validation and audit.
- **The existing custody boundary is reused.** One query-only SQLite read
  snapshot resolves mission and corpus allowlists, selects a bounded total-order
  prefix, and runs the existing snapshot-integrity verifier before pure-Python
  scoring. SQL belongs to `LensService`, never the CLI. No schema migration or
  parallel source/evidence domain model is introduced.
- **Replay meaning is explicit.** The v1 receipt binds normalized query and
  SHA-256, Unicode database, algorithm/scoring version, sorted filters, bounds,
  searched snapshot identities and snapshot-set SHA-256, exact quote bytes and
  coordinates, score components, rank/tie-break, exclusions, omissions,
  truncation, semantic non-effects, and a complete receipt digest. It contains
  no random ID or timestamp.
- **Source correction semantics do not change.** Minerva models no source or
  snapshot retraction state, and immutable deletion remains forbidden. Evidence
  withdrawal and finding/inference retraction do not retract source bytes, so
  they do not remove a snapshot from Lens. The receipt says source-retraction
  metadata is not modeled; tampering fails closed.
- **No capability-manifest or packet change.** Lens is an operator/query CLI,
  not an authenticated external protocol surface. `minerva.capabilities.v2` and
  `minerva.research-brief.v2` remain byte/semantics unchanged; packet v3, MCP,
  Athena/external principals, signing, and cryptographic identity remain gated.

This decision does **not** authorize live web or scholarly API access, crawling,
PDF/OCR ingestion, embeddings, vector stores, mutable indexes, background work,
provider calls, autonomous adoption, publishing, messaging, or execution. Those
remain under their existing owner/security gates.
