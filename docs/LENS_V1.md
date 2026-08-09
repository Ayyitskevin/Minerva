# Lens v1: deterministic candidate-context retrieval

Status: search implemented under the repository owner's 2026-08-08 directive;
receipt verification and current-database exact reproduction implemented under the
owner's subsequent instruction to continue the accepted dependency order. A later
continuation separately accepts Review Dossier v1, which consumes the same captured
receipt and exact replay path without changing Lens search, verification, or adoption
semantics. The later Lens Evidence Adoption v1 decision adds a separate, explicit
evidence command; it does not make Lens search, verification, replay, or Dossier
mutating.

Lens is the narrow, local retrieval exception to the otherwise closed D-6
retrieval/ingestion gate. It searches only immutable UTF-8 snapshots that an
operator has already imported into one Minerva mission. It does not authorize
web/PDF/OCR ingestion, crawling, embeddings, vector databases, background
indexing, provider calls, or packet changes.

## Operator workflow

```bash
minerva lens search --db research.db --mission MIS_ID \
  --query "immutable provenance" --limit 10
```

Optional `--source` and `--snapshot` arguments are repeatable allowlists. When
both are present, Lens searches their intersection. Every supplied identifier
must resolve inside the named mission; unknown and cross-mission identifiers
produce the same non-reflective refusal.

The command writes one compact JSON object using the normal CLI output
convention. Its `lens` member is a `minerva.lens-search.v1` receipt containing
ordered `candidate_context` leads. It is simultaneously the machine-readable
result and the operator view: each candidate includes its rank, source label,
exact quote, byte range, score components, and deterministic explanation.

An operator may capture that complete stdout envelope and verify it without a
database, then separately ask the current database to reproduce it exactly:

```bash
minerva lens search --db research.db --mission MIS_ID \
  --query "immutable provenance" --limit 10 > lens-receipt.json
minerva lens verify --input lens-receipt.json
minerva lens replay --db research.db --input lens-receipt.json
```

`verify` means strict self-consistency verification of captured Lens v1 data.
`replay` means exact reproduction against one current local database read snapshot.
Neither word means that Minerva persisted a canonical Lens artifact, archived a
historical corpus, authenticated the producer, or authorized disclosure.

After those review steps, the separately accepted bridge can adopt one explicitly
confirmed candidate through normal evidence validation:

```bash
minerva evidence add-from-lens --db research.db \
  --mission MIS_ID --claim CLM_ID --lens-input lens-receipt.json \
  --candidate-rank 1 --stance supports \
  --expected-retrieval-receipt-sha256 RECEIPT_SHA256 \
  --expected-snapshot-sha256 SNAPSHOT_SHA256 \
  --expected-start-byte START --expected-end-byte END \
  --expected-quote-sha256 QUOTE_SHA256
```

That command is an evidence mutation, not a Lens command. Its exact current replay,
duplicate check, evidence creation, and two audit events share one immediate write
transaction. See [`LENS_EVIDENCE_ADOPTION_V1.md`](LENS_EVIDENCE_ADOPTION_V1.md).

## Scope and bounds

The request bounds are part of the receipt:

| Bound | Default | Allowed range |
| --- | ---: | ---: |
| Results | 20 | 1–100 |
| Snapshots | 50 | 1–200 |
| Searched snapshot bytes | 16 MiB | 1 byte–64 MiB |
| Bytes in one quoted logical line | 1,024 | 32–4,096 |

Queries are valid UTF-8 without NUL or surrogate code points, at most 512 bytes
after input and normalization checks, and contain 1–32 lexical terms. Each
normalized term is at most 128 UTF-8 bytes. Each source/snapshot allowlist accepts
at most 200 supplied entries, then canonicalizes them to unique, sorted identifiers.

Lens opens exactly one `Database.read()` snapshot and immediately enables
connection-local `PRAGMA query_only=ON`. Eligible snapshots are ordered by
`(imported_at, snapshot_id)`. It selects the deterministic prefix under the
snapshot limit and stops before the first whole snapshot that would exceed the
corpus-byte limit; it never skips that snapshot to opportunistically search a
later, smaller one. Every searched row passes the existing source import-audit,
length, SHA-256, encoding, and byte-integrity verifier before scoring.

## Algorithm `bounded-unicode-line-lexical` version `2`

1. Normalize query and candidate text by repeatedly applying Unicode NFKC and
   then full case folding until the value is unchanged. The equality-confirming
   application counts toward a four-application cap; failure to converge refuses
   instead of returning a partial normalization. Collapse Unicode whitespace to
   ASCII spaces, strip, and tokenize Unicode word runs. The resulting representation
   is a fixed point. The receipt records the Python Unicode database version because
   Unicode tables can differ between supported runtimes. This Minerva transform is
   specified directly and is not a claim to implement Unicode `NFKC_Casefold`.
   The receipt identifies it as
   `unicode-nfkc-then-casefold-fixed-point-cap4-whitespace-collapse-word-token-v2`.
2. Treat each nonempty logical line as one candidate passage. Exact byte spans
   exclude LF and the CR in CRLF. Source bytes are never normalized or changed.
3. Omit, rather than truncate, a line above `max_quote_bytes`; record the line
   count and byte count. Exclude and count empty and nonmatching passages.
4. Retain a line when it contains at least one query term. Rank by this total
   order, with all numeric components represented as integers:

   ```text
   exact contiguous query-token phrase                 descending
   distinct query terms matched                        descending
   total query-term occurrences                        descending
   occurrences * 1,000,000 // candidate term count    descending
   snapshot_id, start_byte, end_byte                   ascending
   ```

5. Derive `why` only from those recorded components. Lens has no generative or
   provider dependency and makes no semantic-relevance claim beyond this
   documented lexical rule.

The implementation retains only the best bounded results while counting every
matching passage inside the searched corpus. Therefore result-limit truncation
and the complete match count remain explicit without unbounded candidate
materialization.

## Reproduction receipt

Every result carries:

- mission, source, snapshot, digest, media type, and source-label identity;
- exact half-open UTF-8 byte coordinates, quote text, base64 quote bytes, and
  quote SHA-256;
- normalized query, terms, query digest, normalization/Unicode versions;
- algorithm and scoring versions, score components, explanation, rank, and
  stable tie-break fields;
- configured bounds and canonical source/snapshot allowlists;
- ordered identities of every searched snapshot and a snapshot-set digest;
- eligible/searched/omitted snapshot and byte counts, filter exclusions,
  passage exclusions/omissions, result-limit omissions, and truncation state;
- a SHA-256 over the complete receipt except its own digest field.

The snapshot-set digest is SHA-256 over compact, sorted-key JSON containing
`minerva.lens-snapshot-set.v1`, the mission ID, and searched snapshot identities
in search order. The query digest is SHA-256 over normalized UTF-8 query bytes.
No wall-clock time, random result ID, provider metadata, or machine-local path
enters the receipt.

## Captured-envelope intake

`minerva lens verify` and `minerva lens replay` accept exactly one compact or
pretty-printed JSON object with the search CLI's normal `{"lens": {...}}` envelope.
The operator may create that file by ordinary shell redirection; Minerva does not
export, overwrite, persist, or bless the captured file as a canonical artifact.

The shared standalone-file boundary:

- rejects parent path segments, symbolic links in any component, non-regular files,
  unreadable targets, and a target that changes across two descriptor-pinned reads;
- reads at most 8 MiB (8,388,608 bytes) and refuses an over-limit file before JSON
  decoding;
- requires strict UTF-8 JSON, rejects duplicate object fields and non-finite numbers,
  and bounds nesting/object/array shape before DTO construction;
- accepts no omitted or unknown envelope/receipt fields and applies producer-maximum list
  limits: 32 query terms, three tie-break fields, 200 searched snapshots, 100
  candidates, and 200 source or snapshot filter identifiers.

This protects the local parsing boundary, not the confidentiality of the captured
quotes. A successful maximum-size input may still disclose substantial mission text
to the trusted local operator.

## Database-free receipt verification

`minerva lens verify --input FILE` first applies the captured-envelope boundary and
then verifies all invariants derivable from the receipt itself:

- schema, result kind, algorithm, algorithm version, normalization version, scoring
  declaration, stable tie-break, semantic notice, and semantic-boundary constants;
- compatibility with the running Python Unicode database version;
- mission/source/snapshot identifier shapes, canonical filter sorting/uniqueness,
  bounds, normalized query/token correspondence, and query SHA-256;
- searched-snapshot identity uniqueness, media type/label shape, count and byte
  totals, corpus bounds, and snapshot-set SHA-256;
- omission/count/truncation arithmetic;
- candidate ranks, mission/source/snapshot relationships, byte-span bounds,
  base64/UTF-8/text equality, quote length and SHA-256, lexical score recomputation,
  deterministic `why`, span uniqueness, and total rank order; and
- the canonical whole-receipt SHA-256.

Success emits a `lens_receipt_verification` envelope containing a
`minerva.lens-receipt-verification.v1` report with `status: "verified"`,
`canonical_digest_verified: true`, `internal_consistency_verified: true`, and
`runtime_compatible: true`. It deliberately reports
`searched_snapshot_content_verified: false`: database-free verification cannot rehash
the source snapshots or prove that the claimed snapshot identities ever existed.
The fixed report contains only schema/kind/status, algorithm/runtime identity,
query/snapshot-set/receipt digests, bounded counts/flags, and its semantic boundary;
it does not repeat mission/source/snapshot IDs, labels, quotes, the input path, or
other receipt text.

The receipt digest and all recomputed fields establish internal consistency only. A
same-OS-user producer can create a different self-consistent receipt. Verification
does not establish origin, external authenticity, human identity, authority,
approval, source truth, evidence quality, corpus freshness, or permission to disclose
the quoted bytes.

## Current-database exact reproduction

`minerva lens replay --db DATABASE --input FILE` performs the full standalone
verification before constructing or opening the database. It then runs the captured
mission, canonical filters, deterministic bounds, normalized query, and query-token
sequence through the existing `LensService` search implementation in one current
query-only SQLite snapshot. The service's normal source-integrity verifier rechecks
every currently selected snapshot's stored bytes and import audit before scoring.

Replay uses a package-private execution seam instead of interpreting that verified
fixed-point representation as new raw operator input. The seam is not a second public
search algorithm, and ordinary callers still use `LensService.search(...)`.

Success requires dataclass equality of the newly produced and captured complete
receipts—not merely matching result quotes or digests. It therefore detects a changed
mission/filter count, eligible corpus prefix, snapshot identity/metadata/bytes, query
behavior, candidate, score, rank, omission, truncation flag, snapshot-set digest, or
receipt digest. Any same-mission snapshot append changes at least the mission/filter
accounting and causes a mismatch even when an explicit filter excludes that snapshot
and the candidate array is unchanged; foreign-mission changes are irrelevant.
The bounded `minerva.lens-replay.v1` report says `status: "reproduced"`,
`exact_receipt_match: true`, `current_database_snapshot_matched: true`,
`searched_snapshot_content_verified: true`, and `historical_corpus_replay: false`.
Its report uses the same non-reflective digest/count shape and does not echo private
receipt text or identifiers.

This is current-state reproduction, not historical replay. The captured receipt does
not contain every source byte, restore an old database state, force selection of only
its recorded snapshot IDs, or prove when the original search ran. New or changed
same-mission accounting or currently eligible state can legitimately cause a mismatch
even though immutable snapshot rows cannot be edited through Minerva.

## Stable refusal codes

Expected receipt/input/reproduction failures use CLI exit status `3` with one bounded,
non-reflective JSON error. `argparse` misuse remains exit `2`; unexpected local OS or
SQLite failures remain exit `4`; unexpected internal failures remain exit `1`.
After strict DTO parsing, the verifier requires a well-shaped matching canonical
receipt digest before it classifies a self-consistent schema, algorithm, or Unicode
runtime incompatibility. An ordinary un-rehashed field edit therefore reports
`lens_receipt_digest_mismatch`, not a version-specific code.

| Error code | Meaning |
| --- | --- |
| `lens_receipt_input_unsafe` | The selected path contains an unsafe component. |
| `lens_receipt_input_symlink` | A symbolic link occurs in the selected path. |
| `lens_receipt_input_not_found` | The selected input does not exist. |
| `lens_receipt_input_unreadable` | The target cannot be read through the safe regular-file boundary. |
| `lens_receipt_input_changed` | File/path identity or captured bytes changed during the stable read. |
| `lens_receipt_too_large` | The input exceeds 8 MiB. |
| `lens_receipt_malformed` | The input is not strict UTF-8 JSON or has invalid nesting. |
| `lens_receipt_duplicate_field` | A JSON object contains a duplicate field. |
| `lens_receipt_nonstandard_number` | JSON contains a non-finite/non-standard number. |
| `lens_receipt_too_complex` | JSON shape or a producer-bounded sequence exceeds its safety limit. |
| `lens_receipt_schema_unsupported` | The receipt schema is not Lens v1. |
| `lens_receipt_algorithm_unsupported` | Algorithm or normalization identity is not the pinned v1 contract. |
| `lens_receipt_runtime_incompatible` | The local Unicode database version differs from the receipt. |
| `lens_receipt_digest_mismatch` | The recorded receipt digest differs from its canonical payload. |
| `lens_receipt_invalid` | Strict DTO or derived semantic invariants fail. |
| `lens_replay_mismatch` | A valid receipt is not reproduced exactly by the current database selection. |

Replay may also return existing database-open, `database_migration_required`,
`mission_not_found`, or `snapshot_tampered` failures when current local state cannot
safely be searched. Legacy databases follow the normal explicit migration path; this
slice adds no migration and does not silently upgrade during a read. A captured
source/snapshot filter that no longer resolves is deliberately collapsed to
`lens_replay_mismatch`; the refusal does not reflect the missing identifier.

## Semantic boundary

A Lens result is a lead for review, never evidence. Lens itself cannot:

- create an evidence card or retract a finding;
- alter claim status, confidence, or any evidence stance;
- persist or promote an agent inference;
- modify source/snapshot bytes or write an audit event;
- expand beyond the mission and explicit allowlists;
- adopt a quote into the research record.

The candidate stance is always `unassessed` and its evidence status is always
`candidate_only`. Adoption remains separate: direct `evidence add` accepts an exact
quote and coordinates, while `evidence add-from-lens` requires a strictly verified,
currently reproduced candidate plus explicit receipt/snapshot/span/quote-digest
confirmation. Both require a claim, operator-supplied stance, local OS-user attribution, normal
integrity validation, and atomic audit. Search rank never supplies stance or epistemic
weight.

Minerva has no source/snapshot retraction state. Immutable source deletion is
blocked, and later evidence withdrawals, finding retractions, or inference
retractions do not erase or hide the underlying snapshot from Lens. The receipt
states `source_retraction_metadata: not_modeled`; corrupt or tampered snapshots
fail the existing integrity check instead of being silently omitted.

Verification and replay inherit and strengthen this non-effect boundary. They create
no identity, run, audit event, evidence card, finding, inference, status, correction,
confidence value, queue state, packet, export, or file; modify no database row or
source/snapshot byte; read no provider credential; and invoke no model, provider,
network, REST/web API, MCP, Athena/Icarus adapter, or external agent protocol. They add
no migration, index, capability-manifest entry, or packet field/version.

## Evaluation

Run the checked-in synthetic harness completely offline:

```bash
uv run python scripts/evaluate_lens.py
```

It creates two missions and eight deterministic sources, evaluates three labeled
queries, and emits integer-parts-per-million metrics for precision@3, recall@3, and
byte-span accuracy. The checked-in expected result remains 750,000 ppm precision,
1,000,000 ppm recall, and 1,000,000 ppm byte accuracy. Boolean checks cover receipt
verification, current-database exact reproduction, a self-consistent offline tamper
that replay rejects, same-mission corpus drift rejection, canonical-filter and
foreign-mission stability, canonical Unicode fixed-point replay, explicit-empty-filter
isolation, byte determinism, and mission isolation; unauthorized mutation count is
zero. Hostile-envelope/error classification, algorithm/runtime incompatibility,
snapshot tamper, legacy migration, installed-wheel behavior, and provider/network
non-invocation also remain invariant-level tests. These are fixture-bound regression
claims, not evidence of external authenticity or retrieval quality on an unseen
corpus.

## Known limits

- Retrieval is lexical and line-scoped; relevant paraphrases and useful passages
  split across lines may be missed.
- Long logical lines are disclosed as explicit omissions instead of partially
  quoted candidates.
- Unicode normalization semantics are runtime-versioned, not independently
  reimplemented by Minerva.
- Unicode normalization and case folding do not detect homoglyphs or confusable
  characters.
- A captured receipt is not a historical snapshot bundle; exact reproduction can fail
  after same-mission corpus accounting changes, even outside an explicit filter.
- Snapshot-set and receipt hashes establish deterministic self-consistency, not
  source truth, external authenticity, or cryptographic identity.

Review Dossier v1 may embed and reproduce a captured Lens receipt in the same current
query-only snapshot as Queue, focal Review, and focal Lineage. That co-location is an
operator-supplied review association only: a candidate is still unassessed and never
becomes claim evidence. The PROV-O/RO-Crate interoperability decision packet
is accepted only as non-authorizing architectural guidance; a public profile, proof
serializer, and canonical exporter remain separately owner-gated. The explicit
single-candidate bridge is now implemented under its own narrow decision and does not
change this read-only Lens contract.
