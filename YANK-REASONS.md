# YANK-REASONS.md

## yank jittest==0.4.0 (action required on PyPI by a maintainer)

**Reason**: the published 0.4.0 artifact was built by a release workflow whose
test gate was masked by `|| true`. The wheel installs and runs, but it reports
`jittest.__version__ == "0.3.5"` while claiming to be 0.4.0 - the exact
defect class this project exists to catch in other people’s code. Its
provenance trail therefore cannot be trusted to mean what it says.

**Not a security vulnerability**: no malicious code, no credential exposure,
no behavioral change vs. the intended 0.4.0 tree. This is an integrity/
provenance defect.

**Replacement**: 0.4.1 (this branch) - same feature set, version drift fixed
in all four declarations, release gate fail-closed, plus the wave-100x stress
and chaos batteries that would have caught this.

**Command for the maintainer**:
```
# PyPI web UI: Releases -> 0.4.0 -> Options -> Yank, reason:
#   "integrity defect: artifact reports wrong __version__; see YANK-REASONS.md"
```
Do NOT reuse the v0.4.0 tag. Do NOT delete and re-upload (PyPI forbids it).
