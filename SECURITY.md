# Security

## Reporting a vulnerability

Please report privately through
[GitHub Security Advisories](https://github.com/GiaSip/kb-init/security/advisories/new) rather than a
public issue. This is a small project — expect a human, not an SLA.

## What kb-init does and doesn't do

kb-init is a local CLI. It reads an exported folder or zip, writes to an output directory you name,
and exits.

- **No account access.** No OAuth, no API tokens, no credentials of any kind. Input is a file tree.
- **One network call, on first run only:** downloading the ~90MB embedding model. `--no-index` skips it
  entirely, and the whole run then works offline.
- **Both HTML reports are single-file**, with no JavaScript and no external requests. Opening one does
  not phone anywhere.
- **The run is atomic.** Output lands in a staging directory and is published with a single rename, so
  an interrupted run cannot leave a half-written knowledge base.

## The privacy property you have to check yourself

`kb-init compile` writes `report.share.html`, described as "the version you can send out". It is built
from an explicit field allowlist — no note titles, no body fragments, no file paths, no run IDs.

**But it contains keywords, and keywords come straight out of your notes.** Field-level filtering
cannot fix that, and no tool can decide for you whether a given word is safe to publish. So compile
prints every keyword the shareable report contains to your terminal.

**Read that list before you send the file.** If a keyword shouldn't leave your machine, untick that
entry in `insights.md` and run compile again.

The same applies to the archive (`CLAUDE.md` / `AGENTS.md` / …): it contains only sentences you ticked,
and those sentences contain keywords from your notes.

`report.private.html` is *not* built from an allowlist and does contain note titles. It is for you.

## Reporting a leak in the repository itself

If you find real personal data in this repository or its git history, that's a valid security report —
please use the private advisory link above. There's a detector for this class
(`probes/corpus_leak_probe.py`), but its known blind spot is strings broken across lines: both
`git grep` and `git log -S` match line by line.
