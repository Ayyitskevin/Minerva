# Current threat model: provenance foundation through Guided Evidence Intake v1

## Boundary and assets

Minerva is a single-user local application. The trusted principal is the OS account
that can read the database and start the process. Full authentication, multi-user
authorization, and remote access are explicitly deferred. The application must not
pretend a caller-supplied header is an authenticated identity.

Protected assets are source snapshot contents, local filesystem paths, provenance and
audit integrity, citation correctness, exported research artifacts, request/result
binding integrity, provider credentials, and the operator's control over which exact
evidence leaves the machine. Lens adds candidate quotes and deterministic retrieval
receipts to the protected local disclosure surface. Captured receipt verification and
current-database reproduction additionally treat the operator-selected receipt path,
quoted receipt contents, and bounded verification result as untrusted local input and
protected disclosure-bearing output; they add no egress. Claim Review adds claim text,
correction reasons, finding/inference text, and deterministic structural receipts to
that same local disclosure surface. Claim Lineage Graph adds the complete typed
claim-owned provenance topology, exact citation bytes, source/snapshot metadata, and
correction/promotion relationships to that local disclosure surface; none of these
views adds external egress. Mission Research Queue adds mission-wide claim text,
structural review cues, related-record IDs, child review digests, and aggregate
receipts to the same protected local disclosure surface. Review Dossier combines
those mission-wide and claim-scoped disclosures with exact Lens quotes, component
digests, and structural cross-checks in one potentially large local result. It remains
inside the trusted OS-user boundary and adds no egress. Lens Evidence Adoption adds
the integrity of the operator's explicit candidate confirmations and the durable link
between one reproduced receipt candidate, one evidence card, and two append-only audit
events. It adds no new disclosure destination.
Guided Evidence Intake adds bounded exact-quote context and a digest-bound local
preview to that disclosure surface. Filing remains inside the same trusted OS-user
boundary and creates only one normal evidence card and its existing audit event.

## Threats and controls

| Threat | Current controls | Residual risk |
| --- | --- | --- |
| Remote browser reaches local service | Default `127.0.0.1` bind; loopback Host and Origin allowlist; no permissive CORS | Malicious software already running as the OS user shares the trust boundary |
| Cross-site request forgery or stale cockpit replay | Unsafe forms require one accepted same-origin `Origin` plus a signed double-submit token in an `HttpOnly`, `SameSite=Strict` cookie and exact form field; claim status requires the current claim version; claim/finding creation requires the current mission audit sequence inside the same immediate transaction | Same-OS-user malware can read process memory and act as the trusted principal; a process restart invalidates open forms |
| Oversized or malformed requests | Whole-request byte cap before framework parsing; strict exact URL-encoded form contracts; Pydantic field bounds; bounded pagination | Body buffering uses memory up to the configured cap |
| Oversized or adversarial research packet | Reject above 20 MiB before JSON decoding; strict fail-fast DTOs; bound JSON object width/depth and error classification; linear-time dependency and citation-supersession checks | A packet within the cap still consumes bounded parse and validation memory |
| Unsafe standalone packet path | Reject `..`; descriptor-relative component walk with `O_NOFOLLOW`; `O_PATH`-pin and type-check the final target before readable open; metadata cap before read; two stable reads | A trusted same-OS-user process can still coordinate changes outside the finite observation window |
| Hostile offline research request | Same no-follow stable-file boundary; 64 KiB cap before decode; strict canonical DTO/digest; duplicate/non-standard/shape/fanout defenses; exact prefix/hex IDs; unknown fields rejected | Digest self-consistency does not establish origin, authenticity, authority, disclosure permission, or freshness against a later database snapshot |
| Evidence cherry-picking or stale request | Only `complete_claim_ledger`; requested sorted active set must exactly equal the target claim's snapshot ledger; no stance filtering; withdrawn history retained | A producer can choose which claim to request; policy does not assess whether the mission itself is complete or research is true |
| Request scope crosses mission/claim boundary | Mission and claim resolved by parameterized primary-key lookups in one query-only read snapshot; claim mission checked; all missing/out-of-scope evidence fails closed with non-reflective errors | The trusted OS user who owns the database remains the security principal; no remote authorization exists |
| Lens query expands scope or injects SQL | Query and limits validated before DB open; parameterized values; allowlisted SQL composition only; source/snapshot allowlists intersect; every filter ID must resolve inside the named mission with the same non-reflective error | Candidate quotes intentionally disclose matching mission bytes to the local operator; an operator with database access already shares that boundary |
| Lens search mutates research or silently becomes evidence | One `Database.read()` snapshot plus connection-local `query_only`; no identity, audit, writer, evidence, finding, inference, provider, or export dependency; candidate DTOs say `unassessed`/`candidate_only`; table dump and main-file digest regression tests | A human can later create evidence from the lead, but only through the separately audited evidence command and explicit stance |
| Lens work or result amplification | Query/filter/result/snapshot/corpus-byte/quote-byte caps; deterministic whole-snapshot prefix; oversized lines omitted explicitly; bounded top-result retention; integer scoring | A corpus inside the 64 MiB maximum can contain many short lines and consume local CPU; v1 has a byte bound, not a SQLite instruction or wall-clock bound |
| Corrupt snapshot creates plausible Lens text | Existing snapshot length/digest/UTF-8/import-audit verifier runs on every searched row before scoring; corruption fails the search rather than being omitted | No external signature detects a coordinated same-OS-user rewrite of database bytes and audit history |
| Hostile captured Lens receipt or path exhausts/redirects verification | Shared descriptor-pinned no-follow stable regular-file reader; reject parent segments, symlinks, non-regular/changing files; 8 MiB cap before decode; strict UTF-8 JSON, duplicate/non-standard-number rejection, bounded shape/fanout, strict frozen DTOs with unknown fields forbidden; fixed non-reflective errors | A valid maximum-size receipt can still consume bounded local parse memory and disclose substantial quoted mission text to the trusted OS user |
| A self-consistent forged receipt is mistaken for authentic history | Database-free verification recomputes schema/algorithm/runtime, query/snapshot/quote digests, score/order, counts/omissions/truncation, semantic constants, and the whole-receipt digest; output explicitly says snapshot content was not verified and authenticity/origin/authority/approval/freshness/disclosure permission are unestablished | A same-OS-user producer can construct a different internally valid receipt; there is no signature, cryptographic identity, trusted timestamp, historical database archive, or external integrity anchor |
| Lens reproduction hides current corpus or algorithm drift | Strict receipt verification precedes DB construction/open; runtime and algorithm incompatibility fail separately; the captured normalized query/tokens, canonical filters, and bounds run through the existing query-only search/integrity path; the complete newly built receipt must equal the captured one or `lens_replay_mismatch` | Reproduction is current-state exact comparison, not as-of replay. Any same-mission snapshot append changes mission/filter accounting and therefore mismatches even if excluded by an explicit filter; only foreign-mission changes are irrelevant |
| Lens verification/reproduction mutates state or triggers external behavior | Pure verifier plus one `Database.read()`/`query_only` replay; no identity, writer, audit, export, provider, credential, network, REST/web, MCP, packet, capability, or external-agent dependency; dump/main-file/non-invocation regressions | The operator may separately retain the shell-captured receipt or invoke an existing audited evidence command; those actions are outside verify/replay |
| Hostile or mistaken Lens adoption selects different bytes than the operator reviewed | Safe captured-file load and strict receipt verification complete before database open; mission must equal the explicit mission; one-based rank plus expected receipt digest, snapshot digest, exact byte span, and quote digest must all match the selected candidate; normal exact-citation validation runs again | Confirmations prove equality to the selected self-consistent receipt, not that the operator understood the text, chose the right claim/stance, or had disclosure rights |
| Lens receipt or database changes between review and adoption | The complete verified receipt is reproduced through the normal Lens integrity/search path inside the same `BEGIN IMMEDIATE` transaction as evidence creation and audit; any corpus/result/omission/order/digest mismatch refuses | This is equality to current local state, not historical/as-of replay or authenticated receipt origin; a same-OS-user attacker controlling the database and receipt remains inside the trust boundary |
| Concurrent or repeated Lens adoption duplicates an evaluation | `BEGIN IMMEDIATE` serializes an exact tuple check and insert; duplicate identity includes mission, claim, snapshot identity/digest, span, quote, stance, and supersession and includes withdrawn cards | A different stance or explicit supersession target is intentionally a distinct operator evaluation and can be contradictory; Minerva does not decide which evaluation is correct |
| Lens adoption bypasses evidence or correction rules | On the caller-owned transaction, the bridge first applies the evidence package's bounded predecessor-chain check, then calls the existing evidence insert seam with its normal direct-target, claim/snapshot mission, exact UTF-8 byte, immutable-snapshot, and stance checks; it never auto-withdraws an older card | A trusted operator can deliberately record a poor or contradictory stance. Supersession remains lineage and does not itself deactivate the prior card |
| Lens rank/digest is mistaken for truth, confidence, or authority | Required operator-supplied stance; result and docs say rank is selector-only; semantic-boundary flags deny truth/quality/confidence/status/finding/inference effects; receipt digest is labeled self-consistency only | A consumer that ignores the typed boundary can still overinterpret a highly ranked candidate or a SHA-256 value |
| Lens adoption succeeds without attributable audit provenance | Evidence insert, normal `evidence.card.created`, and bounded `lens.candidate.adopted` share one immediate transaction; before commit the service requires exactly adjacent creation/adoption rows, canonical details and metadata, and stored/returned adoption audit-event ID equality, so a silent or forged injected sink raises `lens_adoption_audit_invalid` and rolls back card/events/new run; deep doctor independently reconciles durable state; query/quote/path text is omitted | No external signature or trusted timestamp prevents a determined same-OS-user coordinated rewrite of database and audit history |
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
| Hostile or foreign Lens input is smuggled into a dossier | Existing no-follow 8 MiB reader and strict Lens verifier run before database construction/open; receipt mission must equal the explicit dossier mission; exact reproduction through the normal Lens integrity/search path is the first operation in the shared read snapshot | The captured receipt remains unauthenticated operator-managed CLI output, and a same-OS-user producer can construct a different internally valid receipt for current state |
| Dossier components observe different states or silently disagree | One `Database.read()`/`query_only` snapshot owns Lens reproduction, Queue plus its retained focal Review, and focal Lineage; fixed cross-checks require scope, summary, cue, receipt, claim, status, exact evidence/withdrawal, Review-reported claim-owned citation/retraction/promotion payload and provenance, shared-snapshot, and replay agreement; any false check refuses the whole result | The affected-record check covers the claim-owned subset reported by Review, while Lineage can contain additional unaffected owned records. Cross-checks reconcile overlapping stored structure, not semantic relevance, entailment, source quality, whole-database audit integrity, or external authenticity; disjoint Lens/Lineage snapshot sets are allowed |
| Dossier composition turns a Lens lead, Queue cue, or Lineage edge into truth or action | Explicit semantic fields say the Lens association is operator-supplied, candidates are unassessed/non-evidence, Queue items are not tasks, Lineage edges establish no truth, and human correction/adoption remains separate and audited | A reader who ignores the embedded semantic boundary can still overinterpret co-location in one large document |
| Dossier work or output amplification | Existing Queue, Review, Lineage, Lens, snapshot/citation, and child-output bounds remain active; one cumulative SQLite-VM ceiling covers all database work; queue/lineage VM bound fields must equal it; final canonical dossier bytes have a 128 MiB ceiling; completion is all-or-nothing while Lens retains explicit bounded truncation | SQLite VM steps are runtime/query-plan local rather than wall-clock or memory bounds; a valid maximum-size dossier duplicates component content and can disclose substantial local research text |
| Dossier mutates state, persists an artifact, or triggers external behavior | Service has no identity, writer, audit, exporter, credential, provider, network, REST/web, packet, capability, MCP, or external-agent dependency; CLI emits stdout only; database dump/main-file and non-invocation regressions | The OS user can redirect stdout or separately invoke audited correction/adoption commands; those operator actions are outside the dossier service |
| Excessive work or text materialization during fulfillment | Bounded claim-history/preflight queries, one connection-local progress budget over the complete query-only snapshot, targeted audit and claim-scoped finding indexes (migration 0003) whose selection is asserted by an `EXPLAIN QUERY PLAN` regression test, and an exact-multiplicity NUL-safe storage-byte lower bound before full database text or snapshot content is returned to Python; exhaustion becomes non-reflective `brief_work_limit` before file writes | The SQLite budget limits virtual-machine instructions, not elapsed time; aggregate length queries inspect stored values and are not an SQLite-memory limit; final canonical byte validation remains authoritative; same-mission audit history that the claim-scoped query must examine row by row still consumes budget; the plan test is the only guard on index selection — `INDEXED BY` names `idx_findings_claim` so its absence fails at preparation, but `idx_audit_event_entity` is planner-selected and its absence degrades silently to a scan, and neither hint forces a seek if a predicate is later dropped |
| Script/HTML/Markdown injection | Jinja autoescape; CSP; stored text rendered as text/`pre`; no raw HTML Markdown mode | Future rich rendering requires a reviewed sanitizer policy |
| SQL injection | Parameterized SQL; dynamic choices selected from fixed enums/queries only | A future ad hoc query could violate the rule; tests and review remain necessary |
| Import traversal or symlink escape | Root-relative paths only; reject absolute/`..`; descriptor traversal with `O_NOFOLLOW`; regular-file and size checks | The OS user can still submit any directory they are authorized to choose as root |
| Secret ingestion | Common credential/private-key pattern rejection; bounded audit details; synthetic fixtures; safe errors | Pattern scans are defense in depth, not exhaustive data-loss prevention |
| Source mutation | Snapshot bytes stored in SQLite; SHA-256 and length checked; append-only triggers; import never references original afterward | Doctor/export detect partial or inconsistent corruption, but no external signature or anchor detects a determined same-OS-user coordinated rewrite |
| Citation forgery | Exact byte offsets and quote match at creation and export; cross-mission checks; stable IDs | Source assertions may themselves be false; Minerva records provenance, not truth |
| Intake selects the wrong repeated quote | Preview returns all exact and overlapping occurrences in byte order with bounded context; filing requires an explicit one-based rank and regenerates the digest-bound preview in the write transaction | Exact matching and context cannot determine semantic relevance; the trusted operator can still choose the wrong occurrence or stance |
| Stale or replayed intake duplicates evidence | Preview binds mission audit sequence, snapshot identity/digest, quote, candidates, semantic boundary, and context; `BEGIN IMMEDIATE` checks the sequence and digest before a tuple-complete duplicate refusal and insert; the creation audit postcondition is required before commit | Re-previewing after unrelated same-mission work is required. A different stance or explicit supersession is intentionally a distinct evaluation |
| Intake amplifies local work or silently truncates candidates | Imported snapshots retain their existing byte cap; quotes retain the evidence cap; context is fixed at 80 bytes per side; more than 100 exact occurrences refuses rather than returning a prefix | A near-limit source and quote can still consume local CPU and emit substantial but bounded local text |
| Intake becomes model-assisted or expands the trust boundary | Exact byte matching only; no provider, network, URL fetch, PDF/OCR/HTML extraction, file path, source import, API/web/MCP adapter, or generic mutation surface; semantic flags deny truth/confidence/stance inference | Future richer extraction requires a new reviewed threat model and cannot inherit this approval |
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
- Every server-rendered mutation requires one accepted local Origin, a valid signed
  double-submit CSRF token, an exact form contract, and a current domain precondition;
  rejected or stale forms create no run, domain state, or audit event.
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
- Captured Lens receipt intake is limited to one no-follow stable regular file no
  larger than 8 MiB and strictly verifies structure, canonical digest, query/snapshot
  relationships, quote bytes, deterministic scoring/order, and count/omission
  arithmetic. Database-free verification explicitly does not claim snapshot-content
  verification or authenticity.
- Lens reproduction verifies first, then performs one normal current-database Lens
  read with the captured normalized representation and requires exact receipt
  equality. It is not historical/as-of replay, persists nothing, and any same-mission
  snapshot append causes a mismatch even if a filter excludes that snapshot.
- A Lens candidate is never evidence, a finding, an inference, confidence, or claim
  status. `evidence add-from-lens` is a separate explicit trusted-local-operator mutation: it requires
  exact candidate confirmations and stance, reproduces current state, and uses normal
  validation and audit behavior.
- Lens evidence adoption creates exactly one evidence card and no other semantic
  state. Receipt replay, exact duplicate refusal, evidence creation, and both audit
  events share one `BEGIN IMMEDIATE`; a refusal leaves none of them. Search, verify,
  replay, and dossier remain query-only.
- Adoption rank is selection order only. It cannot calculate confidence, choose
  stance, alter claim status, create/retract findings, persist inference, withdraw
  earlier evidence, change source/snapshot bytes, or authorize bulk adoption.
- Guided intake preview is a read-only, bounded, digest-bound local DTO over one
  mission/claim/snapshot and exact quote. It returns all candidates or refuses; it is
  not a packet, draft, evidence card, stance, model result, or truth assessment.
- Guided intake filing requires one explicit candidate and stance, exact preview and
  snapshot digests, and the current mission audit sequence. Preview regeneration,
  duplicate refusal, normal evidence creation, and audit-postcondition verification
  share one immediate transaction; any failure leaves no new evidence or audit row.
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
- Review Dossier verifies one captured Lens receipt before database open, then exactly
  reproduces it, builds Queue with its retained focal Review, and builds focal Lineage
  inside one current query-only snapshot under one cumulative work guard. All five
  component receipts and every declared cross-check are bound into the deterministic
  result; failure returns no partial dossier.
- Dossier completeness does not mean unbounded retrieval: the embedded Lens omissions
  and `lens_retrieval_truncated` remain explicit. Composition makes no candidate/claim
  relevance, evidence, task, truth, confidence, priority, correction, or adoption
  claim and creates no persisted dossier, audit event, or external interaction.
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
product/security approval. The accepted Lens Evidence Adoption slice does not
authorize a persistent assign/defer/resolve queue, migration, external principal,
cryptographic identity, Athena/Icarus adapter, MCP or other agent protocol, packet
revision, bulk/automatic adoption, or canonical PROV-O/RO-Crate exporter. The
[PROV-O/RO-Crate interoperability decision packet](PROVENANCE_INTEROPERABILITY_DECISION_PACKET.md)
is accepted only as non-authorizing architectural guidance: it records the offline-
context, disclosure, identity, canonicalization, and correction-semantics threats,
while a profile, context asset, serializer, source-byte mode, exporter, and publication
surface remain separate owner decisions.
