# Gumloop chat prompt — paste this to trigger a release

Copy the block below into the Gumloop chat, fill in the four values at the top,
and attach the zip.

```text
Publish the attached jittest artifact to GitHub.

ARTIFACT:       jittest-v0.2.0.zip
REPO_URL:       https://github.com/Kartik24Hulmukh/jittest.git
BRANCH:         main
COMMIT_MESSAGE: feat: jittest v0.2.0 - zero-dependency core, differential oracle, assessor, ledger
TAG:            v0.2.0

Do this:
1. Unzip the artifact. It contains one top-level folder `jittest/`; publish its
   CONTENTS as the repository root.
2. Run the pre-flight checks from your system prompt: required files present,
   every .py file parses, `PYTHONPATH=src python -m unittest discover -s . -p
   'test_*.py' -t .` exits 0, and no secrets or .db files are staged.
3. If any check fails, STOP and tell me which one. Do not push.
4. If all checks pass, commit as the release bot and push to `main`. Never force-push.
5. Create the annotated tag and push it.
6. Reply with the STATUS / COMMIT / BRANCH / CHECKS / FILES / NOTES block.

If you get stuck on any step, skip it, keep going where it is safe to do so, and
list the skipped step in NOTES. Do not fix the source to make a check pass.
```

## First-time setup (once per repository)

If `Kartik24Hulmukh/jittest` does not exist yet, create it on GitHub as an **empty public
repository** — no README, no .gitignore, no licence — then run the prompt above.
The artifact already contains `README.md`, `.gitignore`, `LICENSE` and
`CITATION.cff`, and an auto-initialised repo will cause a merge conflict on the
first push.

## After the first successful push

In the GitHub repository settings:

1. **Actions → General → Workflow permissions**: set *Read and write* so the
   jittest workflow can post its PR comment.
2. **Secrets → Actions**: add `JITTEST_API_KEY` if you want live runs. Without
   it the workflow still runs in `--dry-run` mode and stays free.
3. **PyPI**: configure Trusted Publishing (OIDC) for the project name `jittest`
   before running `.github/workflows/release.yml`. No API token is needed and
   none should be stored.
4. **Branch protection on `main`**: require the `ci` check. The release agent is
   explicitly forbidden from force-pushing, so protection will not fight it.
