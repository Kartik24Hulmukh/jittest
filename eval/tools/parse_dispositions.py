"""Parses candidate telemetry records from jittest evaluation log files.

Counts occurrences of candidate dispositions (rate_limited, parse_failed,
catching, model_declined, head_failed_base_failed_latent, etc.) and extracts
associated metadata and errors.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def parse_dispositions(log_path: str | Path) -> dict:
    with open(log_path, encoding="utf-8", errors="ignore") as f:
        text = f.read()

    items = []
    start_token = "telemetry: {"
    idx = 0
    while True:
        pos = text.find(start_token, idx)
        if pos == -1:
            break
        start_json = pos + len("telemetry: ")
        depth = 0
        in_string = False
        escape = False
        end_json = -1
        for i in range(start_json, len(text)):
            char = text[i]
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"' and not escape:
                in_string = not in_string
                continue
            if not in_string:
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        end_json = i + 1
                        break
        if end_json != -1:
            raw_json = text[start_json:end_json]
            try:
                items.append(json.loads(raw_json, strict=False))
            except Exception:
                pass
            idx = end_json
        else:
            idx = pos + len(start_token)

    dispositions: dict[str, int] = {}
    records_by_disp: dict[str, list[dict]] = {}

    for data in items:
        disp = data.get("disposition", "unknown")
        dispositions[disp] = dispositions.get(disp, 0) + 1
        if disp not in records_by_disp:
            records_by_disp[disp] = []
        records_by_disp[disp].append(data)

    return {
        "total_records": len(items),
        "dispositions": dispositions,
        "records": records_by_disp,
    }


def main():
    if len(sys.argv) < 2:
        log_path = "eval/artifacts/flask-fp-ladder-w1r.log"
    else:
        log_path = sys.argv[1]

    res = parse_dispositions(log_path)
    print(f"Total Telemetry Records: {res['total_records']}")
    print("Dispositions Breakdown:")
    for k, v in sorted(res["dispositions"].items()):
        print(f"  {k}: {v}")

    if "head_failed_base_failed_latent" in res["records"]:
        print("\nhead_failed_base_failed_latent record:")
        for r in res["records"]["head_failed_base_failed_latent"]:
            print(f"  {r}")


if __name__ == "__main__":
    main()
