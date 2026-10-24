"""A resumable Codex pilot: collect once, exchange JSON files, reuse validation.

No command in this module sends model requests over the network. Codex supplies
response files; arXiv collection is the only network operation in prepare/wake.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
from datetime import date, datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from .briefing_agent import create_daily_briefing
from .codex_transport import FileResponseProvider, PendingModelRequest, RequestLimitExceeded, request_identifier
from .collector import Paper, fetch_csro_recent
from .common_robotics_institutions import COMMON_ROBOTICS_INSTITUTIONS
from .institution_filter import build_institution_specs
from .log_capture import redact_text
from .renderer import build_dashboard, render_html, render_markdown
from .response_schemas import AffiliationOutput, ClassificationOutput, ExecutiveOutput, OverviewOutput

SCHEMAS = {s.__name__: s for s in (AffiliationOutput, ClassificationOutput, OverviewOutput, ExecutiveOutput)}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     prefix='.' + path.name, delete=False) as f:
        temporary = Path(f.name)
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _lock(run_dir: Path):
    # A short CLI operation holds the lock; no process must survive between wakes.
    locks = Path(tempfile.gettempdir()) / 'daily-briefing-codex-locks'
    locks.mkdir(exist_ok=True)
    name = hashlib.sha256(str(run_dir.resolve()).encode()).hexdigest()
    with (locks / name).open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def _settings(filters_path: Path) -> dict:
    cfg = yaml.safe_load(filters_path.read_text()) or {}
    if not isinstance(cfg, dict):
        raise ValueError('Filters must be a mapping')
    settings = dict(
        institutions=cfg.get('institutions', []), topics=cfg.get('topics', []),
        max_papers=int(cfg.get('max_papers', 400)),
        classification_batch_size=int(cfg.get('classification_batch_size', min(int(cfg.get('max_papers_for_llm', 25)), 25))),
        summary_batch_size=int(cfg.get('summary_batch_size', 10)),
        max_topic_matches=int(cfg.get('max_topic_matches', 10)),
        affiliation_batch_size=int(cfg.get('affiliation_batch_size', 12)),
        affiliation_max_input_chars=int(cfg.get('affiliation_max_input_chars', 120000)),
        affiliation_snippet_chars=int(cfg.get('affiliation_snippet_chars', 4000)),
        max_pdf_megabytes=int(cfg.get('max_pdf_megabytes', 32)),
    )
    positive = ['max_papers', 'classification_batch_size', 'summary_batch_size',
                'affiliation_batch_size', 'affiliation_snippet_chars', 'max_pdf_megabytes']
    if any(settings[k] < 1 for k in positive) or min(settings['max_topic_matches'], settings['affiliation_max_input_chars']) < 0:
        raise ValueError('Invalid collection or model-request limits')
    if not isinstance(settings['institutions'], list) or not isinstance(settings['topics'], list):
        raise ValueError('Institutions and topics must be lists')
    return settings


def _status(run_dir: Path) -> dict:
    state = _read(run_dir / 'status.json')
    result = {**state, 'run_dir': str(run_dir.resolve())}
    if state.get('request_id'):
        result['request_path'] = str((run_dir / 'requests' / (state['request_id'] + '.json')).resolve())
    return result


def prepare(run_dir: Path, report_date: date, filters_path: Path,
            source_report: Path | None = None, max_requests: int = 64) -> dict:
    with _lock(run_dir):
        if (run_dir / 'manifest.json').exists():
            manifest = _read(run_dir / 'manifest.json')
            if manifest['report_date'] != report_date.isoformat():
                raise ValueError('Existing run has a different report date')
            return _status(run_dir)
        if run_dir.exists() and any(run_dir.iterdir()):
            raise ValueError('Refusing to overwrite a nonempty run directory')
        if max_requests < 1:
            raise ValueError('max_requests must be positive')
        settings = _settings(filters_path)
        submission_date = report_date - timedelta(days=1)
        if source_report:
            saved = _read(source_report)
            if saved['submission_date'] != submission_date.isoformat():
                raise ValueError('Saved report covers a different submission date')
            papers = []
            for raw in saved['papers'][:settings['max_papers']]:
                fields = {k: copy.deepcopy(v) for k, v in raw.items() if k in Paper.__dataclass_fields__}
                fields['affiliation_issues'] = [i for i in fields.get('affiliation_issues', [])
                                                if not i.startswith('affiliation_')]
                fields['affiliation_status'] = 'unknown'
                papers.append(Paper(**fields).to_dict())
        else:
            papers = [p.to_dict() for p in fetch_csro_recent(
                max_papers=settings['max_papers'], submission_date=submission_date,
                max_pdf_bytes=settings['max_pdf_megabytes'] * 1024 * 1024)]
        snapshot = dict(report_date=report_date.isoformat(), submission_date=submission_date.isoformat(),
                        settings=settings, papers=papers)
        manifest = dict(version=1, backend='codex-files', created_at=_now(),
                        report_date=report_date.isoformat(), submission_date=submission_date.isoformat(),
                        source_sha256=_hash(snapshot), max_requests=max_requests)
        baseline = source_report or Path('reports') / report_date.isoformat() / (report_date.isoformat() + '.json')
        saved_baseline = None
        if baseline.is_file():
            saved = _read(baseline)
            if saved.get('submission_date') == submission_date.isoformat():
                saved_baseline = saved
        state = dict(status='ready' if papers else 'no_papers', report_date=report_date.isoformat(),
                     paper_count=len(papers), updated_at=_now())
        # Publish the whole initial checkpoint together. An interrupted preparation
        # must not leave a manifest whose source or status is missing on retry.
        run_dir.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix='.' + run_dir.name + '.prepare-', dir=run_dir.parent))
        try:
            _write(staging / 'source.json', snapshot)
            _write(staging / 'manifest.json', manifest)
            _write(staging / 'status.json', state)
            if saved_baseline is not None:
                _write(staging / 'baseline.json', saved_baseline)
            if not papers:
                _write(staging / 'metrics.json', dict(status='no_papers', paper_count=0, api_requests=0,
                                                     codex_token_usage=None, request_count=0))
            os.replace(staging, run_dir)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        return _status(run_dir)


def _request_metrics(run_dir: Path) -> dict:
    stages: dict[str, int] = {}
    repairs = 0
    for path in (run_dir / 'requests').glob('*.json'):
        request = _read(path)
        stage = request['text']['format']['name']
        stages[stage] = stages.get(stage, 0) + 1
        repairs += '\nCorrect this validation error in your new response: ' in request['input'][0]['content']
    return dict(request_count=sum(stages.values()), requests_by_stage=stages,
                repair_request_count=repairs, api_requests=0, codex_token_usage=None)


def _enrich(result: dict) -> None:
    papers = result['papers']
    result['papers_fetched'] = result['papers_analyzed'] = len(papers)
    result['affiliation_status_counts'] = {s: sum(p['institution_match_status'] == s for p in papers)
                                          for s in ('matched', 'no_match', 'unresolved', 'source_unavailable')}
    c = result['affiliation_status_counts']
    result['affiliation_coverage'] = dict(matched=c['matched'], no_match=c['no_match'],
                                        unknown=c['unresolved'] + c['source_unavailable'])
    result['affiliation_extraction_counts'] = {s: sum(p['affiliation_extraction_status'] == s for p in papers)
                                             for s in ('complete', 'incomplete', 'no_usable_evidence')}
    result['affiliation_resolution_counts'] = {s: sum(p['affiliation_resolution_status'] == s for p in papers)
                                              for s in ('filter_match', 'no_recognized_filter_match',
                                                        'incomplete_extraction', 'no_usable_evidence')}


def _compare(result: dict, baseline: dict) -> dict:
    def selected(r):
        b = r['briefing']
        return {p['paper_id'] for section in ('institution_matches', 'topic_matches') for p in b[section]}
    before = {p['arxiv_id']: p for p in baseline['papers']}
    changes = []
    for p in result['papers']:
        old = before.get(p['arxiv_id'])
        if old is None:
            continue
        a = old.get('manual_institution_extraction', {}).get('paper_level_institutions', [])
        b = p['manual_institution_extraction']['paper_level_institutions']
        if sorted(a) != sorted(b):
            changes.append(dict(paper_id=p['arxiv_id'], baseline=a, pilot=b))
    old_ids, new_ids = selected(baseline), selected(result)
    return dict(note='Differences for source review; neither run is ground truth.',
                baseline_paper_count=len(baseline['papers']), pilot_paper_count=len(result['papers']),
                selected_added=sorted(new_ids - old_ids), selected_removed=sorted(old_ids - new_ids),
                institution_changes=changes)


def advance(run_dir: Path, retry_failed: bool = False) -> dict:
    with _lock(run_dir):
        state = _read(run_dir / 'status.json')
        if state['status'] in ('complete', 'no_papers'):
            return _status(run_dir)
        if state['status'] == 'failed' and not retry_failed:
            return _status(run_dir)
        manifest = _read(run_dir / 'manifest.json')
        source = _read(run_dir / 'source.json')
        if _hash(source) != manifest['source_sha256']:
            raise ValueError('Frozen source snapshot changed')
        cfg = source['settings']
        filters = [s.canonical for s in build_institution_specs(cfg['institutions'])]
        provider = FileResponseProvider(run_dir, max_requests=manifest['max_requests'])
        try:
            result = create_daily_briefing(
                copy.deepcopy(source['papers']), filters, cfg['topics'],
                date.fromisoformat(source['submission_date']), model='codex-session',
                max_topic_matches=cfg['max_topic_matches'],
                classification_batch_size=cfg['classification_batch_size'],
                summary_batch_size=cfg['summary_batch_size'],
                institution_entries=[*cfg['institutions'], *COMMON_ROBOTICS_INSTITUTIONS],
                affiliation_cache_dir=None, affiliation_batch_size=cfg['affiliation_batch_size'],
                affiliation_max_input_chars=cfg['affiliation_max_input_chars'],
                affiliation_snippet_chars=cfg['affiliation_snippet_chars'], response_provider=provider)
        except PendingModelRequest as pending:
            _write(run_dir / 'status.json', dict(status='waiting', report_date=manifest['report_date'],
                                                request_id=pending.request_id, updated_at=_now()))
            return _status(run_dir)
        except (ValueError, RequestLimitExceeded) as error:
            _write(run_dir / 'metrics.json', dict(status='failed', paper_count=len(source['papers']),
                                                 **_request_metrics(run_dir)))
            _write(run_dir / 'status.json', dict(status='failed', report_date=manifest['report_date'],
                                                error=redact_text(str(error)), updated_at=_now()))
            return _status(run_dir)
        _enrich(result)
        result['filters'] = dict(institutions=filters, topics=cfg['topics'])
        request_metrics = _request_metrics(run_dir)
        request_count = request_metrics['request_count']
        result['codex_pilot'] = dict(backend='codex-files', request_count=request_count,
                                     codex_token_usage=None, source_sha256=manifest['source_sha256'])
        # The engine's counter tracks local model requests on this path, not SDK calls.
        result['api_usage'] = dict(sdk_requests=0, input_tokens=0, output_tokens=0,
                                   cached_input_tokens=0, reasoning_tokens=0, responses=[])
        output = run_dir / 'report'
        output.mkdir(exist_ok=True)
        _write(output / 'briefing.json', result)
        arguments = dict(briefing=result['briefing'], matched_institutions=filters, matched_topics=cfg['topics'],
                         submission_date=date.fromisoformat(source['submission_date']),
                         papers_fetched=len(source['papers']), papers_analyzed=len(source['papers']))
        (output / 'briefing.md').write_text(render_markdown(**arguments), encoding='utf-8')
        (output / 'briefing.html').write_text(render_html(**arguments), encoding='utf-8')
        build_dashboard(output, output / 'index.html')
        rows = result['briefing']['institution_matches'] + result['briefing']['topic_matches']
        metrics = dict(status='complete', paper_count=len(source['papers']), **request_metrics,
                       selected_paper_count=len({r['paper_id'] for r in rows}),
                       affiliation_extraction_counts=result['affiliation_extraction_counts'],
                       summaries_unavailable=sum(r.get('summary_status') == 'abstract_unavailable' for r in rows),
                       created_at=manifest['created_at'], completed_at=_now())
        _write(run_dir / 'metrics.json', metrics)
        if (run_dir / 'baseline.json').exists():
            _write(run_dir / 'comparison.json', _compare(result, _read(run_dir / 'baseline.json')))
        _write(run_dir / 'status.json', dict(status='complete', report_date=manifest['report_date'],
                                            report_path='report/briefing.html', updated_at=_now()))
        return _status(run_dir)


def submit(run_dir: Path, request_id: str, response_file: Path) -> dict:
    if not re.fullmatch(r'[a-f0-9]{64}', request_id):
        raise ValueError('Invalid request ID')
    with _lock(run_dir):
        request_path = run_dir / 'requests' / (request_id + '.json')
        if request_path.is_symlink():
            raise ValueError('Request must not be a symlink')
        request = _read(request_path)
        if request_identifier(request) != request_id:
            raise ValueError('Request content does not match its ID')
        schema = SCHEMAS[request['text']['format']['name']]
        response = schema.model_validate_json(response_file.read_text(encoding='utf-8')).model_dump()
        target = run_dir / 'responses' / (request_id + '.json')
        if target.is_symlink():
            raise ValueError('Response must not be a symlink')
        if target.exists() and _read(target) != response:
            raise ValueError('Refusing to overwrite a different saved response')
        if not target.exists():
            _write(target, response)
        return dict(status='submitted', run_dir=str(run_dir.resolve()), request_id=request_id)


def wake(config_path: Path, today: date | None = None) -> dict:
    cfg = _read(config_path)
    start, end = date.fromisoformat(cfg['start_date']), date.fromisoformat(cfg['end_date'])
    if start > end or type(cfg['max_requests']) is not int or cfg['max_requests'] < 1:
        raise ValueError('Invalid pilot window or request limit')
    today = today or datetime.now(ZoneInfo(cfg['timezone'])).date()
    if not start <= today <= end:
        return dict(status='inactive', reason='Outside the configured pilot dates', date=today.isoformat())
    if cfg.get('publish') is not False:
        raise ValueError('This pilot supports separate review outputs only')
    filters = Path('config/filters.yaml')
    if not filters.exists():
        filters = Path('config/filters.example.yaml')
    return prepare(Path(cfg['output_root']) / today.isoformat(), today, filters,
                   max_requests=cfg['max_requests'])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('prepare')
    p.add_argument('--run-dir', required=True, type=Path)
    p.add_argument('--report-date', required=True, type=date.fromisoformat)
    p.add_argument('--filters', type=Path, default=Path('config/filters.yaml'))
    p.add_argument('--source-report', type=Path)
    p.add_argument('--max-requests', type=int, default=64)
    p = commands.add_parser('wake')
    p.add_argument('--config', type=Path, default=Path('config/codex-pilot.json'))
    for command in ('advance', 'status', 'submit'):
        p = commands.add_parser(command)
        p.add_argument('--run-dir', required=True, type=Path)
        if command == 'advance':
            p.add_argument('--retry-failed', action='store_true')
        if command == 'submit':
            p.add_argument('--request-id', required=True)
            p.add_argument('--response-file', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            result = prepare(args.run_dir, args.report_date, args.filters, args.source_report, args.max_requests)
        elif args.command == 'wake':
            result = wake(args.config)
        elif args.command == 'advance':
            result = advance(args.run_dir, args.retry_failed)
        elif args.command == 'submit':
            result = submit(args.run_dir, args.request_id, args.response_file)
        else:
            result = _status(args.run_dir)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        result = dict(status='error', error=redact_text(str(error)))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if result['status'] in ('failed', 'error') else 0


if __name__ == '__main__':
    raise SystemExit(main())
