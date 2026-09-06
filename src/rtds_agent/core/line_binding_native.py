"""Internal, fixed SDK observation -> source-token projection adapter.

Caller must hold the execution lock, bind installed SDK/definition identities,
authorize this local API lane, and protect all operator files and companions.
This module grants no execution authority and never Compiles or starts Runtime.
The SDK save-as is retained as migration evidence, never as the candidate.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
import zipfile

from ..safety import ToolSafetyError
from .line_binding import COMPONENT_TYPE, _source, calculation_declarations, prepare_line_binding, project_line_binding
from .native_edit import values_equal
from .structured_patch import write_patched_archive
from .topology_parser import _section_lines


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _path(value):
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ToolSafetyError("Line binding requires absolute non-traversing paths")
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink() or (ancestor.exists() and
                getattr(ancestor.stat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ToolSafetyError("Linked line-binding path or ancestor refused")
    return path


def _read(path, maximum):
    _path(path)
    try:
        with path.open("rb") as stream:
            raw = stream.read(maximum + 1)
    except OSError as exc:
        raise ToolSafetyError("Unable to read bound line-binding file: " + str(path)) from exc
    if not raw or len(raw) > maximum:
        raise ToolSafetyError("Line-binding file exceeds its nonempty byte bound")
    return raw


def _archive(path):
    raw = _read(path, 32 * 1024 * 1024)
    members, metadata = {}, []
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        if not 1 <= len(infos) <= 64 or sum(i.file_size for i in infos) > 32 * 1024 * 1024:
            raise ToolSafetyError("Line-binding archive inventory exceeds bounds")
        folded = set()
        for info in infos:
            name = info.filename
            parts = PurePosixPath(name).parts
            if (not name or len(name) > 1024 or "\\" in name or ":" in name or
                    name.startswith("/") or any(p in {".", ".."} for p in name.split("/")) or
                    not parts or name.casefold() in folded or info.flag_bits & 1 or
                    stat.S_ISLNK(info.external_attr >> 16)):
                raise ToolSafetyError("Unsafe, duplicate or linked archive member")
            folded.add(name.casefold())
            members[name] = archive.read(info)
            metadata.append([name, info.date_time, info.compress_type, info.external_attr,
                             info.internal_attr, info.create_system, info.comment.hex(), info.extra.hex()])
        dfx = [n for n in members if n.lower().endswith(".dfx")]
        if len(dfx) != 1 or not 0 < len(members[dfx[0]]) <= 8 * 1024 * 1024:
            raise ToolSafetyError("Exactly one bounded Draft member is required")
        comment = archive.comment
    if _sha(_read(path, 32 * 1024 * 1024)) != _sha(raw):
        raise ToolSafetyError("Archive changed while being read")
    return {"path": str(path), "sha256": _sha(raw), "bytes": len(raw), "members": members,
            "metadata": metadata, "comment": comment, "dfx": dfx[0]}


def _reference(snapshot):
    return {k: snapshot[k] for k in ("path", "sha256", "bytes", "dfx")} | {
        "members": {n: {"sha256": _sha(b), "bytes": len(b)} for n, b in snapshot["members"].items()},
        "comment_sha256": _sha(snapshot["comment"])}


def _declarations(definition):
    if not isinstance(definition, bytes) or not 0 < len(definition) <= 2 * 1024 * 1024:
        raise ToolSafetyError("Definition bytes exceed bounds")
    declarations = {}
    for line in _section_lines(definition.decode("utf-8-sig"), "PARAMETERS"):
        text = line.strip()
        if not text or text.startswith(("//", "SECTION:")):
            continue
        fields = shlex.split(text)
        if (len(fields) < 6 or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", fields[0]) or
                fields[0].casefold() in {name.casefold() for name in declarations} or len(declarations) >= 500 or
                fields[4] not in {"REAL", "INTEGER", "NAME", "TOGGLE", "REAL_ARRAY"}):
            raise ToolSafetyError("Unsupported or ambiguous definition parameter inventory")
        declarations[fields[0]] = {"type": fields[4], "default": fields[5], "choices": fields[2]}
    return declarations


def allow_line_binding_rpc(path, method, args, journal, inp, export, candidate):
    """Fixed read surface; exact durable pending intent required for mutations."""
    value = journal.value
    if path == "rscad" and method == "ping" and args == []:
        return True
    if value.get("status") == "operator_recovery_required":
        return False
    paths = [str(inp), str(export), str(candidate)]
    owned = value.get("owned_case")
    prefix = f"rscad.case:{owned}" if type(owned) is int else None
    calls = value.get("native_calls", [])
    pending = value.get("permitted_rpc")
    operation = {"openCase": "open_case", "saveAs": "save_as", "close": "close", "setParameter": "set_parameter"}.get(method)
    intent = (pending == [path, method, args] and bool(calls) and
              calls[-1].get("status") == "started" and calls[-1].get("mutation") is True and
              calls[-1].get("operation") == operation and
              calls[-1].get("arguments") == {"path": path, "method": method, "args": args})
    if intent:
        if path == "rscad" and method == "openCase" and args in ([paths[0]], [paths[2]]):
            return True
        if prefix and path == prefix and value.get("identity_verified"):
            if method == "saveAs" and args == [paths[1]]:
                return True
            if method == "close" and len(args) == 1 and args[0] is False:
                return True
        match = re.fullmatch(re.escape(prefix or "NO_CASE") + r"\.draft\.comp_id:(\d+)", path)
        if match and value.get("identity_verified") and method == "setParameter":
            return any(args == [op["parameter"], op["new_value"]] and
                       int(match[1]) == op["component_id"] for op in value.get("binding_operations", []))
    if path == "rscad":
        if method in {"getMinimumApiVersion", "getApiVersion", "getVersion"}:
            return args == []
        return method == "getCaseNamed" and len(args) == 2 and args[0] in paths and args[1] is False
    if not prefix:
        return False
    if path == prefix:
        return method in {"getFile", "getRunState", "getModified"} and args == []
    if path == prefix + ".draft":
        if method == "numSubpages":
            return args == []
        return method == "getComponent" and len(args) == 1 and type(args[0]) is int and args[0] in value.get("read_ids", [])
    match = re.fullmatch(re.escape(prefix) + r"\.draft\.comp_id:(\d+)", path)
    if match and int(match[1]) in value.get("read_ids", []):
        if method in {"getComponentType", "getParameters"}:
            return args == []
        return method == "getParameter" and len(args) == 1 and args[0] in value.get("read_parameters", {}).get(match[1], [])
    return False


def bind_line_case(app, input_path, export_path, candidate_path, source_sha256,
                   tli: bytes, tlo: bytes, definition: bytes, plan: dict, journal, *,
                   calculation_definition: bytes | None = None, calculation_id: int | None = None) -> dict:
    """Observe twelve endpoint edits and an optional calculation-file binding.

    Failures raise with the durable journal retained. An uncertain owned case is
    never force-closed or retried. Caller must honor operator_recovery_required.
    """
    inp, export, candidate = map(_path, (input_path, export_path, candidate_path))
    if (journal.value.get("status") != "prepared" or journal.value.get("native_calls") or
            journal.value.get("owned_case") is not None or journal.value.get("native_mutation_possible")):
        raise ToolSafetyError("A fresh unexecuted native journal is required")
    if (len({inp, export, candidate}) != 3 or inp.suffix.lower() != ".rtfx" or
            export.suffix.lower() != ".rtfx" or candidate.suffix.lower() != ".rtfx" or
            export.parent.is_relative_to(candidate.parent) or candidate.parent.is_relative_to(export.parent) or
            export.parent.exists() or candidate.parent.exists()):
        raise ToolSafetyError("Fresh distinct export/candidate parent directories are required")
    source = _archive(inp)
    if source["sha256"] != source_sha256:
        raise ToolSafetyError("Source archive hash mismatch")
    source_dfx = source["members"][source["dfx"]]
    fresh_plan = prepare_line_binding(source_dfx, tli, tlo, definition,
                                      plan["endpoint_ids"], plan["companion_basename"],
                                      calculation_definition=calculation_definition, calculation_id=calculation_id)
    if (json.dumps(plan, sort_keys=True, separators=(",", ":"), allow_nan=False) !=
            json.dumps(fresh_plan, sort_keys=True, separators=(",", ":"), allow_nan=False)):
        raise ToolSafetyError("Line-binding plan or bound inputs changed")
    # Copy caller-owned mutable declarations before any SDK callback can run.
    plan = json.loads(json.dumps(fresh_plan))
    declarations = _declarations(definition)
    binding_ids = list(plan["endpoint_ids"])
    declarations_by_id = {uid: declarations for uid in binding_ids}
    types_by_id = {uid: COMPONENT_TYPE for uid in binding_ids}
    calculation_evidence = None
    if calculation_id is not None:
        calculation_evidence = calculation_declarations(calculation_definition, plan["source_calculation_parameters"])
        binding_ids.append(calculation_id)
        declarations_by_id[calculation_id] = calculation_evidence["declarations"]
        types_by_id[calculation_id] = "lf_rtds_sharc_sld_TL16CAL"
    source_rows = {r["uuid"]: r for r in _source(source_dfx)[1] if r["uuid"] in binding_ids}
    if any(not set(r["parameters"]) <= set(declarations_by_id[uid]) for uid, r in source_rows.items()):
        raise ToolSafetyError("Source parameters are not covered by the definition")
    bound_files = {inp: source_sha256}
    for suffix, raw in ((".tli", tli), (".tlo", tlo)):
        path = inp.parent / (plan["companion_basename"] + suffix)
        if _read(path, 65536) != raw:
            raise ToolSafetyError("Generated input companion differs from bound bytes")
        bound_files[path] = _sha(raw)
    journal.value.update(backend="hybrid_api_observed_source_patch", native_serialized_output=False,
                         compile_called=False, runtime_called=False, integration_qualified=False,
                         execution_authorized=False, automatic_retry=False,
                         source=_reference(source), plan_id=plan["plan_id"],
                         binding_operations=plan["operations"], read_ids=binding_ids,
                         read_parameters={str(uid): list(declarations_by_id[uid]) for uid in binding_ids},
                         definition_sha256=_sha(definition), observations={}, archive_deltas={})
    journal.value.update(binding_scope=plan["binding_scope"], calculation_id=calculation_id,
                         calculation_definition_sha256=_sha(calculation_definition) if calculation_definition is not None else None,
                         calculation_definition_evidence=calculation_evidence,
                         native_parameter_counts={str(uid): len(declarations_by_id[uid]) for uid in binding_ids},
                         compiler_dependency_binding_verified=False)
    journal.flush()
    case = None
    expected_file = None
    connection_attempted = disconnected = False
    open_uncertain = False
    baseline = None

    def recheck():
        for path, digest in bound_files.items():
            if _sha(_read(path, 32 * 1024 * 1024)) != digest:
                raise ToolSafetyError("Bound file changed during line binding: " + str(path))

    def call(name, path, method, args, fn, mutation=True):
        journal.value["permitted_rpc"] = [path, method, args]
        try:
            return journal.call(name, fn, mutation=mutation, arguments={"path": path, "method": method, "args": args})
        finally:
            journal.value.pop("permitted_rpc", None)
            journal.flush()

    def identity(clean=False):
        try:
            if (case is None or type(case.caseid) is not int or case.caseid != journal.value["owned_case"] or
                    case.file != str(expected_file) or case.state.run_state != "stopped" or
                    (clean and case.state.modified is not False)):
                raise ToolSafetyError("Owned line case identity, stopped state or clean state mismatch")
            journal.value["identity_verified"] = True
            journal.flush()
        except Exception:
            journal.lost_identity()
            raise

    def open_owned(path):
        nonlocal case, expected_file, open_uncertain
        recheck()
        open_uncertain = True
        case = call("open_case", "rscad", "openCase", [str(path)], lambda: app.open_case(str(path)))
        expected_file = path
        if case is None or type(case.caseid) is not int or case.caseid < 0:
            journal.lost_identity()
            raise ToolSafetyError("Unconfirmed native open identity")
        journal.value.update(owned_case=case.caseid, identity_verified=False)
        journal.flush()
        identity(clean=True)
        open_uncertain = False
        if case.draft.num_subpages() != 1:
            raise ToolSafetyError("Only one native Draft subsystem is supported")
        recheck()

    def close_owned():
        nonlocal case
        identity(clean=True)
        path = expected_file
        try:
            if call("close", f"rscad.case:{case.caseid}", "close", [False], lambda: case.close(force=False)) is not True:
                raise ToolSafetyError("Native close was not confirmed")
            if app.get_case(file=str(path), open_file=False) is not None:
                raise ToolSafetyError("Native case remains open after close")
        except Exception:
            journal.lost_identity()
            raise
        journal.value["cleanup"].append({"action": "close", "file": str(path), "verified": True})
        case = None
        journal.value.update(owned_case=None, identity_verified=False)
        journal.flush()
        recheck()

    def component(uid):
        item = case.draft.get_object(uid)
        if item is None or type(item.unique_id) is not int or item.unique_id != uid or item.component_type != types_by_id[uid]:
            raise ToolSafetyError("Native endpoint component identity mismatch")
        names = item.parameters
        if not isinstance(names, list) or len(names) != len(set(names)) or set(names) != set(declarations_by_id[uid]):
            raise ToolSafetyError("Native parameter inventory differs from bound definition")
        return item

    def observe(stage, changed):
        identity()
        observations = {}
        journal.value["observations"][stage] = observations
        for uid in binding_ids:
            item = component(uid)
            values = {}
            observations[str(uid)] = values
            for name in declarations_by_id[uid]:
                value = item.get_parameter(name)
                values[name] = value if isinstance(value, str) else {"unsupported_type": type(value).__name__}
                journal.flush()
                if not isinstance(value, str) or len(value) > 8192:
                    raise ToolSafetyError("Native parameter readback must be a bounded string")
                if baseline is not None:
                    expected = next((o["new_value"] for o in plan["operations"] if changed and
                                     o["component_id"] == uid and o["parameter"] == name), baseline[str(uid)][name])
                    if value != expected:
                        raise ToolSafetyError("Nonselected or selected native parameter readback drift: " + name)
            identity()
        pair = [observations[str(uid)]["Tnam1"] for uid in plan["endpoint_ids"]]
        if not pair[0].strip() or pair[0] != pair[1]:
            raise ToolSafetyError("Observed endpoint line-name pair differs or is empty")
        if calculation_id is not None and observations[str(calculation_id)]["Name"] != pair[0]:
            raise ToolSafetyError("Observed calculation line name differs from endpoint pair")
        recheck()
        return observations

    def check_baseline():
        evidence = []
        journal.value["baseline_equivalence"] = evidence
        for uid in binding_ids:
            stored = source_rows[uid]["parameters"]
            for name, declaration in declarations_by_id[uid].items():
                actual = baseline[str(uid)][name]
                expected = stored.get(name, declaration["default"])
                origin = "source_stored" if name in stored else "definition_default"
                kind = declaration["type"]
                if kind == "TOGGLE" and origin == "definition_default":
                    try:
                        choices = declaration["choices"].split(";")
                        index = int(expected)
                        if not 0 <= index < len(choices):
                            raise ValueError("selector default outside choices")
                        expected = choices[index]
                    except (ValueError, IndexError) as exc:
                        raise ToolSafetyError("Unresolved definition selector default") from exc
                if kind == "NAME" and "#" in expected:
                    matches = None
                    interpretation = "enumerated_name_observed_and_pinned; raw_to_api_mapping_unverified"
                elif kind in {"REAL", "INTEGER"}:
                    matches = values_equal(actual, expected, numeric=True)
                    interpretation = "finite_decimal_equivalence"
                elif kind == "REAL_ARRAY":
                    a, e = actual.split(","), expected.split(",")
                    matches = len(a) == len(e) and all(values_equal(x, y, numeric=True) for x, y in zip(a, e))
                    interpretation = "finite_decimal_array_equivalence"
                else:
                    matches = actual == expected
                    interpretation = "exact_literal"
                evidence.append({"component_id": uid, "parameter": name, "origin": origin,
                                 "expected_raw_or_default_label": expected, "observed": actual,
                                 "equivalent": matches, "interpretation": interpretation})
                journal.flush()
                if matches is False:
                    raise ToolSafetyError("Native baseline differs from stored/default parameter: " + name)

    try:
        recheck()
        export.parent.mkdir(parents=True, exist_ok=False)
        connection_attempted = True
        journal.call("connect", app.connect)
        version = app.get_version()
        journal.value["observed_rscad_version"] = version
        if str(version) not in {"2.7", "2.7.3"}:
            raise ToolSafetyError("RSCAD version outside reviewed scope")
        for path in (inp, export, candidate):
            if app.get_case(file=str(path), open_file=False) is not None:
                raise ToolSafetyError("Line-binding path is already open")
        open_owned(inp)
        baseline = observe("before", False)
        check_baseline()
        for selectors in plan["source_endpoint_selectors"]:
            observed = baseline[str(selectors["component_id"])]
            if (observed["endsr"] != selectors["endsr"] or
                    not values_equal(observed["numc"], selectors["numc"], numeric=True) or
                    not values_equal(observed["PERCENT_OF_LINE"], selectors["PERCENT_OF_LINE"], numeric=True)):
                raise ToolSafetyError("Native baseline endpoint selectors differ from the source plan")
        for op in plan["operations"]:
            if baseline[str(op["component_id"])][op["parameter"]] != op.get("expected_old_api_value", op["expected_old_value"]):
                raise ToolSafetyError("Native baseline selected value differs from source token")
        for op in plan["operations"]:
            recheck()
            identity()
            item = component(op["component_id"])
            call("set_parameter", f"rscad.case:{case.caseid}.draft.comp_id:{op['component_id']}",
                 "setParameter", [op["parameter"], op["new_value"]],
                 lambda: item.set_parameter(op["parameter"], op["new_value"]))
        after = observe("after", True)
        recheck()
        identity()
        if export.exists() or any(export.parent.iterdir()):
            raise ToolSafetyError("Native export destination is no longer fresh")
        try:
            call("save_as", f"rscad.case:{case.caseid}", "saveAs", [str(export)], lambda: case.save(str(export)))
        except Exception:
            journal.lost_identity()
            raise
        expected_file = export
        identity(clean=True)
        native = _archive(export)
        bound_files[export] = native["sha256"]
        journal.value["native_export"] = _reference(native)
        journal.flush()
        close_owned()
        native_rows = _source(native["members"][native["dfx"]])[1]
        exported = {r["uuid"]: r for r in native_rows if r["uuid"] in binding_ids}
        for op in plan["operations"]:
            row = exported.get(op["component_id"])
            if (row is None or row["component_type"] != op["component_type"] or row["context"] != "subsystem:0" or
                    row["parameters"].get(op["parameter"]) != op["new_value"]):
                raise ToolSafetyError("Native exported raw value differs from exact plan")
        journal.value["archive_deltas"] = {
            "added_members": sorted(native["members"].keys() - source["members"].keys()),
            "removed_members": sorted(source["members"].keys() - native["members"].keys()),
            "changed_members": sorted(n for n in source["members"].keys() & native["members"].keys()
                                      if source["members"][n] != native["members"][n]),
            "source_components": _source(source_dfx)[1], "exported_components": native_rows,
            "raw_export_retained": str(export), "export_is_candidate": False}
        readbacks = [{"component_id": o["component_id"], "parameter": o["parameter"],
                      "before": baseline[str(o["component_id"])][o["parameter"]],
                      "after": after[str(o["component_id"])][o["parameter"]]} for o in plan["operations"]]
        projection, projected = project_line_binding(source_dfx, tli, tlo, definition, plan, readbacks,
                                                      calculation_definition=calculation_definition, calculation_id=calculation_id)
        recheck()
        _path(candidate)
        if candidate.parent.exists():
            raise ToolSafetyError("Projection destination is no longer fresh")
        write_patched_archive(inp, candidate, source["dfx"], projected)
        built = _archive(candidate)
        if (built["metadata"] != source["metadata"] or built["comment"] != source["comment"] or
                list(built["members"]) != list(source["members"]) or
                any(built["members"][n] != (projected if n == source["dfx"] else raw)
                    for n, raw in source["members"].items())):
            raise ToolSafetyError("Projected archive changed unrequested bytes or metadata")
        bound_files[candidate] = built["sha256"]
        for suffix, raw in ((".tli", tli), (".tlo", tlo)):
            path = _path(candidate.parent / (plan["companion_basename"] + suffix))
            with path.open("xb") as stream:
                stream.write(raw)
            bound_files[path] = _sha(raw)
        journal.value.update(projection=projection, candidate=_reference(built))
        journal.flush()
        recheck()
        open_owned(candidate)
        observe("candidate_reopen", True)
        close_owned()
        recheck()
        journal.value.update(status="verified_hybrid_binding", all_declared_parameters_pinned=True,
                             native_parameter_count=len(declarations), candidate_reopen_verified=True,
                             compiler_dependency_binding_verified=calculation_id is not None,
                             non_dfx_bytes_preserved=True, source_unrequested_bytes_preserved=True)
    except Exception as exc:
        journal.value.update(error_type=type(exc).__name__, error=str(exc))
        if journal.value["status"] != "operator_recovery_required":
            journal.value["status"] = "failed"
        raise
    finally:
        if case is not None and journal.value["status"] != "operator_recovery_required":
            try:
                close_owned()
            except Exception as exc:
                journal.value["cleanup"].append({"action": "close", "verified": False, "error": str(exc)})
        if open_uncertain or case is not None:
            journal.value["status"] = "operator_recovery_required"
        if connection_attempted:
            try:
                app.disconnect(terminate=False)
                disconnected = True
                journal.value["cleanup"].append({"action": "disconnect", "verified": True, "terminate": False})
            except Exception as exc:
                journal.value["cleanup"].append({"action": "disconnect", "verified": False, "error": str(exc)})
                journal.value["status"] = "operator_recovery_required"
        journal.value["cleanup_verified"] = case is None and not open_uncertain and disconnected
        errors = []
        for path, digest in bound_files.items():
            try:
                if _sha(_read(path, 32 * 1024 * 1024)) != digest:
                    errors.append(str(path))
            except Exception as exc:
                errors.append(str(path) + ": " + str(exc))
        journal.value["final_hash_errors"] = errors
        journal.value["bound_files"] = {str(p): h for p, h in bound_files.items()}
        if errors and journal.value["status"] != "operator_recovery_required":
            journal.value["status"] = "failed"
        if journal.value["status"] != "verified_hybrid_binding" or not journal.value["cleanup_verified"]:
            journal.value["compiler_dependency_binding_verified"] = False
        journal.flush()
    if journal.value["status"] != "verified_hybrid_binding" or not journal.value["cleanup_verified"]:
        raise ToolSafetyError("Hybrid binding or cleanup was not verified")
    return journal.value
