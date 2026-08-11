# Phase D Preregistration Document

## Instrument Specifications
- **Instrument Name**: Phase D Differential Explorer
- **Architecture**: Seed-First Generator -> Context Compiler -> Paired Execution -> Mechanical Repair with AST Assertion Preservation -> Differential Feedback Loop -> Oracle-Last Assertion Synthesis
- **Model**: `mistral/codestral-2508`
- **Endpoint**: `https://api.mistral.ai/v1/chat/completions`
- **Prompt Version**: `v1.5-phase-d`
- **Max Differential Mutations**: 2
- **Max Mechanical Repairs**: 2
- **Context Byte Budget**: 32,000 bytes

## Calibration Gate Criteria
- `bug_catches` >= 3 / 10
- `controls_flagged` <= 1 / 20
- `completion_pct` >= 90.0%
- Zero unsafe execution
- Zero provenance violations

## Launch Gate Criteria
- `bug_catches` >= 4 / 16
- `controls_flagged` <= 1 / 60
- `completion_pct` >= 90.0%
- `median_cost_usd` <= $0.25 per eligible PR
- `p95_runtime_s` <= 600.0 seconds (10 minutes)
- Zero unsafe execution
