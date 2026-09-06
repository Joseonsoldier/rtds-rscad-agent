"""Read-only comparison of supplied scalar line input/output and generation records."""
from __future__ import annotations

from pathlib import Path

from .core import line_constants as core
from .input_contracts import schema, validate
from .line_authoring import _Observation, _json, MAX_REQUEST_BYTES
from .safety import ToolSafetyError

REQUEST_SCHEMA = schema('line_constants_request.schema.json')
RECEIPT_SCHEMA = schema('line_generation_receipt.schema.json')


def _implementation_files():
    root = Path(__file__).resolve().parent
    return [root / name for name in ('line_constants.py', 'core/line_constants.py',
            'schemas/line_constants_request.schema.json', 'schemas/line_generation_receipt.schema.json')]


def inspect_line_constants(request_path: str) -> dict:
    """Compare current bytes; a supplied generation record is never execution proof."""
    observation = _Observation()
    for path in _implementation_files():
        observation.observe(str(path), roots=(path.parent,))
    for name, contract in (('line_constants_request.schema.json', REQUEST_SCHEMA),
                           ('line_generation_receipt.schema.json', RECEIPT_SCHEMA)):
        path = Path(__file__).resolve().parent / 'schemas' / name
        if _json(observation.bodies[str(path)]) != contract:
            raise ToolSafetyError('Loaded constants schema differs from current bytes')
    request = _json(observation.observe(request_path, maximum=MAX_REQUEST_BYTES))
    validate(request, REQUEST_SCHEMA)
    if Path(request['input']['path']).suffix.casefold() != '.tli' or Path(request['output']['path']).suffix.casefold() != '.tlo':
        raise ToolSafetyError('This constants comparison requires metric scalar .tli and .tlo files')
    inputs = {}
    for role in ('input', 'output'):
        ref = request[role]
        inputs[role] = observation.observe(ref['path'], expected=ref['sha256'], maximum=65536)
    refs = request['provenance']
    identities = [(row['source_path'], row['source_sha256'], row['locator']) for row in refs]
    if len(set(identities)) != len(identities):
        raise ToolSafetyError('Duplicate line constants provenance')
    for ref in refs:
        observation.observe(ref['source_path'], expected=ref['source_sha256'])
    for role in ('input', 'output'):
        if not any(row['source_path'] == request[role]['path'] and row['source_sha256'] == request[role]['sha256'] for row in refs):
            raise ToolSafetyError('Constants provenance must pin exact input and output paths/hashes')
    receipt_report = {'status': 'not_supplied', 'claims_verified': False}
    if ref := request['generation_receipt']:
        receipt = _json(observation.observe(ref['path'], expected=ref['sha256'], maximum=MAX_REQUEST_BYTES))
        validate(receipt, RECEIPT_SCHEMA)
        if any(receipt[key] != request[key] for key in ('profile_id', 'input', 'output')):
            raise ToolSafetyError('Generation receipt differs from the exact requested input/output/profile')
        artifacts = receipt['generator']['artifacts']
        if len({row['path'] for row in artifacts}) != len(artifacts):
            raise ToolSafetyError('Duplicate generator artifact path')
        for artifact in (*artifacts, receipt['execution']['events']):
            observation.observe(artifact['path'], expected=artifact['sha256'])
        receipt_report = {'status': 'bound_supplied_record', 'claims_verified': False,
            'attempt_id': receipt['attempt_id'], 'generator': receipt['generator'],
            'declared_execution': receipt['execution'], 'record': ref,
            'limitation': 'Hash identity verifies current supplied bytes, not origin, freshness or the recorded process restrictions.'}
    report = core.compare_line_constants(inputs['input'], inputs['output'], request['profile_id'])
    return observation.finish({**report, 'input_inspection': report['input'], 'output_inspection': report['output'],
        'input': request['input'], 'output': request['output'],
        'algorithm_evidence_status': {'basis': 'historical_installed_source_discovery',
            'current_sources_verified': False,
            'limitation': 'Current reference grounding covers source_bindings only; it does not revalidate every historical algorithm source.'},
        'generation_record': receipt_report, 'provenance': refs,
        'native_origin_verified': False, 'freshness_verified': False, 'generator_execution_verified': False,
        'compile_called': False, 'generation_called': False})
