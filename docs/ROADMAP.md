# jittest roadmap: 25 July to 12 September 2026

Six weeks of build, preceded by one week of talking to humans.

**Ship date: Thursday 10 September 2026.** Hard gate: Friday 12 September.
If the gates below are not met, you do not launch. You publish what you learned
and stop. That option is real and taking it is not failure.

---

## Reality check before you start

Read these three sentences every week.

1. The reference-implementation move is **verified to work for distribution**
   (Qodo Cover: HN front page, Trendshift, freeCodeCamp, academic citation, then
   a $40M Series A) and **verified not to be a company** (same repo abandoned
   2025-06-15, approximately $1M revenue in 2024).
2. Therefore the repo is a **credibility and search-term wedge with a six-week
   clock**, not the business.
3. The clock does not run out on a calendar date. It runs out when Qodo decides
   to ship catching tests. They have the motive, the exact prior art, and $120M.

---

## WEEK 0 - 25 to 31 July. No code.

This is the week you have skipped four times. The entire roadmap is conditional
on it.

| Task | Output | Metric | Deadline |
|---|---|---|---|
| Send 12 messages to Python OSS maintainers with 200+ open PRs | 12 sent | 4 replies | Sun 26 Jul |
| Manual reproduction: 5 real regressions, by hand, in a chat window, no repo | `docs/MANUAL-REPRO.md` filled in | catching test produced for 3 of 5 | Tue 28 Jul |
| Re-run the "does a JiTTest implementation exist" search | one paragraph in PRIOR-ART.md | still zero | Wed 29 Jul |
| Email Mark Harman: one paragraph, you are answering the FSE 2025 challenge, ask nothing | sent | any reply is upside | Wed 29 Jul |
| 3 calls with maintainers who replied | notes | 2 say "yes, send it to me" | Fri 31 Jul |

**GATE 0 (Fri 31 July):** at least 3 of 5 manual reproductions succeeded AND at
least 2 maintainers said they would install it. If not, the thesis is weaker
than the paper suggests and you stop here having spent $40 and a week. **This is
the cheapest possible kill and it is the most valuable line in this document.**

---

## WEEK 1 - 1 to 7 August. The oracle.

Build the thing that cannot be faked. If the oracle does not work nothing else
matters, so it goes first.

- `diff.py`, `risk.py`, `execute.py` working end to end on a toy repo
- `differential_check` correctly rejects: passing-on-head, flaky, fails-on-both
- 30+ unit tests, CI green on Python 3.10-3.13
- No LLM yet. Feed it hand-written tests.

**Exit:** given a repo with a seeded regression and a hand-written catching test,
`jittest` classifies it correctly 10 times out of 10.

## WEEK 2 - 8 to 14 August. The generator.

- `llm.py`, `prompts.py`, `pipeline.py`
- Prompt iteration against the 5 bugs from Week 0
- Cost accounting and the hard budget cap
- First real end-to-end run on a real PR in a real repo

**Exit:** on the 5 Week-0 bugs, generate a mechanically-verified catching test
for at least 2 of 5, unassisted, under $1 each.

**GATE 1 (Fri 14 August):** if the answer is 0 of 5, the 4x result does not
transfer outside Meta's infrastructure and you should publish that as a negative
result. **A credible negative result on a Meta paper is itself a reputation
asset.** Do not pretend it worked.

## WEEK 3 - 15 to 21 August. The assessor and the ledger.

This is the week that decides whether this is a product or a demo.

- `assess.py`, `ledger.py`, `report.py`
- Label 100 candidates by hand: regression / intended / invalid. This is the
  seed corpus and you cannot outsource it.
- Tune `MIN_CONFIDENCE` against that hand-labelled set
- Measure and publish false-positive rate

**Exit:** on 100 hand-labelled candidates, precision above 0.80 at the reporting
threshold. Precision, not recall. A tool that cries wolf dies.

## WEEK 4 - 22 to 28 August. Evaluation.

- `eval/run_bugsinpy.py` against 50 BugsInPy bugs using the fixed-to-buggy
  inversion
- Cross-check on GitBug-Java-adjacent recent bugs for memorisation
- Produce the numbers table that goes in the README

**Exit:** one honest table with catch rate, false-positive rate, and cost per PR
side by side. Publish it even if the numbers are mediocre. Especially then.

## WEEK 5 - 29 August to 4 September. Make it installable.

- Composite GitHub Action, published to Marketplace
- PyPI release, semantic versioning, changelog
- README with a 30-second quickstart and a real screenshot of a real finding
- jittest running on jittest in CI (the self-check job)
- **5 design partners running it on real repos**

**Exit:** someone who is not you installs it from the README alone and gets a
result without asking you a question.

## WEEK 6 - 5 to 12 September. Launch.

| Day | Action |
|---|---|
| Mon 7 Sep | Final search: has anyone shipped a JiTTest implementation? If yes, contribute to theirs instead. |
| Tue 8 Sep | Write the launch post. Headline is the inverted oracle, not the model. |
| Wed 9 Sep | Send the post to Harman and the paper authors 24h early. Courtesy, not permission. |
| **Thu 10 Sep** | **Ship.** HN Show HN at 13:00 UTC, r/Python, r/programming, X, Lobsters. |
| Fri 11 Sep | Answer every single comment. This is the highest-leverage day of the quarter. |
| Fri 12 Sep | **GATE 2.** |

**GATE 2 (12 September):** 500 GitHub stars AND 20 repos with the Action
installed AND 5 confirmed real regressions caught in other people's code.
Stars alone do not pass. Qodo Cover proves stars are obtainable and insufficient.

---

## The launch post structure

1. Meta published JiTTest in 2026: tests that fail on your diff and pass without
   it. 4x more faults than hardening tests.
2. In 2024 the community open-sourced TestGen-LLM as Cover-Agent. It only kept
   tests that **passed**. A peer-reviewed critique said this "may inadvertently
   reinforce existing bugs." The top HN comment said the same thing.
3. Harman posed catching-test generation as an open challenge to the community.
4. Here is an implementation. Here are its numbers, including where it fails.
5. Five days before we started, a paper found **50.4% of agentic PRs that modify
   tested code ship with no test changes at all.**
6. Install: one YAML block.

No hype adjectives. The credibility is the whole asset; spending it on marketing
language is the one unrecoverable mistake.

---

## What happens after 12 September (decide by 5 September, not later)

The repo is not the business. Pick the conversion target **before** launch or
the traffic is wasted, exactly as it was in 2024.

| Option | What it is | Evidence needed by 5 Sep |
|---|---|---|
| **A. Hosted jittest** | We run it, you install an app, you pay per analysed PR | 5 teams say they will not run their own API keys |
| **B. The corpus** | Publish the open benchmark, sell the calibrated assessor | 100+ labelled candidates showing tuning beats the default |
| **C. Latent-fault mode** | Harman's stated expansion: point it at legacy code, not just diffs | 2 maintainers ask "can I run this on my whole repo?" |
| **D. Nothing** | Keep it a well-maintained OSS project, get hired or get consulting | You do not want to run a company |

Option C is the most under-priced. Harman explicitly notes any catching-JiTTest
solution can be repurposed to catch latent faults in legacy code, and the market
for "find the bugs already in my codebase" is larger and less contested than PR
review. `execute.py` already routes fails-on-both to that backlog.

---

## Risks, ranked by probability times impact

| Risk | P | Impact | Mitigation |
|---|---|---|---|
| Catch rate too low outside Meta's infra | 0.45 | Fatal | GATE 1 at Week 2. $40 pre-check in Week 0. |
| False positives destroy trust | 0.40 | Fatal | Precision-first, silence by default, mechanical oracle |
| Qodo ships catching tests first | 0.25 | Severe | Six-week clock; monitor their changelog weekly |
| Stars but no users (the Qodo Cover outcome) | 0.60 | Severe | GATE 2 counts installs and caught bugs, not stars |
| Cost per PR unacceptable | 0.30 | Moderate | Risk targeting and hard budget cap built in from v0.1 |
| You do not have the hours to build it | ? | Fatal | **Unknown. Answer this before Week 1.** |
| Solo maintainer burnout, repo abandoned | 0.35 | Severe | The abandonment of Cover-Agent is our opening; do not repeat it |

---

## What is still missing from this plan

The founder context ledger is empty. This roadmap assumes roughly 25 hours a
week and that you can write and debug a CI-integrated Python tool alone. Neither
has been established in six sessions of conversation.

If either is false, the correct plan is not this one. It is: do Week 0, publish
the manual reproduction as a blog post answering Harman's challenge, and decide
afterwards.
