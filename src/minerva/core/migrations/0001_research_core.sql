CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    checksum TEXT NOT NULL CHECK(length(checksum) = 64),
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE research_runs (
    id TEXT PRIMARY KEY CHECK(id GLOB 'run_[0-9a-f]*' AND length(id) = 36 AND substr(id, 5) NOT GLOB '*[^0-9a-f]*'),
    actor_id TEXT NOT NULL CHECK(length(actor_id) BETWEEN 1 AND 120),
    actor_kind TEXT NOT NULL CHECK(actor_kind IN ('os_user', 'system')),
    purpose TEXT NOT NULL CHECK(length(purpose) BETWEEN 1 AND 200),
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE research_missions (
    id TEXT PRIMARY KEY CHECK(id GLOB 'mis_[0-9a-f]*' AND length(id) = 36 AND substr(id, 5) NOT GLOB '*[^0-9a-f]*'),
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 200),
    objective TEXT NOT NULL CHECK(length(objective) BETWEEN 1 AND 2000),
    creator_id TEXT NOT NULL CHECK(length(creator_id) BETWEEN 1 AND 120),
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE research_questions (
    id TEXT PRIMARY KEY CHECK(id GLOB 'que_[0-9a-f]*' AND length(id) = 36 AND substr(id, 5) NOT GLOB '*[^0-9a-f]*'),
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE RESTRICT,
    question_text TEXT NOT NULL CHECK(length(question_text) BETWEEN 1 AND 2000),
    creator_id TEXT NOT NULL CHECK(length(creator_id) BETWEEN 1 AND 120),
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    UNIQUE(id, mission_id)
) STRICT;

CREATE TABLE claims (
    id TEXT PRIMARY KEY CHECK(id GLOB 'clm_[0-9a-f]*' AND length(id) = 36 AND substr(id, 5) NOT GLOB '*[^0-9a-f]*'),
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE RESTRICT,
    question_id TEXT NOT NULL,
    statement TEXT NOT NULL CHECK(length(statement) BETWEEN 1 AND 2000),
    falsification_criteria TEXT NOT NULL CHECK(length(falsification_criteria) BETWEEN 1 AND 2000),
    creator_id TEXT NOT NULL CHECK(length(creator_id) BETWEEN 1 AND 120),
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    UNIQUE(id, mission_id),
    FOREIGN KEY(question_id, mission_id)
        REFERENCES research_questions(id, mission_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE claim_status_events (
    id TEXT PRIMARY KEY CHECK(id GLOB 'cst_[0-9a-f]*' AND length(id) = 36 AND substr(id, 5) NOT GLOB '*[^0-9a-f]*'),
    claim_id TEXT NOT NULL,
    mission_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version >= 1),
    status TEXT NOT NULL CHECK(status IN (
        'open', 'provisionally_supported', 'contested', 'unsupported', 'inconclusive'
    )),
    reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 1000),
    creator_id TEXT NOT NULL CHECK(length(creator_id) BETWEEN 1 AND 120),
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    UNIQUE(claim_id, version),
    FOREIGN KEY(claim_id, mission_id) REFERENCES claims(id, mission_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE sources (
    id TEXT PRIMARY KEY CHECK(id GLOB 'src_[0-9a-f]*' AND length(id) = 36 AND substr(id, 5) NOT GLOB '*[^0-9a-f]*'),
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE RESTRICT,
    source_kind TEXT NOT NULL CHECK(source_kind = 'local_utf8'),
    original_label TEXT NOT NULL CHECK(length(original_label) BETWEEN 1 AND 500),
    url_metadata TEXT CHECK(url_metadata IS NULL OR length(url_metadata) BETWEEN 1 AND 2000),
    creator_id TEXT NOT NULL CHECK(length(creator_id) BETWEEN 1 AND 120),
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    UNIQUE(id, mission_id)
) STRICT;

CREATE TABLE source_snapshots (
    id TEXT PRIMARY KEY CHECK(id GLOB 'snp_[0-9a-f]*' AND length(id) = 36 AND substr(id, 5) NOT GLOB '*[^0-9a-f]*'),
    source_id TEXT NOT NULL,
    mission_id TEXT NOT NULL,
    content BLOB NOT NULL,
    sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
    byte_length INTEGER NOT NULL CHECK(byte_length > 0),
    encoding TEXT NOT NULL CHECK(encoding = 'utf-8'),
    media_type TEXT NOT NULL CHECK(length(media_type) BETWEEN 1 AND 100),
    original_label TEXT NOT NULL CHECK(length(original_label) BETWEEN 1 AND 500),
    imported_at TEXT NOT NULL,
    creator_id TEXT NOT NULL CHECK(length(creator_id) BETWEEN 1 AND 120),
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE RESTRICT,
    CHECK(length(content) = byte_length),
    UNIQUE(id, mission_id),
    FOREIGN KEY(source_id, mission_id) REFERENCES sources(id, mission_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE evidence_cards (
    id TEXT PRIMARY KEY CHECK(id GLOB 'evd_[0-9a-f]*' AND length(id) = 36 AND substr(id, 5) NOT GLOB '*[^0-9a-f]*'),
    mission_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    snapshot_sha256 TEXT NOT NULL CHECK(length(snapshot_sha256) = 64),
    start_byte INTEGER NOT NULL CHECK(start_byte >= 0),
    end_byte INTEGER NOT NULL CHECK(end_byte > start_byte),
    quote TEXT NOT NULL CHECK(length(quote) > 0),
    stance TEXT NOT NULL CHECK(stance IN ('supports', 'opposes', 'context', 'inconclusive')),
    supersedes_evidence_id TEXT,
    creator_id TEXT NOT NULL CHECK(length(creator_id) BETWEEN 1 AND 120),
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    UNIQUE(id, mission_id),
    FOREIGN KEY(claim_id, mission_id) REFERENCES claims(id, mission_id) ON DELETE RESTRICT,
    FOREIGN KEY(snapshot_id, mission_id)
        REFERENCES source_snapshots(id, mission_id) ON DELETE RESTRICT,
    FOREIGN KEY(supersedes_evidence_id, mission_id)
        REFERENCES evidence_cards(id, mission_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE evidence_withdrawals (
    id TEXT PRIMARY KEY CHECK(id GLOB 'wdr_[0-9a-f]*' AND length(id) = 36 AND substr(id, 5) NOT GLOB '*[^0-9a-f]*'),
    mission_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 1000),
    creator_id TEXT NOT NULL CHECK(length(creator_id) BETWEEN 1 AND 120),
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    UNIQUE(evidence_id),
    FOREIGN KEY(evidence_id, mission_id)
        REFERENCES evidence_cards(id, mission_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE audit_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE CHECK(id GLOB 'aud_[0-9a-f]*' AND length(id) = 36 AND substr(id, 5) NOT GLOB '*[^0-9a-f]*'),
    event_type TEXT NOT NULL CHECK(length(event_type) BETWEEN 1 AND 100),
    entity_type TEXT NOT NULL CHECK(length(entity_type) BETWEEN 1 AND 100),
    entity_id TEXT NOT NULL CHECK(length(entity_id) BETWEEN 1 AND 100),
    mission_id TEXT REFERENCES research_missions(id) ON DELETE RESTRICT,
    actor_id TEXT NOT NULL CHECK(length(actor_id) BETWEEN 1 AND 120),
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE RESTRICT,
    occurred_at TEXT NOT NULL,
    details_json TEXT NOT NULL CHECK(length(details_json) BETWEEN 2 AND 4096)
) STRICT;

CREATE INDEX idx_questions_mission ON research_questions(mission_id, created_at, id);
CREATE INDEX idx_claims_mission ON claims(mission_id, created_at, id);
CREATE INDEX idx_claim_status_claim ON claim_status_events(claim_id, version);
CREATE INDEX idx_sources_mission ON sources(mission_id, created_at, id);
CREATE INDEX idx_snapshots_mission ON source_snapshots(mission_id, imported_at, id);
CREATE INDEX idx_evidence_claim ON evidence_cards(claim_id, created_at, id);
CREATE INDEX idx_evidence_snapshot ON evidence_cards(snapshot_id, id);
CREATE INDEX idx_audit_mission ON audit_events(mission_id, sequence);

CREATE TRIGGER schema_migrations_no_update BEFORE UPDATE ON schema_migrations
BEGIN SELECT RAISE(ABORT, 'migration history is append-only'); END;
CREATE TRIGGER schema_migrations_no_delete BEFORE DELETE ON schema_migrations
BEGIN SELECT RAISE(ABORT, 'migration history is append-only'); END;
CREATE TRIGGER research_runs_no_update BEFORE UPDATE ON research_runs
BEGIN SELECT RAISE(ABORT, 'research runs are append-only'); END;
CREATE TRIGGER research_runs_no_delete BEFORE DELETE ON research_runs
BEGIN SELECT RAISE(ABORT, 'research runs are append-only'); END;
CREATE TRIGGER missions_no_update BEFORE UPDATE ON research_missions
BEGIN SELECT RAISE(ABORT, 'research missions are append-only'); END;
CREATE TRIGGER missions_no_delete BEFORE DELETE ON research_missions
BEGIN SELECT RAISE(ABORT, 'research missions are append-only'); END;
CREATE TRIGGER questions_no_update BEFORE UPDATE ON research_questions
BEGIN SELECT RAISE(ABORT, 'research questions are append-only'); END;
CREATE TRIGGER questions_no_delete BEFORE DELETE ON research_questions
BEGIN SELECT RAISE(ABORT, 'research questions are append-only'); END;
CREATE TRIGGER claims_no_update BEFORE UPDATE ON claims
BEGIN SELECT RAISE(ABORT, 'claims are append-only'); END;
CREATE TRIGGER claims_no_delete BEFORE DELETE ON claims
BEGIN SELECT RAISE(ABORT, 'claims are append-only'); END;
CREATE TRIGGER claim_status_no_update BEFORE UPDATE ON claim_status_events
BEGIN SELECT RAISE(ABORT, 'claim status history is append-only'); END;
CREATE TRIGGER claim_status_no_delete BEFORE DELETE ON claim_status_events
BEGIN SELECT RAISE(ABORT, 'claim status history is append-only'); END;
CREATE TRIGGER sources_no_update BEFORE UPDATE ON sources
BEGIN SELECT RAISE(ABORT, 'sources are append-only'); END;
CREATE TRIGGER sources_no_delete BEFORE DELETE ON sources
BEGIN SELECT RAISE(ABORT, 'sources are append-only'); END;
CREATE TRIGGER snapshots_no_update BEFORE UPDATE ON source_snapshots
BEGIN SELECT RAISE(ABORT, 'source snapshots are immutable'); END;
CREATE TRIGGER snapshots_no_delete BEFORE DELETE ON source_snapshots
BEGIN SELECT RAISE(ABORT, 'source snapshots are immutable'); END;
CREATE TRIGGER evidence_no_update BEFORE UPDATE ON evidence_cards
BEGIN SELECT RAISE(ABORT, 'evidence cards are append-only'); END;
CREATE TRIGGER evidence_no_delete BEFORE DELETE ON evidence_cards
BEGIN SELECT RAISE(ABORT, 'evidence cards are append-only'); END;
CREATE TRIGGER withdrawals_no_update BEFORE UPDATE ON evidence_withdrawals
BEGIN SELECT RAISE(ABORT, 'evidence withdrawals are append-only'); END;
CREATE TRIGGER withdrawals_no_delete BEFORE DELETE ON evidence_withdrawals
BEGIN SELECT RAISE(ABORT, 'evidence withdrawals are append-only'); END;
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit records are append-only'); END;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit records are append-only'); END;
