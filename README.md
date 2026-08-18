# kb-init

**English** | [简体中文](README.zh-CN.md)

Compile the note export you've been ignoring for years into a clean knowledge base your AI agent can actually read.

Point it at a Notion or Apple Notes export. It gives you back standard Markdown, a report about your own notes, and a `CLAUDE.md` (or `AGENTS.md`, or whatever file your agent reads) describing what's in there.

[![CI](https://github.com/GiaSip/kb-init/actions/workflows/ci.yml/badge.svg)](https://github.com/GiaSip/kb-init/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.12 | 3.13](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue.svg)](pyproject.toml)

---

## What it actually does, in numbers

Measured on two real exports, not synthetic fixtures:

| Input | Read | Kept | Dropped as empty shells |
|---|---|---|---|
| Notion export | 1,925 files | **757 (39%)** | 1,168 (60.7%) |
| Apple Notes export | 620 files | **287 (46%)** | 333 (53.7%) |

Roughly 60% of a years-old Notion export is empty shells — titles with no body, orphaned database rows,
duplicate pages. Dropping them is most of the value. **Nothing is actually deleted**: every dropped
record stays in `manifest.json` with the reason it was dropped, which is exactly why the number
`1,925 → 757` can be computed at all.

Three more numbers worth knowing before you run it, because they set expectations that most tools in
this space quietly get wrong:

- **Dates barely exist in exports.** Parseable creation dates: 5.2% (Notion export), 6.3% (Apple Notes
  export), 43% (a maintained Obsidian vault). The export packages simply don't carry creation time.
  When date coverage falls under 30%, timeline insights are switched off entirely rather than computed
  from a 5% sample.
- **About 70% of documents don't join any topic.** They land in `residual`. Saying "these did not form
  a topic" beats smearing them into the nearest cluster.
- **The archive therefore explains a small slice of your knowledge base** — 16% and 23% on the two real
  corpora. That's stated inside the archive itself, in a section called "what this archive covers",
  because an agent that doesn't read that line will treat the slice as the whole.

## Quick start

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/). No Python installation needed:

```bash
uvx --from git+https://github.com/GiaSip/kb-init kb-init ~/Downloads/notion-export -o my-kb
```

> Not on PyPI yet, which is why the command has `--from git+…` in it. When the package ships, this
> becomes `uvx kb-init` — writing the short form today would just hand you a command that fails.

> First run downloads Python, dependencies and a ~90MB embedding model. Minutes, not seconds. This is
> "zero project setup", not "zero install". The indexing stage reports what it is doing the whole time
> (progress goes to stderr, so `kb-init … | pipe` is unaffected). It will **not** show you a fake ETA —
> we can't estimate it honestly.

## The one step you cannot delegate

Installing and running can go to an agent. The middle step cannot.

When `insights.md` is written, **every entry is pre-checked**. Running `compile` straight away means
accepting all of them. And cluster naming does fail: when a single language dominates a cluster, the
keywords that come out can be nothing but that language's common words. Measured: one corpus produced
9 recognisable groups out of 10, the other only 3 out of 5.

**Only the person who wrote the notes can tell which group is recognisable.** That's the whole reason
the confirmation step exists.

| Who | Does what |
|---|---|
| agent | installs uv, runs `kb-init`, hands you `report.private.html` |
| **you** | **open the report, uncheck the groups you don't recognise** (a dozen or so entries, a few minutes) |
| agent | runs `kb-init compile`, puts the archive where it belongs |

A prompt you can paste to your agent verbatim:

```
Run kb-init for me (a CLI that compiles note exports into a knowledge base an AI can use):
1. Make sure uv is installed, then:
   uvx --from git+https://github.com/GiaSip/kb-init kb-init <my export folder> -o my-kb
2. When it finishes, open my-kb/report.private.html for me, then STOP and wait.
3. I'll tell you when I've finished ticking my-kb/insights.md. Then run:
   uvx --from git+https://github.com/GiaSip/kb-init kb-init compile my-kb/insights.md --agent-file AGENTS.md
   (pick the filename your agent reads: CLAUDE.md for Claude Code, AGENTS.md for Codex)
You MUST stop after step 2 — that review is mine to do, and the tool's reliability rests on it.
Notes: the first run downloads a ~90MB model and takes minutes; don't mistake it for a hang.
It will not install on Intel Macs (a dependency ships no wheel for that platform) — if you hit a
build failure there, do not try to fix it.
```

## What you get

```
my-kb/
├── knowledge/          clean standard Markdown (relative-path links by default, not Obsidian-bound)
│   └── CLAUDE.md       the archive your agent reads (after compile; rename with --agent-file)
├── report.private.html for you: double-click to open, then go tick insights.md
├── report.share.html   the version you can send to someone (after compile, see below)
├── index.json          topic index: chunks, cluster assignment, representative docs, timeline gate
├── index-vectors.npy   document vector matrix (derived; deleting it costs you nothing readable)
├── insights.json       source of truth for insights — do not hand-edit
├── insights.md         the checklist: change only [x] / [ ]; edits to the prose have no effect
├── compile.json        compile receipt: which run wrote this archive, and its content hash
└── manifest.json       per-document status, identity, date provenance and destination
```

With `--no-index` you get only `knowledge/` and `manifest.json`.

Besides the per-document records, `manifest.json` carries three ledgers:

- `counts` — read / kept / dropped, by category
- `unresolved_links` — internal links pointing at something that doesn't exist (never existed, or was
  judged an empty shell or a duplicate). **These degrade to plain text; the output never contains a
  dead link.**
- `skipped_inputs` — inputs skipped because their filenames are equivalent at the filesystem level
  (`A.md` vs `a.md`, NFC/NFD). Not rare in macOS exports.

## Two reports

The main command produces `report.private.html` — **double-click it, no network needed**.

It isn't decoration. The insight checklist needs your line-by-line confirmation, and nobody
proof-reads a config file. So the checklist is rendered as a report about you first. Read it, then go
back to `insights.md` and uncheck. Every entry carries the same short ID as the checklist
(`T1` / `R1` / `C1`).

`kb-init compile` then writes `report.share.html` — **the one you can send out**:

- only entries you **left checked**;
- only keywords and counts — **no note titles, no body fragments, no file paths, no run IDs**;
- compile prints every keyword the shareable version contains to your terminal. **Keywords come
  straight out of your notes**, and field-level filtering cannot fix that — read the printed list
  before you send the file.

Both reports are single-file, no JavaScript, no external requests.

## Generating the archive your agent reads

Once you've finished ticking:

```bash
kb-init compile my-kb/insights.md                            # → my-kb/knowledge/CLAUDE.md
kb-init compile my-kb/insights.md --agent-file AGENTS.md     # Codex and others
kb-init compile my-kb/insights.md --agent-file GEMINI.md     # Gemini
```

**Producing a file your agent doesn't read is the same as producing nothing**, so the name is yours to
pick.

It only takes insights you checked *and* that declared a destination — corpus-level statistics
(retention rate, broken-link counts) are useless to an agent and never enter the archive.

**Every sentence in the archive is word-for-word the sentence you approved on the checklist.** It is
not rephrased, because "what you reviewed is what went in" is the entire value of that review step.

How many sections there are depends on how much material there is upstream; this version has two
(focus areas / coverage). An unrecognised section is a hard error, never a silently missing section.

Re-running is safe. But compile **only overwrites an archive it wrote itself** (verified by receipt
and content hash). Any other file with that name — including an archive you hand-edited — is refused.

> ⚠️ If your knowledge base already contains a note called `CLAUDE.md`, compile refuses to write and
> tells you. Delete or rename it and re-run.

## Supported platforms

| Platform | Status |
|---|---|
| Windows x64 | ✅ dependencies complete, covered by CI |
| Linux x64 | ✅ dependencies complete, covered by CI. Needs glibc ≥ 2.28 (Ubuntu 20.04+, Debian 10+, RHEL 8+) |
| macOS Apple Silicon | ✅ dependencies complete, covered by CI. Needs macOS ≥ 14 |
| Windows arm64 / Linux aarch64 | ⚠️ wheels exist, but **we have not tested it** — probably fine; please open an issue if not |
| **macOS Intel** | ❌ **not supported** |

Python: **3.12 / 3.13**. The upper bound is deliberate — we haven't tested anything newer. It will be
raised once it's been tested, not before.

macOS Intel isn't laziness on our part. Vector inference depends on
[`onnxruntime`](https://pypi.org/project/onnxruntime/#files), which no longer publishes macOS x86_64
wheels (checked version by version; gone since at least 1.18). Installing on an Intel Mac degrades to
a source build and fails. Better to say so now than to let you spend twenty minutes hitting a wall.

## Options

| Option | Meaning |
|---|---|
| `-o, --out` | Output directory (default `kb-out`). Refuses to overwrite a non-empty directory |
| `--no-index` | Skip indexing: no model download, no network, cleaned output in seconds |
| `--wikilinks` | Keep the `[[wikilink]]` dialect. **Off by default** — the default emits standard relative links, because `[[...]]` is not standard Markdown and renders as a dead link in VS Code and on GitHub. It changes only the **output syntax**, not resolution: targets still resolve to the frozen output name (`[[Project A]]` → `[[Project-A\|Project A]]`, because the file is actually `Project-A.md`), and ambiguous targets still degrade. **Existing standard relative links are remapped either way**, otherwise they break once the tree is flattened |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | output directory not empty, refused to overwrite |
| 2 | usage error |
| 3 | input unsafe, corrupt, or missing |
| 4 | read/write failure |
| 5 | cleaned output published, indexing did not finish (re-run with a different `--out` to add it) |
| 6 | cleaned output and index present, insights layer missing |
| 7 | `validate` judged `insights.md` invalid (fix the file and re-run; **no need to re-index**) |
| 8 | `compile`: checklist valid, but no entry qualifies for the archive (go tick some) |
| 9 | `compile`: `insights.json` doesn't match this version of kb-init (re-run with the current version) |
| 10 | cleaning, index and insights all present, only the report is missing (the checklist still works) |

Errors print a one-line diagnostic. End users never see a Python traceback.

5 / 6 / 7 are deliberately distinct: the next action differs completely in each case — re-index (needs
network and the model), recompute insights only, or fix the checklist in your hand. Merging them would
make scripts do unnecessary work.

8 and 9 likewise: the fix for 8 is in *your* hands (change the ticks), the fix for 9 is in the *tool's*
(re-run). Reporting 9 as 8 would send you off to edit a file that has nothing wrong with it.

## Using the insight checklist

`insights.md` is a checklist with visible short IDs. **You should only change `[x]` / `[ ]`:**

```bash
kb-init validate my-kb/insights.md    # standalone validation, returns 0 on success
```

Editing the prose has no effect — downstream reads the text from `insights.json` by ID and does not
trust hand-edited copy. A missing, duplicated, unknown, or cross-run ID is an error with a line number.
It will **never silently compile a few entries fewer.**

## FAQ

**Does it need Obsidian?**
No. None of the three outputs require it. If you do use Obsidian, open the output directory as a vault.

**Does it touch my Notion / Apple Notes account?**
No. Input is an exported folder or zip. No OAuth, no API tokens, entirely local.

**Does anything get sent anywhere?**
No. The only network access is downloading the embedding model on first run. Both HTML reports are
single-file with no JavaScript and no external requests.

**Can I run it without downloading the model?**
Yes — `--no-index`. You get `knowledge/` and `manifest.json` in seconds, without insights or reports.

**Why is 60% of my export thrown away?**
It isn't thrown away, it's marked. Years-old exports are mostly empty shells: titles with no body,
orphaned database rows, duplicates. Every one stays in `manifest.json` with its drop reason.

**Why does the archive only cover 16–23% of my notes?**
Because ~70% of documents don't form a topic, and saying so is more useful than diluting real clusters
with unrelated documents. The archive states its own coverage so your agent doesn't mistake the slice
for the whole.

**Why doesn't it use file modification time to judge freshness?**
Because that number is a lie. Measured on a normally maintained knowledge base, "untouched for 180+
days" came out as 0% — sync, git and bulk operations all refresh mtime. The fallback chain is
frontmatter → date in body → date in filename → first git commit, and `unknown` when all of those miss.

**Can my agent do the whole thing end to end?**
No, and that's the design. See [the one step you cannot delegate](#the-one-step-you-cannot-delegate).

**Is it on PyPI?**
Not yet. Install with `uvx --from git+https://github.com/GiaSip/kb-init`.

**Which agents work with it?**
Any agent that reads a Markdown context file. Use `--agent-file` to pick the name: `CLAUDE.md` for
Claude Code, `AGENTS.md` for Codex, `GEMINI.md` for Gemini.

## Design decisions

- **No Obsidian dependency.** None of the three outputs need it.
- **Never touches your account.** Export folder or zip in, local processing, nothing out.
- **Cleaning marks, it doesn't delete.** Dropped records stay in the manifest with their reason — that
  is precisely why `1,925 → 757` is a number anyone can check.
- **Never uses mtime for freshness.** See the FAQ. Falls back through frontmatter → body date →
  filename date → first git commit, then marks `unknown`. It does not guess.
- **The run is atomic.** Output lands in a sibling staging directory and is published with a **single
  directory rename** once everything succeeded. A failure mid-run leaves no half-finished state; just
  run it again.
- **Ambiguity is never guessed.** When a link alias matches more than one document, it degrades to
  plain text and gets recorded, rather than pointing at one of them. A dead link gets noticed; a live
  link pointing at the wrong document does not.
- **Exactly one link base.** Standard relative links resolve against the **directory of the current
  document**, per [CommonMark](https://spec.commonmark.org/) — no cross-directory fallback by filename,
  and no "try the export root if the current directory misses". `(note.md)` inside `a/linker.md` can
  only ever mean `a/note.md`; if the corpus only has `b/note.md`, it degrades to plain text.

## Known limitations

- **Timeline insights are unavailable on export-type corpora.** Parseable date rates: Notion export
  5.2%, Apple Notes export 6.3%, maintained Obsidian vault 43%. The root cause is that exports don't
  carry creation time — not a parsing weakness. Below 30% coverage the index sets
  `time_axis.available` to `false` and timeline-dependent insights simply aren't produced.
- **Most notes join no topic.** ~70% land in `residual` on real corpora, so **the archive explains only
  a small part of your knowledge base** (16% / 23% measured).
- **Archive sentences are review language** ("the most distinctive words among these N documents
  are …"), which doesn't read like prose written for an agent. That's a price paid on purpose: the
  sentence must be word-for-word what you approved, or compile would emit text you never reviewed.
- **Report sentences are identical to archive sentences.** The report will not phrase it more nicely —
  otherwise you'd be deciding based on sentence A while sentence B goes into the archive. "Looking
  good" is the typography's job.
- **Cluster names are keywords, not topic names.** When one language dominates a cluster, the result
  can be that language's common words. Keywords are therefore always shown with the document count and
  three evidence titles — enough for you to judge at a glance, and to untick when it's wrong.
- Nested-structure links (e.g. `[![img](x.png)](target.md)`) are not remapped — the matching regex
  disallows `]` inside a link label. On the real Notion corpus (1,925 files), the remaining 2 of 237
  dead links are all of this kind.
- Under `--wikilinks`, a `[[...]]` pointing at a target that **never existed** is preserved as-is (in
  Obsidian that's a legal "not yet created" link). Output in that mode may therefore contain wikilinks
  to non-existent files; all of them are recorded in the manifest's `unresolved_links`. The default
  mode has no such case — unresolvable means plain text.
- Filenames are treated as equivalent under **NFC + case-insensitive** rules (the macOS/Windows
  default). On a case-sensitive filesystem, `Guide.md` and `guide.md` collide; the first wins and the
  other is recorded in `skipped_inputs`. Link resolution uses the same equivalence rules, so entry and
  exit stay consistent.
- Title slugification covers only the CJK Basic Multilingual Plane (U+4E00–U+9FFF); extension-plane
  Han characters are stripped as unsafe.
- Attachments and images are not copied to the output directory.

## Contributing

Bug reports and platform reports are the most useful thing right now — especially on Windows arm64 and
Linux aarch64, which have wheels but no test coverage. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[Apache-2.0](LICENSE). See [NOTICE](NOTICE).
