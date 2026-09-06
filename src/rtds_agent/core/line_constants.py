"""Pure, narrow inspection of supplied scalar Bergeron line-constants bytes.

Numerical agreement is not evidence of generation, freshness, or native origin.
"""
from __future__ import annotations

from decimal import Decimal, DecimalException, localcontext
import hashlib
import math
import re

from .line_authoring import PROFILE_ID, inspect_line_input


MAX_BYTES = 65536
MAX_LINES = 1024
MAX_TOKEN_BYTES = 128
RELATIVE_TOLERANCE = Decimal("1e-12")
NUMERIC = re.compile(rb"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
TRANSFORM = (("0.5773503", "0.8164967", "0.0"),
             ("0.5773503", "-0.4082483", "0.7071068"),
             ("0.5773503", "-0.4082483", "-0.7071068"))
FLAGS = {"freshness_verified": False, "native_origin_verified": False,
         "generator_execution_verified": False, "companion_generated": False,
         "solver_called": False, "draft_created": False, "compile_called": False,
         "integration_qualified": False, "engineering_verdict": "not_evaluated",
         "execution_authorized": False, "automatic_retry": False, "source_written": False}
EVIDENCE = [
    {"source_id": "TLINEEDIT/tline_constants_manual.pdf",
     "source_sha256": "5a19071f514ec365d0401d1f0ed8e46b658590b56011fd125282d01970314cfc",
     "locator": "pages 9, 23-27: Bergeron header/modal fields, units and balanced three-phase mode order"},
    {"source_id": "BIN/rscad_fx.jar",
     "source_sha256": "f715cccd6f81e0cb028d55bebc80f4b73706d491cb3374eb43f6c3ccee23ba27",
     "locator": "v5applications/tlineedit/datamodel/TLRLCData.class: ohmic three-phase calculation, fixed transform and generateTLO",
     "member_sha256": "30a4be0e027a55948b2e5335db67c2b1c4cddbb56a375792f160f3a3b02174e2"},
]
LIMITATIONS = [
    "Only the supplied three-phase scalar metric ohmic Bergeron profile is inspected; comments are untrusted text, not native provenance.",
    "Sending/receiving IDs 1, 2, 3 and subsystem placeholders 1 are the narrow unbound output profile, not verified Draft connectivity.",
    "Numerical consistency cannot establish generation time, input/output freshness, generator execution, native origin or engineering suitability.",
    "Ground resistivity effects, arbitrary transformation matrices, geometry, cable, per-unit, six-phase and frequency-dependent profiles are not evaluated.",
    "No simulation time-step/travel-time acceptance rule or resistance correction to modal impedance is inferred.",
]


def _base(raw, profile_id):
    if not isinstance(raw, bytes):
        raise ValueError("Line output inspection requires supplied raw bytes")
    return {"schema_version": "1.0", "profile_id": profile_id, "status": "unsupported",
            "source_sha256": hashlib.sha256(raw).hexdigest(), "source_bytes": len(raw),
            "header": {}, "modes": [], "raw_lines": [], "reasons": [],
            "parser_coverage": "unsupported", "algorithm_evidence": [dict(x) for x in EVIDENCE],
            "limitations": list(LIMITATIONS), **FLAGS}


def _decimal(token):
    if len(token) > MAX_TOKEN_BYTES or not NUMERIC.fullmatch(token):
        raise ValueError("Unsupported or oversized numeric token")
    value = Decimal(token.decode("ascii"))
    if len(value.as_tuple().digits) > 64:
        raise ValueError("Numeric tokens exceed the supported 64 significant digit comparison bound")
    numeric = float(value)
    if not value.is_finite() or not math.isfinite(numeric) or (value != 0 and numeric == 0):
        raise ValueError("Non-finite or binary64-underflow numeric token")
    return value


def _field(match, line, offset, units):
    token = match.group()
    value = _decimal(token)
    return {"value": float(value), "raw_value": token.decode("ascii"), "units": units,
            "line": line, "byte_start": offset + match.start(), "byte_end": offset + match.end()}


def inspect_line_output(raw: bytes, profile_id: str = PROFILE_ID) -> dict:
    """Inspect an exact bounded three-mode supplied TLO subset without I/O."""
    result = _base(raw, profile_id)

    def unsupported(reason):
        result["reasons"].append(reason)
        return result

    if profile_id != PROFILE_ID:
        return unsupported("Unsupported line-constants profile")
    if len(raw) > MAX_BYTES:
        return unsupported("Line output exceeds 64 KiB")
    try:
        raw.decode("ascii")
    except UnicodeDecodeError:
        return unsupported("Only ASCII output is supported")
    if any(c < 32 and c not in (9, 10, 13) for c in raw) or 127 in raw:
        return unsupported("Unsupported control character in line output")
    lines = raw.splitlines(keepends=True)
    if len(lines) > MAX_LINES:
        return unsupported("Line output exceeds 1024 lines")
    data = []
    offset = 0
    for number, line in enumerate(lines, 1):
        body = line.rstrip(b"\r\n")
        text = body.strip()
        kind = "comment" if text.startswith(b"!") else "data" if text else "blank"
        result["raw_lines"].append({"line": number, "byte_start": offset,
                                    "byte_end": offset + len(body), "text": body.decode("ascii"), "kind": kind})
        if kind == "data":
            data.append((number, offset, body))
        offset += len(line)
    if len(data) != 4:
        return unsupported("Expected exactly one header and three modal data rows")
    try:
        number, offset, body = data[0]
        tokens = list(re.finditer(rb"\S+", body))
        if len(tokens) != 10 or tokens[-1].group() != b"/":
            raise ValueError("Header requires nine fields and a separate slash terminator")
        if [m.group() for m in tokens[:4]] != [b"3", b"0", b"1", b"1"]:
            raise ValueError("Unsupported conductor count, unused selector or subsystem placeholders")
        names = ("conductors", "unused_integer", "sending_subsystem", "receiving_subsystem",
                 "frequency_hz_1", "frequency_hz_2", "length_m", "unused_float_1", "unused_float_2")
        units = ("count", "unused", "unbound_id", "unbound_id", "Hz", "Hz", "m", "unused", "unused")
        header = {name: _field(token, number, offset, unit) for name, token, unit in zip(names, tokens, units)}
        for name in ("frequency_hz_1", "frequency_hz_2", "length_m"):
            if Decimal(header[name]["raw_value"]) <= 0:
                raise ValueError("Frequency and length must be positive for this narrow output profile")
        if any(Decimal(header[name]["raw_value"]) != Decimal("1e-9")
               for name in ("unused_float_1", "unused_float_2")):
            raise ValueError("Unsupported generated-header unused float constants")
        modes = []
        for mode_index, (number, offset, body) in enumerate(data[1:], 1):
            tokens = list(re.finditer(rb"\S+", body))
            if len(tokens) != 9:
                raise ValueError("Each three-phase modal row requires exactly nine fields")
            if [m.group() for m in tokens[:2]] != [str(mode_index).encode()] * 2:
                raise ValueError("Modal rows must retain ordered unbound node placeholders 1, 2, 3")
            names = ("sending_node", "receiving_node", "travel_time_ms", "impedance_ohm",
                     "resistance_ohm_per_m_1", "resistance_ohm_per_m_2")
            units = ("unbound_id", "unbound_id", "ms", "ohm", "ohm/m", "ohm/m")
            fields = {name: _field(token, number, offset, unit) for name, token, unit in zip(names, tokens, units)}
            for name in names[2:]:
                if Decimal(fields[name]["raw_value"]) <= 0:
                    raise ValueError("Modal time, impedance and resistance must be positive in this narrow profile")
            fields["transformation_row"] = [_field(token, number, offset, "dimensionless") for token in tokens[6:]]
            modes.append({"mode": mode_index, "sequence": ("zero", "positive", "negative")[mode_index - 1],
                          "fields": fields})
    except (ValueError, DecimalException, OverflowError) as exc:
        return unsupported(str(exc))
    result.update(status="supported", header=header, modes=modes, parser_coverage="complete_within_declared_subset")
    return result


def _check(name, observed, expected, relative_tolerance=Decimal(0)):
    actual = Decimal(observed["raw_value"])
    error = abs(actual - expected)
    tolerance = abs(expected) * relative_tolerance
    return {"check": name, "status": "passed" if error <= tolerance else "failed",
            "observed": dict(observed), "expected_decimal": str(expected),
            "absolute_error_decimal": str(error), "absolute_tolerance_decimal": str(tolerance),
            "relative_tolerance_decimal": str(relative_tolerance),
            "comparison": "exact_decimal" if relative_tolerance == 0 else "bounded_relative_numerical_agreement"}


def _positive_binary64(value):
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Scalar calculation exceeds the positive finite binary64 comparison domain")
    return value


def _header_conversion(source, converted):
    canonical = str(_positive_binary64(converted))
    return {"source_raw_value": str(source), "converted_decimal": canonical,
            "converted_value": converted, "binary64_exact_decimal": str(Decimal.from_float(converted)),
            "conversion_loss": Decimal.from_float(converted) != source,
            "canonical_decimal_changed": Decimal(canonical) != source,
            "conversion": "binary64_then_shortest_decimal; observed output is never rounded for comparison"}


def compare_line_constants(input_raw: bytes, output_raw: bytes, profile_id: str = PROFILE_ID) -> dict:
    """Compare supplied bytes to resolved scalar equations; never attest freshness."""
    input_report = inspect_line_input(input_raw, profile_id)
    output_report = inspect_line_output(output_raw, profile_id)
    result = {"schema_version": "1.0", "profile_id": profile_id, "status": "inconclusive",
              "input_sha256": input_report["source_sha256"], "output_sha256": output_report["source_sha256"],
              "input": input_report, "output": output_report, "checks": [], "header_conversions": {}, "reasons": [],
              "algorithm": "source_observed_scalar_bergeron_3phase_numerical_comparison_v1",
              "calculation_profile": {"length": "binary64(input_km) * 1000 -> m; comparison uses the canonical decimal of that binary64 result",
                                      "omega": "2 * binary64_pi * frequency_hz",
                                      "inductance_h": "(x_ohm_per_km / omega) * length_km",
                                      "capacitance_f": "1 / (omega * (xc_megohm_km * 1e6 / length_km))",
                                      "travel_time_ms": "sqrt(inductance_h * capacitance_f) / 0.001",
                                      "impedance_ohm": "sqrt(inductance_h / capacitance_f)",
                                      "resistance_ohm_per_m": "r_ohm_per_km * 0.001",
                                      "relative_tolerance": str(RELATIVE_TOLERANCE), "absolute_tolerance_floor": "0",
                                      "tolerance_basis": "agent_selected_binary64_roundoff_allowance_not_an_engineering_tolerance",
                                      "decimal_precision": 96, "native_algorithm_executed": False},
              "algorithm_evidence": [dict(x) for x in EVIDENCE], "limitations": list(LIMITATIONS),
              "assumptions": ["ideally_transposed", "frequency_independent_bergeron", "metric_ohmic_scalar_input"],
              "applicability_verified": False, **FLAGS}
    if input_report["status"] != "supported" or output_report["status"] != "supported":
        result["reasons"].append("Both supplied files must be supported; unsupported grammar is not numerical agreement")
        return result
    try:
        with localcontext() as context:
            context.prec = 96
            fields = {name: _decimal(row["raw_value"].encode("ascii")) for name, row in input_report["fields"].items()}
            header, modes = output_report["header"], output_report["modes"]
            native_length_m = _positive_binary64(float(fields["line_length_km"]) * 1000.0)
            native_frequency = _positive_binary64(float(fields["frequency_hz"]))
            conversions = {"frequency_hz": _header_conversion(fields["frequency_hz"], native_frequency),
                           "length_m": _header_conversion(fields["line_length_km"] * 1000, native_length_m)}
            conversions["frequency_hz"]["source_raw_value"] = input_report["fields"]["frequency_hz"]["raw_value"]
            conversions["length_m"]["source_raw_value"] = input_report["fields"]["line_length_km"]["raw_value"]
            conversions["length_m"]["source_units"] = "km"
            conversions["length_m"]["exact_metric_value_decimal"] = str(fields["line_length_km"] * 1000)
            result["header_conversions"] = conversions
            checks = [_check("frequency_hz_1", header["frequency_hz_1"], Decimal(conversions["frequency_hz"]["converted_decimal"])),
                      _check("frequency_hz_2", header["frequency_hz_2"], Decimal(conversions["frequency_hz"]["converted_decimal"])),
                      _check("length_m", header["length_m"], Decimal(conversions["length_m"]["converted_decimal"]))]
            angular_frequency = Decimal(2) * Decimal(str(math.pi)) * fields["frequency_hz"]
            native_length_km = _positive_binary64(native_length_m / 1000.0)
            native_omega = _positive_binary64((2.0 * math.pi) * native_frequency)
            for index, mode in enumerate(modes):
                sequence = "zero" if index == 0 else "positive"
                inductance = (fields[f"x_{sequence}_ohm_per_km"] / angular_frequency) * fields["line_length_km"]
                xc_total = fields[f"xc_{sequence}_megohm_km"] * 1000000 / fields["line_length_km"]
                capacitance = 1 / (angular_frequency * xc_total)
                travel_ms = (inductance * capacitance).sqrt() / Decimal("0.001")
                impedance = (inductance / capacitance).sqrt()
                resistance = fields[f"r_{sequence}_ohm_per_km"] * Decimal("0.001")
                # Inspect each binary64 operation in the resolved Java branch,
                # including divisions that could underflow before a later multiply.
                native_xc = _positive_binary64(_positive_binary64(float(fields[f"xc_{sequence}_megohm_km"]) * 1e6) / native_length_km)
                native_c = _positive_binary64(1.0 / _positive_binary64(native_omega * native_xc))
                native_l = _positive_binary64(_positive_binary64(float(fields[f"x_{sequence}_ohm_per_km"]) / native_omega) * native_length_km)
                native_lc = _positive_binary64(native_l * native_c)
                native_l_over_c = _positive_binary64(native_l / native_c)
                _positive_binary64(math.sqrt(native_lc) / 0.001)
                _positive_binary64(math.sqrt(native_l_over_c))
                _positive_binary64(float(fields[f"r_{sequence}_ohm_per_km"]) * 0.001)
                # Refuse values outside the finite binary64 computation domain. A
                # finite Decimal result must not conceal native intermediate overflow.
                for value in (angular_frequency, inductance, xc_total, capacitance,
                              inductance * capacitance, inductance / capacitance, travel_ms, impedance, resistance):
                    _positive_binary64(float(value))
                for name, expected in (("travel_time_ms", travel_ms), ("impedance_ohm", impedance),
                                       ("resistance_ohm_per_m_1", resistance), ("resistance_ohm_per_m_2", resistance)):
                    checks.append(_check(f"mode_{index + 1}.{name}", mode["fields"][name], expected, RELATIVE_TOLERANCE))
                for column, expected in enumerate(TRANSFORM[index]):
                    checks.append(_check(f"mode_{index + 1}.transform_{column + 1}",
                                         mode["fields"]["transformation_row"][column], Decimal(expected)))
    except (ValueError, DecimalException, OverflowError) as exc:
        result["reasons"].append(str(exc))
        return result
    result["checks"] = checks
    result["status"] = "inconsistent" if any(row["status"] == "failed" for row in checks) else "consistent"
    result["reasons"].append("Supplied-byte numerical comparison only; freshness and generator execution require separate evidence")
    return result
