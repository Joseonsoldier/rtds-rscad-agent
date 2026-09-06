"""Synthetic supplied initialization checks; no load flow, SDK or live backend."""
import test_environment
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

from jsonschema import Draft202012Validator
from pydantic import TypeAdapter

import test_public_release as fixture
from rtds_agent.core.loadflow_initialization import (
    INITIALIZATION_SCHEMA, check_preconditions, plan_sha256, semantic_diff,
    validate_initialization, validate_supplied,
)
from rtds_agent.core.state_machine import sha256_file, sha256_json
from rtds_agent.initialization import InitializationRequest, inspect_initialization
from rtds_agent.project_tools import _document


class InitializationTests(unittest.TestCase):
    def setUp(self):
        fixture.PublicReleaseTests.setUp(self)
        (self.defs / "synthetic_source").write_text(
            'PARAMETERS:\n P "Active power" "MW" REAL 1 -100 100\n Q "Reactive power" "Mvar" REAL 0 -100 100\n'
            ' V "Voltage" "pu" REAL 1 0 2\n angle "Phase" "deg" REAL 0 -360 360\nNODES:\n', encoding="utf-8")
        self.dfx = ('DRAFT 1\nSUBSYSTEM-START:\nCOMPONENT_TYPE=synthetic_source\n0 0 0 0 4\n'
                    'PARAMETERS-START:\nP: 1\nQ: 0\nV: 1\nangle: 0\nPARAMETERS-END:\nUUID: 1\nSUBSYSTEM-END:\n')
        self.write_model(self.project, self.dfx)
        self.point = {
            "P": {"value": 1, "units": "MW", "sign_convention": "injection"},
            "Q": {"value": 0, "units": "Mvar", "sign_convention": "injection"},
            "V": {"value": 1, "units": "pu", "sign_convention": "magnitude", "pu_base": 13.8},
            "angle": {"value": 0, "units": "deg", "sign_convention": "positive_sequence"}}

    def write_model(self, path, text, runtime=b"unchanged saved Runtime", comment=b"", member="model.dfx"):
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(member, text)
            archive.writestr("model.rtx", runtime)
            archive.comment = comment

    def request(self):
        return {"schema_version": "1.0", "mode": "preconditions", "input_project_sha256": sha256_file(self.project),
                "entities": [{"entity_id": "source1", "role": "source", "context": "subsystem:0", "component_id": 1,
                              "component_type": "synthetic_source", "requested_operating_point": copy.deepcopy(self.point),
                              "parameter_bindings": [{"quantity": name, "parameter": name, "expected_stored_value": str(value),
                                                      "calculated_parameter": name, "expected_calculated_stored_value": str(value)}
                                                     for name, value in (("P", 1), ("Q", 0), ("V", 1), ("angle", 0))]}],
                "provenance": [{"source_path": str(self.guide), "source_sha256": sha256_file(self.guide), "locator": "Synthetic roles and units"}]}

    def evaluate(self, request=None):
        return inspect_initialization(str(self.project), None, request or self.request())

    def supplied(self, *, changed=True):
        request = self.request()
        after_path = self.sources / "initialized.rtfx"
        self.write_model(after_path, self.dfx.replace("P: 1\n", "P: 1.5\n") if changed else self.dfx)
        after = _document(str(after_path))[2]
        point = copy.deepcopy(self.point)
        point["P"]["value"] = 1.5 if changed else 1
        document = {"schema_version": "1.0", "evidence_id": "synthetic-lf-result", "initialization_plan_sha256": plan_sha256(request),
                    "input_project_sha256": sha256_file(self.project), "after_project_sha256": sha256_file(after_path),
                    "solver_report": {"reported_status": "converged", "warnings": []},
                    "calculated_states": [{"entity_id": "source1", "operating_point": point}],
                    "parameter_changes": [{"context": "subsystem:0", "component_id": 1, "component_type": "synthetic_source",
                                           "parameter": "P", "before_value": "1", "after_value": "1.5"}] if changed else []}
        data_path = self.data / "initialization.json"
        data_path.write_text(json.dumps(document), encoding="utf-8")
        request.update(mode="supplied_evidence", evidence={"data_path": str(data_path), "data_sha256": sha256_file(data_path),
                       "after_project": str(after_path), "after_project_sha256": sha256_file(after_path), "after_snapshot_id": after["snapshot_id"]})
        return request, document

    def update_artifact(self, request, document):
        path = Path(request["evidence"]["data_path"])
        path.write_text(json.dumps(document), encoding="utf-8")
        request["evidence"]["data_sha256"] = sha256_file(path)

    def update_after(self, request, document, *, text=None, runtime=b"unchanged saved Runtime", comment=b""):
        path = Path(request["evidence"]["after_project"])
        self.write_model(path, text if text is not None else self.dfx.replace("P: 1\n", "P: 1.5\n"), runtime, comment)
        request["evidence"]["after_project_sha256"] = sha256_file(path)
        request["evidence"]["after_snapshot_id"] = _document(str(path))[2]["snapshot_id"]
        document["after_project_sha256"] = sha256_file(path)
        self.update_artifact(request, document)

    def test_schema_and_preconditions_are_strict_deterministic_read_only(self):
        Draft202012Validator.check_schema(INITIALIZATION_SCHEMA)
        before = {path: sha256_file(path) for path in (self.project, self.guide)}
        request = self.request()
        with patch("rtds_agent.execution._backend") as backend, patch("rtds_agent.core.runtime_backend.RscadFxRuntimeDriver._new_connection") as connect:
            first = self.evaluate(request)
            self.assertEqual(first, self.evaluate(request))
            backend.assert_not_called()
            connect.assert_not_called()
        self.assertEqual(first["status"], "preconditions_checked")
        self.assertEqual(first["preconditions"]["status"], "checked")
        self.assertEqual(first["initialization_plan_sha256"], plan_sha256(request))
        self.assertEqual({path: sha256_file(path) for path in before}, before)
        self.assertFalse(first["execution_authorized"])
        self.assertFalse(first["integration_qualified"])
        self.assertEqual(first["engineering_verdict"], "not_evaluated")
        self.assertFalse((self.data / "execution_policy.json").exists())

    def test_pydantic_annotation_inlines_refs_and_preserves_strict_schema(self):
        rendered = TypeAdapter(InitializationRequest).json_schema()
        Draft202012Validator.check_schema(rendered)
        self.assertNotIn('"$ref"', json.dumps(rendered))
        Draft202012Validator(rendered).validate(self.request())
        request = self.request()
        request["entities"][0]["parameter_bindings"][0].pop("calculated_parameter")
        self.assertFalse(Draft202012Validator(rendered).is_valid(request))
        request = self.request()
        request["execute"] = True
        self.assertFalse(Draft202012Validator(rendered).is_valid(request))

    def test_request_rejects_unknown_authority_fields_and_bad_modes(self):
        for field, value in (("execute", True), ("integration_qualified", True), ("mode", "run_loadflow")):
            request = self.request()
            request[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.evaluate(request)
        request = self.request()
        request["evidence"] = {}
        with self.assertRaises(ValueError):
            self.evaluate(request)

    def test_duplicate_entity_and_quantity_binding_and_nonfinite_values_rejected(self):
        changes = [lambda r: r["entities"].append(copy.deepcopy(r["entities"][0])),
                   lambda r: r["entities"][0]["parameter_bindings"].__setitem__(1, r["entities"][0]["parameter_bindings"][0]),
                   lambda r: r["entities"][0]["requested_operating_point"]["P"].update(value=True),
                   lambda r: r["entities"][0]["requested_operating_point"]["P"].update(value=float("nan")),
                   lambda r: r["entities"][0]["requested_operating_point"]["P"].update(value=10**1000),
                   lambda r: r["entities"][0].update(component_id=True),
                   lambda r: r["provenance"][0].update(locator=" "),
                   lambda r: r["entities"].__imul__(65)]
        for change in changes:
            request = self.request()
            change(request)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_initialization(request)

    def test_units_base_and_point_mapping_are_exact(self):
        for quantity, update in (("P", {"units": "kVA"}), ("V", {"pu_base": 0}),
                                 ("V", {"value": -1}), ("angle", {"units": "rad", "pu_base": 1})):
            request = self.request()
            request["entities"][0]["requested_operating_point"][quantity].update(update)
            with self.subTest(quantity=quantity, update=update), self.assertRaises(ValueError):
                validate_initialization(request)
        request = self.request()
        request["entities"][0]["parameter_bindings"].pop()
        with self.assertRaises(ValueError):
            validate_initialization(request)

    def test_preconditions_block_missing_identity_stale_stored_and_different_numeric_request(self):
        changes = [lambda r: r["entities"][0].update(component_id=999),
                   lambda r: r["entities"][0].update(component_type="other"),
                   lambda r: r["entities"][0]["parameter_bindings"][0].update(expected_stored_value="2"),
                   lambda r: r["entities"][0]["requested_operating_point"]["P"].update(value=2)]
        for change in changes:
            request = self.request()
            change(request)
            with self.subTest(change=change):
                report = self.evaluate(request)
                self.assertEqual(report["status"], "blocked")
                self.assertTrue(report["preconditions"]["entities"][0]["reasons"])

    def test_input_and_provenance_hashes_and_roots_are_rechecked(self):
        for field in ("input_project_sha256", "provenance"):
            request = self.request()
            if field == "provenance":
                request[field][0]["source_sha256"] = "0" * 64
            else:
                request[field] = "0" * 64
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.evaluate(request)
        request = self.request()
        request["provenance"][0]["source_path"] = str(self.config)
        request["provenance"][0]["source_sha256"] = sha256_file(self.config)
        with self.assertRaises(ValueError):
            self.evaluate(request)

    def test_static_errors_and_incomplete_dependencies_block_preconditions(self):
        request = self.request()
        document = _document(str(self.project))[2]
        report = check_preconditions(request, document, {"status": "errors_found"})
        self.assertEqual(report["status"], "blocked")
        document["coverage"]["definition_coverage"] = 0
        document["snapshot"]["evidence"]["companions"]["status"] = "incomplete"
        report = check_preconditions(request, document, {"status": "no_errors_in_checked_scope"})
        self.assertIn("component_definition_coverage_incomplete", report["reasons"])
        self.assertIn("companion_dependency_evidence_incomplete", report["reasons"])

    def test_supplied_changed_state_and_exact_diff_are_consistent_only(self):
        request, _ = self.supplied()
        before = self.project.read_bytes()
        report = self.evaluate(request)
        evidence = report["supplied_evidence"]
        self.assertEqual(report["status"], "consistent_supplied_evidence", evidence)
        self.assertEqual(evidence["status"], "consistent")
        self.assertEqual(evidence["semantic_diff"]["parameter_change_count"], 1)
        self.assertTrue(evidence["archive_evidence"]["non_dfx_unchanged"])
        self.assertTrue(evidence["archive_evidence"]["dfx_changes_fully_accounted"])
        self.assertEqual(evidence["reported_convergence"]["reported_status"], "converged")
        self.assertFalse(evidence["convergence_independently_verified"])
        self.assertFalse(evidence["python_return_used_as_convergence_evidence"])
        self.assertFalse(report["execution_authorized"])
        self.assertEqual(self.project.read_bytes(), before)

    def test_unchanged_models_and_nonconvergence_reports_are_not_promoted(self):
        for status in ("converged", "not_converged", "unknown"):
            request, document = self.supplied(changed=False)
            document["solver_report"] = {"reported_status": status, "warnings": ["Supplied warning"]}
            self.update_artifact(request, document)
            report = self.evaluate(request)
            evidence = report["supplied_evidence"]
            self.assertEqual(evidence["status"], "consistent")
            self.assertEqual(evidence["reported_convergence"], document["solver_report"])
            self.assertFalse(evidence["convergence_independently_verified"])
            self.assertEqual(evidence["semantic_diff"]["parameter_change_count"], 0)

    def test_artifact_cannot_supply_python_return_or_qualification_authority(self):
        for key, value in (("python_return", None), ("convergence_independently_verified", True)):
            request, document = self.supplied()
            document[key] = value
            self.update_artifact(request, document)
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.evaluate(request)

    def test_stale_artifact_plan_before_after_and_snapshot_refs_are_rejected(self):
        for key in ("initialization_plan_sha256", "input_project_sha256", "after_project_sha256"):
            request, document = self.supplied()
            document[key] = "0" * 64
            self.update_artifact(request, document)
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.evaluate(request)
        for key in ("data_sha256", "after_project_sha256", "after_snapshot_id"):
            request, _ = self.supplied()
            request["evidence"][key] = "0" * 64
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.evaluate(request)

    def test_duplicate_json_and_oversized_evidence_are_rejected(self):
        request, _ = self.supplied()
        path = Path(request["evidence"]["data_path"])
        path.write_text('{"schema_version":"1.0","schema_version":"1.0"}', encoding="utf-8")
        request["evidence"]["data_sha256"] = sha256_file(path)
        with self.assertRaisesRegex(ValueError, "Duplicate key"):
            self.evaluate(request)
        path.write_bytes(b" " * (1024 * 1024 + 1))
        request["evidence"]["data_sha256"] = sha256_file(path)
        with self.assertRaisesRegex(ValueError, "exceeds 1 MiB"):
            self.evaluate(request)

    def test_calculated_metadata_missing_entities_and_unreflected_state_block_consistency(self):
        changes = [lambda d: d["calculated_states"][0].update(entity_id="missing"),
                   lambda d: d["calculated_states"][0]["operating_point"]["P"].update(units="kW"),
                   lambda d: d["calculated_states"][0]["operating_point"]["P"].update(sign_convention="consumption"),
                   lambda d: d["calculated_states"][0]["operating_point"]["V"].update(pu_base=100),
                   lambda d: d["calculated_states"][0]["operating_point"]["Q"].update(value=2)]
        for change in changes:
            request, document = self.supplied()
            change(document)
            self.update_artifact(request, document)
            with self.subTest(change=change):
                self.assertEqual(self.evaluate(request)["status"], "blocked")

    def test_requested_and_calculated_parameters_are_explicitly_distinct(self):
        definition = self.defs / "synthetic_source"
        definition.write_text(definition.read_text(encoding="utf-8").replace('NODES:\n', ' Pt "Requested power" "MW" REAL 2 -100 100\nNODES:\n'), encoding="utf-8")
        self.dfx = self.dfx.replace("0 0 0 0 4", "0 0 0 0 5").replace("PARAMETERS-END:\n", "Pt: 2\nPARAMETERS-END:\n")
        self.write_model(self.project, self.dfx)
        request, supplied = self.supplied()
        entity = request["entities"][0]
        entity["requested_operating_point"]["P"]["value"] = 2
        entity["parameter_bindings"][0].update(parameter="Pt", expected_stored_value="2",
                                              calculated_parameter="P", expected_calculated_stored_value="1")
        supplied["initialization_plan_sha256"] = plan_sha256(request)
        supplied["calculated_states"][0]["operating_point"]["P"]["value"] = 3
        supplied["parameter_changes"][0]["after_value"] = "3"
        self.update_after(request, supplied, text=self.dfx.replace("P: 1\n", "P: 3\n"))
        report = self.evaluate(request)
        self.assertEqual(report["status"], "consistent_supplied_evidence", report)
        self.assertEqual(report["preconditions"]["entities"][0]["requested_operating_point"]["P"]["value"], 2)
        self.assertEqual(report["supplied_evidence"]["calculated_states"][0]["operating_point"]["P"]["value"], 3)
        self.assertEqual(report["supplied_evidence"]["semantic_diff"]["parameter_changes"][0]["parameter"], "P")

    def test_nonnumeric_definition_and_definition_unit_contradiction_are_blocked(self):
        definition = self.defs / "synthetic_source"
        original = definition.read_text(encoding="utf-8")
        for declaration, reason in ((' P "Active power" "MW" STRING 1', "numeric_parameter_definition_unresolved_or_unsupported:P"),
                                    (' P "Active power" "kW" REAL 1 -100 100', "declared_units_contradict_parameter_definition:P")):
            definition.write_text(original.replace(' P "Active power" "MW" REAL 1 -100 100', declaration), encoding="utf-8")
            report = self.evaluate()
            self.assertEqual(report["status"], "blocked")
            self.assertIn(reason, report["preconditions"]["entities"][0]["reasons"])

    def test_installed_mvar_literal_is_supported_without_case_normalization(self):
        definition = self.defs / "synthetic_source"
        definition.write_text(definition.read_text(encoding="utf-8").replace('"Mvar"', '"MVAR"'), encoding="utf-8")
        self.assertEqual(self.evaluate()["status"], "blocked")
        request = self.request()
        request["entities"][0]["requested_operating_point"]["Q"]["units"] = "MVAR"
        self.assertEqual(self.evaluate(request)["status"], "preconditions_checked")

    def test_partial_calculated_quantities_must_match_explicit_bindings(self):
        request, supplied = self.supplied()
        entity = request["entities"][0]
        entity["requested_operating_point"] = {"P": entity["requested_operating_point"]["P"]}
        entity["parameter_bindings"] = entity["parameter_bindings"][:1]
        supplied["initialization_plan_sha256"] = plan_sha256(request)
        self.update_artifact(request, supplied)
        report = self.evaluate(request)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("calculated_quantities_do_not_match_explicit_bindings:source1", report["supplied_evidence"]["reasons"])
        supplied["calculated_states"][0]["operating_point"] = {"P": supplied["calculated_states"][0]["operating_point"]["P"]}
        self.update_artifact(request, supplied)
        report = self.evaluate(request)
        self.assertEqual(report["status"], "consistent_supplied_evidence")
        self.assertEqual(report["preconditions"]["entities"][0]["unbound_quantities_not_evaluated"], ["Q", "V", "angle"])

    def test_unreported_or_falsely_reported_parameter_changes_are_blocked(self):
        request, document = self.supplied()
        document["parameter_changes"] = []
        self.update_artifact(request, document)
        evidence = self.evaluate(request)["supplied_evidence"]
        self.assertIn("reported_parameter_changes_do_not_match_observed_changes", evidence["reasons"])
        self.assertFalse(evidence["archive_evidence"]["dfx_changes_fully_accounted"])
        request, document = self.supplied()
        document["parameter_changes"][0]["after_value"] = "2"
        self.update_artifact(request, document)
        self.assertEqual(self.evaluate(request)["status"], "blocked")

    def test_non_dfx_archive_comment_and_opaque_dfx_changes_are_blocked(self):
        for kwargs, reason in (({"runtime": b"changed control"}, "non_dfx_members_or_archive_identity_changed"),
                               ({"comment": b"changed"}, "non_dfx_members_or_archive_identity_changed"),
                               ({"text": self.dfx.replace("P: 1\n", "P: 1.5\n") + "OPAQUE: injected\n"}, "dfx_contains_unexplained_or_unsupported_byte_changes")):
            request, document = self.supplied()
            self.update_after(request, document, **kwargs)
            report = self.evaluate(request)
            self.assertEqual(report["status"], "blocked")
            self.assertIn(reason, report["supplied_evidence"]["reasons"])

    def test_geometry_change_is_recorded_as_prohibited(self):
        request, document = self.supplied()
        self.update_after(request, document, text=self.dfx.replace("P: 1\n", "P: 1.5\n").replace("0 0 0 0 4", "10 0 0 0 4"))
        report = self.evaluate(request)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("component_location_changed", [row["kind"] for row in report["supplied_evidence"]["semantic_diff"]["prohibited_changes"]])

    def test_companion_copies_match_relative_identity_and_changed_bytes_block(self):
        definition = self.defs / "synthetic_source"
        definition.write_text(definition.read_text(encoding="utf-8").replace('NODES:\n', ' DataFile "Input file" "" STRING input.dat\nNODES:\n'), encoding="utf-8")
        self.dfx = self.dfx.replace("0 0 0 0 4", "0 0 0 0 5").replace("PARAMETERS-END:\n", "DataFile: input.dat\nPARAMETERS-END:\n")
        self.write_model(self.project, self.dfx)
        (self.sources / "input.dat").write_bytes(b"synthetic companion")
        request, supplied = self.supplied()
        isolated = self.sources / "isolated"
        isolated.mkdir()
        after_path = isolated / "initialized.rtfx"
        after_path.write_bytes(Path(request["evidence"]["after_project"]).read_bytes())
        companion = isolated / "input.dat"
        companion.write_bytes(b"synthetic companion")
        request["evidence"].update(after_project=str(after_path), after_snapshot_id=_document(str(after_path))[2]["snapshot_id"])
        report = self.evaluate(request)
        self.assertEqual(report["status"], "consistent_supplied_evidence", report)
        self.assertTrue(report["supplied_evidence"]["archive_evidence"]["same_definition_and_companion_evidence"])
        companion.write_bytes(b"different payload")
        request["evidence"]["after_snapshot_id"] = _document(str(after_path))[2]["snapshot_id"]
        report = self.evaluate(request)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("definition_or_companion_evidence_changed", report["supplied_evidence"]["reasons"])

    def test_duplicate_model_identity_and_bounded_diff_are_not_silently_accepted(self):
        document = _document(str(self.project))[2]
        changed = copy.deepcopy(document)
        changed["components"].append(copy.deepcopy(changed["components"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate model identity"):
            semantic_diff(document, changed)
        changed = copy.deepcopy(document)
        changed["components"][0]["parameters"].update({"extra" + str(index): "1" for index in range(129)})
        diff = semantic_diff(document, changed)
        self.assertTrue(diff["truncated"])
        self.assertEqual(len(diff["parameter_changes"]), 128)
        self.assertEqual(diff["parameter_change_count"], 129)

    def test_duplicate_raw_bound_parameter_is_blocked_even_with_no_model_changes(self):
        self.dfx = self.dfx.replace("P: 1\n", "P: 1\nP: 1\n")
        self.write_model(self.project, self.dfx)
        report = self.evaluate()
        self.assertEqual(report["status"], "blocked")
        self.assertIn("bound_parameter_raw_occurrence_not_unique_or_unsupported", report["preconditions"]["reasons"])
        request, _ = self.supplied(changed=False)
        report = self.evaluate(request)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("bound_parameter_raw_occurrence_not_unique_or_unsupported", report["preconditions"]["reasons"])

    def test_provenance_and_artifact_changes_during_check_are_rejected(self):
        request = self.request()
        from rtds_agent import initialization
        original = initialization.check_preconditions
        def change_provenance(*args):
            result = original(*args)
            self.guide.write_text("changed after verification", encoding="utf-8")
            return result
        with patch("rtds_agent.initialization.check_preconditions", side_effect=change_provenance):
            with self.assertRaisesRegex(ValueError, "provenance or settings changed"):
                self.evaluate(request)
        request, _ = self.supplied()
        original_evaluate = initialization.evaluate_supplied
        def change_artifact(*args):
            result = original_evaluate(*args)
            Path(request["evidence"]["data_path"]).write_text("{}", encoding="utf-8")
            return result
        with patch("rtds_agent.initialization.evaluate_supplied", side_effect=change_artifact):
            with self.assertRaisesRegex(ValueError, "artifact changed"):
                self.evaluate(request)


if __name__ == "__main__":
    unittest.main()
