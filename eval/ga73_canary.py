"""Two paid Defect-13 canaries; seeded evidence, never a real-bug catch rate."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from jittest.config import load_config  # noqa: E402
from jittest.llm import build_llm  # noqa: E402
from jittest.pipeline import run  # noqa: E402

OLD = 'return min(covering, key=lambda s: s[2] - s[1])'
NEW = 'return max(covering, key=lambda s: s[2] - s[1])'
MODEL = 'melious/glm-5.3-flash'


def acceptance(rows: list[dict]) -> bool:
    return len(rows) == 2 and all(
        any(f['assessment']['verdict'] == 'real_regression'
            and f['assessment']['confidence'] >= 0.70
            and f['assessment']['should_report'] for f in row.get('findings', []))
        and any(t.get('disposition') == 'catching' and t.get('base_outcome') == 'pass'
                and t.get('head_outcome') == 'fail' for t in row.get('telemetry', []))
        for row in rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, default=Path('ga73-canary.json'))
    args = ap.parse_args()
    evidence = {'scope': 'seeded Defect-13 live canary, NOT real-bug GA rates',
        'accounted_budget_usd': 1.0, 'per_run_budget_usd': 0.50, 'runs_required': 2,
        'budget_caveat': 'Response-accounted price guard, not a provider reservation; unreceived failures can have unobserved spend.',
        'risk_threshold': 0.0, 'min_confidence': 0.70, 'model': MODEL,
        'mutation': {'file': 'src/jittest/diff.py', 'old': OLD, 'new': NEW},
        'runs': [], 'passed': False, 'pr_comment_posted': False}
    try:
        if os.getenv('JITTEST_SANDBOX') != 'required':
            raise ValueError('isolation mandatory')
        source = Path(__file__).resolve().parent.parent
        evidence['code_sha'] = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
        evidence['runtime_image'] = os.environ['JITTEST_RUNTIME_IMAGE']
        with tempfile.TemporaryDirectory(prefix='jittest-live-canary-') as td:
            repo = Path(td) / 'repo'
            subprocess.run(['git', 'clone', '--quiet', '--no-hardlinks', '--local', str(source), str(repo)], check=True, timeout=60)
            def git(*cmd: str) -> str:
                return subprocess.check_output(['git', '-C', str(repo), *cmd], text=True).strip()
            base = git('rev-parse', 'HEAD')
            target = repo / 'src/jittest/diff.py'
            text = target.read_text()
            if text.count(OLD) != 1:
                raise ValueError('canary source mismatch')
            target.write_text(text.replace(OLD, NEW, 1))
            git('add', 'src/jittest/diff.py')
            git('-c', 'user.name=Jittest canary', '-c', 'user.email=canary@localhost',
                'commit', '--quiet', '-m', 'test: seeded inner-scope selection regression')
            head = git('rev-parse', 'HEAD')
            evidence.update(base_sha=base, head_sha=head)
            for _ in range(2):
                cfg = load_config(repo, overrides={'model': MODEL, 'budget_usd': 0.50,
                    'max_targets': 1, 'candidates_per_target': 4, 'risk_threshold': 0.0,
                    'min_confidence': 0.70, 'persist_candidates': False})
                llm = build_llm(MODEL, budget_usd=0.50, temperature=cfg.temperature,
                                request_ceiling=10)
                report = run(repo, base, head, cfg, llm)
                evidence['runs'].append(report.as_dict())
                args.out.write_text(json.dumps(evidence, indent=2) + '\n')
                if report.diff_status in ('quota_exhausted', 'model_unavailable'):
                    break
        evidence['passed'] = acceptance(evidence['runs'])
    except Exception as exc:
        evidence['error_type'] = type(exc).__name__
    args.out.write_text(json.dumps(evidence, indent=2) + '\n')
    print('Seeded live canary acceptance passed.' if evidence['passed'] else 'Seeded live canary failed; raw evidence retained.')
    return 0 if evidence['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
