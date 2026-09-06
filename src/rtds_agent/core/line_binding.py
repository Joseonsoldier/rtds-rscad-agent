"""Pure hybrid projection of observed line parameters into immutable source bytes.

This is not a native serializer, an API proof verifier, or a publication backend.
"""
from __future__ import annotations

import copy
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re
import shlex

from .line_constants import compare_line_constants
from .topology_parser import parse_dfx_components, parse_parameter_schema, parse_project_settings, _section_lines


COMPONENT_TYPE = "lf_rtds_sharc_sld_TLINE"
CALCULATION_TYPE = "lf_rtds_sharc_sld_TL16CAL"
CALCULATION_TYPES = {
    **dict.fromkeys(("Name", "Dnm1"), "NAME"),
    **dict.fromkeys(("cntyp", "pptline", "Icon", "elimCrtLag", "dataType", "exclu", "AorM", "Rprc", "AM", "rdData", "hmnpp", "frcpi", "alwpi", "raistt", "Ph", "Type", "enDebug"), "TOGGLE"),
    **dict.fromkeys(("CARD", "CORE", "final_tl_berg_format_tlbclb_tloclo_or_tlines_012", "num_normal_dt_in_SE_dt", "num_normal_dt_in_RE_dt", "local_nmcond"), "INTEGER"),
    **dict.fromkeys(("pp_var", "final_tl_berg_percentage_line_length", "Lgrd", "Rgrd", "Laer", "Raer"), "REAL"),
    **dict.fromkeys(("note1", "note2", "final_tl_constants_file_name_cw_sufx"), "CHAR"),
}
CALCULATION_GUARDS = {"cntyp": "Bergeron", "pptline": "No", "dataType": "File", "rdData": "tlo/clo", "Type": "TLINE", "hmnpp": "(pp_var)%"}
INACTIVE_SECTION = 'SECTION: "OPTIONS" cntyp>0 & pptline=1'
BERGERON_SECTION = 'SECTION: "OPTIONS WHEN USING BERGERON DATA" cntyp<1 && (getBoxParentType()!=2  || dataType == 0)'
REPEATED_PARAMETERS = {"pp_var", "hmnpp", "frcpi", "alwpi", "raistt"}
PARAMETERS = ("tlb", "LENGTH", "ZM", "TM", "R", "TI")
TYPES = {"tlb": "NAME", "LENGTH": "REAL", "ZM": "REAL_ARRAY", "TM": "REAL_ARRAY",
         "R": "REAL_ARRAY", "TI": "REAL_ARRAY", "endsr": "TOGGLE", "numc": "INTEGER",
         "Tnam1": "NAME", "PERCENT_OF_LINE": "REAL"}
NUMERIC = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
SAFE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,79}\Z")
RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
FLAGS = {"backend": "hybrid_api_observed_source_patch", "native_serialized_output": False,
         "observations_authenticated": False, "definition_identity_authenticated": False,
         "filesystem_name_uniqueness_verified": False, "files_written": 0,
         "integration_qualified": False, "execution_authorized": False,
         "engineering_verdict": "not_evaluated", "automatic_retry": False,
         "live_calls_made": False, "compile_called": False, "runtime_called": False}
LIMITATIONS = [
    "Supplied readbacks are exact-value declarations, not authenticated API execution or native-export provenance.",
    "The candidate is a source-preserving parameter-token projection, not native-serialized whole Draft output or a rescued native-save result.",
    "Unrequested native defaults, format migrations and Runtime changes are never projected; their effects remain outside this pure comparison.",
    "The caller must verify source/definition/attempt identity, all relevant native defaults and selector state, fresh companion files, exact candidate reopen and cleanup before publication.",
    "Non-DFX archive preservation and filesystem basename uniqueness require separate checks; this function receives only supplied member bytes.",
]


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError("Line-binding contract must contain bounded JSON data") from exc
    if len(raw) > 1024 * 1024:
        raise ValueError("Line-binding JSON exceeds 1 MiB")
    return raw


def _text(raw, label, maximum, line_limit):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= maximum:
        raise ValueError(f"{label} requires nonempty bounded bytes")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError(f"{label} requires UTF-8 or UTF-8-SIG") from exc
    if len(text.splitlines()) > line_limit or any(ord(c) < 32 and c not in "\t\r\n" for c in text):
        raise ValueError(f"{label} exceeds line bound or contains unsupported control characters")
    return text


def _number(value):
    if not isinstance(value, str) or len(value) > 128 or not NUMERIC.fullmatch(value):
        raise ValueError("Line-binding numeric token has unsupported syntax")
    try:
        exact = Decimal(value)
        numeric = float(value)
        if not exact.is_finite() or not math.isfinite(numeric) or (exact != 0 and numeric == 0):
            raise ValueError("Line-binding numbers must be finite and non-underflowing")
    except (InvalidOperation, OverflowError) as exc:
        raise ValueError("Invalid line-binding numeric token") from exc
    return exact


def _value(parameter, value):
    if not isinstance(value, str) or len(value) > 1200 or not value:
        raise ValueError("Line-binding parameter values must be bounded strings")
    if parameter in {"tlb", "Dnm1"}:
        if not SAFE_NAME.fullmatch(value) or value.upper() in RESERVED_NAMES:
            raise ValueError("Companion name must be a safe ASCII basename without path or extension")
    elif parameter == "LENGTH":
        _number(value)
    else:
        values = value.split(",")
        if len(values) != (9 if parameter == "TI" else 3):
            raise ValueError("Line-binding array arity does not match the three-phase profile")
        for item in values:
            _number(item)


def _definition(raw):
    text = _text(raw, "Definition", 2 * 1024 * 1024, 50000)
    if len(re.findall(r"(?m)^PARAMETERS:[ \t]*\r?$", text)) != 1:
        raise ValueError("Definition requires one unambiguous PARAMETERS section")
    declarations = {}
    for line in _section_lines(text, "PARAMETERS"):
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "SECTION:")):
            continue
        try:
            tokens = shlex.split(stripped, posix=True)
        except ValueError as exc:
            raise ValueError("Malformed definition parameter declaration") from exc
        if not tokens or tokens[0] in declarations or len(declarations) >= 500:
            raise ValueError("Duplicate or excessive definition parameter declarations")
        declarations[tokens[0]] = stripped
    schema = parse_parameter_schema(text)
    for parameter, kind in TYPES.items():
        if parameter not in declarations or schema.get(parameter, {}).get("data_type") != kind:
            raise ValueError(f"Definition does not uniquely declare {parameter} as {kind}")
        if parameter in PARAMETERS and schema[parameter]["unit"] != "":
            raise ValueError("Hidden line-cache unit declarations differ from the observed blank-unit profile")
    if schema["endsr"]["enum_values"] != ["SENDING", "RECEIVING"]:
        raise ValueError("Definition endpoint selector differs from the supported profile")
    return {name: {"data_type": schema[name]["data_type"], "unit": schema[name]["unit"],
                   "raw_declaration": declarations[name]} for name in TYPES}


def calculation_declarations(raw: bytes, parameters: dict) -> dict:
    """Resolve only the fixed Bergeron/File profile's one inactive duplicate block.

    Other section/field expressions are retained, never executed or qualified.
    All parameters must be explicitly saved, including the two blank CHAR notes.
    """
    if (type(parameters) is not dict or set(parameters) != set(CALCULATION_TYPES) or
            any(type(v) is not str or len(v) > 8192 for v in parameters.values())):
        raise ValueError("Calculation component requires all 34 exact explicit stored parameters")
    if any(parameters[k] != v for k, v in CALCULATION_GUARDS.items()) or _number(parameters["pp_var"]) != Decimal(100):
        raise ValueError("Calculation selectors differ from the fixed full-length Bergeron/File/TLINE profile")
    if parameters["note1"] != "" or parameters["note2"] != "":
        raise ValueError("The supported calculation profile requires explicit blank note fields")
    text = _text(raw, "Calculation definition", 2 * 1024 * 1024, 50000)
    if len(re.findall(r"(?m)^PARAMETERS:[ \t]*\r?$", text)) != 1:
        raise ValueError("Calculation definition requires one PARAMETERS section")
    declarations, inactive, section = {}, [], None
    section_counts = {INACTIVE_SECTION: 0, BERGERON_SECTION: 0}
    for line in _section_lines(text, "PARAMETERS"):
        value = line.strip()
        if not value or value.startswith("//"):
            continue
        if value.startswith("SECTION:"):
            section = value
            if section in section_counts:
                section_counts[section] += 1
                if section_counts[section] > 1:
                    raise ValueError("Repeated calculation section scope")
            continue
        try:
            tokens = shlex.split(value)
        except ValueError as exc:
            raise ValueError("Malformed calculation definition declaration") from exc
        if (section is None or len(tokens) < 5 or tokens[0] not in CALCULATION_TYPES or
                tokens[4] != CALCULATION_TYPES[tokens[0]] or
                (len(tokens) < 6 and tokens[0] not in {"note1", "note2"})):
            raise ValueError("Unsupported calculation definition inventory or type")
        name = tokens[0]
        declaration = {"type": tokens[4], "default": tokens[5] if len(tokens) >= 6 else None,
                       "choices": tokens[2], "raw_declaration": value, "raw_section": section}
        if section == INACTIVE_SECTION:
            if (name not in REPEATED_PARAMETERS or name not in declarations or
                    declarations[name]["raw_section"] != BERGERON_SECTION or
                    any(r["parameter"] == name for r in inactive)):
                raise ValueError("Unrecognized inactive calculation declaration")
            if any(declaration[k] != declarations[name][k] for k in ("type", "default", "choices")):
                raise ValueError("Inactive duplicate changes parameter type/default/choices")
            inactive.append({"parameter": name, "raw_declaration": value})
        else:
            if name in declarations:
                raise ValueError("Ambiguous calculation definition duplicate outside the fixed inactive section")
            declarations[name] = declaration
    if (set(declarations) != set(CALCULATION_TYPES) or any(n != 1 for n in section_counts.values()) or
            {r["parameter"] for r in inactive} != REPEATED_PARAMETERS):
        raise ValueError("Calculation definition does not match the complete observed declaration profile")
    enum_profiles = {"cntyp": "Bergeron;Fre-Dep;Fre-Phase", "pptline": "No;Yes", "dataType": "File;Local",
                     "rdData": "tlb/cbl;tlo/clo", "Type": "TLINE;CABLE", "hmnpp": "(pp_var)%;(100-pp_var)%"}
    if (any(declarations[k]["choices"] != v for k, v in enum_profiles.items()) or
            declarations["Dnm1"]["choices"] != "Omit .xxx" or declarations["Name"]["choices"].strip() or
            declarations["pp_var"]["choices"] != "%"):
        raise ValueError("Calculation definition selector or parameter semantics differ from the fixed profile")
    return {"declarations": declarations, "definition_sha256": _sha(raw),
            "inactive_section": INACTIVE_SECTION, "inactive_declarations": inactive,
            "profile_guards": {**CALCULATION_GUARDS, "pp_var": parameters["pp_var"]},
            "conditional_basis": "Stored cntyp=Bergeron (index 0) and pptline=No (index 0) exclude only the exact OPTIONS cntyp>0 & pptline=1 branch; other expressions are not evaluated."}


def _source(raw):
    text = _text(raw, "Source DFX", 8 * 1024 * 1024, 100000)
    # Embedded Runtime GROUP: records are opaque preserved bytes. Draft GROUP
    # and hierarchy control syntax, including indented aliases, is unsupported.
    if re.search(r"(?m)^[ \t]*(?:HIERARCHY-(?:START|END):|GROUP-END:|COMPONENT_TYPE=(?:GROUP|HIERARCHY)[ \t]*\r?$)", text):
        raise ValueError("Line binding requires a flat Draft without groups or hierarchy")
    if re.search(r"(?m)^[ \t]+COMPONENT_TYPE=", text):
        raise ValueError("Indented component declarations are unsupported")
    lines, offset = [], 0
    for line in raw.splitlines(keepends=True):
        body = line.rstrip(b"\r\n")
        lines.append((body, offset))
        offset += len(line)
    starts = [i for i, (body, _) in enumerate(lines) if body.startswith(b"COMPONENT_TYPE=")]
    substarts = [i for i, (body, _) in enumerate(lines) if body.strip() == b"SUBSYSTEM-START:"]
    subends = [i for i, (body, _) in enumerate(lines) if body.strip() == b"SUBSYSTEM-END:"]
    if len(substarts) != 1 or len(subends) != 1 or not substarts[0] < subends[0]:
        raise ValueError("Line binding requires one explicit flat subsystem")
    if not 2 <= len(starts) <= 500 or any(not substarts[0] < start < subends[0] for start in starts):
        raise ValueError("Component count or subsystem placement is unsupported")
    components, spans, ids = [], {}, set()
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else subends[0]
        body, _ = lines[start]
        component_type = body.split(b"=", 1)[1].strip().decode("utf-8")
        position = start + 1
        while position < end and not lines[position][0].strip():
            position += 1
        header = re.fullmatch(rb"[ \t]*(-?[0-9]+)[ \t]+(-?[0-9]+)[ \t]+([0-9]+)[ \t]+([0-9]+)[ \t]+([0-9]+)[ \t]*", lines[position][0]) if position < end else None
        if header is None or int(header[5]) > 500:
            raise ValueError("Invalid or oversized component header")
        params, local_spans, uuid_values, parameter_names = {}, {}, [], set()
        active = False
        sections = endings = 0
        for number in range(position + 1, end):
            body, byte_start = lines[number]
            stripped = body.strip()
            if stripped == b"PARAMETERS-START:":
                if active or sections:
                    raise ValueError("Duplicate parameter sections")
                active, sections = True, sections + 1
            elif stripped == b"PARAMETERS-END:":
                if not active:
                    raise ValueError("Orphan parameter section terminator")
                active, endings = False, endings + 1
            elif active:
                if not stripped:
                    continue
                match = re.fullmatch(rb"[ \t]*([A-Za-z_][A-Za-z0-9_.-]*)[ \t]*:([ \t]*)(.*?)([ \t]*)", body)
                if match is None:
                    raise ValueError("Malformed stored parameter line")
                name = match[1].decode("ascii")
                if name.casefold() in parameter_names:
                    raise ValueError("Duplicate stored parameter")
                parameter_names.add(name.casefold())
                value = match[3].decode("utf-8")
                params[name] = value
                local_spans[name] = (byte_start + match.start(3), byte_start + match.end(3))
            elif stripped.startswith(b"UUID:"):
                match = re.fullmatch(rb"UUID:[ \t]*([0-9]+)", stripped)
                if not match:
                    raise ValueError("Malformed component UUID")
                uuid_values.append(int(match[1]))
        if active or sections != endings or len(uuid_values) != 1 or not 0 <= uuid_values[0] <= 2147483647:
            raise ValueError("Ambiguous component UUID or parameter section")
        if len(params) != int(header[5]) or (params and sections != 1):
            raise ValueError("Declared parameter count does not match unique raw lines")
        uuid = uuid_values[0]
        if uuid in ids:
            raise ValueError("Component UUIDs must be globally unique")
        ids.add(uuid)
        components.append({"uuid": uuid, "component_type": component_type, "parameters": params})
        spans.update({(uuid, key): value for key, value in local_spans.items()})
    parsed = parse_dfx_components(text)
    if len(parsed) != len(components) or any(row["context"] != "subsystem:0" for row in parsed):
        raise ValueError("Component parser and explicit flat source inventory disagree")
    for checked, row in zip(components, parsed):
        if any(checked[key] != row[key] for key in ("uuid", "component_type", "parameters")):
            raise ValueError("Raw and semantic component inventories disagree")
    return text, parsed, spans


def prepare_line_binding(source_dfx: bytes, tli: bytes, tlo: bytes, definition: bytes,
                         endpoint_ids: list[int], companion_basename: str, *,
                         calculation_definition: bytes | None = None, calculation_id: int | None = None) -> dict:
    """Prepare twelve endpoint fields and optionally one calculation file binding."""
    if (calculation_definition is None) != (calculation_id is None):
        raise ValueError("Calculation definition and ID must be supplied together")
    if calculation_id is not None and (type(calculation_id) is not int or not 0 <= calculation_id <= 2147483647):
        raise ValueError("Calculation ID must be a bounded integer")
    if type(endpoint_ids) is not list or len(endpoint_ids) != 2 or any(type(i) is not int or not 0 <= i <= 2147483647 for i in endpoint_ids) or len(set(endpoint_ids)) != 2:
        raise ValueError("Exactly two distinct integer endpoint IDs are required")
    _value("tlb", companion_basename)
    definition_schema = _definition(definition)
    text, components, spans = _source(source_dfx)
    if re.search(r"(?<![A-Za-z0-9_])" + re.escape(companion_basename) + r"(?![A-Za-z0-9_])", text, re.IGNORECASE):
        raise ValueError("New companion basename already occurs in the source")
    selected = [row for row in components if row["uuid"] in endpoint_ids]
    if len(selected) != 2 or any(row["component_type"] != COMPONENT_TYPE for row in selected):
        raise ValueError("Endpoints must identify exactly two supported TLINE components")
    for row in selected:
        params = row["parameters"]
        if any(key not in params for key in TYPES):
            raise ValueError("Endpoint is missing explicit line binding or selector parameters")
        if params["numc"] != "3" or _number(params["PERCENT_OF_LINE"]) != Decimal(100):
            raise ValueError("Only three-conductor full-length endpoints are supported")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}#?", params["Tnam1"]):
            raise ValueError("Unsupported saved line-name identity")
        for parameter in PARAMETERS:
            _value(parameter, params[parameter])
    if {row["parameters"]["endsr"] for row in selected} != {"SENDING", "RECEIVING"}:
        raise ValueError("Exactly one sending and one receiving endpoint are required")
    if len({row["parameters"]["Tnam1"] for row in selected}) != 1 or len({row["parameters"]["tlb"] for row in selected}) != 1:
        raise ValueError("Selected endpoints do not share one exact saved line identity and companion")
    line_name = selected[0]["parameters"]["Tnam1"]
    if any(row not in selected and row["component_type"] == COMPONENT_TYPE and row["parameters"].get("Tnam1") == line_name for row in components):
        raise ValueError("Saved line identity is shared by additional endpoints")
    calculation = calculation_evidence = None
    if calculation_id is not None:
        rows = [row for row in components if row["uuid"] == calculation_id]
        matching = [row for row in components if row["component_type"] == CALCULATION_TYPE and row["parameters"].get("Name") == line_name]
        if (len(rows) != 1 or rows[0]["component_type"] != CALCULATION_TYPE or
                len(matching) != 1 or matching[0]["uuid"] != calculation_id):
            raise ValueError("Calculation ID must identify the unique supported component for the exact saved line name")
        calculation = rows[0]
        old_basename = selected[0]["parameters"]["tlb"]
        if calculation["parameters"].get("Dnm1") not in {old_basename, old_basename + "#"}:
            raise ValueError("Calculation file binding does not match the selected endpoint companion")
        calculation_evidence = calculation_declarations(calculation_definition, calculation["parameters"])
    for raw in (tli, tlo):
        if not isinstance(raw, bytes) or not 0 < len(raw) <= 65536:
            raise ValueError("Supplied line constants require bounded input/output bytes")
    comparison = compare_line_constants(tli, tlo)
    if comparison["status"] != "consistent" or len(comparison["checks"]) != 24:
        raise ValueError("Supplied scalar input/output must pass all 24 numerical comparisons")
    output = comparison["output"]
    modes = [row["fields"] for row in output["modes"]]
    if any(_number(row["resistance_ohm_per_m_1"]["raw_value"]) != _number(row["resistance_ohm_per_m_2"]["raw_value"]) for row in modes):
        raise ValueError("Both TLO resistance columns must agree exactly for a single cache value")
    new_values = {"tlb": companion_basename, "LENGTH": output["header"]["length_m"]["raw_value"],
                  "ZM": ",".join(row["impedance_ohm"]["raw_value"] for row in modes),
                  "TM": ",".join(row["travel_time_ms"]["raw_value"] for row in modes),
                  "R": ",".join(row["resistance_ohm_per_m_1"]["raw_value"] for row in modes),
                  "TI": ",".join(value["raw_value"] for row in modes for value in row["transformation_row"])}
    operations = []
    for row in selected:
        for parameter in PARAMETERS:
            _value(parameter, new_values[parameter])
            start, end = spans[row["uuid"], parameter]
            operations.append({"component_id": row["uuid"], "context": "subsystem:0", "component_type": COMPONENT_TYPE,
                               "parameter": parameter, "expected_old_value": row["parameters"][parameter],
                               "new_value": new_values[parameter], "source_byte_start": start, "source_byte_end": end})
    if calculation is not None:
        start, end = spans[calculation_id, "Dnm1"]
        operations.append({"component_id": calculation_id, "context": "subsystem:0", "component_type": CALCULATION_TYPE,
                           "parameter": "Dnm1", "expected_old_value": calculation["parameters"]["Dnm1"],
                           "expected_old_api_value": selected[0]["parameters"]["tlb"], "new_value": companion_basename,
                           "source_byte_start": start, "source_byte_end": end})
    plan = {"schema_version": "1.0", "status": "prepared_unexecuted",
            "source_dfx_sha256": _sha(source_dfx), "tli_sha256": _sha(tli), "tlo_sha256": _sha(tlo),
            "definition_sha256": _sha(definition), "endpoint_ids": sorted(endpoint_ids),
            "companion_basename": companion_basename, "operations": operations,
            "definition_schema": definition_schema, "source_component_count": len(components),
            "source_settings": parse_project_settings(text), "source_line_name": line_name,
            "source_endpoint_selectors": [{"component_id": row["uuid"], **{key: row["parameters"][key] for key in ("Tnam1", "endsr", "numc", "PERCENT_OF_LINE")}} for row in selected],
            "binding_scope": "endpoint_and_calculation_parameters" if calculation is not None else "endpoint_parameters_only",
            "compiler_dependency_binding_verified": False,
            "calculation_id": calculation_id, "calculation_definition_sha256": _sha(calculation_definition) if calculation is not None else None,
            "calculation_definition_evidence": calculation_evidence,
            "source_calculation_parameters": copy.deepcopy(calculation["parameters"]) if calculation is not None else None,
            "constants_comparison": {"status": "consistent", "checks": 24, "freshness_verified": False},
            "limitations": list(LIMITATIONS), **FLAGS}
    plan["limitations"].append("Compiler dependency coverage and Compile acceptance are not established by this pure plan; endpoint-only plans omit the calculation component file reference.")
    plan["plan_id"] = _sha(_json(plan))
    return plan


def project_line_binding(source_dfx: bytes, tli: bytes, tlo: bytes, definition: bytes,
                         plan: dict, readbacks: list[dict], *, calculation_definition: bytes | None = None,
                         calculation_id: int | None = None) -> tuple[dict, bytes]:
    """Require exact supplied observations and replace only existing value spans."""
    if type(plan) is not dict:
        raise ValueError("Line binding requires a prepared plan")
    actual_plan = _json(plan)
    try:
        expected = prepare_line_binding(source_dfx, tli, tlo, definition, plan["endpoint_ids"], plan["companion_basename"],
                                        calculation_definition=calculation_definition, calculation_id=calculation_id)
    except KeyError as exc:
        raise ValueError("Incomplete line-binding plan") from exc
    if actual_plan != _json(expected):
        raise ValueError("Line-binding plan or bound source evidence changed")
    if type(readbacks) is not list or len(readbacks) != len(expected["operations"]):
        raise ValueError("Exactly one supplied readback per planned parameter is required")
    _json(readbacks)
    observed = {}
    for row in readbacks:
        if type(row) is not dict or set(row) != {"component_id", "parameter", "before", "after"}:
            raise ValueError("Readback fields must match the strict four-field contract")
        if type(row["component_id"]) is not int or type(row["parameter"]) is not str or row["parameter"] not in (*PARAMETERS, "Dnm1"):
            raise ValueError("Readback identity is invalid")
        _value(row["parameter"], row["before"])
        _value(row["parameter"], row["after"])
        key = row["component_id"], row["parameter"]
        if key in observed:
            raise ValueError("Duplicate parameter readback identity")
        observed[key] = row
    for operation in expected["operations"]:
        row = observed.get((operation["component_id"], operation["parameter"]))
        if row is None or row["before"] != operation.get("expected_old_api_value", operation["expected_old_value"]) or row["after"] != operation["new_value"]:
            raise ValueError("Supplied before/after readback differs from the exact planned value")
    candidate = source_dfx
    for operation in sorted(expected["operations"], key=lambda row: row["source_byte_start"], reverse=True):
        start, end = operation["source_byte_start"], operation["source_byte_end"]
        if source_dfx[start:end].decode("utf-8") != operation["expected_old_value"]:
            raise ValueError("Planned source token span changed")
        candidate = candidate[:start] + operation["new_value"].encode("ascii") + candidate[end:]
    before_text, before, _ = _source(source_dfx)
    after_text, after, _ = _source(candidate)
    intended = copy.deepcopy(before)
    for operation in expected["operations"]:
        next(row for row in intended if row["uuid"] == operation["component_id"])["parameters"][operation["parameter"]] = operation["new_value"]
    if intended != after or parse_project_settings(before_text) != parse_project_settings(after_text):
        raise ValueError("Projected source differs from the bounded component/settings change")
    # Reconstruct the source using only the new token positions. This verifies
    # every opaque byte, not merely fields recognized by the semantic parser.
    shift, changes, inverse = 0, [], candidate
    for operation in sorted(expected["operations"], key=lambda row: row["source_byte_start"]):
        start = operation["source_byte_start"] + shift
        end = start + len(operation["new_value"].encode("ascii"))
        changes.append({**operation, "candidate_byte_start": start, "candidate_byte_end": end})
        shift += len(operation["new_value"].encode("ascii")) - (operation["source_byte_end"] - operation["source_byte_start"])
    for change in reversed(changes):
        inverse = inverse[:change["candidate_byte_start"]] + change["expected_old_value"].encode("utf-8") + inverse[change["candidate_byte_end"]:]
    if inverse != source_dfx:
        raise ValueError("Projection changed bytes outside the authorized parameter tokens")
    report = {"schema_version": "1.0", "status": "projected_in_memory", "plan_id": expected["plan_id"],
              "source_dfx_sha256": expected["source_dfx_sha256"], "candidate_dfx_sha256": _sha(candidate),
              "tli_sha256": expected["tli_sha256"], "tlo_sha256": expected["tlo_sha256"],
              "definition_sha256": expected["definition_sha256"], "candidate_bytes": len(candidate),
              "readbacks_sha256": _sha(_json(sorted(readbacks, key=lambda row: (row["component_id"], row["parameter"])))),
              "changes": changes, "observation_count": len(readbacks), "only_requested_value_tokens_changed": True,
              "binding_scope": expected["binding_scope"], "compiler_dependency_binding_verified": False,
              "calculation_id": calculation_id, "calculation_definition_sha256": expected["calculation_definition_sha256"],
              "parsed_components_and_settings_verified": True, "unrequested_bytes_preserved": True,
              "limitations": list(expected["limitations"]), **FLAGS}
    report["projection_id"] = _sha(_json(report))
    return report, candidate
