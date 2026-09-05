"""Packaged skill contracts and isolated, non-overwriting export behavior."""
from __future__ import annotations
import test_environment  # isolate config and credentials before application imports

import ast
import asyncio
from contextlib import redirect_stdout
import io
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import queue
from pathlib import Path
import re
import subprocess
import sys
import threading
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from rtds_agent import skill_catalog


class SkillCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rtds-skills-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_nine_packaged_skills_frontmatter_links_and_hashes(self):
        catalog = skill_catalog.list_skills()
        expected = {"rscad-understand-model", "rscad-edit-model", "rscad-diagnose-compile",
                    "rtds-run-experiment", "rtds-validate-results", "rtds-ground-with-manuals", "rtds-read-documentation",
                    "rtds-derive-test-requirements", "rtds-verify-grid-code"}
        self.assertEqual({entry["name"] for entry in catalog["skills"]}, expected)
        self.assertFalse(catalog["host_configuration_changed"])
        for entry in catalog["skills"]:
            files = skill_catalog._bundled_files(entry["name"])
            body = files["SKILL.md"].decode("utf-8")
            for section in ("Use when", "Do not use when", "Prerequisites", "Tool order", "Completion", "On failure"):
                self.assertIn(f"## {section}\n", body)
            for file in entry["files"]:
                self.assertEqual(hashlib.sha256(files[file["path"]]).hexdigest(), file["sha256"])
            for link in re.findall(r"\[[^\]]+\]\(([^)]+)\)", body):
                self.assertNotIn("..", Path(link).parts)
                self.assertIn(link, files, f"Broken packaged reference in {entry['name']}")

    def test_documented_tool_names_and_named_arguments_exist(self):
        package = Path(skill_catalog.__file__).parent
        functions = {}
        for path in package.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions[node.name] = {arg.arg for arg in node.args.args + node.args.kwonlyargs}
        found = 0
        for name in skill_catalog.SKILL_NAMES:
            body = skill_catalog._bundled_files(name)["SKILL.md"].decode("utf-8")
            for tool, arguments in re.findall(r"`([a-z_]+)\(([a-z_, ]*)\)`", body):
                with self.subTest(skill=name, tool=tool):
                    self.assertIn(tool, functions)
                    provided = {arg.strip() for arg in arguments.split(",") if arg.strip()}
                    self.assertLessEqual(provided, functions[tool])
                    found += 1
        self.assertGreater(found, 20)

    def test_documented_calls_match_actual_advertised_mcp_schema(self):
        from rtds_agent.mcp_server import server
        advertised = {tool.name: tool.input_schema for tool in asyncio.run(server.list_tools())}
        for name in skill_catalog.SKILL_NAMES:
            body = skill_catalog._bundled_files(name)["SKILL.md"].decode("utf-8")
            for tool, arguments in re.findall(r"`([a-z_]+)\(([a-z_, ]*)\)`", body):
                with self.subTest(skill=name, tool=tool):
                    self.assertIn(tool, set(advertised))
                    provided = {arg.strip() for arg in arguments.split(",") if arg.strip()}
                    schema = advertised[tool]
                    self.assertLessEqual(provided, set(schema.get("properties", {})))
                    self.assertLessEqual(set(schema.get("required", [])), provided)

    def test_cli_list_dry_run_export_and_conflict_without_config(self):
        from rtds_agent.cli import main
        target = self.root / "cli-export"
        for arguments, expected in ((["list"], 0),
                                    (["export", "--destination", str(target), "--dry-run"], 0),
                                    (["export", "--destination", str(target)], 0),
                                    (["export", "--destination", str(target)], 1)):
            with self.subTest(arguments=arguments):
                stream = io.StringIO()
                with patch.dict(os.environ, {"RTDS_AGENT_CONFIG": str(self.root / "absent.json")}), redirect_stdout(stream):
                    self.assertEqual(main(["skills", *arguments]), expected)
                payload = json.loads(stream.getvalue())
                if "--dry-run" in arguments:
                    self.assertEqual(payload["files_written"], 0)
                    self.assertFalse(target.exists())
                if expected == 1:
                    self.assertEqual(payload["error"], "FileExistsError")
        self.assertEqual(len(list(target.glob("*/SKILL.md"))), 9)

    def test_release_integrity_protects_bundled_skill_text(self):
        import rtds_agent.integrity as integrity
        root = self.root / "package"
        skill = root / "skills" / "example" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_bytes(b"original instruction")
        (root / "integrity.py").write_bytes(b"# synthetic package")
        manifest = {"files": {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in root.rglob("*") if path.is_file()}}
        (root / "release_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with patch.object(integrity, "__file__", str(root / "integrity.py")):
            self.assertEqual(integrity.verify_release()["status"], "passed")
            skill.write_bytes(b"altered instruction")
            with self.assertRaises(PermissionError):
                integrity.verify_release()
            skill.write_bytes(b"original instruction")
            (skill.parent / "unexpected.md").write_bytes(b"extra instruction")
            with self.assertRaises(PermissionError):
                integrity.verify_release()

    def test_dry_run_requires_no_configuration_and_writes_nothing(self):
        target = self.root / "new" / "export"
        with patch.dict(os.environ, {"RTDS_AGENT_CONFIG": str(self.root / "missing-config"),
                                     "OPENAI_API_KEY": "", "OPENAI_VECTOR_STORE_ID": ""}, clear=True):
            result = skill_catalog.export_skills(target, dry_run=True)
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["files_written"], 0)
        self.assertFalse((self.root / "new").exists())
        self.assertFalse(result["host_discovery_verified"])

    def test_export_reproduces_all_packaged_bytes_and_preserves_other_files(self):
        target = self.root / "skills"
        target.mkdir()
        original = target / "host-config.toml"
        original.write_bytes(b"untouched")
        result = skill_catalog.export_skills(target)
        self.assertEqual(result["status"], "exported")
        self.assertEqual(original.read_bytes(), b"untouched")
        for name in skill_catalog.SKILL_NAMES:
            for relative, body in skill_catalog._bundled_files(name).items():
                self.assertEqual((target / name / relative).read_bytes(), body)
        self.assertEqual(result["files_written"], len(result["files"]))

    def test_all_conflicts_rejected_before_any_write_including_dry_run(self):
        target = self.root / "skills"
        target.mkdir()
        conflict = target / skill_catalog.SKILL_NAMES[-1]
        conflict.mkdir()
        marker = conflict / "SKILL.md"
        marker.write_bytes(b"user authored")
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run), self.assertRaises(FileExistsError):
                skill_catalog.export_skills(target, dry_run=dry_run)
            self.assertEqual(sorted(path.name for path in target.iterdir()), [conflict.name])
            self.assertEqual(marker.read_bytes(), b"user authored")

    def test_selected_subset_and_invalid_names(self):
        selected = ["rscad-edit-model"]
        result = skill_catalog.export_skills(self.root / "one", names=selected)
        self.assertEqual(result["skills"], selected)
        self.assertEqual([path.name for path in (self.root / "one").iterdir()], selected)
        for names in ([], ["../escape"], ["rscad-edit-model"] * 2, ["no-such-skill"]):
            with self.subTest(names=names), self.assertRaises(ValueError):
                skill_catalog.export_skills(self.root / "invalid", names=names)
        self.assertFalse((self.root / "invalid").exists())

    def test_destination_path_boundaries(self):
        for destination in ("", self.root / "nested" / ".." / "escape", Path(self.root.anchor),
                            Path(skill_catalog.__file__).parent / "skills" / "rewrite"):
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                skill_catalog.export_skills(destination)
        target = self.root / "file"
        target.write_bytes(b"existing")
        with self.assertRaises(ValueError):
            skill_catalog.export_skills(target / "nested")
        self.assertEqual(target.read_bytes(), b"existing")

    def test_symlink_destination_and_ancestor_rejected(self):
        real = self.root / "real"
        real.mkdir()
        link = self.root / "link"
        try:
            link.symlink_to(real, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"OS does not permit test symlink: {exc.errno}")
        for target in (link, link / "nested"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                skill_catalog.export_skills(target)
        self.assertEqual(list(real.iterdir()), [])

    @unittest.skipUnless(sys.platform == "win32", "Windows junction boundary")
    def test_windows_junction_destination_and_ancestor_rejected(self):
        import _winapi
        real = self.root / "real-junction-target"
        real.mkdir()
        link = self.root / "junction"
        _winapi.CreateJunction(str(real), str(link))
        self.addCleanup(link.rmdir)
        self.assertTrue(link.is_junction())
        for target in (link, link / "nested"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                skill_catalog.export_skills(target)
        self.assertEqual(list(real.iterdir()), [])

    def test_failed_publication_removes_only_this_exports_files(self):
        target = self.root / "skills"
        target.mkdir()
        marker = target / "keep.txt"
        marker.write_bytes(b"keep")
        original_open = Path.open
        writes = 0

        def fail_second_write(path, mode="r", *args, **kwargs):
            nonlocal writes
            if mode == "xb":
                writes += 1
                if writes == 2:
                    raise OSError("synthetic publication failure")
            return original_open(path, mode, *args, **kwargs)

        with patch.object(Path, "open", fail_second_write), self.assertRaises(OSError):
            skill_catalog.export_skills(target)
        self.assertEqual(list(target.iterdir()), [marker])
        self.assertEqual(marker.read_bytes(), b"keep")

    def test_concurrent_exports_never_overwrite_or_merge(self):
        target = self.root / "skills"
        target.mkdir()

        def export():
            try:
                return skill_catalog.export_skills(target)["status"]
            except FileExistsError:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: export(), range(2)))
        self.assertCountEqual(outcomes, ["exported", "conflict"])
        for name in skill_catalog.SKILL_NAMES:
            self.assertTrue((target / name / "SKILL.md").is_file())

    @unittest.skipUnless(os.environ.get("RTDS_TEST_CODEX_DISCOVERY") == "1", "opt-in installed Codex discovery")
    def test_installed_codex_discovers_temporary_repo_skills(self):
        project = self.root / "project"
        project.mkdir()
        (project / ".git").mkdir()
        child_home = self.root / "codex-home"
        child_home.mkdir()
        skill_catalog.export_skills(project / ".agents" / "skills")
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(("OPENAI_", "RTDS_", "RSCAD_"))}
        environment.update({"CODEX_HOME": str(child_home), "HOME": str(self.root), "USERPROFILE": str(self.root)})
        process = subprocess.Popen(["codex", "app-server", "--stdio", "-c", "analytics.enabled=false"],
                                   cwd=project, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                   creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        responses = queue.Queue()

        def reader():
            for line in process.stdout:
                try:
                    responses.put(json.loads(line))
                except json.JSONDecodeError:
                    pass

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()

        def send(payload):
            process.stdin.write(json.dumps(payload) + "\n")
            process.stdin.flush()

        def receive(expected):
            for _ in range(50):
                payload = responses.get(timeout=20)
                if payload.get("id") == expected:
                    self.assertNotIn("error", payload)
                    return payload["result"]
            self.fail("No matching Codex discovery response")

        try:
            send({"id": 1, "method": "initialize", "params": {
                "clientInfo": {"name": "rtds-skill-discovery-test", "version": "1.0"}}})
            receive(1)
            send({"method": "initialized"})
            send({"id": 2, "method": "skills/list", "params": {"cwds": [str(project)], "forceReload": True}})
            entry = receive(2)["data"][0]
            ours = [item for item in entry["skills"] if item["name"] in skill_catalog.SKILL_NAMES]
            self.assertEqual({item["name"] for item in ours}, set(skill_catalog.SKILL_NAMES))
            self.assertEqual(entry["errors"], [])
            for item in ours:
                self.assertEqual(item["scope"], "repo")
                self.assertTrue(item["enabled"])
                self.assertTrue(Path(item["path"]).resolve().is_relative_to(project))
        finally:
            process.terminate()
            process.communicate(timeout=10)
            thread.join(timeout=5)

    def test_zip_import_can_read_and_export_resources_without_source_checkout(self):
        package = Path(skill_catalog.__file__).parent
        bundle = self.root / "isolated-package.zip"
        with zipfile.ZipFile(bundle, "w") as archive:
            for relative in ("__init__.py", "skill_catalog.py"):
                archive.write(package / relative, "rtds_agent/" + relative)
            for name in skill_catalog.SKILL_NAMES:
                archive.writestr(f"rtds_agent/skills/{name}/", b"")
                for relative, body in skill_catalog._bundled_files(name).items():
                    archive.writestr(f"rtds_agent/skills/{name}/{relative}", body)
        script = ("import sys,json; sys.path.insert(0,sys.argv[1]); "
                  "from rtds_agent.skill_catalog import list_skills,export_skills; "
                  "print(json.dumps({'count':len(list_skills()['skills']),"
                  "'export':export_skills(sys.argv[2])}))")
        completed = subprocess.run([sys.executable, "-I", "-c", script, str(bundle), str(self.root / "zip-export")],
                                   cwd=self.root, capture_output=True, text=True, timeout=30, check=True)
        result = json.loads(completed.stdout)
        self.assertEqual(result["count"], 9)
        self.assertEqual(result["export"]["status"], "exported")


if __name__ == "__main__":
    unittest.main()
