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

**A cautionary note that belongs beside the citation.** Qodo, which shipped
Cover-Agent, archived the repository (banner dated 2025-06-15) while raising 40
and then 70 million dollars. The lineage citation buys attention. Retention is
earned separately, and by a different mechanism than the one that gets you on
the front page.

---

## Tier 3 - demand evidence (cite these, do not assert them)

### 5. All Smoke No Alarm - testing practices in agent-authored pull requests
**arXiv:2606.18168**. Over **932,000 agent-authored pull requests** analysed.

This is the launch statistic. It supersedes the 4,882-PR study below as the
headline number, not because that study is wrong but because this one is two
orders of magnitude larger, and the objection *"your evidence is a few thousand
PRs from five agents"* is the first thing a sceptical reader reaches for.

The title is the argument: agent-authored changes carry the *appearance* of
testing without the alarm that a test is supposed to raise. That is precisely
the failure mode a catching test is built to detect, and it is why a hardening
generator makes the problem worse rather than better - it manufactures more
smoke.

### 6. Test Coverage Analysis of Agentic Pull Requests
**arXiv:2607.18057** (approx. 20 July 2026) - 4,882 agent-generated PRs from the
AIDev dataset, 532 Java and 4,350 Python, across five coding agents.

> **Agents include test changes in only 49.6% of PRs that change code under test.**

Equivalently: 50.4% of agentic PRs that touch tested code ship with no test
changes at all. Retained as the precise, per-agent breakdown behind the headline
above - it is the more useful citation when the audience is technical, because it
names the agents and separates the languages.

### 7. Where Do AI Coding Agents Fail?
**arXiv:2601.15195** (21 January 2026). Failure taxonomy for agentic PRs.

### 8. Why Are Agentic Pull Requests Merged or Rejected?
MSR 2026 mining challenge (13 April 2026). Copilot and Devin PRs are
reviewer-mediated; Codex and Cursor PRs are merged with minimal interaction.
The second group is where undetected regressions land.

### 9. Are "Solved Issues" in SWE-bench Really Solved Correctly?
ICSE 2026 - 11.0% of plausible patches are incorrect; **50% of incorrect patches
cannot be identified by running all developer tests.** Existing test suites are
structurally insufficient for verifying generated code. This is the deepest
justification for the whole category.

---

## Tier 4 - technique we borrow

### 10. A systematic literature review of LLM-based test oracles
**arXiv:2607.05031**.

Surveys the oracle families used with LLM-generated tests: specification-derived,
metamorphic, regression, and differential. The finding that matters to us is
structural rather than numerical - **the differential oracle is the only family
that requires no specification and no human-supplied expected value.** It needs
only two revisions of the same program and the ability to run a test twice.

That is the cleanest available justification for the division of labour in this
repository, and it explains an asymmetry a reader will otherwise find odd:

- `execute.py` is trustworthy because it asks a question with a mechanical
  answer. Passes on base, fails on head. No judgement is involved, so there is
  nothing for a model to be wrong about.
- `assess.py` is *not* trustworthy in the same way, because "is this regression
  intended?" has no mechanical answer. It is a judgement, and Defect 13 - in
  which the assessor labelled six of six oracle-confirmed catches as intended
  changes at up to 1.00 confidence - is what that difference costs.

The review is therefore cited as a reason to keep the oracle authoritative and
the assessor advisory, and never to let the assessor overrule the oracle silently.

### 11. PatchGuru - automated patch correctness assessment
**arXiv:2602.05270**.

The same problem as `assess.py`, approached from the opposite end: given a patch
that makes the tests pass, decide whether it is actually correct. We are given a
test that fails and must decide whether the failure is a real regression. Both
reduce to classifying a program change as intended or defective, which is why the
techniques transfer and why the failure modes rhyme.

The relevant lesson for us is calibration. A patch-correctness classifier that
is confidently wrong is worse than one that abstains, because a reviewer cannot
tell a confident correct answer from a confident incorrect one without doing the
work themselves - at which point the classifier has saved nothing. This is the
argument for keeping `unclear` as a first-class verdict that suppresses a report,
and against tuning `MIN_CONFIDENCE` downward to make the pipeline look livelier.

### 12. LLMs are the key to mutation testing and better compliance (Meta ACH)
Meta Engineering, 30 September 2025 - Automated Compliance Hardening applies
LLM-driven mutation testing to compliance coverage. Confirms Meta's continued
investment in the adjacent space and supplies the fault-seeding technique used
in `eval/` to synthesise regressions.

### 13. Mutation testing tool comparisons
- Cosmic Ray and mutmut remain the maintained Python options; a 2025 NSF-hosted
  comparison found Poodle produced the most competent mutants (50.9%), Cosmic
  Ray second (25.7%).
- We do **not** depend on a mutation framework at runtime. We use mutation only
  in `eval/` to seed known regressions and measure our catch rate. Runtime
  mutation testing is too slow for PR-time, which is precisely the gap JiTTest
  fills.

---

## Tier 5 - papers that argue against us

A research file that cites only supporting work is a marketing document. These
are the strongest published arguments against the design, kept here so that
nobody has to rediscover them in a review thread, and so that the conditions
under which we would be wrong are written down in advance.

### 14. Change And Cover - diff-targeted versus whole-suite generation
**arXiv:2601.10942**.

Argues that targeting generation at the diff underperforms whole-suite
generation on defect detection per unit of compute. If that result holds in our
setting it is a direct challenge to `risk.py`, which exists specifically to
spend the budget on high-risk changed symbols and ignore everything else.

**Why we still target the diff.** The comparison assumes compute is the scarce
resource. At PR time it is not - reviewer attention is, and a whole-suite run
produces findings distributed across code nobody is currently reading. A finding
about an unchanged module is a true positive that arrives at the wrong moment,
and the JiTTest economics in Tier 1 only work because we do not run on every
diff.

**The conditions under which this paper beats us**, stated plainly so the
evaluation can detect them:

1. If our measured catch rate on BugsInPy sits near zero *while* the seeded
   regression is reachable from an unchanged symbol, diff targeting is the thing
   that lost the fault, not the generator.
2. If `risk.py` is the stage that most often produces zero targets on real PRs,
   then the gate is throwing away work that the budget could have afforded.
3. If cost per PR turns out low enough that a whole-suite pass is affordable
   overnight, the compute-scarcity premise fails and the paper's conclusion
   applies to us directly.

All three are measurable with the harness we already have, and none has been
measured yet. `eval/` should report per-bug whether the seeded fault was inside
a targeted symbol, which would settle point 1 without any new infrastructure.

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

**Honesty rule for this file:** a paper cited here must have been read, and a
number quoted here must have been read in the paper rather than recalled. Where
a figure is second-hand, say so. The alphaXiv researcher map, which has been
suggested repeatedly as a source, is a single-page application that serves no
paper data to a fetcher - it returns navigation chrome and a pan/zoom blurb, and
reporting it as "reviewed in depth" would be a fabrication.
