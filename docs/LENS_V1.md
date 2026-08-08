# Lens v1: deterministic candidate-context retrieval

Status: implemented under the repository owner's 2026-08-08 directive.

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

## Algorithm `bounded-unicode-line-lexical` version `1`

1. Normalize query and candidate text with Unicode NFKC, case folding, and
   whitespace collapse; tokenize Unicode word runs. The receipt records the
   Python Unicode database version because Unicode tables can differ between
   supported runtimes.
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

## Semantic boundary

A Lens result is a lead for review, never evidence. Lens itself cannot:

- create an evidence card or retract a finding;
- alter claim status, confidence, or any evidence stance;
- persist or promote an agent inference;
- modify source/snapshot bytes or write an audit event;
- expand beyond the mission and explicit allowlists;
- adopt a quote into the research record.

The candidate stance is always `unassessed` and its evidence status is always
`candidate_only`. Adoption remains the existing, separate `evidence add`
operation, which requires a claim, explicit stance, exact quote and coordinates,
local human identity, normal integrity validation, and an atomic audit record.

Minerva has no source/snapshot retraction state. Immutable source deletion is
blocked, and later evidence withdrawals, finding retractions, or inference
retractions do not erase or hide the underlying snapshot from Lens. The receipt
states `source_retraction_metadata: not_modeled`; corrupt or tampered snapshots
fail the existing integrity check instead of being silently omitted.

## Evaluation

Run the checked-in synthetic harness completely offline:

```bash
uv run python scripts/evaluate_lens.py
```

It creates two missions and five fixed sources, evaluates three labeled queries
twice, and emits integer-parts-per-million metrics for precision@3, recall@3,
and byte-span accuracy plus determinism, mission isolation, and unauthorized
mutation count. The checked-in expected result is 750,000 ppm precision,
1,000,000 ppm recall, 1,000,000 ppm byte accuracy, deterministic output, mission
isolation, and zero unauthorized mutations. This fixture is a regression harness,
not an external quality claim or canonical research packet.

## Known limits

- Retrieval is lexical and line-scoped; relevant paraphrases and useful passages
  split across lines may be missed.
- Long logical lines are disclosed as explicit omissions instead of partially
  quoted candidates.
- Unicode normalization semantics are runtime-versioned, not independently
  reimplemented by Minerva.
- Snapshot-set and receipt hashes establish deterministic self-consistency, not
  source truth, external authenticity, or cryptographic identity.
