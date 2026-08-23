# Evaluation

Three numbers, always published together:

| Number | Script | Target at launch |
|---|---|---|
| **Catch rate** (recall on real seeded bugs) | `run_bugsinpy.py` | > 0.25 |
| **False-positive rate** (reports on clean PRs) | `false_positives.py` | < 0.10 |
| **Cost per analysed PR** | reported by both | < $1.00 |

Publishing catch rate alone is marketing. Meta's contribution in
arXiv:2601.22832 was a ~70% reduction in review load - that is a precision
result, not a recall result.

## Datasets

| Dataset | Get it | Notes |
|---|---|---|
| **BugsInPy** (493 Python bugs) | `git clone https://github.com/soarsmu/BugsInPy` | Primary harness. Inversion: base = fixed commit, head = buggy commit. |
| **Defects4J 3.0.1** (854 Java bugs) | `git clone https://github.com/rjust/defects4j` | For the v0.6 Java port. |
| **GitBug-Java** | `github.com/gitbugactions/gitbug-java` | More recent, lower memorisation risk. Report alongside BugsInPy. |
| Your own repo's revert history | `git log --merges --grep=revert` | The most honest dataset you have. |

## Data leakage warning

BugsInPy and Defects4J appear in public code corpora, so models may have
memorised the fixes. Every published number must state which dataset it came
from, and headline claims should cite the lower of BugsInPy and a recent-bug
set. Silently reporting the higher number is the mistake that gets a project
torn apart on Hacker News.

## Running

```bash
git clone https://github.com/soarsmu/BugsInPy /tmp/BugsInPy
pip install -e ".[eval]"
export ANTHROPIC_API_KEY=...

python eval/run_bugsinpy.py --bugsinpy /tmp/BugsInPy --limit 50 --out results.json
python eval/false_positives.py --repo ~/src/some-active-repo --count 40
```

Budget: 50 bugs at roughly $0.50 each is about $25 per full sweep. Run the
10-bug smoke sweep while iterating on prompts.

## Arm C (crossed) — FCR denominator disclosure

Arm C applies a **donor** instance's solution patch against the current
instance's base. Because the patch was generated against the donor's
`base_commit` (a different commit), `git apply` may fail even with
`--3way`. When the donor patch does not apply, the arm returns
`crossed_patch_apply_failed / inconclusive` and **no crossed-arm
observation exists** for that row.

The False Catch Rate (FCR) must be reported as **0 / N** where N is the
number of crossed rows with `donor_patch_applied == true`, never `0 / 20`
by default. If N is small (e.g. 2 of 20), the gate "FCR = 0" is trivially
satisfied and the confidence is correspondingly low. Report N alongside
FCR in all summaries.
