# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-08-18

First public release. Not on PyPI; install with
`uvx --from git+https://github.com/GiaSip/kb-init`.

### Added

- **Cleaning.** Reads a Notion or Apple Notes export (folder or zip) and emits standard Markdown.
  Empty shells, orphans and duplicates are marked and dropped, never silently deleted — every dropped
  record stays in `manifest.json` with its reason. Measured: 1,925 → 757 (Notion), 620 → 287
  (Apple Notes).
- **Link remapping.** Standard relative links resolve against the current document's directory
  (CommonMark semantics), with no cross-directory fallback. Unresolvable links degrade to plain text
  and are recorded in `unresolved_links`; the output never contains a dead link. Optional `--wikilinks`
  preserves the `[[…]]` dialect.
- **Indexing and insights.** Local embedding (fastembed/ONNX), clustering, and a topic index. Documents
  that don't form a topic land in `residual` rather than being smeared into the nearest cluster.
  Timeline insights are switched off entirely when date coverage falls below 30%.
- **`insights.md`** — a human review checklist with visible short IDs, plus `kb-init validate` to check
  it standalone. Only `[x]` / `[ ]` are meaningful; downstream reads text from `insights.json` by ID
  and does not trust hand-edited prose.
- **Two reports.** `report.private.html` for you (contains note titles); `report.share.html` built from
  a field allowlist for sending out. Both are single-file, no JavaScript, no external requests.
  Compile prints every keyword the shareable report contains.
- **`kb-init compile`** — writes the archive your agent reads. `--agent-file` picks the filename
  (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, …), because producing a file your agent doesn't read is the
  same as producing nothing. Every sentence is word-for-word the one you approved. Overwrites only an
  archive it wrote itself, verified by receipt and content hash.
- **`--no-index`** — cleaned output in seconds, no model download, no network.
- **Distinct exit codes 0–10**, deliberately not merged: the next action differs in each case. Errors
  print a one-line diagnostic; end users never see a Python traceback.
- **First-run progress reporting** to stderr (model preparation, vector progress, clustering), so
  piping is unaffected. No ETA is shown — there is no honest basis for one.

### Known limitations

See [Known limitations](README.md#known-limitations). The two that surprise people most: the archive
explains only 16–23% of a knowledge base (because ~70% of documents form no topic), and timeline
insights don't work on export-type corpora at all (parseable date rates are 5.2% and 6.3%).

### Platform support

Windows x64, Linux x64 (glibc ≥ 2.28) and macOS Apple Silicon (≥ 14) are covered by CI on Python 3.12
and 3.13. **macOS Intel is not supported** — `onnxruntime` no longer publishes macOS x86_64 wheels.
Windows arm64 and Linux aarch64 have wheels but no test coverage.

[Unreleased]: https://github.com/GiaSip/kb-init/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/GiaSip/kb-init/releases/tag/v0.1.0
