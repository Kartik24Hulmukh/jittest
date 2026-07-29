<!-- Thank you for contributing to jittest. -->

## What this changes

<!-- One or two sentences. What behaviour is different after this PR? -->

## Why

<!-- What was wrong, or what was missing? If this fixes a defect, say what the
     defect allowed to happen that should not have been possible. -->

## Evidence

This project's rule is that a claim needs an execution behind it. Please fill in
what you actually ran, not what you expect to happen.

- [ ] `PYTHONPATH=src python -m unittest discover -s . -p 'test_*.py' -t .` passes locally
- [ ] `ruff check src tests` is clean
- [ ] New behaviour has a test that **fails before this change and passes after it**

Paste the relevant output:

```
<!-- test count, or the ruff output, or the before/after of the new test -->
```

## Things this PR must not do

- [ ] It does not weaken lint configuration, add `# noqa`, or add per-file ignores to make a check pass
- [ ] It does not change a test's expected value in order to make the test pass
- [ ] It does not make a candidate test able to pass without executing (see Defect 32)

## Anything a reviewer should be suspicious of

<!-- Optional, and valued. If part of this is a guess, or is unverified, say so
     here. An honest "I could not test X" is more useful than silence. -->
