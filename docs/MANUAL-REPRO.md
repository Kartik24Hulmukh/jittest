# Week 0: the $40 manual reproduction

**Do this before you write a line of code.** It costs about $40 in API credits
and one afternoon, and it tests the single weakest assumption in the entire
thesis: that Meta's 4x result transfers outside Meta's infrastructure.

There is no repository in this experiment. No framework, no CLI, no CI. You, a
chat window, and five real regressions.

---

## Protocol

### 1. Get five real regressions (60 min)

Find five commits that introduced a bug which a later commit fixed. Sources, in
order of quality:

- **BugsInPy** (`soarsmu/BugsInPy`) - 493 curated real Python bugs, each with a
  buggy commit, a fixed commit, and a triggering test. Use the fixed commit as
  "before" and the buggy commit as "after". Ground truth included.
- A repo you know well: `git log --grep="fix" --grep="regression" -i` then find
  the commit that caused it.
- Any "revert" commit in a large project.

Record for each: repo, base SHA (correct), head SHA (broken), the diff, and the
real triggering test.

### 2. For each one, paste this into a chat window (30 min)

> You are performing adversarial review. Below is a code change. Write a single
> pytest test that PASSES on the BEFORE version and FAILS on the AFTER version.
> A test that passes on AFTER is worthless. Aim at boundaries, error paths,
> None handling, and state left behind on partial failure.
>
> BEFORE: [paste function]
> AFTER: [paste function]
> DIFF: [paste diff]

Generate 4 candidates per bug. 20 candidates total.

### 3. Run each candidate by hand (90 min)

```bash
git checkout <base_sha> && pytest candidate.py   # want: PASS
git checkout <head_sha> && pytest candidate.py   # want: FAIL
```

### 4. Fill in this table

| # | Repo | Bug | Candidates | Passed base | Failed head | **Caught** | Notes |
|---|---|---|---|---|---|---|---|
| 1 |  |  | 4 |  |  |  |  |
| 2 |  |  | 4 |  |  |  |  |
| 3 |  |  | 4 |  |  |  |  |
| 4 |  |  | 4 |  |  |  |  |
| 5 |  |  | 4 |  |  |  |  |

---

## Decision rule - write this down before you run it

| Result | Meaning | Action |
|---|---|---|
| **4-5 of 5 caught** | Thesis strong; the paper transfers | Build. Full six weeks. |
| **3 of 5 caught** | Thesis holds; needs the risk targeter to be good | Build, but Week 1 is the oracle and Week 3 is precision |
| **1-2 of 5 caught** | Marginal. Meta's 4x is probably infrastructure-dependent | Build only the eval harness, publish the negative result, do not build the product |
| **0 of 5 caught** | The method does not transfer to a cold-context single-file prompt | **Stop.** Publish what you found. You saved six weeks for $40. |

Deciding the rule before seeing the data is the entire point. Do not renegotiate
it afterwards.

---

## Also record (this is the real product insight)

For every candidate that passed base and failed head, ask yourself: **would a
reviewer thank me for this, or would they roll their eyes?**

That ratio is the assessor's job, and it is the only number that predicts
whether anyone keeps the tool installed. Meta's headline contribution was a 70%
reduction in human review load, not the generation. If 9 of 10 mechanically
valid catching tests are eye-rollers, the product is the filter, and you should
spend Week 3 on it rather than Week 2 on prompts.

---

## The twelve messages (send these Saturday)

Target: maintainers of Python repos with 200+ open PRs, or engineering leads at
20-200 person companies. Not enterprises - they build in-house (Cloudflare,
Atlassian both did).

Template - do not embellish it:

> Subject: catching tests for PRs - would this be useful to you?
>
> Hi [name] - Meta published a method this year called JiTTest: instead of
> generating tests that pass, it generates tests that FAIL on a diff and pass
> without it, so the failing test IS the bug report. They report 4x more faults
> caught than conventional generated tests.
>
> There is no open-source implementation. I am considering building one and I do
> not want to build something nobody wants.
>
> Two questions:
> 1. Roughly how many PRs land in [repo] with no test changes?
> 2. If a bot posted a runnable failing test on such a PR - one comment, silent
>    when it finds nothing - would you leave it installed, or turn it off?
>
> Happy with a one-line answer. Not selling anything; there is nothing to sell yet.

**What counts as a real answer:** "yes, send it to me when it works" plus their
repo. Compliments do not count. Stars do not count. Waitlist signups do not
count.
