# Workspace — mickey checkout

This is the operator map for running Minerva as the fleet's research-memory on
mickey. It does not change the product contract. Identity and non-goals live in
[VISION.md](VISION.md). Domain invariants live in [PRD.md](PRD.md).

Minerva remains alpha software for one trusted OS user. The review server binds
to `127.0.0.1`. Loopback is not authentication. Do not expose it remotely.

## Working copy

Each seat uses its own clone of `git@github.com:Ayyitskevin/Minerva.git`.
The Grok seat's clone is `~/ai-workspace/grok/minerva`. Do not scratch-edit
another seat's tree, and do not edit a live database from two writers at once.

Install the locked environment from the clone you are working in:

```bash
uv sync --frozen --extra dev
uv run minerva --help
```

Machine-local wrappers that inject `--db` stay out of git. From your clone,
pass the persistent database path on every command that takes `--db`.

## Persistent database

Research state is one SQLite file plus exported packets. It does not live in
git, in ORACLE, or on the Syncthing mesh.

Recommended path on mickey, owner-only:

```text
~/data/minerva/research.db
~/data/minerva/backups/
~/data/minerva/exports/
```

That tree is created. It does not live in git. Initialize once, then keep using
that file:

```bash
install -d -m 700 ~/data/minerva ~/data/minerva/backups
uv run minerva init --db ~/data/minerva/research.db
```

Throwaway demo databases stay under `/tmp`. Do not point a seat at a demo path
and call it the record.

## Review server

```bash
uv run minerva serve --db ~/data/minerva/research.db --host 127.0.0.1 --port 8765
```

A user systemd unit may run that exact command. The host argument is rejected
unless it is `127.0.0.1`. There is no reverse proxy and no Tailscale bind in
this season. An example unit lives in `contrib/systemd/`. Machine-local units
stay out of git. If `http://127.0.0.1:8765/healthz` already answers, do not
start a second serve against the live database.

## How a seat files evidence

Agents append to the record through the CLI against the persistent database.
They do not paste findings into Buzz and they do not treat an Athena issue body
as a citation.

The vertical slice is the same as the README: `mission create`, `question add`,
`claim add`, `source import`, `evidence add` or `evidence add-from-lens` with an
exact UTF-8 byte span, `finding add` or an explicitly labeled assumption, then
`brief export` and `audit list`. `lens search` returns unassessed leads, not
evidence. Corrections are `evidence withdraw` and `finding retract`. There is
still no delete verb.

On mickey, discover live IDs first, then write against the persistent database.
Placeholders come from `mission show`, never invented. Adding evidence on an
existing claim does not require `mission create`:

```bash
uv run minerva mission list --db ~/data/minerva/research.db
uv run minerva mission show --db ~/data/minerva/research.db --mission MIS_ID
uv run minerva source import --db ~/data/minerva/research.db --mission MIS_ID \
  --root ./sources --file FILE.txt --media-type text/plain
uv run minerva source show --db ~/data/minerva/research.db --snapshot SNP_ID
uv run minerva evidence add --db ~/data/minerva/research.db --mission MIS_ID \
  --claim CLM_ID --snapshot SNP_ID --start BYTE --end BYTE \
  --quote "EXACT UTF-8 SPAN" --stance supports
```

`source show` prints stored bytes so the submitted `--quote` can match exactly.
Stance is `supports`, `opposes`, `context`, or `inconclusive`.

Before calling the slice complete on live data:

```bash
uv run minerva doctor --db ~/data/minerva/research.db --deep
```

A nightly backup is a non-overwriting copy. Use a dated output path;
`backup` refuses to overwrite, so a fixed `research.db` destination can
succeed once and then fail forever:

```bash
uv run minerva backup --db ~/data/minerva/research.db \
  --output ~/data/minerva/backups/research-$(date -u +%Y%m%dT%H%M%SZ).db
```

## Packets and siblings

`brief export` writes operator-owned `research-brief.json` and Markdown. That
is not publication. An Athena issue may *point at* a packet digest in its body;
that pointer is not gate D-2 and does not authenticate the caller. ORACLE may
later archive a digest-addressed packet; Minerva does not write into the vault.

## Verification

The eleven commands in `AGENTS.md` are the repository gates. They are not a
deploy. Provider tests use fakes only.

## Runtime on mickey (2026-08-21)

The Grok seat created the persistent database and seeded mission
`Mickey AI workspace — sibling ownership` through the CLI, including one
`evidence add-from-lens` adoption. Review is `http://127.0.0.1:8765/missions`
(loopback). Briefs go under `~/data/minerva/exports/`. Backups are dated files
under `~/data/minerva/backups/`. None of those paths are in git.

## Not this season

Gate D-2, MCP, Tailscale bind, packet `v3`, and writing Minerva state into
ORACLE remain closed.
