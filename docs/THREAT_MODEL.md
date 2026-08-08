# Current threat model: provenance foundation through Mission Research Queue v1

## Boundary and assets

Minerva is a single-user local application. The trusted principal is the OS account
that can read the database and start the process. Full authentication, multi-user
authorization, and remote access are explicitly deferred. The application must not
pretend a caller-supplied header is an authenticated identity.

Protected assets are source snapshot contents, local filesystem paths, provenance and
audit integrity, citation correctness, exported research artifacts, request/result
binding integrity, provider credentials, and the operator's control over which exact
evidence leaves the machine. Lens adds candidate quotes and deterministic retrieval
receipts to the protected local disclosure surface. Claim Review adds claim text,
correction reasons, finding/inference text, and deterministic structural receipts to
that same local disclosure surface. Claim Lineage Graph adds the complete typed
claim-owned provenance topology, exact citation bytes, source/snapshot metadata, and
correction/promotion relationships to that local disclosure surface; none of these
views adds external egress. Mission Research Queue adds mission-wide claim text,
structural review cues, related-record IDs, child review digests, and aggregate
receipts to the same protected local disclosure surface.

## Threats and controls

| Threat | Current controls | Residual risk |
| --- | --- | --- |
| Remote browser reaches local service | Default `127.0.0.1` bind; loopback Host and Origin allowlist; no permissive CORS | Malicious software already running as the OS user shares the trust boundary |
| Cross-site request forgery | Read-only HTML with no server-rendered form to forge; non-local Origin rejection for REST mutations; no cookie or ambient browser credential a forged request could replay | OS-user malware can read local state/process memory |
| Oversized or malformed requests | Whole-request byte cap before framework parsing; Pydantic field bounds; bounded pagination | Body buffering uses memory up to the configured cap |
| Oversized or adversarial research packet | Reject above 20 MiB before JSON decoding; strict fail-fast DTOs; bound JSON object width/depth and error classification; linear-time dependency and citation-supersession checks | A packet within the cap still consumes bounded parse and validation memory |
| Unsafe standalone packet path | Reject `..`; descriptor-relative component walk with `O_NOFOLLOW`; `O_PATH`-pin and type-check the final target before readable open; metadata cap before read; two stable reads | A trusted same-OS-user process can still coordinate changes outside the finite observation window |
| Hostile offline research request | Same no-follow stable-file boundary; 64 KiB cap before decode; strict canonical DTO/digest; duplicate/non-standard/shape/fanout defenses; exact prefix/hex IDs; unknown fields rejected | Digest self-consistency does not establish origin, authenticity, authority, disclosure permission, or freshness against a later database snapshot |
| Evidence cherry-picking or stale request | Only `complete_claim_ledger`; requested sorted active set must exactly equal the target claim's snapshot ledger; no stance filtering; withdrawn history retained | A producer can choose which claim to request; policy does not assess whether the mission itself is complete or research is true |
| Request scope crosses mission/claim boundary | Mission and claim resolved by parameterized primary-key lookups in one query-only read snapshot; claim mission checked; all missing/out-of-scope evidence fails closed with non-reflective errors | The trusted OS user who owns the database remains the security principal; no remote authorization exists |
| Lens query expands scope or injects SQL | Query and limits validated before DB open; parameterized values; allowlisted SQL composition only; source/snapshot allowlists intersect; every filter ID must resolve inside the named mission with the same non-reflective error | Candidate quotes intentionally disclose matching mission bytes to the local operator; an operator with database access already shares that boundary |
| Lens search mutates research or silently becomes evidence | One `Database.read()` snapshot plus connection-local `query_only`; no identity, audit, writer, evidence, finding, inference, provider, or export dependency; candidate DTOs say `unassessed`/`candidate_only`; table dump and main-file digest regression tests | A human can later create evidence from the lead, but only through the separately audited evidence command and explicit stance |
| Lens work or result amplification | Query/filter/result/snapshot/corpus-byte/quote-byte caps; deterministic whole-snapshot prefix; oversized lines omitted explicitly; bounded top-result retention; integer scoring | A corpus inside the 64 MiB maximum can contain many short lines and consume local CPU; v1 has a byte bound, not a SQLite instruction or wall-clock bound |
| Corrupt snapshot creates plausible Lens text | Existing snapshot length/digest/UTF-8/import-audit verifier runs on every searched row before scoring; corruption fails the search rather than being omitted | No external signature detects a coordinated same-OS-user rewrite of database bytes and audit history |
| Claim Review hides adverse or cross-mission correction state | Mission and claim are both required and shape-validated; unknown/foreign claims share one non-reflective refusal; question ownership and the complete contiguous status chain are mission-verified before status text is exposed; target evidence and mission-owned affected records are selected in one query-only snapshot; success is complete-or-refuse rather than paginated; foreign-owner text is never returned | Completeness is over records admitted by their stored owner rows to the named mission. If foreign keys/triggers were defeated and an owner was moved to another mission while a target-mission relationship was forged, owner-first queries exclude it; deep doctor, not a scoped view, detects that whole-file corruption |
| Claim Review mistakes counts or conflict for truth | Active/withdrawn stance counts are descriptive; status validity reuses the presence-only workflow rule; active support plus opposition is labeled only as a structural stance conflict; semantic-boundary fields forbid truth, confidence, or replacement-status claims | The view does not assess source quality, logical incompatibility, causal validity, or whether a human correction was justified |
| Claim Review work or output amplification | Evidence, affected-record, citation-relationship (including inspected promotion-target rows), actual distinct-snapshot-BLOB-byte, and SQLite-VM ceilings; declared/actual snapshot length is checked before BLOB materialization; statement/reason sizes are constrained by schema; any exceeded limit refuses the whole result | The VM ceiling depends on the local SQLite version/query plan and is not a portable elapsed-time or memory bound; a successful maximum-size receipt can still be large |
| Corrupt correction dependency creates plausible Claim Review output | Every admitted target/dependent citation uses the shared exact-byte verifier and snapshot cache; mission-composite correction links, citation scope, acyclic supersession scope, status derivation, and selected promotion target/content/citation/retraction lineage are checked or fail closed | The view does not independently reconcile every correction/audit event or foreign-mission owner row; deep doctor remains the whole-database referential/audit-integrity surface. Snapshot and receipt hashes are not an external signature |
| Claim Review mutates state or triggers external behavior | `Database.read()` plus `query_only`; no identity, writer, audit, export, provider, credential, network, adapter, or queue dependency; database dump and main-file-byte regression checks | The local operator may separately invoke existing audited correction commands after review |
| Claim Lineage silently expands scope or hides history | Both mission and claim are required and shape-validated; the owner question and complete status chain are mission-verified; all claim-owned evidence/findings/inferences/corrections/promotions and their citations are included or the build refuses; fixed exclusions name sibling claims, claimless findings, unreferenced snapshots, audit/run/export/candidate nodes, and reverse dependents | Completeness is the explicit owner-first `claim_owned_closure_v1`, not mission-wide or whole-database closure. Foreign-owner corruption and hidden reverse dependents remain deep-doctor concerns |
| Claim Lineage work or output amplification | Positive node, edge, citation-byte, actual distinct-snapshot-byte, final canonical-output-byte, and cumulative SQLite-VM ceilings; any exceeded bound raises `claim_lineage_work_limit` and returns no partial graph | The VM budget is SQLite-version/query-plan local rather than a wall-clock or memory bound; a successful maximum-size JSON receipt can still disclose substantial local text |
| Corrupt citation or correction topology creates a plausible graph | One query-only snapshot; complete scope/status resolution; shared exact citation and immutable-snapshot verification; mission/claim ownership and correction/promotion relationships checked before output; typed total ordering and node/edge/snapshot/whole-receipt digests | The scoped graph does not replace whole-database audit reconciliation, and no external signature detects a coordinated same-OS-user rewrite of graph state and integrity metadata |
| Claim Lineage is mistaken for truth or triggers action | Receipt fields say structural topology only and forbid truth/confidence/status recommendation; service has no identity, writer, audit, queue, export, provider, credential, network, packet, HTTP/web, MCP, or external-agent dependency | A human may make a separate audited correction after inspecting the graph; that later judgment and action are outside the graph receipt |
| Mission Queue leaks a foreign or silently omitted claim | Mission ID is shape-validated; every owner-admitted claim is enumerated in `(created_at, id)` order in one query-only snapshot; every claim gets a review summary/digest and every pinned cue gets an item; child Claim Review repeats mission/question/status/relationship checks; success is complete-or-refuse | Completeness is over stored mission ownership. Foreign-owner corruption created after disabling foreign keys/triggers remains deep-doctor territory; the trusted OS user can intentionally inspect any mission they can read |
| Mission Queue is mistaken for actionable, prioritized, or completable work | Receipt kind is `structural_review_cue`; fixed claim/catalog order is labeled presentation only; semantic fields forbid actionability, severity, priority, assignment, deferment, resolution, and completion; every current claim necessarily emits a gap or stance-conflict cue | The product name “queue” may still suggest task state to a reader who ignores the receipt boundary; historical correction cues intentionally persist because Queue v1 does not impose an action policy |
| Mission Queue work or output amplification | Aggregate claim, item, distinct verified-evidence-card, distinct stored quote-byte, affected-record, relationship, actual snapshot-byte, final canonical-output-byte, and cumulative SQLite-VM ceilings cover all child reviews; metadata-only quote-length and snapshot-length preflights refuse before oversized quote text or snapshot BLOBs reach Python; any exceeded bound raises `mission_research_queue_work_limit` and returns no prefix | The VM ceiling is SQLite-version/query-plan local rather than a wall-clock or general SQLite-memory bound; a successful maximum-size receipt can still disclose substantial mission text and record identifiers |
| Mission Queue corrupts provenance or invents reason codes | Connection-bound reuse of the pinned Claim Review v1 derivation in one query-only snapshot; child review schema/algorithm/version and digest retained; fixed exhaustive cue catalog; claim/review/item/whole-receipt digests; Claim Lineage is not invoked or reinterpreted as reason policy | Receipt hashes are not signatures and cannot detect a coordinated same-OS-user rewrite of database state and integrity metadata; a future Claim Review taxonomy requires an explicit queue-version decision |
| Mission Queue mutates state or triggers external behavior | No identity, writer, audit, assignment, completion, export, file, packet, provider, credential, network, graph, REST/web, MCP, or external-agent dependency; database dump/main-file and non-invocation regressions | A human may separately use an existing audited research/correction command after inspecting a cue; that later action is outside Queue v1 |
| Excessive work or text materialization during fulfillment | Bounded claim-history/preflight queries, one connection-local progress budget over the complete query-only snapshot, targeted audit and claim-scoped finding indexes (migration 0003) whose selection is asserted by an `EXPLAIN QUERY PLAN` regression test, and an exact-multiplicity NUL-safe storage-byte lower bound before full database text or snapshot content is returned to Python; exhaustion becomes non-reflective `brief_work_limit` before file writes | The SQLite budget limits virtual-machine instructions, not elapsed time; aggregate length queries inspect stored values and are not an SQLite-memory limit; final canonical byte validation remains authoritative; same-mission audit history that the claim-scoped query must examine row by row still consumes budget; the plan test is the only guard on index selection — `INDEXED BY` names `idx_findings_claim` so its absence fails at preparation, but `idx_audit_event_entity` is planner-selected and its absence degrades silently to a scan, and neither hint forces a seek if a predicate is later dropped |
| Script/HTML/Markdown injection | Jinja autoescape; CSP; stored text rendered as text/`pre`; no raw HTML Markdown mode | Future rich rendering requires a reviewed sanitizer policy |
| SQL injection | Parameterized SQL; dynamic choices selected from fixed enums/queries only | A future ad hoc query could violate the rule; tests and review remain necessary |
| Import traversal or symlink escape | Root-relative paths only; reject absolute/`..`; descriptor traversal with `O_NOFOLLOW`; regular-file and size checks | The OS user can still submit any directory they are authorized to choose as root |
| Secret ingestion | Common credential/private-key pattern rejection; bounded audit details; synthetic fixtures; safe errors | Pattern scans are defense in depth, not exhaustive data-loss prevention |
| Source mutation | Snapshot bytes stored in SQLite; SHA-256 and length checked; append-only triggers; import never references original afterward | Doctor/export detect partial or inconsistent corruption, but no external signature or anchor detects a determined same-OS-user coordinated rewrite |
| Citation forgery | Exact byte offsets and quote match at creation and export; cross-mission checks; stable IDs | Source assertions may themselves be false; Minerva records provenance, not truth |
| Audit rewriting | Same-transaction audit insert; update/delete triggers; `PRAGMA recursive_triggers` so conflict-resolution deletes cannot bypass them; no raw source content or paths in details | Direct file replacement by the OS user is outside the process boundary |
| Retraction used to erase or hide a statement | Findings are never edited or deleted; retraction is a separate append-only `finding_retractions` row with its own no-update/no-delete triggers, committed with its audit event; finding reads left-join that row so a retracted finding is still returned, marked with its reason, timestamp, and actor, while synthesis excludes it from the brief instead of asserting it; doctor enforces the triggers by packaged fingerprint and reconciles every retraction row against its audit event | Retraction records that a statement was withdrawn, not why it was wrong or whether the withdrawal was justified; an operator who retracts every inconvenient finding shortens the brief, and only the retained finding history and audit trail show that it happened |
| Export path attack | Fixed contained filenames; reject symlink/pre-existing targets; size bounds; cleanup after caught exceptions | Operator can intentionally select a sensitive directory; a process or power-loss crash can leave a partial new export, but existing files are never overwritten |
| Failure cleanup deletes state Minerva did not create | Opening uses a `mode=rw` URI and never creates or removes a file; fresh initialization stages privately and publishes with an exclusive hard link; pathname removal is reachable only from the device/inode-checked staging cleanup | A crash between the staged commit and publication can leave an orphan staging file for operator cleanup |
| Fulfillment mutates or coordinates work | Request validated before DB open; one query-only snapshot; identity/audit/mutation/export APIs absent; fixed local files only; no provider/network/transport surface | SQLite/file publication is not crash-atomic; a crash can leave a partial new output directory for operator cleanup |
| Result misbinding or coordination leakage | Minimal strict result contains only status, request digest, output schema, and exact file SHA-256; request/scope/result fields never enter canonical v2 | A scoped v2 packet separated from its request/result binding does not prove database completeness |
| Private-data disclosure in errors/API | Stable error codes; packet failures never reflect submitted content or paths; bounded packet inspection omits research text, labels, URLs, identities, and IDs; API omits import paths and snapshot content by default | Authorized source preview intentionally reveals selected source text locally |
| Unauthorized external evidence disclosure | Assistance previews the exact bounded JSON without network I/O; egress requires an explicit flag and matching fresh request digest; no API/web invocation | The trusted OS user can knowingly authorize sensitive material; secret scanning cannot determine confidentiality or disclosure rights |
| Credential disclosure | BYOK credentials are read only after confirmation from `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`; redacted in memory wrappers; never persisted or included in audit/output | Environment variables and process memory are visible to sufficiently privileged local software; provider/account compromise is outside Minerva |
| Prompt injection in research text | Claim/evidence JSON is labeled untrusted; fixed prompt forbids embedded instructions, tools, outside knowledge, and invented citations; active evidence IDs bound locally | Models can still follow malicious text or produce incorrect output; a human must review every candidate |
| Invalid or overreaching model output | Strict structured parsing, size/count bounds, citation membership, secret scan, contradiction-preserving prompt, post-call context revalidation | Validation cannot establish truth, reasoning quality, completeness, or freedom from subtle data leakage in otherwise allowed text |
| Provider retention, training, residency, or cost | Exact disclosure preview; fixed provider origins; one attempt; no fallback; OpenAI `store=false`; usage metadata when returned | Provider policy/account settings are external; every authorized request may be retained, processed, or charged despite local controls |
| Timeout or interrupted provider call | Bounded timeout; no automatic retry; requested event committed before call; unknown outcome recorded when control returns | Provider may process or bill a request whose response Minerva never receives; process death can leave only the requested event |
| Network or execution escalation | Network imports statically restricted to the two reviewed provider adapters; fixed API origins; proxy environment ignored; SDK header/account-routing environment controls fail closed; redirects, retries, fallback, tools, URL fetch, shell/subprocess, `posix_spawn`, `multiprocessing`, process pools, `webbrowser`, `ctypes`, asyncio DNS/socket helpers, notebook, plugin, and dynamic code loading prohibited; tests deny non-loopback sockets suite-wide | Dependency installation and loopback serving use the network stack outside research execution; provider SDK changes require review; static analysis cannot see dynamically constructed attribute access |

## Security invariants

- State-changing domain logic and its audit event commit or roll back together.
- Rejected requests never create success events.
- A failed database open creates no file and removes none. Only staging files
  whose device and inode Minerva recorded are ever unlinked.
- Milestone 1 defines no server-rendered web mutations. Any future unsafe form must
  require both an accepted local origin and a valid CSRF token.
- No endpoint accepts a filesystem path or an actor identity header.
- URL fields are metadata only and never dereferenced.
- Errors never include submitted source contents or absolute private paths.
- Standalone packet commands read only one no-follow regular file, apply the size cap
  before JSON decoding, and emit bounded metadata or fixed non-reflective errors.
- Request verification applies the same file discipline with a 64 KiB cap and opens no
  database, credential source, provider, or network. Fulfillment validates first, then
  uses one query-only snapshot under one cumulative SQLite work guard. Exhaustion creates
  no artifacts, Minerva state, or audit record.
- Lens resolves filters and searches verified bytes in one query-only mission snapshot.
  Its stable receipt reports query/corpus digests, algorithm and Unicode versions,
  exact byte spans, configured bounds, exclusions, omissions, and truncation. It
  performs no provider/network call and leaves all database and audit state unchanged.
- A Lens candidate is never evidence, a finding, an inference, confidence, or claim
  status. Adoption remains a separate explicit human mutation with normal validation
  and audit behavior.
- Claim Review returns one complete-or-refuse, mission-and-claim-scoped structural
  receipt from a query-only snapshot. Every cited snapshot is re-verified; success
  reports configured bounds, measured admitted work, correction/promotion provenance,
  semantic non-effects, and a whole-receipt digest without mutating any table or file.
- A Claim Review gap, active stance conflict, status-validity warning, or correction
  impact is not truth, confidence, quality, sufficiency, a status recommendation, or a
  correction. Human corrections remain separate audited operations.
- Claim Lineage returns one complete-or-refuse `claim_owned_closure_v1` from a single
  query-only snapshot. Success includes every admitted claim-owned status, evidence,
  finding, adopted inference, withdrawal, retraction, promotion, citation edge, and
  referenced snapshot, with exact quote text/base64 bytes, UTF-8 coordinates, digests,
  source/snapshot metadata, provenance, measured work, exclusions, and set/receipt
  hashes.
- Claim Lineage never silently expands to claimless findings, sibling claims,
  unreferenced snapshots, audit/run/export/candidate nodes, or reverse dependents. It
  never truncates a required node or edge; a bound exhaustion refuses the whole graph.
- A Claim Lineage node, edge, lifecycle state, count, or digest is structural recorded
  provenance, not truth, confidence, evidence quality, sufficiency, priority, a status
  recommendation, a correction, an adoption, or a work queue. Every mutation remains a
  separate explicit audited human operation.
- Mission Research Queue returns one complete-or-refuse
  `mission_claim_review_cues_v1` receipt from a single query-only snapshot. Every
  mission claim remains in the reviewed-claim and claim-set receipts; every pinned
  Claim Review v1 cue is bound to its source review digest and emitted in canonical
  presentation order.
- A Queue item is a non-normative structural review cue, not unresolved work, required
  action, severity, priority, confidence, assignment, deferment, resolution, or
  completion. Historical cues remain visible; Claim Lineage remains a separate
  topology inspection and supplies no Queue v1 reason codes.
- Mission Research Queue creates no persisted queue or research state, invokes no
  provider, credential, network, graph service, or external protocol, and returns no
  partial claim/cue prefix when aggregate work is exhausted.
- Retraction deletes nothing. Surfaces that read findings still return a retracted
  finding, marked with its reason, timestamp, and actor; synthesis surfaces exclude
  it from the brief rather than presenting it as asserted. Neither path can make the
  finding, its citations, or its history disappear.
- The complete-ledger active precondition prevents silent stance omission. Result
  bytes bind request digest to exact canonical output without paths, URLs, identity,
  authority, approval, timestamps, transport, or run-coordination metadata.
- Packet digest verification establishes self-consistency, not authenticity, origin,
  approval, truth, or independent verification of source bytes absent from the packet.
- Tests run the demo with outbound connection attempts denied.
- Assistance preview never reads a provider credential or calls a network.
- External model egress exists only in the CLI and requires an explicit confirmation
  plus the exact digest of the reviewed provider/model/destination/context/limits.
- Provider calls use fixed destinations with no automatic retry, redirect, fallback,
  tool use, or environment proxy. Tests use fakes and never contact live providers.
- Returned text is untrusted, ephemeral candidate `agent_inference`; it is not
  persisted, adopted, or promoted to evidence, truth, confidence, or claim status.
- Assistance audit events contain bounded metadata and digests, not credentials,
  prompts, evidence excerpts, responses, or candidates.

The transaction guarantees above cover SQLite domain operations, rejected requests,
and exceptions that return control to Minerva. They do not make a
database-plus-filesystem or database-plus-provider operation crash-atomic. Assistance
uses separate requested and terminal audit transactions around the external call;
process death can leave an unmatched request record. Standalone backups and exports
have no external signature or integrity anchor and must be protected by the operator.
Request fulfillment is database-read-only but its two filesystem writes have the same
caught-error versus process/power-loss limitation as existing export.

## Deferred decisions

Remote access, real authentication, encrypted storage, optional OS keyring support,
multi-tenancy, signed exports, additional providers, provider-side retrieval/tools,
and non-CLI integration authentication require a later threat model and explicit
product/security approval. Mission Research Queue v1 does not authorize a persistent
assign/defer/resolve queue, migration, external principal, cryptographic identity,
Athena/Icarus adapter, MCP or other agent protocol, packet revision, Lens replay,
Lens-to-evidence mutation, or canonical PROV-O/RO-Crate exporter.
