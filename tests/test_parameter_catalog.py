"""Immutable parameter evidence using synthetic files and isolated settings only."""
import test_environment  # isolate config and credentials before application imports
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
from threading import Event
import unittest
from unittest.mock import patch
import zipfile

import test_public_release as fixture
from rtds_agent.core import parameter_catalog as catalog
from rtds_agent.core.state_machine import sha256_file


class ParameterCatalogTests(unittest.TestCase):
    setUp = fixture.PublicReleaseTests.setUp

    def index(self, project=None):
        from rtds_agent.knowledge import index_parameters
        return index_parameters(str(project or self.project))

    def lookup(self, kind="synthetic_gain", snapshot=None):
        from rtds_agent.knowledge import lookup_parameter
        return lookup_parameter(kind, "Gain", parameter_catalog_snapshot_id=snapshot)

    def second_project(self):
        kind = "synthetic_second"
        (self.defs / kind).write_text('PARAMETERS:\n Gain "Second synthetic gain" "pu" REAL 2 0 20\nNODES:\n', encoding="utf-8")
        result = self.sources / "second.rtfx"
        with zipfile.ZipFile(result, "w") as archive:
            archive.writestr("second.dfx", "DRAFT 1\nSUBSYSTEM-START:\nCOMPONENT_TYPE=" + kind + "\n0 0 0 0 1\nPARAMETERS-START:\nGain: 2\nPARAMETERS-END:\nUUID: 1\nSUBSYSTEM-END:\n")
        return result

    def legacy(self):
        folder = self.data / "knowledge"
        folder.mkdir(exist_ok=True)
        database = folder / "parameters.sqlite"
        definition = self.defs / "synthetic_gain"
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute(catalog.TABLE_SQL)
            connection.execute("INSERT INTO parameters VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                               ("synthetic_gain", "Gain", "2.7.3", "REAL", "pu", "1", 0, 10, "[]", "Synthetic gain",
                                str(definition), sha256_file(definition), "parsed_from_local_definition_not_simulation_verified", "synthetic raw"))
        audit_path = folder / "parameter_audit.json"
        audit = {"status": "passed", "checks": {"definitions_resolved": True, "source_hashes_unchanged": True},
                 "database": {"path": str(database), "sha256": sha256_file(database)}, "parameters": 1,
                 "scope": catalog.SCOPE, "created_at": "synthetic"}
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        return database, audit_path

    def test_a_b_a_lookup_preserves_immutable_evidence(self):
        first = self.index()
        first_id = first["parameter_catalog_snapshot_id"]
        first_database = Path(first["database"]["path"])
        first_bytes = first_database.read_bytes()
        second = self.index(self.second_project())
        self.assertNotEqual(first_id, second["parameter_catalog_snapshot_id"])
        self.assertEqual(self.lookup()["parameter_catalog_snapshot_id"], first_id)
        self.assertEqual(self.lookup("synthetic_second")["maximum"], 20)
        self.assertEqual(self.lookup(snapshot=first_id)["default_value"], "1")
        self.assertEqual(first_database.read_bytes(), first_bytes)
        status = catalog.catalog_status()
        self.assertEqual(status["snapshot_count"], 2)
        self.assertEqual(status["current_snapshot_id"], second["parameter_catalog_snapshot_id"])
        self.assertFalse((self.data / "knowledge/parameters.sqlite").exists())

    def test_same_definition_coalesces_without_rewriting_snapshot(self):
        first = self.index()
        second = self.index()
        self.assertNotEqual(first["parameter_catalog_snapshot_id"], second["parameter_catalog_snapshot_id"])
        self.assertEqual(self.lookup()["parameter_catalog_snapshot_id"], second["parameter_catalog_snapshot_id"])
        self.assertEqual(catalog.read_audit(first["parameter_catalog_snapshot_id"])[0], first)

    def test_changed_definition_is_ambiguous_and_old_snapshot_is_stale(self):
        first = self.index()
        path = self.defs / "synthetic_gain"
        path.write_text(path.read_text(encoding="utf-8").replace("0 10", "0 30"), encoding="utf-8")
        second = self.index()
        with self.assertRaisesRegex(ValueError, "Ambiguous.*snapshot"):
            self.lookup()
        with self.assertRaisesRegex(ValueError, "stale"):
            self.lookup(snapshot=first["parameter_catalog_snapshot_id"])
        self.assertEqual(self.lookup(snapshot=second["parameter_catalog_snapshot_id"])["maximum"], 30)

    def test_same_name_at_different_library_path_requires_snapshot(self):
        self.index()
        old = self.defs / "synthetic_gain"
        moved = self.defs / "another-library/synthetic_gain"
        moved.parent.mkdir()
        old.rename(moved)
        second = self.index()
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            self.lookup()
        self.assertEqual(self.lookup(snapshot=second["parameter_catalog_snapshot_id"])["definition_path"], str(moved))

    def test_source_definition_change_without_reindex_is_rejected(self):
        self.index()
        (self.defs / "synthetic_gain").write_text("modified", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "provenance"):
            self.lookup()

    def test_failed_pointer_publication_keeps_previous_generation(self):
        first = self.index()
        pointer = catalog._root() / "current.json"
        before = pointer.read_bytes()
        original = Path.replace

        def interrupted(path, target):
            if Path(target) == pointer:
                raise OSError("synthetic publication interruption")
            return original(path, target)

        with patch.object(Path, "replace", interrupted):
            with self.assertRaisesRegex(OSError, "interruption"):
                self.index(self.second_project())
        self.assertEqual(pointer.read_bytes(), before)
        self.assertEqual(self.lookup()["parameter_catalog_snapshot_id"], first["parameter_catalog_snapshot_id"])
        self.assertEqual(catalog.catalog_status()["snapshot_count"], 1)
        self.assertEqual(list(catalog._root().glob(".staging-*")), [])
        with self.assertRaisesRegex(ValueError, "outside.*subset"):
            self.lookup("synthetic_second")

    def test_db_and_audit_hash_mismatch_are_rejected(self):
        first = self.index()
        database = Path(first["database"]["path"])
        old = database.read_bytes()
        database.write_bytes(old + b"tampered")
        with self.assertRaisesRegex(ValueError, "DB hash"):
            self.lookup()
        self.assertEqual(catalog.catalog_status()["status"], "invalid")
        database.write_bytes(old)
        audit = database.with_name("audit.json")
        audit.write_text(audit.read_text(encoding="utf-8") + " ", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "audit hash"):
            self.lookup()

    def test_concurrent_writer_conflict_and_retry_preserve_both_projects(self):
        project_b = self.second_project()
        entered, release = Event(), Event()
        original = catalog.parse_parameter_schema

        def hold_first(body):
            entered.set()
            if not release.wait(10):
                raise AssertionError("Synthetic lock coordination timed out")
            return original(body)

        with patch.object(catalog, "parse_parameter_schema", hold_first), ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(self.index)
            self.assertTrue(entered.wait(10))
            try:
                with self.assertRaisesRegex(ValueError, "writer conflict"):
                    pool.submit(self.index, project_b).result(timeout=10)
            finally:
                release.set()
            first = first_future.result(timeout=10)
        second = self.index(project_b)
        self.assertEqual(self.lookup()["parameter_catalog_snapshot_id"], first["parameter_catalog_snapshot_id"])
        self.assertEqual(self.lookup("synthetic_second")["parameter_catalog_snapshot_id"], second["parameter_catalog_snapshot_id"])
        self.assertEqual(catalog.catalog_status()["snapshot_count"], 2)

    def test_project_change_during_index_keeps_previous_pointer(self):
        self.index()
        pointer = catalog._root() / "current.json"
        original_pointer = pointer.read_bytes()
        original = catalog.read_rtfx_dfx

        def changed(path):
            value = original(path)
            with zipfile.ZipFile(path, "a") as archive:
                archive.writestr("changed.txt", "changed during synthetic indexing")
            return value

        with patch.object(catalog, "read_rtfx_dfx", changed):
            with self.assertRaisesRegex(ValueError, "Project changed"):
                self.index()
        self.assertEqual(pointer.read_bytes(), original_pointer)
        self.assertEqual(catalog.catalog_status()["snapshot_count"], 1)

    def test_invalid_snapshot_and_pointer_paths_are_rejected(self):
        self.index()
        for value in ("../outside", "A" * 32, "0" * 32, "", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.lookup(snapshot=value)
        pointer = catalog._root() / "current.json"
        value = json.loads(pointer.read_text(encoding="utf-8"))
        value["snapshots"][0]["snapshot_id"] = "../outside"
        pointer.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "snapshot ID"):
            self.lookup()

    def test_definition_resolution_outside_root_is_rejected(self):
        outside = self.root / "outside-definition"
        outside.write_text((self.defs / "synthetic_gain").read_text(encoding="utf-8"), encoding="utf-8")
        with patch.object(catalog.DefinitionIndex, "resolve", return_value=(outside, None)):
            with self.assertRaisesRegex(ValueError, "Cannot resolve"):
                self.index()
        self.assertEqual(catalog.catalog_status()["status"], "missing")

    def test_legacy_reads_migrate_explicitly_and_preserve_original_bytes(self):
        database, audit = self.legacy()
        before = database.read_bytes(), audit.read_bytes()
        self.assertIsNone(self.lookup()["parameter_catalog_snapshot_id"])
        with self.assertRaisesRegex(ValueError, "migrate-parameters"):
            self.index()
        migrated = catalog.migrate_legacy()
        self.assertEqual((database.read_bytes(), audit.read_bytes()), before)
        self.assertEqual(migrated["migration"]["source_database_sha256"], sha256_file(database))
        self.assertFalse(migrated["migration"]["past_workflow_hashes_modified"])
        self.assertEqual(catalog.migrate_legacy(), migrated)
        self.assertEqual(self.lookup()["parameter_catalog_snapshot_id"], migrated["parameter_catalog_snapshot_id"])
        self.index(self.second_project())
        self.assertEqual(self.lookup()["maximum"], 10)

    def test_legacy_migration_refuses_mismatched_audit_and_stale_definition(self):
        database, audit = self.legacy()
        original = audit.read_bytes()
        value = json.loads(original)
        value["database"]["sha256"] = "0" * 64
        audit.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "DB hash"):
            catalog.migrate_legacy()
        audit.write_bytes(original)
        (self.defs / "synthetic_gain").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "provenance"):
            catalog.migrate_legacy()
        self.assertFalse((catalog._root() / "current.json").exists())

    def test_legacy_migration_rejects_unknown_database_schema(self):
        database, audit = self.legacy()
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("ALTER TABLE parameters ADD COLUMN unverified TEXT")
        value = json.loads(audit.read_text(encoding="utf-8"))
        value["database"]["sha256"] = sha256_file(database)
        audit.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "database schema"):
            catalog.migrate_legacy()
        self.assertFalse((catalog._root() / "current.json").exists())

    def test_definition_change_during_parse_is_not_published(self):
        self.index()
        original_pointer = (catalog._root() / "current.json").read_bytes()
        original = catalog.parse_parameter_schema

        def changed(body):
            schema = original(body)
            (self.defs / "synthetic_gain").write_text("changed", encoding="utf-8")
            return schema

        with patch.object(catalog, "parse_parameter_schema", changed):
            with self.assertRaisesRegex(ValueError, "Definition changed"):
                self.index()
        self.assertEqual((catalog._root() / "current.json").read_bytes(), original_pointer)
        self.assertEqual(catalog.catalog_status()["snapshot_count"], 1)

    def test_missing_published_generation_fails_closed(self):
        first = self.index()
        Path(first["database"]["path"]).with_name("audit.json").unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            self.lookup()
        self.assertEqual(catalog.catalog_status()["status"], "invalid")

    def test_legacy_migration_rejects_database_path_escape(self):
        _, audit = self.legacy()
        value = json.loads(audit.read_text(encoding="utf-8"))
        value["database"]["path"] = str(self.root / "outside.sqlite")
        audit.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "audit path"):
            catalog.migrate_legacy()

    def test_explicit_cli_migration_and_status_are_offline(self):
        self.legacy()
        from rtds_agent.cli import main
        from rtds_agent.knowledge import get_knowledge_status
        output = io.StringIO()
        with patch("socket.create_connection", side_effect=AssertionError("Unexpected network")), redirect_stdout(output):
            self.assertEqual(main(["knowledge", "migrate-parameters"]), 0)
            status = get_knowledge_status()
        self.assertEqual(json.loads(output.getvalue())["status"], "passed")
        self.assertTrue(status["parameter_index_ready"])
        self.assertEqual(status["parameter_catalog"]["snapshot_count"], 1)

    def test_patch_manifest_binds_selected_snapshot(self):
        indexed = self.index()
        from rtds_agent.core.structured_patch import build_single_parameter_request, apply_parameter_patch_request
        snapshot = indexed["parameter_catalog_snapshot_id"]
        request = build_single_parameter_request(str(self.project), 1, "synthetic_gain", "Gain", "1", "2",
                                                 context="subsystem:0", parameter_catalog_snapshot_id=snapshot)
        result = apply_parameter_patch_request(request)
        manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        evidence = manifest["request"]["operations"][0]["schema_evidence"]
        self.assertEqual(evidence["parameter_catalog_snapshot_id"], snapshot)
        self.assertEqual(evidence["parameter_database_sha256"], indexed["database"]["sha256"])
        self.assertEqual(evidence["api_version_evidence"], "not_observed")


if __name__ == "__main__":
    unittest.main()
