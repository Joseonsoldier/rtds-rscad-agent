"""Read-only RTIFX/DFX component and topology parser for RSCAD FX 2.7.3.

The parser intentionally never writes an RTIFX file and never connects to RSCAD.
It combines DFX placement data with the installed component definition NODES block.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import shlex
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


GRID_SIZE = 32
SECTION_RE = re.compile(r"^[A-Z][A-Z0-9_-]*:\s*$")
HEADER_RE = re.compile(r"^\s*(-?\d+)\s+(-?\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$")
UUID_RE = re.compile(r"^\s*UUID:\s*(\d+)\s*$")
TYPE_NAMES = {
    "REAL",
    "INTEGER",
    "TOGGLE",
    "NAME",
    "CHAR",
    "TEXT",
    "FILE",
    "COMPLEX",
    "COLOR",
    "TABLE",
    "CHARACTER",
    "IMAGE",
    "REAL_ARRAY",
}
NODE_KINDS = {
    "EXTERNAL",
    "GROUND",
    "INPUT",
    "OUTPUT",
    "I/O",
    "DEFAULT",
    "SHORT",
    "INTERNAL",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_rtfx_dfx(path: Path) -> tuple[str, str, str]:
    """Return DFX member name, decoded text, and DFX SHA-256."""
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".dfx")]
        if len(members) != 1:
            raise ValueError(f"Expected one DFX member in {path}, found {members}")
        data = archive.read(members[0])
    return members[0], data.decode("utf-8-sig"), sha256_bytes(data)


def parse_project_settings(text: str) -> dict[str, str | None]:
    patterns = {
        "draft_format": r"^DRAFT\s+(.+)$",
        "title": r"^\s*TITLE:\s*(.+)$",
        "time_step_seconds": r"^\s*TIME-STEP:\s*(.+)$",
        "finish_time_seconds": r"^\s*FINISH-TIME:\s*(.+)$",
        "configured_rack": r"^\s*RTDS-RACK:\s*(.+)$",
        "compile_mode": r"^\s*COMPILE-MODE:\s*(.+)$",
        "distribution_mode": r"^\s*DISTRIBUTION_MODE:\s*(.+)$",
        "real_time": r"^\s*RTDS REAL-TIME:\s*(.+)$",
    }
    result: dict[str, str | None] = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text, flags=re.MULTILINE)
        result[key] = match.group(1).strip() if match else None
    return result


def _parse_component(lines: list[str], start: int, context: str) -> tuple[dict[str, Any], int]:
    component_type = lines[start].split("=", 1)[1].strip()
    index = start + 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index >= len(lines) or not (header := HEADER_RE.match(lines[index])):
        raise ValueError(f"Missing component header after line {start + 1}: {component_type}")
    x, y, orientation_quadrants, mirrored, declared_parameter_count = map(int, header.groups())
    index += 1
    parameters: dict[str, str] = {}
    uuid: int | None = None
    in_parameters = False
    while index < len(lines):
        line = lines[index]
        if line.startswith("COMPONENT_TYPE=") or line in {"HIERARCHY-START:", "HIERARCHY-END:", "SUBSYSTEM-END:"}:
            break
        stripped = line.strip()
        if stripped == "PARAMETERS-START:":
            in_parameters = True
        elif stripped == "PARAMETERS-END:":
            in_parameters = False
        elif in_parameters and ":" in stripped:
            name, value = stripped.split(":", 1)
            parameters[name.strip()] = value.strip()
        elif match := UUID_RE.match(line):
            uuid = int(match.group(1))
        index += 1
    if uuid is None:
        raise ValueError(f"Missing UUID for {component_type} at ({x}, {y})")
    return (
        {
            "uuid": uuid,
            "component_type": component_type,
            "location": [x, y],
            "orientation": orientation_quadrants * 90,
            "mirrored": bool(mirrored),
            "declared_parameter_count": declared_parameter_count,
            "parsed_parameter_count": len(parameters),
            "parameters": parameters,
            "context": context,
        },
        index,
    )


def parse_dfx_components(text: str) -> list[dict[str, Any]]:
    """Parse Draft components while preserving subsystem/hierarchy coordinate spaces."""
    lines = text.splitlines()
    components: list[dict[str, Any]] = []
    subsystem_index = -1
    hierarchy_stack: list[str | None] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line == "SUBSYSTEM-START:":
            subsystem_index += 1
            hierarchy_stack.clear()
            index += 1
            continue
        if line == "HIERARCHY-START:":
            hierarchy_stack.append(None)
            index += 1
            continue
        if line == "HIERARCHY-END:":
            if hierarchy_stack:
                hierarchy_stack.pop()
            index += 1
            continue
        if not line.startswith("COMPONENT_TYPE="):
            index += 1
            continue

        is_hierarchy = line.split("=", 1)[1].strip() == "HIERARCHY"
        context_parts = [f"subsystem:{max(subsystem_index, 0)}"]
        active_hierarchies = hierarchy_stack[:-1] if is_hierarchy and hierarchy_stack and hierarchy_stack[-1] is None else hierarchy_stack
        context_parts.extend(value for value in active_hierarchies if value)
        component, index = _parse_component(lines, index, "/".join(context_parts))
        components.append(component)
        if is_hierarchy and hierarchy_stack and hierarchy_stack[-1] is None:
            raw_name = component["parameters"].get("Name", "box").rstrip("#") or "box"
            hierarchy_stack[-1] = f"{raw_name}:{component['uuid']}"
    return components


class DefinitionIndex:
    def __init__(self, root: Path):
        self.root = root
        self.by_name: dict[str, list[Path]] = defaultdict(list)
        for path in root.rglob("*"):
            if path.is_file():
                self.by_name[path.name].append(path)

    def resolve(self, component_type: str) -> tuple[Path | None, str | None]:
        candidates = self.by_name.get(component_type, [])
        if len(candidates) == 1:
            if not candidates[0].resolve().is_relative_to(self.root.resolve()):
                return None, "definition_outside_configured_root"
            return candidates[0], None
        if not candidates:
            return None, "definition_not_found"
        return None, "definition_ambiguous:" + "|".join(str(path) for path in candidates)


def _section_lines(text: str, section: str) -> list[str]:
    lines = text.splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line.strip() == f"{section}:") + 1
    except StopIteration:
        return []
    result: list[str] = []
    for line in lines[start:]:
        if line and not line[0].isspace() and SECTION_RE.match(line):
            break
        result.append(line)
    return result


def parse_parameter_schema(text: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for line in _section_lines(text, "PARAMETERS"):
        stripped = line.strip()
        if not stripped or stripped.startswith("SECTION:") or stripped.startswith("//"):
            continue
        try:
            tokens = shlex.split(stripped, posix=True)
        except ValueError:
            continue
        # Parameter names/descriptions can themselves be words such as Name or
        # COLOR, so datatype detection begins after name, description, and unit.
        type_index = next((i for i, token in enumerate(tokens[3:], start=3) if token.upper() in TYPE_NAMES), None)
        if type_index is None:
            continue
        name = tokens[0]
        datatype = tokens[type_index].upper()
        option_or_unit = tokens[2] if len(tokens) > 2 else ""
        tail = tokens[type_index + 1 :]
        default = tail[0] if tail else None
        numeric_tail: list[float] = []
        for value in tail[1:3]:
            try:
                numeric_tail.append(float(value))
            except (TypeError, ValueError):
                break
        result[name] = {
            "parameter": name,
            "description": tokens[1] if len(tokens) > 1 else "",
            "unit": "" if datatype == "TOGGLE" else option_or_unit.strip(),
            "data_type": datatype,
            "default": default,
            "minimum": numeric_tail[0] if numeric_tail else None,
            "maximum": numeric_tail[1] if len(numeric_tail) > 1 else None,
            "enum_values": option_or_unit.split(";") if datatype == "TOGGLE" else None,
            "raw": stripped,
        }
    return result


def parameter_value(name: str, actual: dict[str, str], schema: dict[str, dict[str, Any]]) -> Any:
    raw = actual.get(name)
    if raw is None:
        entry = schema.get(name)
        raw = entry.get("default") if entry else None
    if raw is None:
        raise KeyError(name)
    entry = schema.get(name)
    if entry and entry.get("data_type") == "TOGGLE":
        values = entry.get("enum_values") or []
        for index, value in enumerate(values):
            if str(raw).casefold() == str(value).casefold():
                return index
    aliases = {"no": 0, "false": 0, "off": 0, "yes": 1, "true": 1, "on": 1}
    if str(raw).casefold() in aliases:
        return aliases[str(raw).casefold()]
    try:
        number = float(str(raw))
        return int(number) if number.is_integer() else number
    except ValueError:
        return raw


class ExpressionError(ValueError):
    pass


def _normalise_expression(expression: str) -> str:
    expression = expression.strip()
    expression = expression.replace("&&", " and ").replace("||", " or ")
    expression = re.sub(r"(?<!\|)\|(?!\|)", " or ", expression)
    expression = re.sub(r"(?<!&)\&(?!&)", " and ", expression)
    expression = re.sub(r"!(?!=)", " not ", expression)
    expression = re.sub(r"(?<![<>=!])=(?!=)", "==", expression)
    expression = expression.replace("getBoxParentType()", "parent_type")
    return expression.strip()


def _eval_ast(node: ast.AST, env: dict[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_ast(node.body, env)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise ExpressionError(f"unknown identifier {node.id}")
        return env[node.id]
    if isinstance(node, ast.BoolOp):
        values = (_eval_ast(value, env) for value in node.values)
        return all(values) if isinstance(node.op, ast.And) else any(values)
    if isinstance(node, ast.UnaryOp):
        value = _eval_ast(node.operand, env)
        if isinstance(node.op, ast.Not):
            return not value
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.UAdd):
            return +value
    if isinstance(node, ast.Compare):
        left = _eval_ast(node.left, env)
        for operator, comparator in zip(node.ops, node.comparators):
            right = _eval_ast(comparator, env)
            if isinstance(operator, ast.Eq):
                ok = left == right
            elif isinstance(operator, ast.NotEq):
                ok = left != right
            elif isinstance(operator, ast.Gt):
                ok = left > right
            elif isinstance(operator, ast.GtE):
                ok = left >= right
            elif isinstance(operator, ast.Lt):
                ok = left < right
            elif isinstance(operator, ast.LtE):
                ok = left <= right
            else:
                raise ExpressionError(f"unsupported comparison {type(operator).__name__}")
            if not ok:
                return False
            left = right
        return True
    if isinstance(node, ast.BinOp):
        left, right = _eval_ast(node.left, env), _eval_ast(node.right, env)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Mod):
            return left % right
    raise ExpressionError(f"unsupported expression node {type(node).__name__}")


def evaluate_condition(expression: str, env: dict[str, Any]) -> bool:
    try:
        tree = ast.parse(_normalise_expression(expression), mode="eval")
    except SyntaxError as error:
        raise ExpressionError(str(error)) from error
    return bool(_eval_ast(tree, env))


def _resolve_coordinate(token: str, actual: dict[str, str], schema: dict[str, dict[str, Any]]) -> float:
    token = token.strip().strip("()")
    from_parameter = token.startswith("$")
    if from_parameter:
        value = parameter_value(token[1:], actual, schema)
    else:
        try:
            value = float(token)
        except ValueError as error:
            raise ExpressionError(f"unsupported coordinate {token}") from error
    if not isinstance(value, (int, float)):
        raise ExpressionError(f"non-numeric coordinate {token}={value}")
    # Literal node coordinates are grid units. Position parameters in the shipped
    # definitions commonly store pixel offsets such as +/-32.
    if from_parameter and abs(value) >= GRID_SIZE and value % GRID_SIZE == 0:
        return float(value)
    return float(value) * GRID_SIZE


def _parent_type(component: dict[str, Any]) -> int:
    if component["context"].count("/") == 0:
        return 0
    return 1


def parse_active_nodes(
    definition_text: str,
    component: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    schema = parse_parameter_schema(definition_text)
    env: dict[str, Any] = {"parent_type": _parent_type(component)}
    for name in set(schema) | set(component["parameters"]):
        try:
            value = parameter_value(name, component["parameters"], schema)
            env[name] = value
            # Shipped definitions are not fully consistent about identifier case
            # (for example Type in PARAMETERS and TYPE in NODES).
            env.setdefault(name.lower(), value)
            env.setdefault(name.upper(), value)
        except KeyError:
            pass

    nodes: list[dict[str, Any]] = []
    warnings: list[str] = []
    stack: list[dict[str, Any]] = []
    active = True
    for raw_line in _section_lines(definition_text, "NODES"):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("INITIALIZE_NODE") or stripped.startswith("//"):
            continue
        directive = stripped.upper()
        if directive.startswith("#IF ") or directive.startswith("#IF("):
            expression = stripped[3:].strip()
            parent_active = active
            try:
                matched = evaluate_condition(expression, env) if parent_active else False
            except ExpressionError as error:
                warnings.append(f"condition_unresolved:{expression}:{error}")
                matched = False
            stack.append({"parent_active": parent_active, "branch_taken": matched})
            active = parent_active and matched
            continue
        if directive.startswith("#ELSEIF"):
            if not stack:
                warnings.append("orphan_elseif")
                continue
            expression = stripped[len("#ELSEIF") :].strip()
            frame = stack[-1]
            matched = False
            if frame["parent_active"] and not frame["branch_taken"]:
                try:
                    matched = evaluate_condition(expression, env)
                except ExpressionError as error:
                    warnings.append(f"condition_unresolved:{expression}:{error}")
            active = frame["parent_active"] and not frame["branch_taken"] and matched
            frame["branch_taken"] = frame["branch_taken"] or matched
            continue
        if directive == "#ELSE":
            if not stack:
                warnings.append("orphan_else")
                continue
            frame = stack[-1]
            active = frame["parent_active"] and not frame["branch_taken"]
            frame["branch_taken"] = True
            continue
        if directive in {"#END", "#ENDIF"}:
            if not stack:
                warnings.append("orphan_end")
                continue
            frame = stack.pop()
            active = frame["parent_active"]
            continue
        if stripped.startswith("#"):
            warnings.append(f"directive_unsupported:{stripped}")
            continue
        if not active:
            continue

        tokens = stripped.split()
        if len(tokens) < 3:
            continue
        name, x_token, y_token = tokens[:3]
        kind = tokens[3].upper() if len(tokens) > 3 and tokens[3].upper() in NODE_KINDS else "DEFAULT"
        try:
            local_x = _resolve_coordinate(x_token, component["parameters"], schema)
            local_y = _resolve_coordinate(y_token, component["parameters"], schema)
        except (ExpressionError, KeyError) as error:
            warnings.append(f"node_coordinate_unresolved:{name}:{error}")
            continue
        phase = None
        for token in tokens[3:]:
            if token.startswith("PHASE="):
                phase = token.split("=", 1)[1].replace("_PHASE", "")
        connected_name = None
        connected_mode = None
        for position, token in enumerate(tokens[3:], start=3):
            if token.startswith("NAME_CONNECTED") and position + 1 < len(tokens):
                connected_mode = token.split(":", 1)[1] if ":" in token else "NAMED"
                name_token = tokens[position + 1]
                if name_token.startswith("$"):
                    connected_name = component["parameters"].get(name_token[1:], name_token)
                else:
                    connected_name = name_token
                break
        data_type = None
        if kind in {"INPUT", "OUTPUT"} and len(tokens) > 4:
            data_type = tokens[4].upper()
        nodes.append(
            {
                "name": name,
                "local": [local_x, local_y],
                "kind": kind,
                "phase": phase,
                "direction": kind if kind in {"INPUT", "OUTPUT", "I/O"} else None,
                "data_type": data_type,
                "connected_name": connected_name.rstrip("#") if connected_name else None,
                "connected_mode": connected_mode,
                "link_by_name": component["component_type"] == "wirelabel" or connected_mode == "LINKED",
                "raw": stripped,
            }
        )
    if stack:
        warnings.append("unclosed_node_conditions")
    # Some definitions intentionally repeat a node with alternate name metadata.
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for node in nodes:
        key = (node["name"], *node["local"], node["kind"], node["phase"])
        unique.setdefault(key, node)
    return list(unique.values()), warnings


def rotate(point: tuple[float, float], degrees: int) -> tuple[int, int]:
    radians = math.radians(degrees)
    x, y = point
    return (
        round(x * math.cos(radians) - y * math.sin(radians)),
        round(x * math.sin(radians) + y * math.cos(radians)),
    )


def world(component: dict[str, Any], local: Iterable[float]) -> tuple[int, int]:
    local_x, local_y = local
    if component["mirrored"]:
        local_x = -local_x
    rotated_x, rotated_y = rotate((local_x, local_y), component["orientation"])
    return component["location"][0] + rotated_x, component["location"][1] + rotated_y


def point_on_segment(point: tuple[int, int], start: tuple[int, int], end: tuple[int, int]) -> bool:
    px, py = point
    x1, y1 = start
    x2, y2 = end
    cross = (px - x1) * (y2 - y1) - (py - y1) * (x2 - x1)
    if cross != 0:
        return False
    return min(x1, x2) <= px <= max(x1, x2) and min(y1, y2) <= py <= max(y1, y2)


def segments_touch(first: tuple[tuple[int, int], tuple[int, int]], second: tuple[tuple[int, int], tuple[int, int]]) -> bool:
    # Pure interior crossings remain separate. RSCAD junctions in the validated
    # examples have at least one segment endpoint on the other segment.
    return any(point_on_segment(point, *second) for point in first) or any(point_on_segment(point, *first) for point in second)


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, item: str) -> None:
        self.parent.setdefault(item, item)

    def find(self, item: str) -> str:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, first: str, second: str) -> None:
        self.add(first)
        self.add(second)
        root_first, root_second = self.find(first), self.find(second)
        if root_first != root_second:
            self.parent[root_second] = root_first


def _domain_for_node(node: dict[str, Any]) -> str:
    return f"bus3:{node['phase']}" if node.get("phase") in {"A", "B", "C"} else "wire1"


@dataclass
class TopologyResult:
    document: dict[str, Any]

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_rtfx_topology(rtfx_path: Path, definition_root: Path) -> TopologyResult:
    rtfx_path = rtfx_path.resolve()
    member, dfx_text, dfx_sha = read_rtfx_dfx(rtfx_path)
    components = parse_dfx_components(dfx_text)
    definitions = DefinitionIndex(definition_root)
    definition_cache: dict[Path, str] = {}
    definition_evidence: dict[str, dict[str, Any]] = {}
    ports: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    warnings: list[str] = []
    definition_resolved = 0

    for component in components:
        component_type = component["component_type"]
        definition_path, resolution_error = definitions.resolve(component_type)
        if resolution_error:
            warnings.append(f"component:{component['uuid']}:{component_type}:{resolution_error}")
            continue
        assert definition_path is not None
        definition_resolved += 1
        text = definition_cache.setdefault(definition_path, definition_path.read_text(encoding="utf-8", errors="replace"))
        definition_evidence.setdefault(
            component_type,
            {"path": str(definition_path), "sha256": sha256_file(definition_path)},
        )
        nodes, node_warnings = parse_active_nodes(text, component)
        warnings.extend(f"component:{component['uuid']}:{component_type}:{warning}" for warning in node_warnings)

        if component_type in {"BUS", "WIRE"}:
            parameters = component["parameters"]
            try:
                start = world(component, (float(parameters["x1"]), float(parameters["y1"])))
                end = world(component, (float(parameters["x2"]), float(parameters["y2"])))
            except (KeyError, ValueError) as error:
                warnings.append(f"component:{component['uuid']}:{component_type}:segment_unresolved:{error}")
                continue
            phases: list[str | None] = ["A", "B", "C"] if component_type == "BUS" else [None]
            for phase in phases:
                domain = f"bus3:{phase}" if phase else "wire1"
                segments.append(
                    {
                        "atom": f"segment:{component['context']}:{component['uuid']}:{phase or 'single'}",
                        "component_id": component["uuid"],
                        "component_type": component_type,
                        "context": component["context"],
                        "domain": domain,
                        "phase": phase,
                        "start": list(start),
                        "end": list(end),
                    }
                )
            continue

        for ordinal, node in enumerate(nodes):
            coordinate = world(component, node["local"])
            ports.append(
                {
                    "atom": f"port:{component['context']}:{component['uuid']}:{node['name']}:{ordinal}",
                    "component_id": component["uuid"],
                    "component_type": component_type,
                    "context": component["context"],
                    "port": node["name"],
                    "coordinate": list(coordinate),
                    "domain": _domain_for_node(node),
                    "phase": node["phase"],
                    "kind": node["kind"],
                    "direction": node["direction"],
                    "data_type": node["data_type"],
                    "connected_name": node["connected_name"],
                    "connected_mode": node["connected_mode"],
                    "link_by_name": node["link_by_name"],
                }
            )

    union = UnionFind()
    atoms: dict[str, dict[str, Any]] = {}
    for item in [*segments, *ports]:
        union.add(item["atom"])
        atoms[item["atom"]] = item

    segment_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    port_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for segment in segments:
        segment_groups[(segment["context"], segment["domain"])].append(segment)
    for port in ports:
        port_groups[(port["context"], port["domain"])].append(port)

    for key, group in segment_groups.items():
        for index, first in enumerate(group):
            first_segment = (tuple(first["start"]), tuple(first["end"]))
            for second in group[index + 1 :]:
                second_segment = (tuple(second["start"]), tuple(second["end"]))
                if segments_touch(first_segment, second_segment):
                    union.union(first["atom"], second["atom"])
        for port in port_groups.get(key, []):
            point = tuple(port["coordinate"])
            for segment in group:
                if point_on_segment(point, tuple(segment["start"]), tuple(segment["end"])):
                    union.union(port["atom"], segment["atom"])

    for key, group in port_groups.items():
        by_coordinate: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
        by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for port in group:
            by_coordinate[tuple(port["coordinate"])].append(port)
            if port["connected_name"] and port["link_by_name"]:
                by_name[port["connected_name"]].append(port)
        for matches in [*by_coordinate.values(), *by_name.values()]:
            for item in matches[1:]:
                union.union(matches[0]["atom"], item["atom"])

    # Shipped hierarchy examples pass control signals through matching wire
    # labels on an ancestor canvas and its child canvas. Link only ancestor-child
    # pairs; identical labels in unrelated sibling boxes remain separate.
    hierarchy_links: list[dict[str, Any]] = []
    named_across_contexts: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for port in ports:
        if port["connected_name"] and port["link_by_name"]:
            subsystem = port["context"].split("/", 1)[0]
            named_across_contexts[(subsystem, port["domain"], port["connected_name"])].append(port)
    for (subsystem, domain, name), group in named_across_contexts.items():
        for index, first in enumerate(group):
            for second in group[index + 1 :]:
                first_context, second_context = first["context"], second["context"]
                ancestor_child = (
                    first_context.startswith(second_context + "/")
                    or second_context.startswith(first_context + "/")
                )
                if ancestor_child:
                    union.union(first["atom"], second["atom"])
                    hierarchy_links.append(
                        {
                            "subsystem": subsystem,
                            "domain": domain,
                            "name": name,
                            "first_atom": first["atom"],
                            "second_atom": second["atom"],
                            "contexts": sorted({first_context, second_context}),
                            "evidence": "matching link-enabled wire labels in ancestor/child contexts",
                        }
                    )

    net_atoms: dict[str, list[str]] = defaultdict(list)
    for atom in atoms:
        net_atoms[union.find(atom)].append(atom)
    nets: list[dict[str, Any]] = []
    connected_port_count = 0
    for number, members in enumerate(sorted(net_atoms.values(), key=lambda values: sorted(values)[0]), start=1):
        member_items = [atoms[atom] for atom in members]
        contexts = sorted({item["context"] for item in member_items})
        port_count = sum(atom.startswith("port:") for atom in members)
        segment_count = sum(atom.startswith("segment:") for atom in members)
        if port_count > 1 or segment_count:
            connected_port_count += port_count
        first = member_items[0]
        nets.append(
            {
                "net_id": f"net_{number:04d}",
                "context": contexts[0] if len(contexts) == 1 else contexts[0].split("/", 1)[0],
                "contexts": contexts,
                "cross_context": len(contexts) > 1,
                "domain": first["domain"],
                "port_count": port_count,
                "segment_count": segment_count,
                "members": member_items,
            }
        )

    result = {
        "schema_version": "0.1",
        "status": "parsed_with_declared_limitations",
        "mutations_performed": False,
        "source": {
            "rtfx_path": str(rtfx_path),
            "rtfx_sha256": sha256_file(rtfx_path),
            "dfx_member": member,
            "dfx_sha256": dfx_sha,
            "settings": parse_project_settings(dfx_text),
        },
        "coverage": {
            "component_count": len(components),
            "definition_resolved_count": definition_resolved,
            "definition_coverage": round(definition_resolved / len(components), 6) if components else 1.0,
            "port_count": len(ports),
            "connected_port_count": connected_port_count,
            "segment_count": len(segments),
            "net_count": len(nets),
            "warning_count": len(warnings),
            "hierarchy_link_count": len(hierarchy_links),
        },
        "components": components,
        "ports": ports,
        "segments": segments,
        "nets": nets,
        "hierarchy_links": hierarchy_links,
        "definition_evidence": definition_evidence,
        "warnings": warnings,
        "limitations": [
            "Matching link-enabled wire labels are joined across ancestor/child hierarchy contexts; other implicit hierarchy boundary mechanisms are not yet linked.",
            "Mirror is interpreted as local x-axis reflection before rotation and requires broader corpus validation.",
            "Pure interior wire crossings are treated as unconnected unless an endpoint lies on the other segment.",
            "Component definition expressions outside the supported boolean/comparison/arithmetic subset are reported and skipped.",
            "No compile, load flow, simulation, project write, or hardware operation is performed.",
        ],
    }
    return TopologyResult(result)


__all__ = [
    "DefinitionIndex",
    "TopologyResult",
    "evaluate_condition",
    "parse_active_nodes",
    "parse_dfx_components",
    "parse_parameter_schema",
    "parse_rtfx_topology",
    "read_rtfx_dfx",
]
