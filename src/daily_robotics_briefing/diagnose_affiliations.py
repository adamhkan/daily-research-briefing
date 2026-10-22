"""Replay one failed affiliation batch from a saved report without collecting or publishing."""
from __future__ import annotations

import argparse
import copy
import json
import logging
from pathlib import Path

from openai import OpenAI

from .affiliations import _exception_details, identify_institutions
from .briefing_agent import DEFAULT_MODEL, _request_validated
from .common_robotics_institutions import COMMON_ROBOTICS_INSTITUTIONS
from .log_capture import redact_text
from .main import load_filters

logger = logging.getLogger(__name__)


def write_json(path: Path, data: object) -> None:
    path.write_text(redact_text(json.dumps(data, ensure_ascii=False, indent=2)) + '\n', encoding='utf-8')


def diagnose(report_path: Path, filters_path: Path, output_dir: Path, sample_size: int = 12,
             model: str | None = None) -> bool:
    if not 1 <= sample_size <= 12:
        raise ValueError('sample_size must be between 1 and 12')
    report = json.loads(report_path.read_text(encoding='utf-8'))
    candidates = [p for p in report['papers']
                  if 'affiliation_model_fallback_failed' in p.get('affiliation_issues', [])]
    if not candidates:
        raise ValueError('The selected report contains no failed affiliation model batches to replay')
    papers = copy.deepcopy(candidates[:sample_size])
    for paper in papers:
        paper['affiliation_issues'] = [issue for issue in paper.get('affiliation_issues', [])
                                       if issue != 'affiliation_model_fallback_failed']
    cfg = load_filters(filters_path)
    # Use that report's filters rather than silently changing its institution decisions.
    filters = report['filters']['institutions']
    entries = [*cfg.get('institutions', []), *filters, *COMMON_ROBOTICS_INSTITUTIONS]
    chosen_model = model or report.get('model') or DEFAULT_MODEL
    usage = {'sdk_requests': 0, 'responses': []}
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / 'input-papers.json', papers)
    print(f'Replaying {len(papers)} papers from {report_path}; model={chosen_model}', flush=True)
    print('No collection, classification, summaries, report updates, or publishing.', flush=True)
    responses = 0

    def observe(task, payload, response):
        nonlocal responses
        responses += 1
        write_json(output_dir / f'response-{responses}.json', {
            'task': task, 'response_id': response.id, 'status': response.status,
            'incomplete_details': response.incomplete_details.model_dump() if response.incomplete_details else None,
            'output_text': response.output_text, 'input_payload': payload,
        })

    fatal_error = None
    try:
        with OpenAI(timeout=120.0, max_retries=0) as client:
            client.briefing_usage = usage
            client.briefing_response_observer = observe
            identify_institutions(
                papers, entries, filters, client, chosen_model, _request_validated,
                cache_dir=None, batch_size=12,
                max_input_chars=int(cfg.get('affiliation_max_input_chars', 60000)),
                snippet_chars=int(cfg.get('affiliation_snippet_chars', 4000)),
            )
    except Exception as exc:
        fatal_error = _exception_details(exc)
        logger.error('Affiliation diagnostic failed: %s', fatal_error)
    failed = [p['arxiv_id'] for p in papers
              if 'affiliation_model_fallback_failed' in p.get('affiliation_issues', [])]
    passed = fatal_error is None and not failed and usage['sdk_requests'] > 0
    write_json(output_dir / 'results.json', {
        'report_path': str(report_path), 'model': chosen_model, 'passed': passed,
        'failed_paper_ids': failed, 'fatal_error': fatal_error, 'api_usage': usage, 'papers': papers,
    })
    print(f'Diagnostic {"passed" if passed else "failed"}; API usage: {usage}', flush=True)
    print(f'Saved diagnostic evidence to {output_dir}', flush=True)
    return passed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--filters', type=Path, default=Path('config/filters.yaml'))
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--sample-size', type=int, default=12)
    parser.add_argument('--model', default=None)
    args = parser.parse_args()
    report = args.report
    if report is None:
        reports = sorted(Path('reports').glob('????-??-??/????-??-??.json'))
        if not reports:
            parser.error('No saved report found; supply --report')
        report = reports[-1]
    raise SystemExit(0 if diagnose(report, args.filters, args.output_dir, args.sample_size, args.model) else 1)


if __name__ == '__main__':
    main()
