# Research foundation

Every load-bearing design decision in this repository traces to a paper below.
When you change the design, update this file. When a claim here is unsourced,
delete the claim.

---

## Tier 1 - the method we implement

### 1. Just-in-Time Catching Test Generation at Meta
**arXiv:2601.22832** - Becker, Chen, Cochran, Ghasemi, Gulati, Harman, Haluza,
Honarkhah, Robert, J. Liu, W. Liu, Thummala, Yang, Xin, Zeng.

The paper we are implementing. What we take from it:

| Finding | Where it lands in this repo |
|---|---|
| Catching tests find ~4x more faults than hardening tests, ~20x more than coincidental fault detection | The differential oracle in `execute.py` - a candidate that passes on head is discarded |
| 22,126 tests deployed at Meta | Scale we cannot match. Do not claim we have. |
| Assessors cut human review load by ~70% | `assess.py` - this stage is the product, not the generator |
| Diff Risk Score targets only high-risk diffs | `risk.py` |
| Runs overnight on spare capacity | The `budget_usd` cap and `risk_threshold` gate - JiTTest economics only work if you do not run on every diff |

**What does not transfer:** Meta has an internal monorepo, a build graph, a
DRS trained on years of incident data, and free spare compute. We have none of
those. The 4x figure is a Meta-internal result. Reproducing it externally is an
open question, and `eval/` exists to answer it honestly.

### 2. The Catching JiTTest Challenge
**arXiv:2504.16472** / ACM 10.1145/3696630.3734199 - Mark Harman, FSE 2025 keynote.

Harman explicitly poses catching-test generation as an **open challenge to the
research community**: *"we believe these open challenges represent such exciting
opportunities for researchers, due to the enormous potential real world impact."*

This repository is a response to that challenge. Two consequences:

- The framing in every launch post is *answering a published open challenge*,
  not *cloning a Meta product*.
- Harman notes any catching-JiTTest solution can be **repurposed to catch latent
  faults in legacy code**. That is our v0.5 expansion path, already stubbed by
  the "fails on base too" branch in `execute.py`.

---

## Tier 2 - the prior generation, and why it was not enough

### 3. Automated Unit Test Improvement using LLMs at Meta (TestGen-LLM)
**arXiv:2402.09171** - Alshahwan, Chheda, Finogenova, Gokkaya, Harman, et al.

The hardening predecessor. 75% of generated tests built correctly, 57% passed
reliably, 25% increased coverage; 73% of recommendations were accepted by
engineers.

Critically, the paper states: *"TestGen-LLM discards any test case that does not
pass on first execution."* **That constraint is exactly what JiTTest inverts.**
Our generator prompt is the inversion, and it is the one-sentence explanation of
why this repo is not Cover-Agent v2.

### 4. Are the Machines Learning? / Cover-Agent evaluation
**arXiv:2412.14137**

Contains the design critique that justifies our existence. On Cover-Agent, the
first open-source TestGen-LLM implementation:

> it "may inadvertently reinforce existing bugs in the code by only keeping tests
> that pass on the current, potentially faulty, implementation."

This is the argument, in a peer-reviewed venue, and it is our launch headline.
The top Hacker News comment on Cover-Agent independently said the same thing:
*"What the reasoning behind generating tests until they pass? Isn't the point of
tests to discover erroneous corner cases?"*

---

## Tier 3 - demand evidence (cite these, do not assert them)

### 5. Test Coverage Analysis of Agentic Pull Requests
**arXiv:2607.18057** (approx. 20 July 2026) - 4,882 agent-generated PRs from the
AIDev dataset, 532 Java and 4,350 Python, across five coding agents.

> **Agents include test changes in only 49.6% of PRs that change code under test.**

Equivalently: 50.4% of agentic PRs that touch tested code ship with no test
changes at all. This is the single freshest, most quotable demand statistic
available and it is five days old as of project start. It goes in the README,
the launch post, and the first slide of any talk.

### 6. Where Do AI Coding Agents Fail?
**arXiv:2601.15195** (21 January 2026). Failure taxonomy for agentic PRs.

### 7. Why Are Agentic Pull Requests Merged or Rejected?
MSR 2026 mining challenge (13 April 2026). Copilot and Devin PRs are
reviewer-mediated; Codex and Cursor PRs are merged with minimal interaction.
The second group is where undetected regressions land.

### 8. Are "Solved Issues" in SWE-bench Really Solved Correctly?
ICSE 2026 - 11.0% of plausible patches are incorrect; **50% of incorrect patches
cannot be identified by running all developer tests.** Existing test suites are
structurally insufficient for verifying generated code. This is the deepest
justification for the whole category.

---

## Tier 4 - technique we borrow

### 9. LLMs are the key to mutation testing and better compliance (Meta ACH)
Meta Engineering, 30 September 2025 - Automated Compliance Hardening applies
LLM-driven mutation testing to compliance coverage. Confirms Meta's continued
investment in the adjacent space and supplies the fault-seeding technique used
in `eval/` to synthesise regressions.

### 10. Mutation testing tool comparisons
- Cosmic Ray and mutmut remain the maintained Python options; a 2025 NSF-hosted
  comparison found Poodle produced the most competent mutants (50.9%), Cosmic
  Ray second (25.7%).
- We do **not** depend on a mutation framework at runtime. We use mutation only
  in `eval/` to seed known regressions and measure our catch rate. Runtime
  mutation testing is too slow for PR-time, which is precisely the gap JiTTest
  fills.

---

## Benchmarks we evaluate against

| Benchmark | Repo | Why |
|---|---|---|
| **BugsInPy** | `soarsmu/BugsInPy` | 493 real Python bugs with buggy commit, fixed commit, and a triggering test. Our primary harness: reverse each fix into a synthetic "regression PR" and measure catch rate. |
| **Defects4J 3.0.1** | `rjust/defects4j` | 854 real Java bugs. For the v0.6 Java port. Note documented data-leakage concerns for LLM evaluation. |
| **GitBug-Java** | `gitbugactions/gitbug-java` | Recent bugs, lower memorisation risk than Defects4J. Preferred for headline numbers. |
| **SWE-bench Verified** | `swe-bench/SWE-bench` | Not a fit for catching tests directly, but the ICSE 2026 correctness study above is derived from it. |

**Honesty rule for the eval harness:** report catch rate, false-positive rate,
and cost per PR together. A catch rate published without a false-positive rate
is marketing. Meta's own contribution was the assessor, i.e. precision.
