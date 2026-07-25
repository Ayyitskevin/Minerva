# ADR 0006: Report operator remnants without removing them

- Status: Accepted
- Date: 2026-07-25
- Review: Kevin review required because this changes what `doctor` reports and
  therefore what an operator is told about crash residue

## Context

Several Minerva operations are documented as leaving residue that the operator
must inspect and remove:

- ADR 0004 states that a crash between the staged commit and publication can
  leave an orphan `.{name}.minerva-*.tmp` staging file. Each one is a complete
  copy of a database, so it can hold the same sensitive research content, hidden
  as a dotfile the operator has no reason to look for.
- ADR 0003 states that process death between the metadata-only `requested` audit
  event and its terminal event leaves an unmatched pair, and that the provider
  may still have processed and charged for that request.

Both are honest documentation of real windows. Neither was discoverable: nothing
in `doctor`, the CLI, or the API told an operator that residue existed, so the
documented cleanup contract could not actually be carried out.

The obvious response — have `doctor` clean up — is wrong for the reason ADR 0004
already established: Minerva must not remove state it cannot prove it created.
A staging file matching the pattern could belong to another process or another
database generation.

## Decision

`DoctorReport` gains `notices`, a separate channel from `checks`.

A notice is an observation that needs an operator's attention but is not a
failure. Notices never contribute to `DoctorReport.ok`, so they cannot make a
healthy database report as unready, and `/readyz` continues to map `checks`
only. `doctor` reports; the operator decides and acts.

Two notices ship:

- `staging_remnants` counts `.{name}.minerva-*.tmp` regular files beside the
  database. It runs on every `doctor` invocation, including when the database
  itself is missing, because residue can outlive the database it was staged for.
- `unfinished_assistance` counts assistance invocations that have a `requested`
  audit event and no other event for the same invocation. It runs under `--deep`
  only, in the pass that already reads the audit table.

Notice text is fixed and carries only a count. It never includes a filename or
path: the remnant's name embeds the database filename, and reporting it would
disclose exactly the private path information the threat model keeps out of
errors and API output. The operator already knows which database they ran
`doctor` against.

Nothing is deleted, ever.

## Consequences

- The cleanup contracts in ADR 0003 and ADR 0004 become actionable instead of
  theoretical.
- An operator learns that an assistance request may have been billed without a
  recorded outcome — the case ADR 0003 explicitly cannot resolve automatically.
- `doctor` exit status and `/readyz` behaviour are unchanged. A database with
  remnants is still healthy, because it is.
- `DoctorReport` gained a field. It defaults to an empty tuple, and the CLI
  serializes dataclasses generically, so the notice list appears in
  `minerva doctor` output without a schema change elsewhere.
- The `unfinished_assistance` query groups the audit rows already scanned by the
  deep pass, so it adds no new asymptotic cost and needs no index or migration.

## Explicitly not covered

**Partial export and fulfillment output directories are not discoverable, and
this ADR does not pretend otherwise.** `brief_exports` records a digest, schema
version, and content hashes — deliberately not a filesystem path, because
Minerva does not store private paths. `request fulfill` records nothing at all.
Minerva therefore cannot know where an interrupted export was being written, and
a `doctor` run against a database cannot find one. That residue remains an
operator responsibility guided by documentation, and the honest statement is
that Minerva cannot help locate it rather than a check that silently finds
nothing.

## Rejected alternatives

- **Deleting remnants automatically**: ADR 0004's reasoning applies unchanged.
  A matching filename is not proof of ownership.
- **Reporting remnants as failed checks**: would make a healthy database return
  `/readyz` 503 and a non-zero `doctor` exit for what is housekeeping.
- **Including remnant filenames**: each name embeds the database filename, which
  the threat model keeps out of reported output.
- **Indexing `audit_events(entity_type)` to make the assistance notice cheaper**:
  the deep pass already scans that table, so the index would add write cost for
  no read gain.
- **Scanning the filesystem for export directories**: Minerva has no record of
  where they are, so any search would be a guess over operator-chosen paths.
