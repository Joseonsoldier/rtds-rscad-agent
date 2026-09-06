"""Read-only, source-bound line input inspection and numeric preview.

This module never imports the vendor SDK, writes an input/output companion,
invokes a constants solver, or modifies a Draft project.
"""
from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from pathlib import Path

from .core import line_authoring as core
from .core.state_machine import sha256_json
from .safety import ToolSafetyError
from .settings import get_settings, within

MAX_REQUEST_BYTES = 400000
MAX_SOURCE_BYTES = 64 * 1048576
MAX_TOTAL_BYTES = 128 * 1048576
MAX_OUTPUT_BYTES = 2 * 1048576


def _file(value, roots):
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts:
        raise ToolSafetyError('Line authoring requires absolute, non-traversing paths')
    for item in (path, *path.parents):
        if item.is_symlink() or item.is_junction():
            raise ToolSafetyError('Line authoring refuses linked paths and ancestors')
    if not path.is_file() or not any(within(path, root) for root in roots):
        raise ToolSafetyError('Line input or reference is missing or outside configured roots')
    return path.resolve()


def _read(path, maximum):
    if path.stat().st_size > maximum:
        raise ToolSafetyError('Line input or reference exceeds its byte bound')
    with path.open('rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ToolSafetyError('Line input or reference grew beyond its byte bound')
    return raw


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate line preview JSON key')
        result[key] = value
    return result


def _json(raw):
    def exact_float(token):
        value = float(token)
        if not math.isfinite(value) or Decimal(token) != Decimal(str(value)):
            raise ValueError('Line JSON numeric literal loses precision')
        return value

    try:
        text = raw.decode('utf-8')
        if len(text) > 100000:
            raise ValueError('Line request exceeds 100,000 characters')
        return json.loads(text, object_pairs_hook=_pairs, parse_float=exact_float,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Non-finite JSON')))
    except (ValueError, UnicodeError, RecursionError, OverflowError) as exc:
        raise ToolSafetyError('Invalid bounded line preview JSON') from exc


def _implementation_files():
    root = Path(__file__).resolve().parent
    return [root / name for name in ('line_authoring.py', 'core/line_authoring.py',
            'core/state_machine.py', 'input_contracts.py', 'settings.py', 'safety.py',
            'schemas/line_authoring_request.schema.json')]


class _Observation:
    def __init__(self):
        self.settings = get_settings()
        self.identity = self.settings.as_dict()
        self.roots = (self.settings.data_dir, *self.settings.source_roots,
                      *self.settings.document_roots, self.settings.definition_root, self.settings.sdk_root)
        self.inputs, self.bodies = {}, {}
        for path in _implementation_files():
            self.observe(str(path), roots=(path.parent,))
        if _json(self.bodies[str(_implementation_files()[-1])]) != core.LINE_AUTHORING_SCHEMA:
            raise ToolSafetyError('Loaded line schema differs from current packaged bytes')

    def observe(self, value, *, expected=None, maximum=MAX_SOURCE_BYTES, roots=None):
        roots = self.roots if roots is None else roots
        path = _file(value, roots)
        key = str(path)
        if sum(len(body) for body in self.bodies.values()) + (0 if key in self.bodies else path.stat().st_size) > MAX_TOTAL_BYTES:
            raise ToolSafetyError('Line references exceed 128 MiB aggregate')
        raw = _read(path, maximum)
        digest = hashlib.sha256(raw).hexdigest()
        if expected is not None and digest != expected:
            raise ToolSafetyError('Line input or provenance hash changed')
        if key in self.bodies and raw != self.bodies[key]:
            raise ToolSafetyError('Line reference changed during observation')
        self.bodies[key] = raw
        if sum(len(body) for body in self.bodies.values()) > MAX_TOTAL_BYTES:
            raise ToolSafetyError('Line references exceed 128 MiB aggregate')
        self.inputs[(str(value), tuple(roots))] = {
            'source_path': key, 'source_sha256': digest, 'bytes': len(raw)}
        return raw

    def finish(self, report):
        for (value, roots), row in self.inputs.items():
            path = _file(value, roots)
            if str(path) != row['source_path'] or _read(path, MAX_SOURCE_BYTES) != self.bodies[str(path)]:
                raise ToolSafetyError('Line source, reference or implementation changed before return')
        if get_settings().as_dict() != self.identity:
            raise ToolSafetyError('Line inspection configuration changed before return')
        result = {**report,
            'source_bindings': sorted({row['source_path']: row for row in self.inputs.values()}.values(),
                                      key=lambda row: row['source_path']),
            'configuration_sha256': sha256_json(self.identity),
            'grounding': {'references_current': True, 'interpretation_verified': False,
                          'publisher_authenticated': False},
            'files_written': 0, 'sdk_imported': False, 'live_calls_made': False,
            'execution_authorized': False, 'integration_qualified': False,
            'engineering_verdict': 'not_evaluated', 'automatic_retry': False}
        result['assessment_id'] = sha256_json(result)
        if len(json.dumps(result, allow_nan=False).encode('utf-8')) > MAX_OUTPUT_BYTES:
            raise ToolSafetyError('Line inspection output exceeds 2 MiB')
        return result


def inspect_line_authoring_input(source_path: str, source_sha256: str,
                                 profile_id: str = 'tline_rlc_3phase_ohmic_v1') -> dict:
    """Inspect an explicitly hashed scalar input; no solver or format guessing."""
    if not isinstance(source_sha256, str) or len(source_sha256) != 64 or any(c not in '0123456789abcdef' for c in source_sha256):
        raise ToolSafetyError('Line source SHA must be a lowercase SHA-256 digest')
    if Path(source_path).suffix.casefold() != '.tli':
        raise ToolSafetyError('This input profile requires a .tli source; cable and imperial profiles are unsupported')
    observation = _Observation()
    raw = observation.observe(source_path, expected=source_sha256, maximum=65536)
    report = core.inspect_line_input(raw, profile_id)
    return observation.finish({**report, 'source': {'path': str(Path(source_path).resolve()), 'sha256': source_sha256}})


def preview_line_authoring_request(request_path: str) -> dict:
    """Return a numeric edit preview and candidate hash, without publishing bytes."""
    observation = _Observation()
    raw_request = observation.observe(request_path, maximum=MAX_REQUEST_BYTES)
    request = _json(raw_request)
    core.validate_line_request(request)
    if Path(request['source']['path']).suffix.casefold() != '.tli':
        raise ToolSafetyError('This preview requires a .tli source; cable and imperial profiles are unsupported')
    raw = observation.observe(request['source']['path'], expected=request['source']['sha256'], maximum=65536)
    for ref in request['provenance']:
        observation.observe(ref['source_path'], expected=ref['source_sha256'])
    report, candidate = core.preview_line_input(raw, request)
    # In-memory bytes are deliberately not returned by this public read-only reader.
    return observation.finish({**report,
        'request_file_sha256': hashlib.sha256(raw_request).hexdigest(),
        'candidate': {'sha256': hashlib.sha256(candidate).hexdigest(), 'bytes': len(candidate), 'persisted': False},
        'provenance': request['provenance'],
        'unresolved_steps': ['line_constants_generation_and_fresh_output', 'draft_component_binding',
                             'isolated_save_reopen_and_compile', 'engineering_acceptance']})
