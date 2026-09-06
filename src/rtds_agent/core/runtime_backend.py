"""Fail-closed Runtime signal-capture contract and RSCAD FX driver.

This module deliberately exposes no command-line entry point.  A caller must
pass the driver to ``ProductionRscadBackend`` and enable Runtime explicitly;
the approval-gated orchestrator remains the authority that consumes the
single-use L4 approval.
"""

from __future__ import annotations

import csv
import math
import os
import re
import sys
import time
import traceback
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any, Mapping
from .runtime_binding import bind_live_control
from .state_machine import sha256_file
from .native_acquisition import MODE as NATIVE_MODE, NativeAcquisition, native_channels, discover_saved_signals


class RuntimeContractError(RuntimeError):
    """Raised before a live call when a Runtime plan is outside the contract."""


def _normalized(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _latest_numeric(value: Any) -> float:
    """Return the last finite numeric leaf from a nested meter value."""

    numbers: list[float] = []

    def visit(item: Any) -> None:
        if isinstance(item, bool):
            return
        if isinstance(item, (int, float)):
            number = float(item)
            if math.isfinite(number):
                numbers.append(number)
            return
        if isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    visit(value)
    if not numbers:
        raise RuntimeContractError(
            "Runtime meter returned no finite numeric current value"
        )
    return numbers[-1]


def runtime_meter_ids(working_copy: str | Path) -> dict[str, int]:
    """Return exact signal-path to Runtime meter UUID mappings from an RTFX."""

    target = Path(working_copy).resolve()
    if not target.is_file() or target.suffix.lower() != ".rtfx":
        return {}
    with zipfile.ZipFile(target) as archive:
        rtx_names = [
            name for name in archive.namelist() if name.lower().endswith(".rtx")
        ]
        dfx_names = [
            name for name in archive.namelist() if name.lower().endswith(".dfx")
        ]
        if len(rtx_names) != 1:
            raise RuntimeContractError(
                "RTFX must contain exactly one Runtime layout"
            )
        text = archive.read(rtx_names[0]).decode("utf-8", errors="replace")
        dfx_text = (
            archive.read(dfx_names[0]).decode("utf-8", errors="replace")
            if len(dfx_names) == 1
            else ""
        )
    mappings: dict[str, int] = {}
    for match in re.finditer(
        r"^COMPONENT: TAGGED_V2\.2_METER\s*(.*?)^COMPONENT-END:\s*$",
        text,
        flags=re.MULTILINE | re.DOTALL,
    ):
        body = match.group(1)
        group = re.search(
            r"^\s*GROUP:\s*(.+?)\s*$", body, re.MULTILINE
        )
        desc = re.search(
            r"^\s*DESC:\s*(.+?)\s*$", body, re.MULTILINE
        )
        uuid_match = re.search(
            r"^\s*UUID:\s*(\d+)\s*$", body, re.MULTILINE
        )
        if group is None or desc is None or uuid_match is None:
            continue
        signal_path = f"{group.group(1).strip()}|{desc.group(1).strip()}"
        if signal_path in mappings:
            raise RuntimeContractError(
                f"duplicate Runtime meter path: {signal_path}"
            )
        mappings[signal_path] = int(uuid_match.group(1))

    lnrt_names: set[str] = set()
    for match in re.finditer(
        r"HIERARCHY-START:\s*COMPONENT_TYPE=HIERARCHY"
        r".*?PARAMETERS-START:(.*?)PARAMETERS-END:",
        dfx_text,
        flags=re.DOTALL,
    ):
        parameters = match.group(1)
        box_type = re.search(r"^\s*Type\s*:\s*(.+?)\s*$", parameters, re.MULTILINE)
        name = re.search(r"^\s*Name\s*:\s*(.+?)\s*$", parameters, re.MULTILINE)
        if (
            box_type is not None
            and box_type.group(1).strip().upper() == "LNRT"
            and name is not None
            and name.group(1).strip()
        ):
            lnrt_names.add(name.group(1).strip())

    # An LNRT hierarchy moves compiled signals below an extra path segment,
    # while an unchanged Runtime layout retains its original meter UUIDs.
    # Add aliases only when the target hierarchy is unambiguous.
    if len(lnrt_names) == 1:
        lnrt_name = next(iter(lnrt_names))
        aliases: dict[str, int] = {}
        for signal_path, meter_id in mappings.items():
            subsystem = re.match(r"^(Subsystem #\d+)\|(.*)$", signal_path)
            if subsystem is None:
                continue
            alias = (
                f"{subsystem.group(1)}|LNRT|{lnrt_name}|{subsystem.group(2)}"
            )
            if alias in mappings or alias in aliases:
                raise RuntimeContractError(
                    f"duplicate LNRT Runtime meter alias: {alias}"
                )
            aliases[alias] = meter_id
        mappings.update(aliases)
    return mappings


def runtime_single_curve_plot_ids(working_copy: str | Path) -> dict[str, int]:
    """Return exact signal-path to single-curve Runtime plot UUID mappings."""

    target = Path(working_copy).resolve()
    if not target.is_file() or target.suffix.lower() != ".rtfx":
        return {}
    with zipfile.ZipFile(target) as archive:
        rtx_names = [name for name in archive.namelist() if name.lower().endswith(".rtx")]
        if len(rtx_names) != 1:
            raise RuntimeContractError("RTFX must contain exactly one Runtime layout")
        text = archive.read(rtx_names[0]).decode("utf-8", errors="replace")
    mappings: dict[str, int] = {}
    for match in re.finditer(
        r"^COMPONENT: TAGGED_V2\.2_PLOT\s*(.*?)^COMPONENT-END:\s*$",
        text,
        flags=re.MULTILINE | re.DOTALL,
    ):
        body = match.group(1)
        uuid_match = re.search(r"^\s*UUID:\s*(\d+)\s*$", body, re.MULTILINE)
        pairs = {
            (group.strip(), desc.strip())
            for group, desc in re.findall(
                r"^\s*GROUP:\s*(.+?)\s*$\r?\n^\s*DESC:\s*(.+?)\s*$",
                body,
                flags=re.MULTILINE,
            )
        }
        if uuid_match is None or len(pairs) != 1:
            continue
        group, desc = next(iter(pairs))
        signal_path = f"{group}|{desc}"
        plot_id = int(uuid_match.group(1))
        if signal_path in mappings and mappings[signal_path] != plot_id:
            raise RuntimeContractError(f"duplicate Runtime plot path: {signal_path}")
        mappings[signal_path] = plot_id
    return mappings


def _read_single_curve_plot_csv(path: str | Path) -> tuple[list[float], list[float]]:
    """Read finite time/value pairs from one RSCAD single-curve CSV export."""

    target = Path(path).resolve()
    if not target.is_file():
        raise RuntimeContractError("Runtime plot CSV export was not created")
    times: list[float] = []
    values: list[float] = []
    with target.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.reader(handle):
            numbers: list[float] = []
            for cell in row:
                try:
                    number = float(cell.strip())
                except (TypeError, ValueError):
                    continue
                if math.isfinite(number):
                    numbers.append(number)
            if len(numbers) < 2:
                continue
            times.append(numbers[0])
            values.append(numbers[-1])
    if not values or any(right <= left for left, right in zip(times, times[1:])):
        raise RuntimeContractError(
            "Runtime plot CSV contains no strictly increasing finite samples"
        )
    return times, values



RUNTIME_INPUT_TYPES = {
    "switch": ("SWITCH", "position"),
    "slider": ("SLIDER", "value"),
    "dial": ("DIAL", "position"),
    "binary_switch": ("BINARY_SWITCH", "value"),
    "button": ("BUTTON", "position"),
    "draft_variable": ("DRAFT_VARIABLE", "position"),
}
RUNTIME_WRITE_PURPOSES = {
    "switch_operation",
    "slider_change",
    "dial_change",
    "runtime_parameter_write",
    "lockfree_change",
}


def _finite_control_number(value: Any, label: str) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeContractError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise RuntimeContractError(f"{label} must be finite")
    return int(value) if isinstance(value, int) else number


def _same_control_value(left: Any, right: Any) -> bool:
    try:
        return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-9)
    except (TypeError, ValueError):
        return False


def _canonical_runtime_parameter_writes(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 64:
        raise RuntimeContractError(
            "runtime_parameter_writes must be an array with at most 64 actions"
        )
    output: list[dict[str, Any]] = []
    action_ids: set[str] = set()
    last_target_values: dict[tuple[int, str], int | float] = {}
    last_apply = 0.0
    seen_after_run = False
    required = {
        "action_id",
        "purpose",
        "object_uuid",
        "object_type",
        "object_name",
        "object_group",
        "object_desc",
        "object_subpage",
        "attribute",
        "expected_initial_value",
        "value",
        "apply_after_seconds",
        "restore_after_capture",
    }
    for index, item in enumerate(value):
        if not isinstance(item, Mapping) or set(item) not in (
            required,
            required | {"phase"},
        ):
            raise RuntimeContractError(
                f"runtime_parameter_writes[{index}] fields must exactly match the contract"
            )
        action_id = str(item["action_id"]).strip()
        purpose = str(item["purpose"]).strip()
        object_type = str(item["object_type"]).strip()
        attribute = str(item["attribute"]).strip()
        object_name = str(item["object_name"]).strip()
        object_group = str(item["object_group"]).strip()
        object_desc = str(item["object_desc"]).strip()
        object_subpage = item["object_subpage"]
        if not isinstance(object_subpage,str) or not object_subpage.strip() or len(object_subpage)>256:
            raise RuntimeContractError("Runtime object_subpage must be an exact non-empty live page name")
        phase = str(item.get("phase", "after_run")).strip()
        if not action_id or action_id in action_ids:
            raise RuntimeContractError("Runtime action_id must be non-empty and unique")
        if purpose not in RUNTIME_WRITE_PURPOSES:
            raise RuntimeContractError(f"unsupported Runtime write purpose: {purpose}")
        if object_type not in RUNTIME_INPUT_TYPES:
            raise RuntimeContractError(f"unsupported Runtime input type: {object_type}")
        if attribute != RUNTIME_INPUT_TYPES[object_type][1]:
            raise RuntimeContractError(
                f"{object_type} writes must use attribute {RUNTIME_INPUT_TYPES[object_type][1]}"
            )
        try:
            object_uuid = int(item["object_uuid"])
        except (TypeError, ValueError) as exc:
            raise RuntimeContractError("Runtime object_uuid must be an integer") from exc
        if object_uuid < 0 or not object_name or not object_group or not object_desc:
            raise RuntimeContractError("Runtime target identity is incomplete")
        target = (object_uuid, attribute)
        expected = _finite_control_number(
            item["expected_initial_value"], "expected_initial_value"
        )
        new_value = _finite_control_number(item["value"], "value")
        apply_after = float(
            _finite_control_number(item["apply_after_seconds"], "apply_after_seconds")
        )
        if phase not in {"before_run", "after_run"}:
            raise RuntimeContractError("Runtime action phase must be before_run or after_run")
        if phase == "before_run" and seen_after_run:
            raise RuntimeContractError("before_run actions must precede after_run actions")
        if phase == "before_run" and apply_after != 0.0:
            raise RuntimeContractError("before_run actions must use apply_after_seconds 0")
        if phase == "after_run" and (
            not 0.0 <= apply_after <= 30.0 or apply_after < last_apply
        ):
            raise RuntimeContractError(
                "Runtime action times must be nondecreasing between 0 and 30 seconds"
            )
        if item["restore_after_capture"] is not True:
            raise RuntimeContractError("Runtime writes must restore the original value")
        if attribute == "position":
            if not float(new_value).is_integer() or not float(expected).is_integer():
                raise RuntimeContractError("position values must be integers")
            if object_type in {"switch", "button"} and (
                int(new_value) not in {0, 1} or int(expected) not in {0, 1}
            ):
                raise RuntimeContractError("switch and button positions must be 0 or 1")
            if not 0 <= int(new_value) <= 1024:
                raise RuntimeContractError("positional Runtime value is out of bounds")
            expected = int(expected)
            new_value = int(new_value)
        elif abs(float(new_value)) > 1e12 or abs(float(expected)) > 1e12:
            raise RuntimeContractError("Runtime numeric value is out of bounds")
        previous_value = last_target_values.get(target)
        if previous_value is not None and not _same_control_value(
            expected, previous_value
        ):
            raise RuntimeContractError(
                "repeated Runtime target actions must form an expected-value chain"
            )
        if purpose == "lockfree_change":
            if (
                object_type != "switch"
                or object_name.casefold() != "lockfree"
                or object_desc.casefold() != "lockfree"
                or not re.search(
                    r"(^|\|)(machines|breakers)(\||$)",
                    object_group,
                    flags=re.IGNORECASE,
                )
            ):
                raise RuntimeContractError(
                    "LockFree changes require an exact machine/breaker LockFree switch"
                )
        output.append(
            {
                "action_id": action_id,
                "purpose": purpose,
                "object_uuid": object_uuid,
                "object_type": object_type,
                "object_name": object_name,
                "object_group": object_group,
                "object_desc": object_desc,
                "object_subpage": object_subpage,
                "attribute": attribute,
                "expected_initial_value": expected,
                "value": new_value,
                "apply_after_seconds": apply_after,
                "restore_after_capture": True,
                "phase": phase,
            }
        )
        action_ids.add(action_id)
        last_target_values[target] = new_value
        if phase == "after_run":
            seen_after_run = True
            last_apply = apply_after
    return output


def runtime_input_objects(working_copy: str | Path) -> dict[int, dict[str, Any]]:
    """Return exact writable Runtime input identities from one RTFX layout."""

    target = Path(working_copy).resolve()
    if not target.is_file() or target.suffix.lower() != ".rtfx":
        raise RuntimeContractError("Runtime input discovery requires an RTFX file")
    with zipfile.ZipFile(target) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".rtx")]
        if len(names) != 1:
            raise RuntimeContractError("RTFX must contain exactly one Runtime layout")
        if archive.getinfo(names[0]).file_size>16*1024*1024 or len(archive.namelist())!=len(set(archive.namelist())):
            raise RuntimeContractError("Runtime layout is too large or has duplicate members")
        text = archive.read(names[0]).decode("utf-8-sig")
    from .runtime_parser import parse_runtime_layout
    parsed = parse_runtime_layout(text)
    tag_to_type = {tag: name for name, (tag, _) in RUNTIME_INPUT_TYPES.items()}
    tag_to_type["PUSHBUTTON"] = "button"
    records = {}
    for row in parsed["records"]:
        if row["kind"] not in tag_to_type:
            continue
        refs = row["signal_references"]
        if row["identity_status"] != "stored_unique" or len(refs) != 1 or refs[0]["field_ambiguities"]:
            raise RuntimeContractError("Ambiguous saved Runtime input identity/reference")
        ref = refs[0]
        if not row["name"] or not ref["stored_signal_path"]:
            raise RuntimeContractError("Incomplete saved Runtime input identity")
        uid = row["component_id"]
        records[uid] = {"object_uuid":uid,"object_type":tag_to_type[row["kind"]],"object_name":row["name"],
                        "object_group":ref["group"],"object_desc":ref["description"]}
    return records

def validate_runtime_test_spec(
    test_spec: Mapping[str, Any],
    *,
    max_channels: int = 64,
    max_warmup_seconds: float = 30.0,
) -> dict[str, Any]:
    """Return the canonical bounded Runtime control/capture plan or reject it.

    The supported operation is optionally initializing an already-compiled
    case with the embedded load-flow solver, starting it, collecting numeric
    signal arrays, and stopping it.  The explicit empty action lists prevent a
    future caller from smuggling writes into a generic event or controls object.
    """

    execution_mode = test_spec.get("execution_mode")
    if execution_mode not in {
        "runtime_read_only_signal_capture",
        "runtime_control_and_signal_capture",
    }:
        raise RuntimeContractError("unsupported Runtime execution_mode")
    if test_spec.get("runtime_required") is not True:
        raise RuntimeContractError("Runtime plan must declare runtime_required=true")

    event = test_spec.get("event")
    if not isinstance(event, Mapping) or event.get("type") != "none":
        raise RuntimeContractError(
            "read-only Runtime capture requires event.type=none"
        )

    controls = test_spec.get("runtime_controls")
    required_empty = (
        "hardware_io_changes",
        "rack_configuration_changes",
        "deployment_actions",
    )
    if not isinstance(controls, Mapping):
        raise RuntimeContractError("runtime_controls object is required")
    if controls.get("read_only_signal_capture") is not True:
        raise RuntimeContractError(
            "runtime_controls.read_only_signal_capture must be true"
        )
    unknown_controls = sorted(
        set(controls) - {"read_only_signal_capture", "runtime_parameter_writes", *required_empty}
    )
    if unknown_controls:
        raise RuntimeContractError(
            f"unsupported Runtime control fields: {unknown_controls}"
        )
    for field in required_empty:
        if controls.get(field) != []:
            raise RuntimeContractError(f"{field} must be an explicit empty list")
    runtime_writes = _canonical_runtime_parameter_writes(
        controls.get("runtime_parameter_writes")
    )
    if execution_mode == "runtime_read_only_signal_capture" and runtime_writes:
        raise RuntimeContractError("read-only Runtime mode cannot contain writes")
    if execution_mode == "runtime_control_and_signal_capture" and not runtime_writes:
        raise RuntimeContractError("control Runtime mode requires at least one write")

    channels = test_spec.get("measurement_channels")
    if not isinstance(channels, list) or not channels:
        raise RuntimeContractError("at least one measurement channel is required")
    if len(channels) > max_channels:
        raise RuntimeContractError(
            f"measurement channel count exceeds limit {max_channels}"
        )
    canonical_channels: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for index, item in enumerate(channels):
        if not isinstance(item, Mapping):
            raise RuntimeContractError(
                f"measurement_channels[{index}] must be an object"
            )
        channel_id = str(item.get("channel_id", "")).strip()
        signal_path = str(item.get("signal_path", "")).strip()
        units = str(item.get("units", "")).strip()
        if not channel_id or not signal_path or not units:
            raise RuntimeContractError(
                f"measurement_channels[{index}] requires channel_id, signal_path, and units"
            )
        if channel_id in seen_ids:
            raise RuntimeContractError(f"duplicate channel_id: {channel_id}")
        if signal_path in seen_paths:
            raise RuntimeContractError(f"duplicate signal_path: {signal_path}")
        seen_ids.add(channel_id)
        seen_paths.add(signal_path)
        canonical_channels.append(
            {"channel_id": channel_id, "signal_path": signal_path, "units": units}
        )

    capture = test_spec.get("runtime_capture")
    if not isinstance(capture, Mapping):
        raise RuntimeContractError("runtime_capture object is required")
    unknown_capture = sorted(
        set(capture) - {"warmup_seconds", "minimum_samples_per_channel", "acquisition_mode"}
    )
    if unknown_capture:
        raise RuntimeContractError(
            f"unsupported runtime_capture fields: {unknown_capture}"
        )
    try:
        warmup = float(capture["warmup_seconds"])
        minimum_samples = int(capture["minimum_samples_per_channel"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeContractError(
            "runtime_capture requires numeric warmup_seconds and minimum_samples_per_channel"
        ) from exc
    if not math.isfinite(warmup) or not 0.0 <= warmup <= max_warmup_seconds:
        raise RuntimeContractError(
            f"warmup_seconds must be between 0 and {max_warmup_seconds}"
        )
    if minimum_samples < 1:
        raise RuntimeContractError("minimum_samples_per_channel must be positive")
    acquisition_mode=capture.get("acquisition_mode","legacy")
    if acquisition_mode not in {"legacy",NATIVE_MODE}:raise RuntimeContractError("Unsupported acquisition_mode")
    if acquisition_mode==NATIVE_MODE:
        try:
            canonical_channels=native_channels(channels)
            if type(capture["minimum_samples_per_channel"]) is not int or not 2<=minimum_samples<=100000:
                raise ValueError("Native acquisition requires 2–100000 minimum samples")
        except ValueError as exc:raise RuntimeContractError(str(exc)) from exc
    if runtime_writes and runtime_writes[-1]["apply_after_seconds"] > warmup:
        raise RuntimeContractError("Runtime action time exceeds warmup_seconds")

    loadflow = test_spec.get("loadflow_initialization", {"enabled": False})
    if not isinstance(loadflow, Mapping):
        raise RuntimeContractError("loadflow_initialization must be an object")
    unknown_loadflow = sorted(
        set(loadflow)
        - {
            "enabled",
            "timeout_seconds",
            "zero_impedance_threshold_pu",
            "flat_start",
            "method",
        }
    )
    if unknown_loadflow:
        raise RuntimeContractError(
            f"unsupported loadflow_initialization fields: {unknown_loadflow}"
        )
    enabled = loadflow.get("enabled")
    if not isinstance(enabled, bool):
        raise RuntimeContractError("loadflow_initialization.enabled must be boolean")
    if enabled:
        try:
            loadflow_timeout = int(loadflow["timeout_seconds"])
            zero_impedance_threshold = float(
                loadflow["zero_impedance_threshold_pu"]
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeContractError(
                "enabled loadflow_initialization requires numeric timeout_seconds "
                "and zero_impedance_threshold_pu"
            ) from exc
        flat_start = loadflow.get("flat_start")
        method = str(loadflow.get("method", "")).strip()
        if not 1 <= loadflow_timeout <= 120:
            raise RuntimeContractError(
                "loadflow timeout_seconds must be between 1 and 120"
            )
        if not math.isfinite(zero_impedance_threshold) or not (
            1e-9 <= zero_impedance_threshold <= 1e-3
        ):
            raise RuntimeContractError(
                "zero_impedance_threshold_pu must be between 1e-9 and 1e-3"
            )
        if not isinstance(flat_start, bool):
            raise RuntimeContractError("loadflow flat_start must be boolean")
        if method not in {"FAST_DECOUPLED", "NEWTON_RAPHSON", "GAUSSIAN"}:
            raise RuntimeContractError("unsupported loadflow solution method")
    else:
        if set(loadflow) != {"enabled"}:
            raise RuntimeContractError(
                "disabled loadflow_initialization may contain only enabled=false"
            )
        loadflow_timeout = 60
        zero_impedance_threshold = 1e-6
        flat_start = True
        method = "FAST_DECOUPLED"

    output = test_spec.get("output_requirements")
    if not isinstance(output, Mapping):
        raise RuntimeContractError("output_requirements object is required")
    if output.get("raw_numeric_data_required") is not True:
        raise RuntimeContractError("raw numeric Runtime data must be required")
    if output.get("screenshot_only_pass_fail_forbidden") is not True:
        raise RuntimeContractError("screenshot-only pass/fail must be forbidden")

    test_id = str(test_spec.get("test_id", "")).strip()
    if not test_id:
        raise RuntimeContractError("test_id is required")
    return {
        "test_id": test_id,
        "execution_mode": execution_mode,
        "runtime_required": True,
        "event": {"type": "none"},
        "runtime_controls": {
            "read_only_signal_capture": True,
            "runtime_parameter_writes": runtime_writes,
            **{field: [] for field in required_empty},
        },
        "runtime_capture": {
            "warmup_seconds": warmup,
            "minimum_samples_per_channel": minimum_samples,
            **({"acquisition_mode":NATIVE_MODE} if acquisition_mode==NATIVE_MODE else {}),
        },
        "loadflow_initialization": {
            "enabled": enabled,
            "timeout_seconds": loadflow_timeout,
            "zero_impedance_threshold_pu": zero_impedance_threshold,
            "flat_start": flat_start,
            "method": method,
        },
        "measurement_channels": canonical_channels,
        "output_requirements": {
            "raw_numeric_data_required": True,
            "screenshot_only_pass_fail_forbidden": True,
        },
    }


def validate_samples(
    samples: Mapping[str, Any],
    channels: list[dict[str, str]],
    *,
    minimum_samples: int,
    max_samples_per_channel: int,
) -> dict[str, dict[str, Any]]:
    """Validate numeric driver output and return canonical sample arrays."""

    if set(samples) != {item["channel_id"] for item in channels}:
        raise RuntimeContractError(
            "driver sample channels do not exactly match the approved plan"
        )
    canonical: dict[str, dict[str, Any]] = {}
    for channel in channels:
        channel_id = channel["channel_id"]
        item = samples[channel_id]
        if not isinstance(item, Mapping):
            raise RuntimeContractError(f"samples[{channel_id}] must be an object")
        times = item.get("times")
        values = item.get("values")
        if not isinstance(times, list) or not isinstance(values, list):
            raise RuntimeContractError(
                f"samples[{channel_id}] requires times and values arrays"
            )
        if len(times) != len(values):
            raise RuntimeContractError(
                f"time/value length mismatch for {channel_id}"
            )
        if not minimum_samples <= len(values) <= max_samples_per_channel:
            raise RuntimeContractError(
                f"sample count for {channel_id} is outside approved bounds"
            )
        numeric_times = [float(value) for value in times]
        numeric_values = [float(value) for value in values]
        if not all(math.isfinite(value) for value in numeric_times + numeric_values):
            raise RuntimeContractError(
                f"non-finite Runtime data returned for {channel_id}"
            )
        if any(
            current <= previous
            for previous, current in zip(numeric_times, numeric_times[1:])
        ):
            raise RuntimeContractError(
                f"time axis is not strictly increasing for {channel_id}"
            )
        canonical[channel_id] = {
            "times": numeric_times,
            "values": numeric_values,
            "signal_path": channel["signal_path"],
            "units": channel["units"],
        }
    return canonical


def write_raw_signal_csv(
    path: Path,
    samples: Mapping[str, Mapping[str, Any]],
    channels: list[dict[str, str]],
) -> int:
    """Write an append-free, long-form numeric Runtime evidence file."""

    if path.exists():
        raise RuntimeContractError("Runtime raw output already exists")
    rows = 0
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["channel_id", "signal_path", "units", "sample_index", "time_s", "value"]
        )
        for channel in channels:
            channel_id = channel["channel_id"]
            item = samples[channel_id]
            for index, (timestamp, value) in enumerate(
                zip(item["times"], item["values"])
            ):
                writer.writerow(
                    [
                        channel_id,
                        channel["signal_path"],
                        channel["units"],
                        index,
                        repr(timestamp),
                        repr(value),
                    ]
                )
                rows += 1
    return rows


class RscadFxRuntimeDriver:
    """Thin live driver for start/capture/stop with mandatory cleanup.

    Constructing this class does not connect to RSCAD.  It is never installed
    by default in the production backend and it has no CLI entry point.
    """

    def __init__(self, config: Any, *, sleeper: Any = time.sleep) -> None:
        self.config = config
        self.sleeper = sleeper
        self.plot_update_wait_seconds = 5.0

    def _new_connection(self) -> Any:
        sys.path.insert(0, str(self.config.rtds_site_packages))
        import rtds.comms.connection_setup as connection_setup
        import rtds.rscadfx

        connection_setup.executable = self.config.rscad_executable
        connection_setup.in_existing = True
        connection_setup.timeout = self.config.connection_timeout_seconds
        return rtds.rscadfx.remote_connection()

    def capture_case(
        self,
        *,
        working_copy: str,
        rack: int,
        channels: list[dict[str, str]],
        warmup_seconds: float,
        loadflow_initialization: Mapping[str, Any] | None = None,
        runtime_parameter_writes: list[dict[str, Any]] | None = None,
        capture_directory: str | None = None,
        native_capture: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "connected": False,
            "version": None,
            "available_racks": [],
            "opened_file": None,
            "starting_rack": None,
            "run_state_before": None,
            "execution": {
                "run_call_attempted": False,
                "run_started": False,
                "run_return_value": None,
                "run_state_after_start": None,
                "loadflow_call_attempted": False,
                "loadflow_succeeded": False,
                "loadflow_return_value": None,
                "loadflow_parameters": None,
                "warmup_seconds": warmup_seconds,
                "update_plots_called": False,
                "plot_update_wait_seconds": self.plot_update_wait_seconds,
                "plot_csv_export_called": False,
                "plot_csv_exports": 0,
                "raw_data_collected": False,
                "stop_call_attempted": False,
                "stop_succeeded": False,
                "run_state_after_stop": None,
            },
            "cleanup": {
                "case_close_attempted": False,
                "case_closed": False,
                "disconnect_terminate": False,
                "disconnected": False,
            },
            "safety": {
                "compile_called": False,
                "load_flow_called": False,
                "runtime_parameter_write_called": False,
                "case_settings_write_called": False,
                "rack_power_change_called": False,
                "rack_security_change_called": False,
                "rack_configuration_changed": False,
                "deployment_called": False,
                "hardware_io_called": False,
                "case_save_called": False,
                "source_write_called": False,
            },
            "signals": {},
            "runtime_controls": {
                "planned": len(runtime_parameter_writes or []),
                "restore_targets_planned": len(
                    {
                        (int(item["object_uuid"]), str(item["attribute"]))
                        for item in (runtime_parameter_writes or [])
                    }
                ),
                "applied": 0,
                "restored": 0,
                "all_readbacks_verified": False,
                "all_restored": False,
                "actions": [],
            },
            "samples": {},
            "errors": [],
            "cleanup_errors": [],
        }
        app = None
        case = None
        signal_handles: dict[str, Any] = {}
        meter_handles: dict[str, Any] = {}
        plot_handles: dict[str, Any] = {}
        original_control_values: dict[tuple[int, str], Any] = {}
        acquisition = None
        writes = list(runtime_parameter_writes or [])
        try:
            writes = _canonical_runtime_parameter_writes(writes)
            binding_sha256 = sha256_file(Path(working_copy)) if writes else None
            input_records = runtime_input_objects(working_copy) if writes else {}
            if native_capture is not None:
                channels=native_channels(channels)
                if set(native_capture)!={'context','minimum_samples','maximum_samples'} or type(native_capture['minimum_samples']) is not int or type(native_capture['maximum_samples']) is not int or not 2<=native_capture['minimum_samples']<=native_capture['maximum_samples']<=100000:
                    raise RuntimeContractError('Invalid native acquisition limits')
                if set(native_capture['context'])!={'run_id','attempt_id','input_project_sha256'} or not all(isinstance(v,str) and v for v in native_capture['context'].values()):
                    raise RuntimeContractError('Invalid native acquisition context')
                if native_capture['context']['input_project_sha256']!=sha256_file(Path(working_copy)):
                    raise RuntimeContractError('Native capture input hash mismatch')
                discover_saved_signals(working_copy,channels)
            app = self._new_connection()
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                app.connect()
            result["connected"] = True
            result["version"] = str(app.get_version())
            if result["version"] != self.config.expected_rscad_version:
                raise RuntimeContractError(
                    f"unexpected RSCAD FX version: {result['version']}"
                )
            result["available_racks"] = sorted(
                int(item.num) for item in app.get_available_racks()
            )
            if int(rack) not in result["available_racks"]:
                raise RuntimeContractError(
                    f"selected rack {rack} is no longer available"
                )
            existing = app.get_case(file=str(working_copy), open_file=False)
            if existing is not None:
                raise RuntimeContractError(
                    "working copy is already open; refusing to reuse it"
                )
            case = app.open_case(str(working_copy))
            result["opened_file"] = str(case.file)
            if _normalized(case.file) != _normalized(working_copy):
                raise RuntimeContractError(
                    f"RSCAD opened unexpected file: {case.file}"
                )
            result["starting_rack"] = int(case.settings.starting_rack)
            if result["starting_rack"] != int(rack):
                raise RuntimeContractError(
                    "case starting rack does not match compiled rack"
                )
            result["run_state_before"] = str(case.state.run_state)
            if result["run_state_before"].lower() != "stopped":
                raise RuntimeContractError(
                    f"case must be stopped before Runtime start: {result['run_state_before']}"
                )
            loadflow = dict(loadflow_initialization or {"enabled": False})
            execution = result["execution"]
            if native_capture is not None:
                acquisition=NativeAcquisition(case,working_copy,channels,native_capture['context'],
                    minimum_samples=native_capture['minimum_samples'],maximum_samples=native_capture['maximum_samples'])
                result['acquisition']=acquisition.evidence
                acquisition.bind()
            if loadflow.get("enabled") is True:
                parameters = {
                    "timeout_seconds": int(loadflow["timeout_seconds"]),
                    "zero_impedance_threshold_pu": float(
                        loadflow["zero_impedance_threshold_pu"]
                    ),
                    "flat_start": bool(loadflow["flat_start"]),
                    "method": str(loadflow["method"]),
                }
                execution["loadflow_call_attempted"] = True
                execution["loadflow_parameters"] = parameters
                result["safety"]["load_flow_called"] = True
                loadflow_value = case.run_loadflow(
                    parameters["timeout_seconds"],
                    parameters["zero_impedance_threshold_pu"],
                    parameters["flat_start"],
                    parameters["method"],
                )
                execution["loadflow_return_value"] = repr(loadflow_value)
                execution["loadflow_succeeded"] = True
            meter_ids = {} if acquisition else runtime_meter_ids(working_copy)
            plot_ids = {} if acquisition else runtime_single_curve_plot_ids(working_copy)
            for channel in ([] if acquisition else channels):
                channel_id = channel["channel_id"]
                signal_handles[channel_id] = case.get_signal(
                    channel["signal_path"]
                )
                meter_id = meter_ids.get(channel["signal_path"])
                if meter_id is not None:
                    meter_handles[channel_id] = case.runtime.get_object(
                        meter_id
                    )
                plot_id = plot_ids.get(channel["signal_path"])
                if plot_id is not None:
                    plot_handles[channel_id] = case.runtime.get_object(plot_id)
                result["signals"][channel_id] = {
                    "signal_path": channel["signal_path"],
                    "units": channel["units"],
                    "lookup_succeeded": True,
                    "meter_uuid": meter_id,
                    "plot_uuid": plot_id,
                }

            if writes:
                for action in writes:
                    record = input_records.get(action["object_uuid"])
                    expected_identity = {
                        key: action[key]
                        for key in (
                            "object_uuid",
                            "object_type",
                            "object_name",
                            "object_group",
                            "object_desc",
                        )
                    }
                    if record != expected_identity:
                        raise RuntimeContractError(
                            f"Runtime input identity mismatch: {action['action_id']}"
                        )
                    handle, binding = bind_live_control(case,working_copy,binding_sha256,action)
                    result["runtime_controls"].setdefault("bindings",[]).append(binding)

            def apply_action(action: dict[str, Any]) -> None:
                handle, binding = bind_live_control(case,working_copy,binding_sha256,action)
                attribute = action["attribute"]
                before = getattr(handle, attribute)
                if not _same_control_value(
                    before, action["expected_initial_value"]
                ):
                    raise RuntimeContractError(
                        f"Runtime initial value mismatch: {action['action_id']}"
                    )
                binding["value_verified"] = True
                result["runtime_controls"].setdefault("write_bindings",[]).append(binding)
                original_control_values.setdefault(
                    (action["object_uuid"], attribute), before
                )
                result["safety"]["runtime_parameter_write_called"] = True
                setattr(handle, attribute, action["value"])
                readback = getattr(handle, attribute)
                if not _same_control_value(readback, action["value"]):
                    raise RuntimeContractError(
                        f"Runtime write readback mismatch: {action['action_id']}"
                    )
                result["runtime_controls"]["applied"] += 1
                result["runtime_controls"]["actions"].append(
                    {
                        **action,
                        "before": before,
                        "readback": readback,
                        "applied": True,
                        "restored": False,
                    }
                )
            for action in writes:
                if action["phase"] == "before_run":
                    apply_action(action)

            execution["run_call_attempted"] = True
            run_value = case.run()
            execution["run_return_value"] = repr(run_value)
            execution["run_state_after_start"] = str(case.state.run_state)
            execution["run_started"] = (
                execution["run_state_after_start"].lower() == "running"
            )
            if not execution["run_started"]:
                raise RuntimeError(
                    "case did not enter running state after case.run()"
                )
            elapsed = 0.0
            for action in writes:
                if action["phase"] != "after_run":
                    continue
                delay = action["apply_after_seconds"] - elapsed
                if delay:
                    self.sleeper(delay)
                elapsed = action["apply_after_seconds"]
                apply_action(action)
            remaining_warmup = warmup_seconds - elapsed
            if remaining_warmup or not writes:
                self.sleeper(remaining_warmup)
            result["runtime_controls"]["all_readbacks_verified"] = (
                result["runtime_controls"]["applied"] == len(writes)
            )
            if acquisition:acquisition.start()
            case.update_plots()
            execution["update_plots_called"] = True
            # update_plots() submits a request; the installed API does not
            # document synchronous completion.  LNRT plot transfer can lag
            # the request, so wait a bounded interval before reading arrays.
            self.sleeper(self.plot_update_wait_seconds)
            export_root: Path | None = None
            if acquisition:
                result['samples']=acquisition.read()
                result['signals']=acquisition.evidence['channels']
            for index, channel in enumerate([] if acquisition else channels):
                channel_id = channel["channel_id"]
                handle = signal_handles[channel_id]
                times = list(handle.get_time_data())
                values = list(handle.get_data())
                sample_source = "plot_signal_data"
                if not values and channel_id in plot_handles:
                    if capture_directory is None:
                        raise RuntimeContractError(
                            "Runtime plot CSV fallback requires capture_directory"
                        )
                    if export_root is None:
                        capture_root = Path(capture_directory).resolve()
                        capture_root.mkdir(parents=True, exist_ok=True)
                        export_root = capture_root / "plot_exports"
                        export_root.mkdir(exist_ok=False)
                    export_path = export_root / f"plot_{index:03d}.csv"
                    plot_handles[channel_id].save_data("CSV", str(export_path))
                    execution["plot_csv_export_called"] = True
                    execution["plot_csv_exports"] += 1
                    times, values = _read_single_curve_plot_csv(export_path)
                    sample_source = "runtime_plot_csv_export"
                if not values and channel_id in meter_handles:
                    meter = meter_handles[channel_id]
                    try:
                        meter_value = float(meter.value)
                        sample_source = "runtime_meter_value"
                    except Exception:
                        # The official API documents Meter.value as invalid for
                        # vector meters. Meter.current_values supports both
                        # scalar and vector meters; the remapped IEEE meters
                        # each bind one approved scalar signal.
                        meter_value = _latest_numeric(meter.current_values)
                        sample_source = "runtime_meter_current_values"
                    values = [meter_value]
                    times = [float(warmup_seconds)]
                result["samples"][channel_id] = {
                    "times": times,
                    "values": values,
                }
                result["signals"][channel_id]["sample_count"] = len(values)
                result["signals"][channel_id][
                    "sample_source"
                ] = sample_source
            execution["raw_data_collected"] = True
        except Exception as exc:
            result["errors"].append(
                {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
        finally:
            execution = result["execution"]
            if acquisition:
                acquisition.evidence['recovery']['stop_acquisition_dispatch']='unconfirmed'
                try:acquisition.stop()
                except Exception as exc:result['cleanup_errors'].append({'operation':'stop_acquisition_dispatch','type':type(exc).__name__,'message':str(exc)})
                acquisition.evidence['recovery_order'].append('restore_controls')
            if case is not None and original_control_values:
                for key, original_value in reversed(
                    list(original_control_values.items())
                ):
                    try:
                        object_uuid, attribute = key
                        identity = next(a for a in writes if a["object_uuid"]==object_uuid and a["attribute"]==attribute)
                        handle, _ = bind_live_control(case,working_copy,binding_sha256,identity)
                        setattr(handle, attribute, original_value)
                        restored = getattr(handle, attribute)
                        if not _same_control_value(restored, original_value):
                            raise RuntimeContractError(
                                f"Runtime restore readback mismatch: {object_uuid}:{attribute}"
                            )
                        for action_record in result["runtime_controls"]["actions"]:
                            if (
                                action_record["object_uuid"] == object_uuid
                                and action_record["attribute"] == attribute
                            ):
                                action_record["restored"] = True
                                action_record["restored_value"] = restored
                        result["runtime_controls"]["restored"] += 1
                    except Exception as exc:
                        result["cleanup_errors"].append(
                            {
                                "operation": f"restore_runtime_input:{key[0]}:{key[1]}",
                                "type": type(exc).__name__,
                                "message": str(exc),
                            }
                        )
                result["runtime_controls"]["all_restored"] = (
                    result["runtime_controls"]["restored"]
                    == len(original_control_values)
                )
            elif not writes:
                result["runtime_controls"]["all_readbacks_verified"] = True
                result["runtime_controls"]["all_restored"] = True
            if acquisition:
                acquisition.evidence['recovery']['restore_controls']='not_required' if not original_control_values else 'succeeded' if result['runtime_controls']['all_restored'] else 'unconfirmed'
                acquisition.evidence['recovery_order'].append('stop_runtime')
            if case is not None and execution["run_call_attempted"]:
                execution["stop_call_attempted"] = True
                try:
                    stop_value = case.stop()
                    execution["stop_return_value"] = repr(stop_value)
                    execution["run_state_after_stop"] = str(case.state.run_state)
                    execution["stop_succeeded"] = (
                        execution["run_state_after_stop"].lower() == "stopped"
                    )
                except Exception as exc:
                    result["cleanup_errors"].append(
                        {
                            "operation": "case.stop()",
                            "type": type(exc).__name__,
                            "message": str(exc),
                        }
                    )
            if acquisition:
                acquisition.evidence['recovery']['stop_runtime']='not_required' if not execution['run_call_attempted'] else 'succeeded' if execution['stop_succeeded'] else 'unconfirmed'
                acquisition.evidence['recovery']['close_owned_acquisition_handles']='unconfirmed'
                try:acquisition.close()
                except Exception as exc:result['cleanup_errors'].append({'operation':'close_owned_acquisition_handles','type':type(exc).__name__,'message':str(exc)})
            if case is not None:
                result["cleanup"]["case_close_attempted"] = True
                try:
                    case.close(force=True)
                    result["cleanup"]["case_closed"] = True
                except Exception as exc:
                    result["cleanup_errors"].append(
                        {
                            "operation": "case.close(force=True)",
                            "type": type(exc).__name__,
                            "message": str(exc),
                        }
                    )
            if result["connected"] and app is not None:
                try:
                    app.disconnect(terminate=False)
                    result["cleanup"]["disconnected"] = True
                except Exception as exc:
                    result["cleanup_errors"].append(
                        {
                            "operation": "disconnect(terminate=False)",
                            "type": type(exc).__name__,
                            "message": str(exc),
                        }
                    )
        return result
