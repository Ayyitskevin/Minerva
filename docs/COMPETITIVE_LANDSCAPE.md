# Competitive landscape: provenance-first research systems

Reviewed 2026-08-08 from official product documentation, specifications, and
primary repositories. **D** means the cited source documents the capability.
**I** means a Minerva product inference, usually that the reviewed material did
not document a stronger guarantee; absence from documentation is not proof that
an internal implementation lacks it.

## Research products and adjacent open systems

| Dimension | Elicit | Consensus | PaperQA2 | STORM / Co-STORM | ChatGPT deep research | Minerva |
| --- | --- | --- | --- | --- | --- | --- |
| Discovery and ingestion | **D:** 138M-paper and trials search, PubMed, imports, uploads | **D:** 220M+ paper index, publisher/full-text access, uploads | **D:** PDF, text, Office, code, metadata APIs | **D:** configurable web and corpus retrievers | **D:** public web, uploaded files, connected apps | **D:** explicit local UTF-8 import only |
| Local corpus and web retrieval | **D:** hosted corpus and user data | **D:** hosted corpus, collections, full text | **D:** local full-text index; optional APIs/models | **D:** web and local vector-retriever configurations | **D:** hosted web/app research | **D:** Lens searches only mission-owned immutable snapshots; no web fetch |
| Exact citation provenance | **D:** sentence/figure-backed quotes. **I:** immutable bytes, content hashes, and byte coordinates were not documented | **D:** papers, inline citations, extracted answers. **I:** immutable bytes and byte coordinates were not documented | **D:** passage/page citations. **I:** no immutable-byte coordinate contract was found | **D:** report citations. **I:** no exact immutable span contract was found | **D:** citations and source links. **I:** no immutable-byte coordinate contract was found | **D:** snapshot SHA-256 plus exact half-open UTF-8 byte span, quote text, base64 bytes, and quote digest |
| Claim/evidence relationship | **D:** screening/extraction decisions and claims backed by source sentences | **D:** Claims & Evidence, paper-level answers, cited synthesis | **D:** chunk evidence selected for generated answers | **D:** cited report synthesis | **D:** cited structured reports | **D:** explicit claim, evidence-card, stance, finding, and labeled-inference types; Lens candidates are separate; Claim Lineage exposes their complete typed claim-owned topology |
| Contradiction, correction, retraction | **D:** screening decisions are editable; API defaults to excluding retracted papers | **D:** Yes/No/Possibly/Mixed meter; retracted badge and exclusion from analyses | **D:** `contracrow` and metadata retraction checks | **I:** no durable correction/retraction lifecycle was found | **I:** no append-only correction/retraction lifecycle was found | **D:** four evidence stances, append-only withdrawals/retractions, supersession lineage, retained history, Claim Review's correction impacts, and Claim Lineage's retained corrected nodes/edges |
| Human review and adoption | **D:** override, dual review, collaborative screening, PRISMA audit | **D:** saved collections, visible classifications, feedback and exports | **D:** manual and agentic modes | **D:** Co-STORM supports human steering | **D:** user reviews/edits the plan, can interrupt, and receives activity/source history | **D:** local human mutation authority; generated candidates require separate explicit adoption/promotion; Claim Review supplies cues and Mission Research Queue aggregates them without assigning priority, action, or completion |
| Agent-facing interface | **D:** REST API and OAuth MCP | **D:** REST API, ChatGPT app, OAuth MCP | **D:** Python API, CLI, agent tools | **D:** Python application/retriever interfaces | **D:** ChatGPT UI and connected-app reads | **D:** deterministic CLI, public local Python Lens/review/lineage/queue/dossier services, and strict packet/request files; authenticated external APIs and MCP remain owner-gated |
| Local/offline operation | **I:** hosted service is the documented primary surface | **I:** hosted service is the documented primary surface | **D:** local files and local model/embedding configurations are supported | **D:** code is locally runnable; normal workflows use models/retrievers | **I:** hosted service is required | **D:** core research, Lens search/receipt checking, Claim Review, Claim Lineage, Mission Research Queue, and Review Dossier are offline after installation; provider assistance is a narrow opt-in exception |
| Deterministic replay/export | **D:** keyword search is described as reproducible/deterministic; PRISMA and data exports. **I:** no full retrieval receipt was found | **D:** Paper Search is called deterministic; CSV/RIS/bibliography/PDF exports. **I:** corpus/algorithm replay receipt not documented | **I:** mutable files, configurable models, and agent workflows do not establish byte-identical replay | **I:** live retrieval and LLM generation do not establish byte-identical replay | **D:** Markdown/Word/PDF export. **I:** byte-identical replay was not documented | **D:** canonical packet bytes plus Lens, Claim Review, Claim Lineage, Queue, and Dossier receipts use stable ordering, explicit versions, bounded completion, and SHA-256; Dossier exactly reproduces a captured Lens receipt and cross-checks all component views in one current snapshot, explicitly not as historical replay or a persisted export |
| Auditability | **D:** PRISMA flow, exclusion reasons, criteria scores, quotes, search strategies | **D:** cited inputs and visible contributing papers; library/history surfaces | **D:** stored indexes/answers and configurable callbacks | **D:** cited report and Co-STORM working state | **D:** source list and activity history | **D:** append-only mutation audit plus independently inspectable retrieval/review receipts, strict Lens self-check/current reproduction, typed exact-citation lineage, a mission-wide cue index, and an atomic read dossier with fail-closed cross-component reconciliation |
| Interoperability | **D:** CSV/RIS/BibTeX-style workflows, REST, MCP | **D:** CSV/RIS/bibliographies, REST, MCP | **D:** Python ecosystem, multiple file/index/model backends | **D:** retriever and model adapters | **D:** source links and document exports | **D:** strict v2 packet and v1 request/result artifacts; a PROV-O/RO-Crate mapping decision packet is proposed, while any exporter remains unaccepted and unimplemented |

Minerva's receipt and artifact digests establish deterministic self-consistency,
not origin, authenticity, authority, approval, or permission to disclose research.

## Standards and scholarly data infrastructure

| System | Documented contribution | What Minerva should reuse | Boundary or gap for Minerva |
| --- | --- | --- | --- |
| W3C PROV-O | **D:** interoperable Entity/Activity/Agent provenance, derivation, attribution, quotation, revision, invalidation, roles, and plans | Map snapshots/evidence/artifacts to entities, imports/search/adoption to activities, and local identities to agents | **I:** PROV-O does not itself define Minerva's evidence stance, sufficiency, exact byte coordinates, or canonical replay rules |
| RO-Crate 1.3 | **D:** JSON-LD research-object metadata; attached/detached crates; data/context entities; provenance actions; optional human preview; compatibility with ZIP, BagIt, OCFL, and checksums | A future export profile can package canonical artifacts and snapshot references for exchange without replacing Minerva's internal model | **D/I:** the base spec says metadata need not be an exhaustive fixity manifest; it does not supply Minerva's stance or byte-span semantics |
| Semantic Scholar API | **D:** graph search, recommendations, dated dataset releases/diffs, and snippet text with offsets plus `retrievalVersion` | A future gated adapter could pin a dataset release/retrieval version and import returned material through normal snapshot custody | **I:** reviewed docs do not define snippet offset units as UTF-8 bytes or promise immutable publisher bytes; license/auth/network review remains necessary |

## Defensible position

Elicit and Consensus are increasingly complete research products, while
PaperQA2, STORM, and ChatGPT deep research are strong discovery and synthesis
systems. Competing on “answer a question with citations” would therefore be a
weak position. Minerva's durable role is the custody and adjudication substrate
under those experiences:

1. Freeze the exact bytes that were actually reviewed.
2. Locate every adopted citation in those bytes, not merely at paper or page level.
3. Preserve stance, contradiction, withdrawal, retraction, and supersession as
   explicit history rather than recomputing a single current answer.
4. Keep retrieval leads, model inferences, evidence, and human findings as
   different semantic objects with explicit promotion boundaries.
5. Make search, structural review, and export receipts deterministic enough to
   inspect and replay without a model, network, or hidden mutable corpus.
6. Interoperate outward through mappings and versioned artifacts without
   weakening the internal source-custody contract.

## Dependency-ordered product plan

Delivered foundation:

1. **Lens v1:** deterministic lexical candidate retrieval over existing immutable
   mission snapshots, including exact byte provenance and a zero-mutation receipt.
2. **Retrieval evaluation and explanation:** checked-in recall/precision,
   span-accuracy, determinism, mission-isolation, mutation tests, and explanations
   derived only from score components.
3. **Claim Review v1:** a complete-or-refuse, query-only receipt for structural
   evidence gaps, active stance conflict, recorded-status requirements, and
   correction/inference impacts. It adds no truth or confidence score and performs
   no correction. Its synthetic evaluation measures fixed gap labels, status
   validity, six withdrawal-impact edge classes, determinism, identifier isolation,
   and database non-mutation; UTF-8 citation and promotion checks remain tests rather
   than evaluation metrics.
4. **Claim Lineage Graph v1:** a schema-free, complete-or-refuse typed topology for one
   `claim_owned_closure_v1`, retaining complete status/correction/promotion history and
   exact citation bytes plus source/snapshot metadata. It excludes claimless and
   sibling-claim state, scores nothing, writes nothing, and exposes no external agent
   protocol.
5. **Mission Research Queue v1:** a schema-free mission-wide structural review index
   that binds every pinned Claim Review cue to its claim and source review digest in
   one deterministic receipt. It invokes no lineage graph because topology supplies no
   reason-code policy. Items are not tasks and carry no severity, priority, action,
   assignment, completion, or persisted state. Its fixed evaluation measures claim,
   cue/reason, ordering, digest, isolation, and mutation integrity only.
6. **Lens receipt verification/current reproduction:** safe 8 MiB captured-envelope
   intake, strict database-free self-consistency verification, and exact comparison to
   one current query-only Lens run. It detects version/runtime/corpus/result drift,
   verifies current selected source bytes only on the database-backed path, and
   explicitly makes no historical replay or authenticity claim.
7. **Review Dossier v1:** a schema-free trusted-operator composition of the complete
   mission Queue, its retained focal Review, focal Claim Lineage, and one verified Lens
   search/replay in a single current query-only snapshot. Fixed cross-checks and
   component/whole-receipt digests expose structural disagreement without asserting
   candidate relevance, evidence, task state, truth, confidence, priority, or action.
   Its fixed evaluator measures receipt binding, cross-checks, exact multibyte bytes,
   determinism, mission isolation, explicit Lens truncation, and zero mutation only.

Next, in dependency order:

1. **Owner decision on the PROV-O/RO-Crate packet:** choose the declared projection,
   disclosure mode, profile namespace, context custody, publication timestamp,
   license, and canonicalization before any proof serializer or canonical exporter is
   authorized.
2. **Explicit Lens-to-evidence bridge:** only after a separate owner decision and only
   through normal human stance, digest confirmation, citation validation, and atomic
   audit; search and dossier composition remain read-only.
3. **Authenticated external seams and protocols:** D-2 Athena identity/crypto first,
   D-3 Icarus artifacts second, and D-5 read-only MCP/API only after authentication.
4. **Packet v3 decision:** only after a real authenticated consumer establishes the
   correction/inference requirements; v2 remains frozen meanwhile.

Review Dossier v1 is the newly accepted slice in this continuation. The remaining
order is a proposal, not implementation authorization. Every next slice needs an
explicit owner decision. A persisted assign/defer/resolve queue or adoption bridge,
migration, external principal, crypto, adapter, external/agent-facing API, packet
version, or canonical standards export remains under its recorded owner gate.
Scholarly-source adapters
additionally require licensing, fixed-network, authentication, raw-response custody,
and import/adoption approval. Semantic retrieval remains broad D-6 work until a
pinned local model/index receipt can meet the determinism standard and can never
replace exact snapshot custody.

## Primary sources

- [Elicit systematic literature reviews](https://elicit.com/solutions/literature-review),
  [Elicit API](https://docs.elicit.com/), and
  [Elicit systematic-review evaluation](https://elicit.com/blog/evaluating-elicit-slr)
- [How Consensus works](https://help.consensus.app/en/articles/9922673-how-consensus-works),
  [Consensus research database](https://help.consensus.app/en/articles/10055108-consensus-research-database),
  [Consensus Meter](https://help.consensus.app/en/articles/10069920-the-consensus-meter), and
  [Consensus MCP](https://docs.consensus.app/docs/mcp)
- [PaperQA2 primary repository](https://github.com/future-house/paper-qa)
- [STORM / Co-STORM primary repository](https://github.com/stanford-oval/storm)
- [ChatGPT deep research](https://help.openai.com/en/articles/10500283-deep-research)
- [W3C PROV-O](https://www.w3.org/TR/prov-o/)
- [RO-Crate 1.3](https://www.researchobject.org/ro-crate/specification/1.3/index.html)
- [Semantic Scholar API](https://www.semanticscholar.org/product/api),
  [snippet API](https://api.semanticscholar.org/api-docs/graph#tag/Snippet-Text), and
  [datasets API](https://api.semanticscholar.org/api-docs/datasets)
