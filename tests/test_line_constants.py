"""Authored scalar fixtures only; no vendor files or native execution."""
import hashlib
import json
import unittest
import test_environment

from rtds_agent.core.line_constants import compare_line_constants, inspect_line_output


TLI = b"""Line Summary:
{
 Line Length = 10
 Steady State Frequency = 50
}
Line Constants Ground Data:
{
 GroundResistivity = 100
}
RLC Options:
{
 Data Entry Format = 0
 Positive Sequence Series Resistance = 0.1
 Positive Sequence Series Ind Reactance = 0.25
 Positive Sequence Series Cap Reactance = 0.16
 Zero Sequence Series Resistance = 0.4
 Zero Sequence Series Ind Reactance = 1
 Zero Sequence Series Cap Reactance = 1
 Number of Phases = 3
}
"""
# Analytic fixture: Z0=1000 ohm, Z1=200 ohm; tau0=0.1/pi ms,
# tau1=0.125/pi ms. Synthetic comments deliberately do not claim a publisher.
TLO = b"""! Authored test fixture, no native generation
3 0 1 1 50 50 10000 1e-9 1e-9 /
1 1 0.03183098861837907 1000 0.0004 0.0004 0.5773503 0.8164967 0.0
2 2 0.039788735772973836 200 0.0001 0.0001 0.5773503 -0.4082483 0.7071068
3 3 0.039788735772973836 200 0.0001 0.0001 0.5773503 -0.4082483 -0.7071068
"""


class LineConstantsTests(unittest.TestCase):
    def test_supported_numeric_agreement_has_no_execution_authority(self):
        report = compare_line_constants(TLI, TLO)
        self.assertEqual(report["status"], "consistent")
        self.assertEqual(len(report["checks"]), 24)
        self.assertTrue(all(c["status"] == "passed" for c in report["checks"]))
        for key in ("freshness_verified", "native_origin_verified", "generator_execution_verified",
                    "integration_qualified", "execution_authorized", "automatic_retry", "solver_called", "companion_generated"):
            self.assertIs(report[key], False)
        self.assertEqual(report["engineering_verdict"], "not_evaluated")
        self.assertEqual(report["input_sha256"], hashlib.sha256(TLI).hexdigest())
        self.assertEqual(report["output_sha256"], hashlib.sha256(TLO).hexdigest())
        json.dumps(report, allow_nan=False)

    def test_raw_numeric_spans_survive_whitespace_and_line_endings(self):
        raw = TLO.replace(b"\n", b"\r\r\n").replace(b"3 0 1 1", b"\t3  0\t1  1")
        report = inspect_line_output(raw)
        self.assertEqual(report["status"], "supported")
        records = list(report["header"].values())
        for mode in report["modes"]:
            records.extend(v for k, v in mode["fields"].items() if k != "transformation_row")
            records.extend(mode["fields"]["transformation_row"])
        for record in records:
            self.assertEqual(raw[record["byte_start"]:record["byte_end"]].decode(), record["raw_value"])
        self.assertEqual(compare_line_constants(TLI, raw)["status"], "consistent")

    def test_changed_input_invalidates_old_output_consistency(self):
        for old, new in ((b"Length = 10", b"Length = 11"), (b"Frequency = 50", b"Frequency = 60"),
                         (b"Resistance = 0.1", b"Resistance = 0.2"),
                         (b"Ind Reactance = 0.25", b"Ind Reactance = 0.36"),
                         (b"Cap Reactance = 0.16", b"Cap Reactance = 0.25")):
            with self.subTest(old=old):
                report = compare_line_constants(TLI.replace(old, new), TLO)
                self.assertEqual(report["status"], "inconsistent")

    def test_both_frequency_and_resistance_columns_checked(self):
        for old, new in ((b"50 50", b"50 51"), (b"0.0004 0.0004", b"0.0004 0.0005"),
                         (b"0.0001 0.0001", b"0.0001 0.0002")):
            with self.subTest(old=old):
                self.assertEqual(compare_line_constants(TLI, TLO.replace(old, new))["status"], "inconsistent")

    def test_modal_impedance_time_and_transform_checked(self):
        for old, new in ((b"0.03183098861837907", b"0.04183098861837907"),
                         (b" 200 ", b" 201 "), (b"-0.7071068", b"0.7071068"),
                         (b"0.8164967", b"0.81649670000000000001")):
            with self.subTest(old=old):
                self.assertEqual(compare_line_constants(TLI, TLO.replace(old, new))["status"], "inconsistent")

    def test_exact_header_comparison_does_not_round_tiny_difference(self):
        for old, new in ((b"50 50", b"50.00000000000000000001 50"),
                         (b"10000", b"10000.00000000000000000001")):
            with self.subTest(old=old):
                report = compare_line_constants(TLI, TLO.replace(old, new))
                self.assertEqual(report["status"], "inconsistent")
                self.assertTrue(any(c["status"] == "failed" and c["comparison"] == "exact_decimal" for c in report["checks"]))

    def test_input_binary64_header_conversion_is_explicit(self):
        altered_input = TLI.replace(b"Frequency = 50", b"Frequency = 50.00000000000000000001")
        report = compare_line_constants(altered_input, TLO)
        self.assertEqual(report["status"], "consistent")
        conversion = report["header_conversions"]["frequency_hz"]
        self.assertEqual(conversion["source_raw_value"], "50.00000000000000000001")
        self.assertTrue(conversion["conversion_loss"])
        self.assertEqual(conversion["converted_decimal"], "50.0")
        self.assertIs(report["native_origin_verified"], False)

    def test_header_length_uses_declared_binary64_product(self):
        altered_input = TLI.replace(b"Length = 10", b"Length = 1.001")
        report = compare_line_constants(altered_input, TLO)
        conversion = report["header_conversions"]["length_m"]
        self.assertEqual(conversion["converted_decimal"], "1000.9999999999999")
        self.assertTrue(conversion["conversion_loss"])
        self.assertEqual(conversion["exact_metric_value_decimal"], "1001.000")

    def test_relative_roundoff_allowance_is_explicit_and_has_no_floor(self):
        close = TLO.replace(b" 200 ", b" 200.0000000001 ")
        far = TLO.replace(b" 200 ", b" 200.000000001 ")
        self.assertEqual(compare_line_constants(TLI, close)["status"], "consistent")
        self.assertEqual(compare_line_constants(TLI, far)["status"], "inconsistent")
        report = compare_line_constants(TLI, TLO)
        check = next(c for c in report["checks"] if c["check"] == "mode_2.resistance_ohm_per_m_1")
        self.assertEqual(check["absolute_tolerance_decimal"], "1E-16")

    def test_header_count_and_integer_lexemes_are_narrow(self):
        for old, new in ((b"3 0 1 1", b"6 0 1 1"), (b"3 0 1 1", b"3.0 0 1 1"),
                         (b"3 0 1 1", b"3 0e0 1 1"), (b"3 0 1 1", b"3 0 2 1"),
                         (b"1e-9 1e-9", b"1e-9 2e-9"), (b" /", b"")):
            with self.subTest(old=old, new=new):
                self.assertEqual(inspect_line_output(TLO.replace(old, new))["status"], "unsupported")

    def test_missing_duplicate_reordered_and_extra_rows_refused(self):
        lines = TLO.splitlines(keepends=True)
        for raw in (b"", b"! empty\n", b"".join(lines[:-1]), TLO + lines[-1],
                    b"".join(lines[:2] + [lines[3], lines[2], lines[4]]),
                    TLO.replace(b"2 2 ", b"1 1 "), TLO + b"unexpected format\n"):
            with self.subTest(raw=raw[:30]):
                report = inspect_line_output(raw)
                self.assertEqual(report["status"], "unsupported")
                self.assertFalse(report["header"])
                self.assertFalse(report["modes"])

    def test_unknown_text_keeps_hash_and_raw_line_evidence(self):
        raw = TLO + b"NEW FORMAT 17\n"
        report = inspect_line_output(raw)
        self.assertEqual(report["source_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(report["raw_lines"][-1]["text"], "NEW FORMAT 17")
        self.assertEqual(report["parser_coverage"], "unsupported")

    def test_nonfinite_negative_zero_and_oversized_numbers_refused(self):
        for token in (b"NaN", b"Infinity", b"1e309", b"1e-999", b"-1", b"0", b"True", b"1" * 129):
            with self.subTest(token=token):
                self.assertEqual(inspect_line_output(TLO.replace(b" 200 ", b" " + token + b" "))["status"], "unsupported")

    def test_byte_line_encoding_and_type_bounds(self):
        for raw in (b"!" * 65537, b"\n" * 1025, b"\xef\xbb\xbf" + TLO, TLO + b"\x00", TLO + b"\xff"):
            self.assertEqual(inspect_line_output(raw)["status"], "unsupported")
        with self.assertRaises(ValueError):
            inspect_line_output("text")
        self.assertEqual(inspect_line_output(TLO, "cable")["status"], "unsupported")

    def test_unsupported_tli_cannot_pass_on_plausible_output(self):
        for old, new in ((b"Data Entry Format = 0", b"Data Entry Format = 1"),
                         (b"Number of Phases = 3", b"Number of Phases = 6"),
                         (b"Resistance = 0.1", b"Resistance = 0")):
            report = compare_line_constants(TLI.replace(old, new), TLO)
            self.assertEqual(report["status"], "inconclusive")
            self.assertFalse(report["checks"])

    def test_intermediate_binary64_overflow_or_underflow_is_inconclusive(self):
        for raw in (TLI.replace(b"Frequency = 50", b"Frequency = 1e308"),
                    TLI.replace(b"Cap Reactance = 0.16", b"Cap Reactance = 1e308"),
                    TLI.replace(b"Length = 10", b"Length = 1e-300"),
                    TLI.replace(b"Frequency = 50", b"Frequency = 1e200").replace(b"Ind Reactance = 0.25", b"Ind Reactance = 1e-200")):
            self.assertEqual(compare_line_constants(raw, TLO)["status"], "inconclusive")

    def test_ground_value_does_not_invent_physical_recalculation(self):
        result = compare_line_constants(TLI.replace(b"GroundResistivity = 100", b"GroundResistivity = 200"), TLO)
        self.assertEqual(result["status"], "consistent")
        self.assertTrue(any("Ground resistivity" in x for x in result["limitations"]))
        self.assertIs(result["freshness_verified"], False)


if __name__ == "__main__":
    unittest.main()
