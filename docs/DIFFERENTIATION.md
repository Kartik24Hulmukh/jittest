# Why another one of these

There are, by any honest count, more than a dozen AI code-review tools and at
least half a dozen AI test generators. In June 2026 the front page of Hacker
News carried a thread titled ["There is an AI code review
bubble"](https://news.ycombinator.com/item?id=46766961). The top comment was not
about accuracy. It was: *"I wouldn't want it turned on by default for every PR."*

That is the market jittest is entering. Adding a fourteenth reviewer that talks
more would be worthless. So here is the specific, falsifiable difference.

## 1. A mechanical oracle, not a persuasive model

Every other tool in this space ultimately asks a model *"is this a problem?"* and
relays the answer. jittest asks a model to write a test, then **runs it on both
commits** and keeps it only if it passes on base and fails on head.

The consequence is not marginal. It means:

- jittest can be **silent**, because it has a mechanical way to know it has
  nothing to say. Tools without an oracle cannot be silent — they have no
  ground truth to distinguish "nothing found" from "nothing noticed".
- A finding is **not an opinion**. It ships with a command you can run.
- The false-positive rate is bounded by the oracle, not by prompt quality.

## 2. Catching, not hardening

Qodo (then Codium) shipped the first open implementation of Meta's *TestGen-LLM*
in May 2024 and got real traction with it. The top comment on its Hacker News
launch was:

> *"What the reasoning behind generating tests until they pass? Isn't the point
> of tests to discover erroneous corner cases?"*

That question was never answered by the coverage-maximising generation of tools,
and `qodo-cover` was [archived as unmaintained in June
2025](https://github.com/qodo-ai/qodo-cover). Coverage generators optimise for
green. jittest optimises for red-then-green-on-base, which is the only signal a
reviewer of a *diff* actually needs.

This is also the honest bear case: Qodo raised $70M in March 2026 and could
build this in a quarter. The defence is not the algorithm — it is items 4 and 5
below.

## 3. Zero dependencies

`pip install jittest` adds nothing to your dependency graph. Not `unidiff`, not
`litellm`, not `pydantic`, not `rich`. For a tool whose entire job is to run
inside somebody else's locked CI environment, this is not minimalism for its own
sake — it is the difference between "try it on Monday" and "open a ticket with
platform engineering".

It also means jittest can run where nothing can be installed: hardened runners,
air-gapped builds, and containers with no package index. When `pytest` is not
importable, jittest uses its own 100-line runner with pytest-compatible exit
codes rather than refusing to work.

## 4. The assessor layer

The oracle decides whether a test is **true**. The assessor decides whether it is
**worth saying**. Only a confident `real_regression` is reported; `intended_change`
and `unclear` are recorded in the ledger and stay quiet.

This layer exists because being right is not the bar. Independent 2026
measurements put 15–30% of AI review comments in the low-value or incorrect
bucket, and roughly a third of developers say they trust the output. Every
unnecessary comment spends trust that the necessary one will need.

## 5. The labelled corpus

`jittest outcome <hash> fixed_code|kept_test|intended|false_positive|ignored`

Every candidate, its risk score, the oracle verdict, the assessor call and
**what the human did next** is written to a local SQLite ledger, exportable in
anonymised form.

The code in this repository can be reimplemented by a competent engineer in a
fortnight. A corpus of real diffs paired with real human reactions cannot be
reimplemented at all — it can only be accumulated, one pull request at a time,
by whoever is installed first and is trusted enough to stay installed. That is
the only compounding asset here, and it is why the outcome command exists in
v0.2 rather than "later".

## 6. Reproducibility as a first-class output

Every finding prints the exact two commands that reproduce it. Every run reports
how many symbols were analysed, how many candidates were generated, how many the
oracle discarded and why, and what it cost. A tool asking for a place in your CI
should be auditable by default.

## What jittest is not

- **Not a coverage tool.** It will not raise your coverage percentage and does
  not try to.
- **Not a linter or a style reviewer.** It has exactly one thing to say and says
  it only when proven.
- **Not a replacement for your test suite.** It tests the diff, not the product.
- **Not free to run.** It executes generated code and calls a model. The budget
  cap is a hard stop, not a suggestion.
- **Not yet benchmarked.** See the honest-status table in the README. Numbers
  will be published with methodology and failures included, or not at all.
