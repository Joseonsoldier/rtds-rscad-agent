"""Read-only source binding for optional, explicitly selected domain criteria."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
from typing import Annotated
import zipfile

from pydantic import BeforeValidator, WithJsonSchema

from .core.power_system_rules import RULEPACK_SCHEMA, evaluate_rulepacks, rulepack_catalog, validate_rulepacks
from .core.state_machine import sha256_json
from .core.structured_patch import dfx_components, validate_new_value
from .core.topology_parser import UUID_RE, _section_lines, parse_parameter_schema
from .project_tools import _document
from .safety import ToolSafetyError, checked_file
from .settings import get_settings

MAX_PROJECT_BYTES = 20 * 1024 * 1024
MAX_SOURCE_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024


def _inline_schema(value, resolving=()):
    if isinstance(value, list):
        return [_inline_schema(item, resolving) for item in value]
    if not isinstance(value, dict):
        return value
    if '$ref' in value:
        ref = value['$ref']
        if not ref.startswith('#/$defs/') or ref in resolving:
            raise ValueError('Unsupported rulepack schema reference')
        expanded = _inline_schema(RULEPACK_SCHEMA['$defs'][ref.removeprefix('#/$defs/')], (*resolving, ref))
        siblings = {key: child for key, child in value.items() if key != '$ref'}
        return {'allOf': [expanded, _inline_schema(siblings, resolving)]} if siblings else expanded
    return {key: _inline_schema(child, resolving) for key, child in value.items() if key not in {'$defs', '$id'}}


RulePackRequest = Annotated[dict, BeforeValidator(validate_rulepacks), WithJsonSchema(_inline_schema(RULEPACK_SCHEMA))]


def _file(value, roots):
    candidate = Path(value)
    if not candidate.is_absolute():
        raise ToolSafetyError('Rulepack source paths must be absolute')
    for path in (candidate, *candidate.parents):
        if path.is_symlink() or path.is_junction():
            raise ToolSafetyError('Rulepack inspection refuses linked files or ancestors')
    return checked_file(value, roots)


def _hash(path, maximum=MAX_SOURCE_BYTES):
    if not path.is_file() or path.stat().st_size > maximum:
        raise ToolSafetyError('Rulepack source is absent or exceeds its byte limit')
    digest, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            size += len(block)
            if size > maximum:
                raise ToolSafetyError('Rulepack source grew beyond its byte limit')
            digest.update(block)
    return {'source_path': str(path), 'source_sha256': digest.hexdigest(), 'bytes': size}


def _read_dfx(path):
    if path.stat().st_size > MAX_PROJECT_BYTES:
        raise ToolSafetyError('Rulepack source project exceeds 20 MiB')
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > 256 or sum(row.file_size for row in infos) > MAX_PROJECT_BYTES:
            raise ToolSafetyError('Rulepack expanded project exceeds its member/byte bounds')
        names = [row.filename for row in infos]
        selected = [name for name in names if name.casefold().endswith('.dfx')]
        if len(names) != len(set(names)) or len(selected) != 1:
            raise ToolSafetyError('Rulepacks require one unique DFX member')
        with archive.open(selected[0]) as stream:
            raw = stream.read(MAX_PROJECT_BYTES + 1)
        if len(raw) > MAX_PROJECT_BYTES:
            raise ToolSafetyError('Rulepack DFX exceeds 20 MiB')
    return raw


def _raw_inventory(data):
    text, _, components = dfx_components(data)
    lines = text.splitlines()
    # GROUP containers have no component UUID. Keep their boundaries, but do not
    # pair them with the parser's UUID-bearing component inventory.
    starts = [i for i, line in enumerate(lines)
              if line.startswith('COMPONENT_TYPE=') or line.strip() == 'COMPONENT_TYPE=GROUP']
    ranges = [(start, starts[i + 1] if i + 1 < len(starts) else len(lines))
              for i, start in enumerate(starts) if lines[start].strip() != 'COMPONENT_TYPE=GROUP']
    if len(components) != len(ranges) or len(components) > 5000:
        raise ToolSafetyError('Rulepack raw component inventory is unsupported or exceeds 5000 components')
    records = defaultdict(list)
    boundaries = {'HIERARCHY-START:', 'HIERARCHY-END:', 'SUBSYSTEM-START:', 'SUBSYSTEM-END:', 'GROUP-END:'}
    for component, (start, end) in zip(components, ranges):
        values, starts, ends, inside = defaultdict(list), 0, 0, False
        uuids = []
        kind = lines[start].split('=', 1)[1].strip()
        for line in lines[start + 1:end]:
            stripped = line.strip()
            if stripped in boundaries:
                break
            if stripped == 'PARAMETERS-START:':
                starts += 1; inside = True
            elif stripped == 'PARAMETERS-END:':
                ends += 1; inside = False
            elif inside and ':' in line:
                key, value = line.split(':', 1)
                values[key.strip()].append(value.strip())
            elif match := UUID_RE.match(line):
                uuids.append(int(match.group(1)))
        records[(component['context'], component['uuid'])].append({
            'component_type': kind, 'values': dict(values),
            'sections_exact': (starts == ends == 1 and not inside and uuids == [component['uuid']]
                               and kind == component['component_type']
                               and all(len(rows) == 1 for rows in values.values())
                               and {key: rows[0] for key, rows in values.items()} == component['parameters'])})
    return records


def _definition_rows(body):
    text = body.decode('utf-8-sig')
    # Preserve duplicates instead of the legacy convenience parser's last-value map.
    rows = defaultdict(list)
    if sum(line.strip() == 'PARAMETERS:' for line in text.splitlines()) != 1:
        return rows
    for line in _section_lines(text, 'PARAMETERS'):
        for key, value in parse_parameter_schema('PARAMETERS:\n' + line + '\nNODES:\n').items():
            rows[key].append(value)
    return rows


def _implementation_files():
    root = Path(__file__).resolve().parent
    return [root/name for name in ('rulepacks.py', 'model_check.py', 'project_tools.py', 'settings.py', 'safety.py',
        'input_contracts.py', 'core/power_system_rules.py', 'core/structured_patch.py', 'core/topology_parser.py',
        'core/state_machine.py', 'schemas/power_system_rulepacks.schema.json')]


def inspect_rulepacks(document, request):
    """Bind declared criteria to exact saved data and return advisory observations."""
    validate_rulepacks(request)
    settings = get_settings()
    source = document['source']
    if request['input_project_sha256'] != source['rtfx_sha256']:
        raise ToolSafetyError('Rulepack project hash differs from the requested source')
    project = _file(source['rtfx_path'], (*settings.source_roots, settings.projects_root))
    roots = (*settings.source_roots, *settings.document_roots, settings.definition_root, settings.data_dir)
    observed, allowed_roots = {}, {}

    def observe(path, permitted):
        key = str(path)
        if key not in observed:
            if sum(row['bytes'] for row in observed.values()) + path.stat().st_size > MAX_TOTAL_BYTES:
                raise ToolSafetyError('Rulepack sources exceed 512 MiB')
            row = _hash(path)
            if sum(item['bytes'] for item in observed.values()) + row['bytes'] > MAX_TOTAL_BYTES:
                raise ToolSafetyError('Rulepack sources grew beyond 512 MiB')
            observed[key] = row
            allowed_roots[key] = permitted
        return observed[key]

    if observe(project, (*settings.source_roots, settings.projects_root))['source_sha256'] != source['rtfx_sha256']:
        raise ToolSafetyError('Rulepack source project changed')
    for pack in request['packs']:
        for rule in pack['rules']:
            for reference in rule['source']:
                path = _file(reference['source_path'], roots)
                actual = observe(path, roots)
                if reference['source_sha256'] != actual['source_sha256']:
                    raise ToolSafetyError('Rulepack provenance hash differs from its current source')
    raw_records = _raw_inventory(_read_dfx(project))
    components = defaultdict(list)
    for row in document['components']:
        components[(row['context'], row['uuid'])].append(row)
    definitions = {}
    for pack in request['packs']:
        for binding in pack['bindings']:
            kind = binding['component_type']
            if kind in definitions:
                continue
            reference = document.get('definition_evidence', {}).get(kind)
            if reference is None:
                definitions[kind] = (None, {})
                continue
            path = _file(reference['path'], (settings.definition_root,))
            if path.stat().st_size > 2 * 1024 * 1024:
                raise ToolSafetyError('Rulepack definition exceeds 2 MiB')
            actual = observe(path, (settings.definition_root,))
            if actual['source_sha256'] != reference['sha256']:
                raise ToolSafetyError('Rulepack definition changed during observation')
            with path.open('rb') as stream:
                body = stream.read(2 * 1024 * 1024 + 1)
            if len(body) > 2 * 1024 * 1024 or hashlib.sha256(body).hexdigest() != reference['sha256']:
                raise ToolSafetyError('Rulepack definition bytes changed')
            try:
                rows = _definition_rows(body)
            except UnicodeError:
                rows = {}
            definitions[kind] = (reference, rows)
    for path in _implementation_files():
        observe(_file(str(path), (Path(__file__).resolve().parent,)), (Path(__file__).resolve().parent,))

    bindings = {}
    for pack in request['packs']:
        by_id = {row['binding_id']: row for row in pack['bindings']}
        for rule in pack['rules']:
            pinned = {(row['source_path'], row['source_sha256']) for row in rule['source']}
            for binding_id in rule['inputs'].values():
                ref, _ = definitions[by_id[binding_id]['component_type']]
                if ref and (ref['path'], ref['sha256']) not in pinned:
                    raise ToolSafetyError('Every rule must cite the current exact definition of each input')
        for binding in pack['bindings']:
            identity = (binding['context'], binding['component_id'])
            ref, schema = definitions[binding['component_type']]
            observation = {key: binding[key] for key in ('quantity', 'units', 'basis', 'pu_base', 'origin')}
            observation.update(status='unresolved', reason=None, value=None, evidence=[])
            bindings[(pack['pack_id'], binding['binding_id'])] = observation
            if ref and ref['sha256'] != binding['definition_sha256']:
                raise ToolSafetyError('Rulepack binding references a different definition version')
            try:
                selected, raw = components[identity], raw_records[identity]
                if len(selected) != 1 or len(raw) != 1 or selected[0]['component_type'] != binding['component_type']:
                    raise ValueError('Component identity is missing or ambiguous')
                component, record = selected[0], raw[0]
                if (not record['sections_exact'] or record['component_type'] != binding['component_type']
                        or any(len(values) != 1 for values in record['values'].values())
                        or component['declared_parameter_count'] != component['parsed_parameter_count']):
                    raise ValueError('Stored parameter records are duplicate, incomplete or unsupported')
                parameters = schema.get(binding['parameter'], [])
                if ref is None or len(parameters) != 1:
                    raise ValueError('Numeric definition is unresolved or has ambiguous repeated declarations')
                parameter = parameters[0]
                if parameter['data_type'] not in {'REAL', 'INTEGER'} or parameter['unit'] != binding['units']:
                    raise ValueError('Declared numeric type or exact units do not match')
                stored = record['values'].get(binding['parameter'], [])
                actual_origin = 'stored' if stored else 'definition_default'
                value = stored[0] if stored else parameter['default']
                if actual_origin != binding['origin'] or value != binding['expected_value']:
                    raise ValueError('Expected raw value or stored/default origin differs')
                selectors = []
                for condition in binding['selectors']:
                    choices = schema.get(condition['parameter'], [])
                    if len(choices) != 1 or choices[0]['data_type'] != 'TOGGLE':
                        raise ValueError('Selector declaration is missing, repeated or not TOGGLE')
                    choice = choices[0]
                    saved = record['values'].get(condition['parameter'], [])
                    selected_value = saved[0] if saved else choice['default']
                    if not saved and isinstance(selected_value, str) and selected_value.isdigit():
                        index = int(selected_value)
                        selected_value = choice['enum_values'][index] if index < len(choice['enum_values']) else None
                    if selected_value not in choice['enum_values'] or selected_value != condition['expected_value']:
                        raise ValueError('Declared selector condition is not satisfied')
                    selectors.append({'parameter': condition['parameter'], 'value': selected_value,
                        'origin': 'stored' if saved else 'definition_default', 'declared_modes': choice['enum_values']})
                numeric = validate_new_value(parameter, str(value))['numeric_value']
                if not math.isfinite(numeric) or abs(numeric) > 1e12:
                    raise ValueError('Numeric observation exceeds finite supported bounds')
                observation.update(status='resolved', value=numeric, evidence=[
                    {'source_path': source['rtfx_path'], 'source_sha256': source['rtfx_sha256'],
                     'locator': f"{identity[0]} / component {identity[1]} / parameter {binding['parameter']}",
                     'observed': {'context': identity[0], 'component_id': identity[1], 'component_type': binding['component_type'],
                                 'parameter': binding['parameter'], 'raw_value': value, 'origin': actual_origin,
                                 'selector_conditions': selectors, 'selector_semantics_verified': False}},
                    {'source_path': ref['path'], 'source_sha256': ref['sha256'],
                     'locator': 'Unique parsed parameter declaration: ' + binding['parameter']}])
            except (ValueError, TypeError, OverflowError) as exc:
                observation['reason'] = str(exc)[:1000]
    result = evaluate_rulepacks(request, bindings)
    result.update(snapshot_id=document['snapshot_id'], source=source,
                  request_sha256=sha256_json(request), source_files=[observed[key] for key in sorted(observed)],
                  model_snapshot=document['snapshot'],
                  parser_evidence={'coverage': document['coverage'], 'warnings': document['warnings'], 'limitations': document['limitations']},
                  binding_observations=[{'pack_id': key[0], 'binding_id': key[1], **value} for key, value in sorted(bindings.items())],
                  source_hashes_verified=True, sdk_imported=False, mutations_performed=False)
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > 2 * 1024 * 1024:
        raise ToolSafetyError('Rulepack response exceeds 2 MiB; select fewer criteria')
    _document(source['rtfx_path'], document['snapshot_id'])
    for key, before in observed.items():
        path = _file(key, allowed_roots[key])
        if _hash(path) != before:
            raise ToolSafetyError('Rulepack source changed during assessment')
    if get_settings() != settings:
        raise ToolSafetyError('Rulepack configuration changed during assessment')
    result['assessment_sha256'] = sha256_json(result)
    return result
