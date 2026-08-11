# Phase D Signed Preregistration Document (C-PHASE-D-FIX-1)

## Protocol Metadata
- **Protocol Name**: `C-PHASE-D-FIX-1`
- **Model ID**: `mistral/codestral-2508`
- **Endpoint**: `https://api.mistral.ai/v1/chat/completions`
- **Temperature**: `0.8`
- **Cost Ceiling**: `$15.00 USD`
- **Manifest**: [`phase-c-benchmark-manifest.json`](file:///C:/Users/praja/src/jittest/phase-c-benchmark-manifest.json) (83 rows: 7 calibration, 16 bug holdout, 60 control holdout)

## Attempt Limits
- **Max Mechanical Repairs**: `2`
- **Max Differential Mutations**: `2`
- **Context Byte Budget**: `32,000 bytes`

## Gate Criteria

### 1. Development Replay Gate (7 Real Flask Rows)
- Real catches >= 2 with receipts
- Unique candidates >= 80.0%
- Zero safety escapes

### 2. Fresh Calibration Gate (10 Bugs + 20 Controls)
- Bug catches >= 3 / 10
- Controls flagged <= 1 / 20
- Completion rate >= 90.0%
- Zero unsafe execution
- Zero provenance violations

### 3. Confirmatory Holdout Gate (16 Bugs + 60 Controls)
- Bug catches >= 4 / 16
- Controls flagged <= 1 / 60
- Completion rate >= 90.0%
- Median cost <= $0.25 USD per eligible PR
- p95 runtime <= 600.0s (10 minutes)
- Zero unsafe execution

## Stopping Rule
If any gate fails, execution HALTS immediately. Holdout is not executed if Calibration fails.
