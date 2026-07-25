-- Both index names are load-bearing: claim-scoped synthesis and fulfillment
-- queries name them in INDEXED BY clauses, so renaming or dropping either one
-- makes those queries fail to prepare. audit_events.sequence is the rowid alias
-- and is already the implicit trailing index key, so it is not named here.

CREATE INDEX idx_audit_event_entity ON audit_events(event_type, entity_id);
CREATE INDEX idx_findings_claim ON findings(mission_id, claim_id, created_at, id);
