# Why a raw note export fails as agent context — and what a compile step must do

A common first move when giving an AI agent your notes: locate the Notion or Apple Notes
export folder on disk and point the agent at it. The files are Markdown, the agent reads
Markdown, so it should work. In practice it doesn't — and the reasons are measurable, not
matters of taste. This document lays out those reasons, derives the criteria a "compile
step" must satisfy, and shows how [kb-init](https://github.com/GiaSip/kb-init) implements
each one. All numbers below are measured on two real exports and reproduced in the
[README](../README.md#what-it-actually-does-in-numbers).

## Four reasons a raw export doesn't work as agent context

**1. Most of it is empty shells.** On a real years-old Notion export, 1,168 of 1,925 files
(60.7%) were titles with no body, orphaned database rows, or duplicate pages. On an Apple
Notes export, 333 of 620 (53.7%). An agent pointed at the raw directory spends its context
window on this and inherits a distorted picture of what you actually know.

**2. The dates are missing or lying.** Parseable creation dates: 5.2% of the Notion export,
6.3% of the Apple Notes export — the export packages simply don't carry creation time. The
obvious fallback, file modification time, is worse: measured on a normally maintained
knowledge base, "untouched for 180+ days" came out as **0%**, because sync tools, git, and
bulk operations all refresh mtime. Any time-based reasoning an agent performs on an export
is built on a broken proxy.

**3. The links don't survive flattening.** Exports nest deep (the Notion export ran 11–15
directory levels). Flattening that tree breaks relative links; Notion additionally
URL-encodes its link targets; `[[wikilink]]` syntax is an Obsidian dialect that renders as
a dead link in VS Code and on GitHub. None of this fixes itself when the agent starts
reading.

**4. Volume forces compression, and compression without review fabricates.** 1,925 files
cannot enter a context window. Summarizing them down to something an agent can hold means
making claims about your knowledge — and if nobody reviews those claims, the archive ends
up asserting things you never said.

## The criteria: what a compile step must do

1. **Drop the shells, keep the receipts.** Empty shells must be dropped by measurement —
   but never silently. Every dropped record stays in a manifest with its reason, which is
   the only reason a headline number like `1,925 → 757` can be checked by anyone.
2. **Never emit a live wrong link.** A dead link gets noticed; a link that resolves to the
   *wrong* document does not. Ambiguous targets must degrade to plain text and be recorded,
   and paths must be frozen *before* any link rewriting happens.
3. **Be honest about dates.** Fall back through frontmatter → date in body → date in
   filename → first git commit, and when none of those hit, mark `unknown` and don't guess.
   When date coverage falls under a threshold, switch timeline reasoning off entirely
   rather than compute it from a 5% sample.
4. **Keep a human gate on what enters the archive.** Cluster naming fails in measurable
   ways — on the two real corpora, 9 of 10 and 3 of 5 produced groups were recognizable;
   the rest came out as common-word noise. Only the person who wrote the notes can judge
   which is which, so the review cannot be delegated to the agent.
5. **State what it covers.** On real corpora, ~70% of documents don't join any topic, so
   the archive explains only 16–23% of the knowledge base. If the archive doesn't say so
   inside itself, the agent treats the slice as the whole.
6. **Land in the file the agent actually reads.** `CLAUDE.md` for Claude Code, `AGENTS.md`
   for Codex, `GEMINI.md` for Gemini — a knowledge file the agent doesn't read is
   equivalent to no file.

## How kb-init implements each criterion

- **Receipts:** `manifest.json` records per-document status and drop reason, plus ledgers
  for unresolved links and skipped same-name inputs. Nothing is deleted.
- **Link invariant:** output paths are frozen before link rewriting; unresolvable links
  degrade to plain text and are recorded in `manifest.json`'s `unresolved_links`; under
  ambiguity the tool refuses to pick a winner.
- **Date honesty:** the fallback chain above, then `unknown` — never mtime. Below 30%
  date coverage, the index sets `time_axis.available` to `false` and timeline insights
  simply aren't produced.
- **Human gate:** `insights.md` is a checklist with visible IDs; `kb-init compile` accepts
  only entries you checked, and every archive sentence is word-for-word the sentence you
  approved — not rephrased, not generated fresh. Compile refuses to overwrite an archive
  it didn't write itself.
- **Coverage statement:** the archive carries a "what this archive covers" section stating
  its own share of the corpus.
- **Agent file:** `--agent-file` picks the filename your agent reads.

## Limitations, honestly

- The archive explains only a small slice of the knowledge base (16–23% measured), because
  most notes genuinely don't form topics. Saying so beats smearing documents into the
  nearest cluster.
- Archive sentences are review language ("the most distinctive words among these N
  documents are…"), not prose written for an agent — the price of "what you reviewed is
  what went in."
- kb-init is a one-shot compiler, not a maintenance pipeline: it produces the archive and
  leaves; keeping the knowledge base alive afterwards is out of scope by design.
