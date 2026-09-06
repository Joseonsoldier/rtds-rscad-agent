"""Read-only, source-bound parser regression inspection; never native execution."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .core import compile_diagnostics as diagnostics
from .safety import ToolSafetyError
from .settings import get_settings, within

MAX_MANIFEST_BYTES = 400000
MAX_SOURCE_BYTES = 256 * 1048576
MAX_TOTAL_BYTES = 512 * 1048576
MAX_OUTPUT_BYTES = 2 * 1048576


def _file(value, roots):
    path = Path(value)
    if not path.is_absolute():
        raise ToolSafetyError('Corpus paths must be absolute')
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink() or ancestor.is_junction():
            raise ToolSafetyError('Corpus refuses linked paths or ancestors')
    if not any(within(path, root) for root in roots) or not path.is_file():
        raise ToolSafetyError('Corpus file is missing or outside configured roots')
    return path.resolve()


def _read(path, maximum):
    with path.open('rb') as stream:
        body = stream.read(maximum + 1)
    if len(body) > maximum:
        raise ToolSafetyError('Corpus input exceeds its byte bound')
    return body


def _hash(path):
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise ToolSafetyError('Corpus source exceeds 256 MiB')
    digest, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        while chunk := stream.read(1048576):
            size += len(chunk)
            if size > MAX_SOURCE_BYTES:
                raise ToolSafetyError('Corpus source exceeds 256 MiB')
            digest.update(chunk)
    return {'source_path': str(path), 'source_sha256': digest.hexdigest(), 'bytes': size}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate corpus JSON key')
        result[key] = value
    return result


def _json(body):
    try:
        text = body.decode('utf-8')
        if len(text) > 100000:
            raise ValueError('Corpus JSON exceeds 100,000 characters')
        return json.loads(text, object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Non-finite JSON')))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ToolSafetyError('Invalid bounded corpus JSON') from exc


def _implementation_files():
    root = Path(__file__).resolve().parent
    return [root / name for name in ('compile_corpus.py', 'core/compile_diagnostics.py',
            'core/state_machine.py', 'input_contracts.py', 'settings.py', 'safety.py',
            'schemas/compile_failure_corpus.schema.json')]


def inspect_compile_corpus(corpus_path: str) -> dict:
    """Compare supplied parser expectations after validating all current source bytes."""
    settings = get_settings()
    settings_identity = settings.as_dict()
    roots = (settings.data_dir, *settings.source_roots, *settings.document_roots, settings.definition_root)
    manifest = _file(corpus_path, roots)
    observed, permitted = {}, {}
    input_paths = [(corpus_path, manifest)]

    def observe(path, allowed):
        key = str(path)
        if key not in observed:
            if sum(item['bytes'] for item in observed.values()) + path.stat().st_size > MAX_TOTAL_BYTES:
                raise ToolSafetyError('Corpus sources exceed 512 MiB aggregate')
            row = _hash(path)
            if sum(item['bytes'] for item in observed.values()) + row['bytes'] > MAX_TOTAL_BYTES:
                raise ToolSafetyError('Corpus sources exceed 512 MiB aggregate')
            observed[key], permitted[key] = row, allowed
        return observed[key]

    manifest_body = _read(manifest, MAX_MANIFEST_BYTES)
    manifest_ref = observe(manifest, roots)
    if hashlib.sha256(manifest_body).hexdigest() != manifest_ref['source_sha256']:
        raise ToolSafetyError('Corpus manifest changed while reading')
    contract = _json(manifest_body)
    implementation = []
    for path in _implementation_files():
        implementation.append(observe(_file(str(path), (path.parent,)), (path.parent,)))
    schema_path = _implementation_files()[-1]
    if _json(_read(schema_path, MAX_MANIFEST_BYTES)) != diagnostics.CORPUS_SCHEMA:
        raise ToolSafetyError('Loaded corpus schema differs from current schema bytes')
    diagnostics.validate_corpus(contract)
    cases = []
    for case in contract['cases']:
        raw_ref = case['raw_ref']
        raw_path = _file(raw_ref['path'], roots)
        input_paths.append((raw_ref['path'], raw_path))
        raw = _read(raw_path, 1048576)
        row = observe(raw_path, roots)
        if row['source_sha256'] != raw_ref['sha256'] or row['bytes'] != raw_ref['bytes']:
            raise ToolSafetyError('Corpus fixture hash or byte count mismatch')
        for reference in case['provenance']:
            path = _file(reference['source_path'], roots)
            input_paths.append((reference['source_path'], path))
            if observe(path, roots)['source_sha256'] != reference['source_sha256']:
                raise ToolSafetyError('Corpus provenance hash mismatch')
        parsed = diagnostics.parse_compile_log(raw, raw_ref, case['format_id'])
        # No model is supplied. The corpus hash only satisfies the pure classifier's
        # required identity argument; it is never returned as a model snapshot.
        records = diagnostics.classify_compile_diagnostics(parsed['records'], [], manifest_ref['source_sha256'])
        actual = {'categories': [r['category'] for r in records],
                  'component_mappings': [r['component_mapping'] for r in records],
                  'parser_coverage': parsed['parser_coverage']}
        cases.append({'case_id': case['case_id'], 'status': 'passed' if actual == case['expectations'] else 'failed',
                      'expected': case['expectations'], 'actual': actual, 'counts': parsed['counts'],
                      'decode_status': parsed['decode_status'], 'raw_ref': raw_ref,
                      'declared_evidence_kind': case['evidence_kind'], 'native_origin_verified': False,
                      'source_provenance': case['provenance'], 'declared_sanitization': case['sanitization'],
                      'limitations': case['limitations'], 'parser_limitations': parsed['limitations']})
    passed = sum(case['status'] == 'passed' for case in cases)
    result = {'schema_version': '1.0', 'corpus_id': contract['corpus_id'],
              'status': 'passed' if passed == len(cases) else 'failed',
              'purpose': 'deterministic_parser_regression', 'source': manifest_ref,
              'counts': {'cases': len(cases), 'passed': passed, 'failed': len(cases) - passed},
              'cases': cases, 'implementation': implementation, 'source_hashes_verified': True,
              'component_mapping_scope': 'not_model_mapped', 'native_origin_verified': False,
              'execution_authorized': False, 'writes_performed': False,
              'limitations': ['Passed means supplied parser expectations matched; it does not mean Compile succeeded.',
                              'Evidence kind, source locators and sanitization descriptions are caller declarations.',
                              'No model component inventory is supplied; exact component mapping is unavailable.',
                              'Source hash equality does not verify provenance interpretation or native origin.'],
              **diagnostics.FLAGS}
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')) > MAX_OUTPUT_BYTES:
        raise ToolSafetyError('Corpus response exceeds 2 MiB')
    for key, expected in observed.items():
        if _hash(_file(key, permitted[key])) != expected:
            raise ToolSafetyError('Corpus source or implementation changed during inspection')
    for original, expected in input_paths:
        if _file(original, roots) != expected:
            raise ToolSafetyError('Corpus input path changed during inspection')
    if get_settings().as_dict() != settings_identity:
        raise ToolSafetyError('Corpus settings changed during inspection')
    return result
