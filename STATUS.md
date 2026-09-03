# Hardening Loop Status

- **Current main SHA**: 6cb695c43e13fc08a09b3a66a649ff0cfad3f587
- **Branch SHA**: fix/isolation-d1-d2-d8
- **Defect Status**:
  - D3 (Path containment in verify.py): CLOSED & MERGED in PR #167
  - D4 (Signer prefix floor in receipt.py): CLOSED & MERGED in PR #167
  - D6 (Unique evidence artifact naming): CLOSED & MERGED in PR #167
  - D7 (Schema/source verdict agreement): CLOSED & MERGED in PR #168
  - D5 (Receipt semantics & provenance verification): CLOSED & MERGED in PR #168
  - D1 (Docker venv discard / Option D refusal): CLOSED (verify.py, tested by test_wave3_isolation.py)
  - D2 (Host provisioning sanitization / Job F): CLOSED (env.py, tested by test_wave3_isolation.py)
  - D8 (Action defaults & artifact hygiene): CLOSED (action.yml, action.py, tested by test_wave3_isolation.py)
  - D9 (Real container isolation daemon proof): OPEN
- **Exact failing test or CI job**: None (Wave 3 tests pass locally)
- **Next patch ID**: Wave 3 PR & Merge -> Wave 4 (D9 daemon proof & ANTIGRAVITY-RESULT.md)
