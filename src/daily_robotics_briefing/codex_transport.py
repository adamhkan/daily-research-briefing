"""Resumable, file-backed model requests for a Codex-driven pilot.

This transport never calls an API. The caller supplies a response file, and the
normal briefing pipeline remains responsible for semantic validation and repair.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from pydantic import BaseModel


class PendingModelRequest(Exception):
    """A request has been saved and needs a Codex-generated response."""

    def __init__(self, request_id: str, request_path: Path):
        self.request_id = request_id
        self.request_path = request_path
        super().__init__(f'Model response required for {request_id}: {request_path}')


class RequestLimitExceeded(Exception):
    """The pilot's bound on distinct model requests has been reached."""

    def __init__(self, max_requests: int):
        self.max_requests = max_requests
        super().__init__(f'Pilot model-request limit reached ({max_requests})')


def request_envelope(
    model: str,
    system_prompt: str,
    payload: dict[str, Any],
    effort: str,
    response_schema: type[BaseModel],
    max_output_tokens: int,
) -> dict[str, Any]:
    """Use the same messages, strict schema and settings as the API transport."""
    return {
        'model': model,
        'input': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
        ],
        'reasoning': {'effort': effort},
        'text': {'format': {
            'type': 'json_schema', 'name': response_schema.__name__,
            'strict': True, 'schema': response_schema.model_json_schema(),
        }},
        'max_output_tokens': max_output_tokens,
    }


def request_identifier(request: dict[str, Any]) -> str:
    canonical = json.dumps(request, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _write_request(path: Path, request: dict[str, Any]) -> None:
    """Publish a complete request file without leaving a partially written JSON."""
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.' + path.stem + '.', suffix='.tmp',
                                         delete=False) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(request, temporary, ensure_ascii=False, indent=2, sort_keys=True)
            temporary.write('\n')
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


class FileResponseProvider:
    """Save unanswered requests and replay responses without credentials or SDK calls."""

    def __init__(self, run_dir: Path | str, max_requests: int = 64):
        if max_requests < 1:
            raise ValueError('max_requests must be positive')
        self.run_dir = Path(run_dir)
        self.max_requests = max_requests
        self.requests_dir = self.run_dir / 'requests'
        self.responses_dir = self.run_dir / 'responses'

    def __call__(
        self,
        model: str,
        system_prompt: str,
        payload: dict[str, Any],
        effort: str,
        response_schema: type[BaseModel],
        max_output_tokens: int,
    ) -> str:
        request = request_envelope(model, system_prompt, payload, effort,
                                   response_schema, max_output_tokens)
        request_id = request_identifier(request)
        request_path = self.requests_dir / (request_id + '.json')
        response_path = self.responses_dir / (request_id + '.json')
        self.requests_dir.mkdir(parents=True, exist_ok=True)
        self.responses_dir.mkdir(parents=True, exist_ok=True)
        if request_path.is_symlink() or response_path.is_symlink():
            raise RuntimeError('Pilot request and response files must not be symlinks')
        if request_path.exists():
            try:
                saved = json.loads(request_path.read_text(encoding='utf-8'))
            except (ValueError, OSError) as exc:
                raise RuntimeError(f'Cannot read saved pilot request: {request_id}') from exc
            if saved != request:
                raise RuntimeError(f'Saved pilot request does not match its content ID: {request_id}')
        else:
            if sum(1 for _ in self.requests_dir.glob('*.json')) >= self.max_requests:
                raise RequestLimitExceeded(self.max_requests)
            _write_request(request_path, request)
        if not response_path.exists():
            raise PendingModelRequest(request_id, request_path)
        # Do not pre-validate here: the production schema and repair loop handle
        # malformed responses and generate a distinct request with repair context.
        return response_path.read_text(encoding='utf-8')
