"""Synthetic filesystem fixture tests; no vendor SDK, native or model execution."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import eval_native_fixture as fixture
from eval_native_host import digest, durable_json, read_json
from rtds_agent.settings import Settings


class FakeInspector:
    def __init__(self, manifest, settings, coordination, *, allow_native):
        if allow_native is not False:
            raise AssertionError("Fixture preparation must never enable native calls")
        self.path, self.settings, self.coordination = Path(manifest), settings, coordination

    def inspect(self):
        manifest = read_json(self.path)
        return {"live_calls_made": False, "fixture_sha256": digest(self.path),
                "source_sha256": manifest["source_sha256"],
                "plan": {"components": [{"uuid": 1, "component_type": "authored"}], "groups": [], "wires": []}}

    def verify(self):
        pass


class NativeFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).absolute()
        self.vendor = self.root / "vendor"
        self.operator = Settings(self.root / "operator-data", self.vendor)
        self.sdk_root = self.operator.sdk_root / "rtds"
        self.sdk_root.mkdir(parents=True)
        (self.sdk_root / "__init__.py").write_text('raise AssertionError("Never import authored SDK")\n')
        (self.vendor / "BIN").mkdir()
        (self.vendor / "BIN/RSCAD_FX.exe").write_bytes(b"authored-not-executable")
        self.operator.definition_root.mkdir(parents=True)
        (self.operator.definition_root / "authored").write_text("Authored definition bytes")
        (self.root / "source.rtfx").write_bytes(b"authored-model-bytes")
        (self.root / "companion.dat").write_bytes(b"authored-companion-bytes")
        self.config = self.root / "coordination.json"
        durable_json(self.config, self.operator.as_dict(), exclusive=True)
        self.document = {"schema_version": "1.0", "cohort_id": "cohort-test",
            "coordination_config": {"path": str(self.config), "sha256": digest(self.config)},
            "rscad_home": str(self.vendor), "sdk_evidence_id": "a" * 64,
            "sdk_files": {"__init__.py": digest(self.sdk_root / "__init__.py")},
            "executable_sha256": digest(self.vendor / "BIN/RSCAD_FX.exe"), "implementation_sha256": "b" * 64,
            "cases": {"EVAL-N03": {"source": "source.rtfx", "files": {
                "source.rtfx": {"path": str(self.root / "source.rtfx"), "sha256": digest(self.root / "source.rtfx")},
                "line/companion.dat": {"path": str(self.root / "companion.dat"), "sha256": digest(self.root / "companion.dat")}},
                "definitions": {"authored": digest(self.operator.definition_root / "authored")},
                "strategy": "insert", "required_component_types": ["authored"]}}}
        self.evidence = {"available": True, "evidence_id": "a" * 64,
                         "sources": copy.deepcopy(self.document["sdk_files"]),
                         "executable_sha256": self.document["executable_sha256"]}
        self.sdk_mock = patch.object(fixture, "_sdk_evidence", return_value=self.evidence).start()
        self.impl_mock = patch.object(fixture, "_implementation_digest", return_value="b" * 64).start()
        self.addCleanup(patch.stopall)
        self.path = self.root / "suite.json"
        durable_json(self.path, self.document, exclusive=True)

    def load(self):
        return fixture.load_suite(self.path, digest(self.path))

    def create(self, name="attempt-1", suite=None):
        return fixture.create_fixture(self.root / name, "EVAL-N03", suite or self.load(), bridge_factory=FakeInspector)

    def rewrite(self):
        self.path.write_text(__import__("json").dumps(self.document), encoding="utf-8")

    def test_load_readonly_and_sources_never_imported(self):
        before = {str(p): digest(p) for p in self.root.rglob("*") if p.is_file()}
        loaded = self.load()
        self.assertEqual(loaded["original_hashes"], before)
        self.assertEqual(before, {str(p): digest(p) for p in self.root.rglob("*") if p.is_file()})
        self.assertNotIn("rtds", sys.modules)

    def test_repetitions_have_distinct_raw_manifests_and_stable_profile(self):
        one, two = self.create(), self.create("attempt-2")
        self.assertEqual(one["fixture_sha256"], two["fixture_sha256"])
        self.assertNotEqual(one["fixture_id"], two["fixture_id"])
        self.assertNotEqual(one["native_manifest_sha256"], two["native_manifest_sha256"])
        self.assertEqual(one["native_component_count"], 1)
        self.assertEqual(one["native_group_count"], 0)
        self.assertEqual(one["native_host_binding"]["manifest_sha256"], one["native_manifest_sha256"])
        self.assertTrue(fixture.verify_fixture(one))
        self.assertFalse((self.operator.data_dir / "execution_policy.json").exists())
        self.assertEqual(Path(one["project_path"]).read_bytes(), (self.root / "source.rtfx").read_bytes())
        self.assertEqual((Path(one["root"]) / "sources/line/companion.dat").read_bytes(), b"authored-companion-bytes")

    def test_reject_suite_hash_mismatch_before_writes(self):
        with self.assertRaisesRegex(ValueError, "hash changed"):
            fixture.load_suite(self.path, "c" * 64)
        self.assertFalse((self.root / "attempt-1").exists())

    def test_source_changed_after_suite_load_is_refused_before_copy(self):
        suite = self.load()
        (self.root / "source.rtfx").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.create(suite=suite)
        self.assertFalse((self.root / "attempt-1").exists())

    def test_sdk_inventory_and_implementation_binding_are_exact(self):
        self.evidence["sources"]["extra.py"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "SDK evidence"):
            self.load()
        self.evidence["sources"].pop("extra.py")
        self.impl_mock.return_value = "c" * 64
        with self.assertRaisesRegex(ValueError, "implementation"):
            self.load()

    def test_unknown_fields_and_unsafe_relative_destinations_refused(self):
        self.document["cases"]["EVAL-N03"]["execute"] = True
        self.rewrite()
        with self.assertRaises(ValueError):
            self.load()
        self.document["cases"]["EVAL-N03"].pop("execute")
        for name in ("../escape", "CON.txt", "ambiguous.", "line\\name", "/absolute", "C:stream"):
            with self.subTest(name=name):
                self.document["cases"]["EVAL-N03"]["files"][name] = {
                    "path": str(self.root / "companion.dat"), "sha256": digest(self.root / "companion.dat")}
                self.rewrite()
                with self.assertRaises(ValueError):
                    self.load()
                self.document["cases"]["EVAL-N03"]["files"].pop(name)

    def test_case_collisions_and_wrong_task_strategy_refused(self):
        self.document["cases"]["EVAL-N03"]["files"]["SOURCE.RTFX"] = self.document["cases"]["EVAL-N03"]["files"]["source.rtfx"]
        self.rewrite()
        with self.assertRaisesRegex(ValueError, "collision"):
            self.load()
        self.document["cases"]["EVAL-N03"]["files"].pop("SOURCE.RTFX")
        self.document["cases"]["EVAL-N03"]["strategy"] = "clipboard"
        self.rewrite()
        with self.assertRaises(ValueError):
            self.load()

    def test_fixture_reuse_and_changed_original_inventory_refused(self):
        meta = self.create()
        with self.assertRaises(FileExistsError):
            self.create()
        (Path(meta["root"]) / "extra.txt").write_text("unrequested")
        with self.assertRaisesRegex(ValueError, "inventory changed"):
            fixture.verify_fixture(meta)

    def test_changed_copy_config_and_scorer_oracle_are_refused(self):
        meta = self.create()
        wrong = copy.deepcopy(meta)
        wrong["native_plan_sha256"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "oracle changed"):
            fixture.verify_fixture(wrong)
        Path(meta["project_path"]).write_bytes(b"changed-copy")
        with self.assertRaisesRegex(ValueError, "hash changed"):
            fixture.verify_fixture(meta)

    def test_alternate_paths_and_policy_creation_are_refused(self):
        meta = self.create()
        wrong = copy.deepcopy(meta)
        wrong["native_config"] = str(self.config)
        with self.assertRaisesRegex(ValueError, "layout changed"):
            fixture.verify_fixture(wrong)
        (Path(meta["data_dir"]) / "execution_policy.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "policy must remain absent"):
            fixture.verify_fixture(meta)

    def test_inspector_cannot_claim_live_execution(self):
        class BadInspector(FakeInspector):
            def inspect(self):
                return {**super().inspect(), "live_calls_made": True}
        with self.assertRaisesRegex(ValueError, "live evidence"):
            fixture.create_fixture(self.root / "bad-attempt", "EVAL-N03", self.load(), bridge_factory=BadInspector)
        self.assertTrue((self.root / "bad-attempt/fixture/manifest.json").exists())

    def test_recovery_barrier_blocks_fixture_without_mutation(self):
        self.operator.data_dir.mkdir()
        (self.operator.data_dir / "native_recovery_required.json").write_text("{}")
        with self.assertRaises(PermissionError):
            self.create()
        self.assertFalse((self.root / "attempt-1").exists())

    def test_no_declared_task_and_modified_loaded_metadata_refused(self):
        suite = self.load()
        with self.assertRaisesRegex(ValueError, "not declared"):
            fixture.create_fixture(self.root / "attempt-1", "EVAL-N04", suite, bridge_factory=FakeInspector)
        suite["document"]["cohort_id"] = "forged"
        with self.assertRaisesRegex(ValueError, "since caller"):
            self.create(suite=suite)


if __name__ == "__main__":
    unittest.main()
