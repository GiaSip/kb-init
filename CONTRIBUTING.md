# Contributing

## What's most useful right now

**Platform reports.** Windows arm64 and Linux aarch64 have wheels for every dependency but no test
coverage — nobody has run kb-init on them. If you do, please open an issue either way. "It worked" is
a useful report here.

**Real-corpus bug reports.** This project's most expensive lesson is that synthetic fixtures don't
reproduce real shapes: the link layer passed every synthetic test while a real Notion export had 288
internal links that were 100% dead. If something breaks on your export, the shape of your export is
the interesting part.

## Setup

```bash
uv sync
```

## Running the tests

```bash
.venv/bin/pytest -q               # everything (real-corpus checks skip if the corpus isn't present)
.venv/bin/pytest -q -m smoke      # real-model smoke test, needs a warm model cache
```

**Use the `pytest` console entry point, not `python -m pytest`.** The `-m` form silently puts the
current directory on `sys.path`; CI's entry point does not. That difference once made CI fail on all
six matrix cells while every local run was green.

**CI also runs Python 3.13, and the local venv is 3.12.** That gap is not theoretical — 3.13 dedents
docstrings at compile time, and a docstring containing a lone surrogate makes the whole module fail at
import, which 3.12 never notices. For changes touching docstrings, encoding, or packaging, run the
suite on 3.13 in a copy (don't use `uv run --python 3.13` in the project itself; it replaces `.venv`):

```bash
rsync -a --exclude .venv --exclude .git --exclude dist ./ /tmp/kb313/ \
  && (cd /tmp/kb313 && uv run --python 3.13 pytest -q)
```

**Windows' default encoding is not UTF-8** (it's cp1252), so any text read/write or
`subprocess(text=True)` without an explicit `encoding` is "green here, red on Windows". The static side
is guarded by `tests/test_source_hygiene.py`; for executed paths there's a runtime probe:

```bash
PYTHONWARNDEFAULTENCODING=1 .venv/bin/pytest -q -W error::EncodingWarning
```

That probe found a real product bug the static check missed.

## Invariants worth knowing before you change things

These are all paid for. The full set lives in `CLAUDE.md` (in Chinese, along with the design docs under
`docs/`); the ones most likely to bite a contributor:

1. **A single fallback path is enough to make a rule stop firing.** This has recurred five times in
   different shapes — "if this base doesn't resolve, try another", an empty-insight placeholder that
   padded the count so a stop condition never triggered, an internal-only bypass flag. Before adding
   any fallback, default-allow, or internal switch, ask: *does this let some rule never fire?*
2. **A failure must not take completed output with it.** Indexing failure is absorbed into state
   (`manifest.index_status`); the CLI maps it to an exit code *after* `run()` returns normally.
3. **Not guessing is a feature.** Unparseable date → `unknown`. Unclusterable → `residual`. Insufficient
   timeline coverage → the whole timeline is switched off. **A default value is also a guess.**
4. **Output must not lie.** A degraded chunker records `fallback_used`; a fake embedder must not be
   reported as fastembed; `coverage` is derived from assignments, never counted separately.
5. **Unit tests never download a model.** `fastembed` and `sklearn` are imported lazily; never at
   module top level.
6. **An assertion can be vacuously true.** When the tokenizer truncates by itself, "every chunk ≤ 512
   tokens" passes forever while the chunker does nothing. Before you commit an assertion, ask whether
   it can ever fail. The same goes for detectors: test that a bad case *is* caught, or a detector that
   always returns "clean" will pass too.

## Test fixtures and privacy

**Never copy URLs, titles or keywords out of real output into a fixture.** Use `example.com` and
placeholder words. Two leaks have happened this way, both while the author was actively thinking about
open-source hygiene, which is why there's a detector rather than a reminder:

```bash
python3 probes/corpus_leak_probe.py <an insights.json outside the repo>
```

Its probe strings are read from a real artifact **outside** the repository — the script itself contains
no personal data. A hit is a lead, not a verdict; a human looks at the list.

## Pull requests

- Keep commits grouped by category; don't mix unrelated changes into one commit.
- CI must be green on all six matrix cells (Windows / Linux / macOS × 3.12 / 3.13) plus the packaging
  job. That job installs the **built wheel** into a fresh environment, because working in a dev
  checkout proves nothing about what gets packaged.
- New behaviour needs a test. New detectors need a negative control.
