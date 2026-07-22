# Milestone 1 threat model

## Boundary and assets

Minerva is a single-user local application. The trusted principal is the OS account
that can read the database and start the process. Full authentication, multi-user
authorization, and remote access are explicitly deferred. The application must not
pretend a caller-supplied header is an authenticated identity.

Protected assets are source snapshot contents, local filesystem paths, provenance and
audit integrity, citation correctness, and exported research artifacts.

## Threats and controls

| Threat | Milestone 1 controls | Residual risk |
| --- | --- | --- |
| Remote browser reaches local service | Default `127.0.0.1` bind; loopback Host and Origin allowlist; no permissive CORS | Malicious software already running as the OS user shares the trust boundary |
| Cross-site request forgery | Read-only HTML; non-local Origin rejection for REST mutations; signed SameSite CSRF primitive required before any unsafe form | OS-user malware can read local state/process memory |
| Oversized or malformed requests | Whole-request byte cap before framework parsing; Pydantic field bounds; bounded pagination | Body buffering uses memory up to the configured cap |
| Script/HTML/Markdown injection | Jinja autoescape; CSP; stored text rendered as text/`pre`; no raw HTML Markdown mode | Future rich rendering requires a reviewed sanitizer policy |
| SQL injection | Parameterized SQL; dynamic choices selected from fixed enums/queries only | A future ad hoc query could violate the rule; tests and review remain necessary |
| Import traversal or symlink escape | Root-relative paths only; reject absolute/`..`; descriptor traversal with `O_NOFOLLOW`; regular-file and size checks | The OS user can still submit any directory they are authorized to choose as root |
| Secret ingestion | Common credential/private-key pattern rejection; bounded audit details; synthetic fixtures; safe errors | Pattern scans are defense in depth, not exhaustive data-loss prevention |
| Source mutation | Snapshot bytes stored in SQLite; SHA-256 and length checked; append-only triggers; import never references original afterward | Doctor/export detect partial or inconsistent corruption, but no external signature or anchor detects a determined same-OS-user coordinated rewrite |
| Citation forgery | Exact byte offsets and quote match at creation and export; cross-mission checks; stable IDs | Source assertions may themselves be false; Minerva records provenance, not truth |
| Audit rewriting | Same-transaction audit insert; update/delete triggers; no raw source content or paths in details | Direct file replacement by the OS user is outside the process boundary |
| Export path attack | Fixed contained filenames; reject symlink/pre-existing targets; size bounds; cleanup after caught exceptions | Operator can intentionally select a sensitive directory; a process or power-loss crash can leave a partial new export, but existing files are never overwritten |
| Private-data disclosure in errors/API | Stable error codes; validation errors omit submitted values; API omits import paths and snapshot content by default | Authorized source preview intentionally reveals selected source text locally |
| Network or execution escalation | No URL fetching, HTTP client, model call, shell/subprocess, notebook, plugin, or dynamic code loading surface | Dependency installation and loopback serving use the network stack outside research execution |

## Security invariants

- State-changing domain logic and its audit event commit or roll back together.
- Rejected requests never create success events.
- Milestone 1 defines no server-rendered web mutations. Any future unsafe form must
  require both an accepted local origin and a valid CSRF token.
- No endpoint accepts a filesystem path or an actor identity header.
- URL fields are metadata only and never dereferenced.
- Errors never include submitted source contents or absolute private paths.
- Tests run the demo with outbound connection attempts denied.

The transaction guarantees above cover SQLite operations, rejected requests, and
exceptions that return control to Minerva. They do not make a database-plus-filesystem
operation crash-atomic. Standalone backups and exports have no external signature or
integrity anchor and must be protected by the operator.

## Deferred decisions

Remote access, real authentication, encrypted storage, OS keyring integration,
multi-tenancy, signed exports, and integration credentials require a later threat
model and explicit product/security approval.
