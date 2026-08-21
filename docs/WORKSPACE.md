# Workspace — mickey checkout

This is the operator map for running Minerva as the fleet's research-memory on
mickey. It does not change the product contract. Identity and non-goals live in
[VISION.md](VISION.md). Domain invariants live in [PRD.md](PRD.md).

Minerva remains alpha software for one trusted OS user. The review server binds
to `127.0.0.1`. Loopback is not authentication. Do not expose it remotely.

## Working copy

The Grok seat's clone is `~/ai-workspace/grok/minerva`, tracking
`git@github.com:Ayyitskevin/Minerva.git`. Other seats keep their own clones.
Do not scratch-edit another seat's tree, and do not edit a live database from
two writers at once.

Install the locked environment from that checkout:

```bash
cd ~/ai-workspace/grok/minerva
uv sync --frozen --extra dev
uv run minerva --help
```

## Persistent database

Research state is one SQLite file plus exported packets. It does not live in
git, in ORACLE, or on the Syncthing mesh.

Recommended path on mickey, owner-only, created in Phase 3 rather than by this
document:

```text
~/data/minerva/research.db
~/data/minerva/backups/
```

Initialize once, then keep using that file:

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

A user systemd unit is optional and is not required to start dogfooding. There
is no reverse proxy and no Tailscale bind in this season.

## How a seat files evidence

Agents append to the record through the CLI against the persistent database.
They do not paste findings into Buzz and they do not treat an Athena issue body
as a citation.

The vertical slice is the same as the README: `mission create`, `question add`,
`claim add`, `source import`, `evidence add` with an exact UTF-8 byte span,
`finding add` or an explicitly labeled assumption, then `brief export` and
`audit list`. Corrections are `evidence withdraw` and `finding retract`. There
is still no delete verb.

Before calling the slice complete on live data:

```bash
uv run minerva doctor --db ~/data/minerva/research.db --deep
```

A nightly backup is a non-overwriting copy:

```bash
uv run minerva backup --db ~/data/minerva/research.db --output ~/data/minerva/backups/research.db
```

`backup` refuses to overwrite. Pick a new output path or a dated name.

## Packets and siblings

`brief export` writes operator-owned `research-brief.json` and Markdown. That
is not publication. An Athena issue may *point at* a packet digest in its body;
that pointer is not gate D-2 and does not authenticate the caller. ORACLE may
later archive a digest-addressed packet; Minerva does not write into the vault.

## Verification

The eleven commands in `AGENTS.md` are the repository gates. They are not a
deploy. Provider tests use fakes only.

## Not yet

Persistent DB creation, the first real mission, systemd, and the Lens rebase
are later phases. This file records the intended layout so those phases do not
invent a second database path.
