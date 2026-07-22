CREATE TABLE findings (
    id TEXT PRIMARY KEY CHECK(id GLOB 'fnd_[0-9a-f]*' AND length(id) = 36 AND substr(id, 5) NOT GLOB '*[^0-9a-f]*'),
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE RESTRICT,
    claim_id TEXT,
    statement TEXT NOT NULL CHECK(length(statement) BETWEEN 1 AND 4000),
    statement_kind TEXT NOT NULL CHECK(statement_kind IN (
        'observed_fact', 'source_assertion', 'agent_inference', 'assumption',
        'calculation', 'recommendation', 'unresolved_question'
    )),
    status TEXT NOT NULL CHECK(status IN (
        'supported', 'contested', 'unsupported', 'inconclusive'
    )),
    uncertainty TEXT NOT NULL CHECK(length(uncertainty) <= 2000),
    creator_id TEXT NOT NULL CHECK(length(creator_id) BETWEEN 1 AND 120),
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    UNIQUE(id, mission_id),
    FOREIGN KEY(claim_id, mission_id) REFERENCES claims(id, mission_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE finding_citations (
    finding_id TEXT NOT NULL,
    mission_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    creator_id TEXT NOT NULL CHECK(length(creator_id) BETWEEN 1 AND 120),
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    PRIMARY KEY(finding_id, evidence_id),
    FOREIGN KEY(finding_id, mission_id) REFERENCES findings(id, mission_id) ON DELETE RESTRICT,
    FOREIGN KEY(evidence_id, mission_id)
        REFERENCES evidence_cards(id, mission_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE brief_exports (
    id TEXT PRIMARY KEY CHECK(id GLOB 'exp_[0-9a-f]*' AND length(id) = 36 AND substr(id, 5) NOT GLOB '*[^0-9a-f]*'),
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE RESTRICT,
    schema_version TEXT NOT NULL CHECK(length(schema_version) BETWEEN 1 AND 40),
    export_digest TEXT NOT NULL CHECK(length(export_digest) = 64),
    markdown_sha256 TEXT NOT NULL CHECK(length(markdown_sha256) = 64),
    json_sha256 TEXT NOT NULL CHECK(length(json_sha256) = 64),
    creator_id TEXT NOT NULL CHECK(length(creator_id) BETWEEN 1 AND 120),
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL
) STRICT;

CREATE INDEX idx_findings_mission ON findings(mission_id, created_at, id);
CREATE INDEX idx_finding_citations_finding ON finding_citations(finding_id, evidence_id);
CREATE INDEX idx_exports_mission ON brief_exports(mission_id, created_at, id);

CREATE TRIGGER findings_no_update BEFORE UPDATE ON findings
BEGIN SELECT RAISE(ABORT, 'findings are append-only'); END;
CREATE TRIGGER findings_no_delete BEFORE DELETE ON findings
BEGIN SELECT RAISE(ABORT, 'findings are append-only'); END;
CREATE TRIGGER finding_citations_no_update BEFORE UPDATE ON finding_citations
BEGIN SELECT RAISE(ABORT, 'finding citations are append-only'); END;
CREATE TRIGGER finding_citations_no_delete BEFORE DELETE ON finding_citations
BEGIN SELECT RAISE(ABORT, 'finding citations are append-only'); END;
CREATE TRIGGER exports_no_update BEFORE UPDATE ON brief_exports
BEGIN SELECT RAISE(ABORT, 'brief exports are append-only'); END;
CREATE TRIGGER exports_no_delete BEFORE DELETE ON brief_exports
BEGIN SELECT RAISE(ABORT, 'brief exports are append-only'); END;
