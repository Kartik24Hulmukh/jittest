"""Predeclared 40 settled Click PRs, preserving all ranking refusals in denominators."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from eval.false_positives import changed_python_files, summarize_rows  # noqa: E402
from eval.ga73_collection import collection_screen  # noqa: E402
from jittest.config import load_config  # noqa: E402
from jittest.diff import extract_targets, git_diff  # noqa: E402
from jittest.llm import build_llm  # noqa: E402
from jittest.pipeline import run  # noqa: E402
from jittest.risk import rank  # noqa: E402

MODEL = 'melious/glm-5.3-flash'


def validate_manifest(manifest: dict) -> None:
    if (manifest.get('repo') != 'https://github.com/pallets/click'
            or manifest.get('since') != '5 years ago' or manifest.get('until') != '90 days ago'
            or len(manifest.get('pairs', [])) != 40):
        raise ValueError('predeclared cohort mismatch')
    if not re.fullmatch(r'[0-9a-f]{40}', manifest.get('sha', '')):
        raise ValueError('unpinned repository')
    pairs = manifest['pairs']
    if any(p['head'] != p.get('merge_sha') or p.get('ranked_preflight', 0) < 1 for p in pairs):
        raise ValueError('not an applied, default-risk eligible PR')
    if any(not re.fullmatch(r'[0-9a-f]{40}', p.get('pr_head', '')) for p in pairs):
        raise ValueError('original PR head identity missing')
    if any(p.get('pr_metadata_status') != 'verified' or not p.get('pr_merged_at') for p in pairs):
        raise ValueError('actual merged PR receipts missing')
    if len({(p['base'], p['head']) for p in pairs}) != 40:
        raise ValueError('duplicate pair')
    if any(not re.fullmatch(r'[0-9a-f]{40}', p[k]) for p in pairs for k in ('base', 'head')):
        raise ValueError('invalid commit identity')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo', type=Path, required=True)
    ap.add_argument('--manifest', type=Path, default=Path('eval/ga73_click_manifest.json'))
    ap.add_argument('--out', type=Path, default=Path('ga73-pr-pilot.json'))
    args = ap.parse_args()
    evidence = {'scope': 'default-risk-eligible applied-PR screening proxy; NOT global FPR or independent human labels',
        'independent_adjudication': 'pending', 'ga_ready': False, 'model': MODEL,
        'risk_threshold': 0.35, 'max_targets': 5, 'candidates_per_target': 4,
        'accounted_budget_usd': 1.0,
        'budget_caveat': 'Response-accounted list-price guard, not a provider-side reservation. Requests can overshoot and failed/unreceived responses can have unobserved spend.',
        'fx_usd_per_eur': os.getenv('JITTEST_EUR_USD'), 'results': [], 'collection_qualified': False}
    try:
        manifest = json.loads(args.manifest.read_text())
        validate_manifest(manifest)
        evidence['manifest'] = manifest
        actual = subprocess.check_output(['git', '-C', str(args.repo), 'rev-parse', 'HEAD'], text=True).strip()
        if actual != manifest['sha'] or os.getenv('JITTEST_SANDBOX') != 'required':
            raise ValueError('source or isolation mismatch')
        evidence['code_sha'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
        evidence['runtime_image'] = os.environ['JITTEST_RUNTIME_IMAGE']
        cfg_profile = load_config(args.repo, overrides={'model': MODEL, 'budget_usd': 0.0,
            'max_targets': 5, 'candidates_per_target': 4, 'risk_threshold': 0.35})
        no_call_proofs = []
        for p in manifest.get('sampling_canaries', []) + manifest.get('risk_skipped_frame', []):
            # Real pipeline, real Git source; budget zero is a safety backstop,
            # not proof of no call: generation attempts must also stay zero.
            llm = build_llm(MODEL, api_key='unused-no-network', budget_usd=0.0, request_ceiling=1)
            report = run(args.repo, p['base'], p['head'], cfg_profile, llm)
            if report.model_request_attempts or report.model_requests or report.findings:
                raise ValueError('static no-call contract violated')
            no_call_proofs.append({'base': p['base'], 'head': p['head'], 'pr_number': p['pr_number'],
                'diff_status': report.diff_status, 'model_requests': report.model_requests,
                'model_request_attempts': report.model_request_attempts, 'reported': 0})
        evidence['no_call_proofs'] = no_call_proofs
        evidence['population_note'] = manifest.get('eligibility')
        # Refuse unavailable pairs before the first paid call; never silently shrink.
        for p in manifest['pairs']:
            for key in ('base', 'head'):
                subprocess.run(['git', '-C', str(args.repo), 'cat-file', '-e', p[key] + '^{commit}'],
                               check=True, capture_output=True, timeout=15)
            parents = subprocess.check_output(['git', '-C', str(args.repo), 'show', '--no-patch',
                                              '--format=%P', p['head']], text=True).strip().split()
            if parents != [p['base'], p['pr_head']]:
                raise ValueError('applied merge-parent identity mismatch')
            ts = extract_targets(git_diff(args.repo, p['base'], p['head']), repo=args.repo,
                                 base=p['base'], head=p['head'])
            if not rank([t for t in ts if not cfg_profile.is_ignored(t.file_path)], 0.35, 5):
                raise ValueError('default-risk eligibility drift')
            if not changed_python_files(args.repo, p['base'], p['head']):
                raise ValueError('non-Python pair')
        rows, spent = [], 0.0
        for p in manifest['pairs']:
            if spent >= 1.0:
                evidence['abort'] = 'accounted_budget_exhausted'
                break
            cfg = load_config(args.repo, overrides={'model': MODEL, 'budget_usd': 1.0 - spent,
                'max_targets': 5, 'candidates_per_target': 4, 'risk_threshold': 0.35})
            llm = build_llm(MODEL, budget_usd=cfg.budget_usd, temperature=cfg.temperature,
                            request_ceiling=25)
            report = run(args.repo, p['base'], p['head'], cfg, llm,
                         pr_title=p['pr_title'], pr_body=p['pr_body'], pr_ref=p['pr_url'])
            spent += report.cost_usd
            claims = [f for f in report.findings if f.assessment.should_report]
            rows.append({'base': p['base'], 'head': p['head'], 'merge_sha': p['merge_sha'],
                'pr_number': p['pr_number'], 'pr_url': p['pr_url'], 'reported': len(claims),
                'cost_usd': report.cost_usd, 'priced': report.priced, 'provider_billing': report.provider_billing,
                'model_requests': report.model_requests, 'model_request_attempts': report.model_request_attempts,
                'input_tokens': report.input_tokens, 'output_tokens': report.output_tokens,
                'tokens_estimated': report.tokens_estimated, 'diff_status': report.diff_status,
                'targets_considered': report.targets_considered, 'candidates_generated': report.candidates_generated,
                'sandbox': report.sandbox, 'telemetry': [t.as_dict() for t in report.telemetry],
                'claims': [f.assessment.summary for f in claims],
                'claim_cases': [{'file': f.target.file_path, 'symbol': f.target.symbol,
                    'source_before': f.target.source_before, 'source_after': f.target.source_after,
                    'test_code': f.test_code, 'assessment': f.assessment.as_dict(),
                    'failure_excerpt': f.failure_excerpt} for f in claims]})
            evidence['results'] = rows
            evidence['accounted_usd'] = spent
            evidence['summary'] = summarize_rows(rows, 40, screened_out=manifest['screened_out'],
                                                window=(manifest['since'], manifest['until']))
            args.out.write_text(json.dumps(evidence, indent=2) + '\n')
            if report.diff_status in ('quota_exhausted', 'model_unavailable'):
                evidence['abort'] = report.diff_status
                break
        telemetry = [t for r in rows for t in r['telemetry']]
        screen = collection_screen(telemetry)
        healthy = screen['healthy_collection']
        evidence['collection_screen'] = screen
        paired = any(t.get('head_outcome') in ('pass', 'fail') and t.get('base_outcome') in ('pass', 'fail') for t in telemetry)
        evidence.update(healthy_collection=healthy, execution_pair_present=paired)
        evidence['collection_qualified'] = (len(rows) == 40 and evidence['summary']['publishable'] and healthy and paired)
    except Exception as exc:
        evidence['error_type'] = type(exc).__name__
    args.out.write_text(json.dumps(evidence, indent=2) + '\n')
    print('Cohort qualified as screening proxy; independent labels still pending.' if evidence['collection_qualified']
          else 'Cohort qualification failed; raw refusals/outcomes retained.')
    return 0 if evidence['collection_qualified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
