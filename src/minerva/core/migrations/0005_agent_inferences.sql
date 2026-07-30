-- An adopted agent inference is a distinct labeled record, never a finding and
-- never evidence. Like a finding it is append-only: regret is recorded as a
-- separate retraction row, and promotion into a human finding is recorded as a
-- separate promotion row, because the update triggers below correctly forbid
-- setting a link column after insert. The retraction table ships in the same
-- migration as the record it retracts; that is the D-9 lesson.

CREATE TABLE agent_inferences (
    id TEXT PRIMARY KEY CHECK(id GLOB 'inf_[0-9a-f]*' AND length(id) = 36 AND substr(id, 5) NOT GLOB '*[^0-9a-f]*'),
    mission_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    statement TEXT NOT NULL CHECK(length(statement) BETWEEN 1 AND 4000),
    uncertainty TEXT NOT NULL CHECK(length(uncertainty) BETWEEN 1 AND 2000),
    provider TEXT NOT NULL CHECK(provider IN ('openai', 'anthropic')),
    model TEXT NOT NULL CHECK(length(model) BETWEEN 1 AND 200),
    request_sha256 TEXT NOT NULL CHECK(length(request_sha256) = 64),
    candidate_index INTEGER NOT NULL CHECK(candidate_index BETWEEN 0 AND 2),
    response_sha256 TEXT NOT NULL CHECK(length(response_sha256) = 64),
    system_prompt_version TEXT NOT NULL CHECK(length(system_prompt_version) BETWEEN 1 AND 120),
    creator_id TEXT NOT NULL CHECK(length(creator_id) BETWEEN 1 AND 120),
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    UNIQUE(id, mission_id),
    UNIQUE(request_sha256, candidate_index, claim_id),
    FOREIGN KEY(claim_id, mission_id) REFERENCES claims(id, mission_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE agent_inference_citations (
    inference_id TEXT NOT NULL,
    mission_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    creator_id TEXT NOT NULL CHECK(length(creator_id) BETWEEN 1 AND 120),
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    PRIMARY KEY(inference_id, evidence_id),
    FOREIGN KEY(inference_id, mission_id)
        REFERENCES agent_inferences(id, mission_id) ON DELETE RESTRICT,
    FOREIGN KEY(evidence_id, mission_id)
        REFERENCES evidence_cards(id, mission_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE agent_inference_retractions (
    id TEXT PRIMARY KEY CHECK(id GLOB 'inr_[0-9a-f]*' AND length(id) = 36 AND substr(id, 5) NOT GLOB '*[^0-9a-f]*'),
    mission_id TEXT NOT NULL,
    inference_id TEXT NOT NULL,
    reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 1000),
    creator_id TEXT NOT NULL CHECK(length(creator_id) BETWEEN 1 AND 120),
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    UNIQUE(inference_id),
    FOREIGN KEY(inference_id, mission_id)
        REFERENCES agent_inferences(id, mission_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE agent_inference_promotions (
    id TEXT PRIMARY KEY CHECK(id GLOB 'inp_[0-9a-f]*' AND length(id) = 36 AND substr(id, 5) NOT GLOB '*[^0-9a-f]*'),
    mission_id TEXT NOT NULL,
    inference_id TEXT NOT NULL,
    finding_id TEXT NOT NULL,
    creator_id TEXT NOT NULL CHECK(length(creator_id) BETWEEN 1 AND 120),
    run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    UNIQUE(inference_id),
    FOREIGN KEY(inference_id, mission_id)
        REFERENCES agent_inferences(id, mission_id) ON DELETE RESTRICT,
    FOREIGN KEY(finding_id, mission_id) REFERENCES findings(id, mission_id) ON DELETE RESTRICT
) STRICT;

CREATE INDEX idx_agent_inferences_mission ON agent_inferences(mission_id, created_at, id);
CREATE INDEX idx_agent_inferences_claim ON agent_inferences(mission_id, claim_id, created_at, id);
CREATE INDEX idx_agent_inference_citations_inference
    ON agent_inference_citations(inference_id, evidence_id);
CREATE INDEX idx_agent_inference_retractions_mission
    ON agent_inference_retractions(mission_id, inference_id);
CREATE INDEX idx_agent_inference_promotions_mission
    ON agent_inference_promotions(mission_id, inference_id);

CREATE TRIGGER agent_inferences_no_update BEFORE UPDATE ON agent_inferences
BEGIN SELECT RAISE(ABORT, 'agent inferences are append-only'); END;
CREATE TRIGGER agent_inferences_no_delete BEFORE DELETE ON agent_inferences
BEGIN SELECT RAISE(ABORT, 'agent inferences are append-only'); END;
CREATE TRIGGER agent_inference_citations_no_update BEFORE UPDATE ON agent_inference_citations
BEGIN SELECT RAISE(ABORT, 'agent inference citations are append-only'); END;
CREATE TRIGGER agent_inference_citations_no_delete BEFORE DELETE ON agent_inference_citations
BEGIN SELECT RAISE(ABORT, 'agent inference citations are append-only'); END;
CREATE TRIGGER agent_inference_retractions_no_update BEFORE UPDATE ON agent_inference_retractions
BEGIN SELECT RAISE(ABORT, 'agent inference retractions are append-only'); END;
CREATE TRIGGER agent_inference_retractions_no_delete BEFORE DELETE ON agent_inference_retractions
BEGIN SELECT RAISE(ABORT, 'agent inference retractions are append-only'); END;
CREATE TRIGGER agent_inference_promotions_no_update BEFORE UPDATE ON agent_inference_promotions
BEGIN SELECT RAISE(ABORT, 'agent inference promotions are append-only'); END;
CREATE TRIGGER agent_inference_promotions_no_delete BEFORE DELETE ON agent_inference_promotions
BEGIN SELECT RAISE(ABORT, 'agent inference promotions are append-only'); END;
