# Phase D Signed Preregistration Document (C-PHASE-D-FIX-2)

## Protocol Metadata
- **Protocol Name**: `C-PHASE-D-FIX-2`
- **Preregistration Commit**: [`0c833f954737868c69198d7bcaff7ec69f74f4c7`](https://github.com/Kartik24Hulmukh/jittest/commit/0c833f954737868c69198d7bcaff7ec69f74f4c7)
- **Model ID**: `mistral/codestral-2508`
- **Endpoint**: `https://api.mistral.ai/v1/chat/completions`
- **Temperature**: `0.8`
- **Cost Ceiling**: `$15.00 USD`
- **Manifest File**: [`phase-c-benchmark-manifest.json`](file:///C:/Users/praja/src/jittest/phase-c-benchmark-manifest.json)
- **Manifest SHA256**: `e6632b71a023e7004b27837375c61b820822156cac2ed4cfb020388bbcefa630`

## Attempt Limits & Constraints
- **Max Mechanical Repairs**: `2`
- **Max Differential Mutations**: `2`
- **Context Byte Budget**: `32,000 bytes` (Minimum `2,000 bytes` per target row)
- **Probe Safety Mode**: `allow_no_assertion=True` at probe generation stage

## Gate Criteria (Development Replay)
- **Evaluated Cohort**: 7 Real Flask Calibration Rows (`bug_flask_01` .. `bug_flask_07`)
- **Required Catches**: `>= 2` real catches among rows with executed candidates
- **Unique Candidates**: `>= 80.0%`
- **Safety Escapes**: `0`

## Stopping Rule
If candidates produce `< 2` catches, the generator track closes permanently and the **evidence-layer pivot** activates.
