# Current threat model: Milestone 1 and Milestone 2B

## Boundary and assets

Minerva is a single-user local application. The trusted principal is the OS account
that can read the database and start the process. Full authentication, multi-user
authorization, and remote access are explicitly deferred. The application must not
pretend a caller-supplied header is an authenticated identity.

Protected assets are source snapshot contents, local filesystem paths, provenance and
audit integrity, citation correctness, exported research artifacts, provider
credentials, and the operator's control over which exact evidence leaves the machine.

## Threats and controls

| Threat | Current controls | Residual risk |
| --- | --- | --- |
| Remote browser reaches local service | Default `127.0.0.1` bind; loopback Host and Origin allowlist; no permissive CORS | Malicious software already running as the OS user shares the trust boundary |
| Cross-site request forgery | Read-only HTML; non-local Origin rejection for REST mutations; signed SameSite CSRF primitive required before any unsafe form | OS-user malware can read local state/process memory |
| Oversized or malformed requests | Whole-request byte cap before framework parsing; Pydantic field bounds; bounded pagination | Body buffering uses memory up to the configured cap |
| Oversized or adversarial research packet | Reject above 20 MiB before JSON decoding; strict DTO bounds; linear-time citation supersession validation | A packet within the cap still consumes bounded parse and validation memory |
| Script/HTML/Markdown injection | Jinja autoescape; CSP; stored text rendered as text/`pre`; no raw HTML Markdown mode | Future rich rendering requires a reviewed sanitizer policy |
| SQL injection | Parameterized SQL; dynamic choices selected from fixed enums/queries only | A future ad hoc query could violate the rule; tests and review remain necessary |
| Import traversal or symlink escape | Root-relative paths only; reject absolute/`..`; descriptor traversal with `O_NOFOLLOW`; regular-file and size checks | The OS user can still submit any directory they are authorized to choose as root |
| Secret ingestion | Common credential/private-key pattern rejection; bounded audit details; synthetic fixtures; safe errors | Pattern scans are defense in depth, not exhaustive data-loss prevention |
| Source mutation | Snapshot bytes stored in SQLite; SHA-256 and length checked; append-only triggers; import never references original afterward | Doctor/export detect partial or inconsistent corruption, but no external signature or anchor detects a determined same-OS-user coordinated rewrite |
| Citation forgery | Exact byte offsets and quote match at creation and export; cross-mission checks; stable IDs | Source assertions may themselves be false; Minerva records provenance, not truth |
| Audit rewriting | Same-transaction audit insert; update/delete triggers; no raw source content or paths in details | Direct file replacement by the OS user is outside the process boundary |
| Export path attack | Fixed contained filenames; reject symlink/pre-existing targets; size bounds; cleanup after caught exceptions | Operator can intentionally select a sensitive directory; a process or power-loss crash can leave a partial new export, but existing files are never overwritten |
| Private-data disclosure in errors/API | Stable error codes; validation errors omit submitted values; API omits import paths and snapshot content by default | Authorized source preview intentionally reveals selected source text locally |
| Unauthorized external evidence disclosure | Assistance previews the exact bounded JSON without network I/O; egress requires an explicit flag and matching fresh request digest; no API/web invocation | The trusted OS user can knowingly authorize sensitive material; secret scanning cannot determine confidentiality or disclosure rights |
| Credential disclosure | BYOK credentials are read only after confirmation from `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`; redacted in memory wrappers; never persisted or included in audit/output | Environment variables and process memory are visible to sufficiently privileged local software; provider/account compromise is outside Minerva |
| Prompt injection in research text | Claim/evidence JSON is labeled untrusted; fixed prompt forbids embedded instructions, tools, outside knowledge, and invented citations; active evidence IDs bound locally | Models can still follow malicious text or produce incorrect output; a human must review every candidate |
| Invalid or overreaching model output | Strict structured parsing, size/count bounds, citation membership, secret scan, contradiction-preserving prompt, post-call context revalidation | Validation cannot establish truth, reasoning quality, completeness, or freedom from subtle data leakage in otherwise allowed text |
| Provider retention, training, residency, or cost | Exact disclosure preview; fixed provider origins; one attempt; no fallback; OpenAI `store=false`; usage metadata when returned | Provider policy/account settings are external; every authorized request may be retained, processed, or charged despite local controls |
| Timeout or interrupted provider call | Bounded timeout; no automatic retry; requested event committed before call; unknown outcome recorded when control returns | Provider may process or bill a request whose response Minerva never receives; process death can leave only the requested event |
| Network or execution escalation | Network imports statically restricted to the two reviewed provider adapters; fixed API origins; proxy environment ignored; SDK header/account-routing environment controls fail closed; redirects, retries, fallback, tools, URL fetch, shell/subprocess, notebook, plugin, and dynamic code loading prohibited | Dependency installation and loopback serving use the network stack outside research execution; provider SDK changes require review |

## Security invariants

- State-changing domain logic and its audit event commit or roll back together.
- Rejected requests never create success events.
- Milestone 1 defines no server-rendered web mutations. Any future unsafe form must
  require both an accepted local origin and a valid CSRF token.
- No endpoint accepts a filesystem path or an actor identity header.
- URL fields are metadata only and never dereferenced.
- Errors never include submitted source contents or absolute private paths.
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

## Deferred decisions

Remote access, real authentication, encrypted storage, optional OS keyring support,
multi-tenancy, signed exports, additional providers, provider-side retrieval/tools,
and non-CLI integration authentication require a later threat model and explicit
product/security approval.
