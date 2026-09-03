# Hardening Loop Status

- **Current main SHA**: 1412238a830036728cb15b9fd89d9810528d235e
- **Branch SHA**: fix/trust-path-d3-d4-d6
- **Defect Status**:
  - D3 (Path containment in verify.py): CLOSED (tested by test_wave1_trust_path.py)
  - D4 (Signer prefix floor in receipt.py): CLOSED (tested by test_wave1_trust_path.py)
  - D6 (Unique evidence artifact naming): CLOSED (tested by test_wave1_trust_path.py)
  - D1 (Docker venv discard): OPEN
  - D2 (Host provisioning before sandbox): OPEN
  - D5 (Receipt semantics verification): OPEN
  - D7 (Schema/source verdict agreement): OPEN
  - D8 (Version/action behavior skew): OPEN
  - D9 (Real container isolation daemon proof): OPEN
- **Exact failing test or CI job**: None (Wave 1 tests pass locally)
- **Next patch ID**: Wave 1 PR & Merge
