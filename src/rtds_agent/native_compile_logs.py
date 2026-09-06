"""Read explicitly attempt-bound log receipts without native calls or writes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .core.compile_diagnostics import classify_compile_diagnostics, parse_compile_log
from .core.state_machine import sha256_json
from .input_contracts import validate
from .rulepacks import _file, _hash
from .safety import ToolSafetyError

_HASH = {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}
_TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 4000, 'pattern': r'\S'}
_LOG_FIELDS = {'path': _TEXT, 'sha256': _HASH, 'bytes': {'type': 'integer', 'minimum': 0, 'maximum': 1048576},
               'encoding': {'enum': ['utf-8', 'utf-8-sig', 'ascii']}, 'format_id': _TEXT,
               'collection_status': {'enum': ['complete', 'partial']}}
_FIELDS = {'schema_version': {'const': '1.0'}, 'workflow_id': _TEXT, 'attempt_id': _TEXT,
           'action': {'const': 'compile'}, 'source_sha256': _HASH, 'working_sha256': _HASH,
           'logs': {'type': 'array', 'minItems': 1, 'maxItems': 16,
                    'items': {'type': 'object', 'additionalProperties': False,
                              'required': list(_LOG_FIELDS), 'properties': _LOG_FIELDS}}}
RECEIPT_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': list(_FIELDS), 'properties': _FIELDS}


def _read(ref, roots):
    path = _file(ref['path'], roots)
    if path.stat().st_size != ref['bytes'] or ref['bytes'] > 1048576:
        raise ToolSafetyError('Native log byte count differs or exceeds 1 MiB')
    with path.open('rb') as stream:
        raw = stream.read(1048577)
    if len(raw) != ref['bytes'] or hashlib.sha256(raw).hexdigest() != ref['sha256']:
        raise ToolSafetyError('Native log content differs from the exact receipt')
    return raw


def revalidate_logs(receipt, roots):
    for ref in receipt['logs']:
        _read(ref, roots)


def inspect_native_compile_logs(receipt, *, workflow_id, attempt_id, input_hashes, document,
                                roots, execution, offset=0, limit=100):
    validate(receipt, RECEIPT_SCHEMA)
    if (receipt['workflow_id'] != workflow_id or receipt['attempt_id'] != attempt_id
            or any(receipt[key] != input_hashes[key] for key in ('source_sha256', 'working_sha256'))):
        raise ToolSafetyError('Native log receipt belongs to another workflow, attempt or input')
    if document['source']['rtfx_sha256'] != input_hashes['working_sha256']:
        raise ToolSafetyError('Native log model snapshot does not match its input')
    if any(type(ref['bytes']) is not int for ref in receipt['logs']):
        raise ToolSafetyError('Native log byte count must be an integer')
    if sum(ref['bytes'] for ref in receipt['logs']) > 4 * 1048576:
        raise ToolSafetyError('Native logs exceed 4 MiB aggregate')
    names = [_file(ref['path'], roots) for ref in receipt['logs']]
    if len(set(names)) != len(names):
        raise ToolSafetyError('Duplicate native log path identity')
    parsed, records = [], []
    implementation = [Path(__file__), Path(__file__).with_name('diagnostics.py'),
                      Path(__file__).with_name('core')/'compile_diagnostics.py',
                      Path(__file__).with_name('rulepacks.py')]
    implementation_hashes = {str(p): _hash(p) for p in implementation}
    for ref in receipt['logs']:
        result = parse_compile_log(_read(ref, roots), {key: ref[key] for key in ('path', 'sha256', 'bytes', 'encoding')}, ref['format_id'])
        records.extend(result.pop('records'))
        parsed.append({**result, 'collection_status': ref['collection_status']})
    classified = classify_compile_diagnostics(records, document['components'], document['snapshot_id'])
    if len(classified) > 10000:
        raise ToolSafetyError('Native diagnostics exceed 10,000 records')
    coverage = 'unsupported' if any(row['parser_coverage'] == 'unsupported' for row in parsed) else (
        'partial' if any(row['parser_coverage'] == 'partial' for row in parsed) else 'complete' if records else 'empty')
    result = {'schema_version': '1.0', 'workflow_id': workflow_id, 'attempt_id': attempt_id,
              'receipt_sha256': sha256_json(receipt), 'input_hashes': input_hashes,
              'mapping_snapshot_id': document['snapshot_id'], 'logs': parsed,
              'diagnostics': classified[offset:offset + limit], 'diagnostic_count': len(classified),
              'offset': offset, 'limit': limit, 'next_offset': offset + limit if offset + limit < len(classified) else None,
              'returned_count': len(classified[offset:offset + limit]), 'parser_coverage': coverage,
              'collection_complete': all(row['collection_status'] == 'complete' for row in parsed),
              'collection_status_is_declared': True, 'native_origin_verified': False, 'freshness_verified': False,
              'recorded_execution': execution, 'native_outcome': 'not_evaluated',
              'empty_log_proves_success': False, 'source_hashes_verified': True,
              'automatic_retry': False, 'automatic_repair': False, 'integration_qualified': False,
              'execution_authorized': False, 'live_calls_made': False, 'mutations_performed': False,
              'implementation_sources': list(implementation_hashes.values())}
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > 2 * 1048576:
        raise ToolSafetyError('Native diagnostic response exceeds 2 MiB; request fewer records')
    revalidate_logs(receipt, roots)
    if any(_hash(Path(name)) != before for name, before in implementation_hashes.items()):
        raise ToolSafetyError('Native diagnostic implementation changed while reading')
    result['assessment_sha256'] = sha256_json(result)
    return result
