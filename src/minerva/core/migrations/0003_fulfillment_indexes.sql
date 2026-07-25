-- Both index names are load-bearing: synthesis and fulfillment queries pin them
-- with INDEXED BY so a claim-scoped read cannot silently fall back to a scan of
-- unrelated mission or audit history. Dropping either name breaks those queries.

CREATE INDEX idx_audit_event_entity ON audit_events(event_type, entity_id, sequence);
CREATE INDEX idx_findings_claim ON findings(mission_id, claim_id, created_at, id);
