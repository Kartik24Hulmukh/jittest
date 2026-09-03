# Hardening Loop Status

- **Current main SHA**: 79856bbc44480cd3edcfddabb5bb71d5eb8d450f
- **Branch SHA**: fix/contract-honesty-d7-d5
- **Defect Status**:
  - D3 (Path containment in verify.py): CLOSED & MERGED in PR #167
  - D4 (Signer prefix floor in receipt.py): CLOSED & MERGED in PR #167
  - D6 (Unique evidence artifact naming): CLOSED & MERGED in PR #167
  - D7 (Schema/source verdict agreement): CLOSED (docs/SCHEMA.md, README.md, test_wave2_contract_honesty.py, test_schema_conformance.py)
  - D5 (Receipt semantics & provenance verification): CLOSED (receipt.py, cli.py, test_wave2_contract_honesty.py)
  - D1 (Docker venv discard): OPEN
  - D2 (Host provisioning before sandbox): OPEN
  - D8 (Version/action behavior skew): OPEN
  - D9 (Real container isolation daemon proof): OPEN
- **Exact failing test or CI job**: None (Wave 2 tests pass locally)
- **Next patch ID**: Wave 2 PR & Merge -> Wave 3 (D1, D2 isolation)
