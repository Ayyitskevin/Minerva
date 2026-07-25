-- Retraction is to a finding what withdrawal is to an evidence card: a separate
-- append-only record, never an edit or a delete. A retracted finding keeps its
-- row, its citations, and its audit history; it stops being asserted.

CREATE TABLE finding_retractions (
    id TEXT PRIMARY KEY CHECK(id GLOB 'ret_[0-9a-f]*' AND length(id) = 36 AND substr(id, 5) NOT GLOB '*[^0-9a-f]*'),
    mission_id TEXT NOT NULL,
    finding_id TEXT NOT NULL,
    reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 1000),
    creator_id TEXT NOT NULL CHECK(length(creator_id) BETWEEN 1 AND 120),
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    UNIQUE(finding_id),
    FOREIGN KEY(finding_id, mission_id) REFERENCES findings(id, mission_id) ON DELETE RESTRICT
) STRICT;

CREATE INDEX idx_finding_retractions_mission ON finding_retractions(mission_id, finding_id);

CREATE TRIGGER finding_retractions_no_update BEFORE UPDATE ON finding_retractions
BEGIN SELECT RAISE(ABORT, 'finding retractions are append-only'); END;
CREATE TRIGGER finding_retractions_no_delete BEFORE DELETE ON finding_retractions
BEGIN SELECT RAISE(ABORT, 'finding retractions are append-only'); END;
