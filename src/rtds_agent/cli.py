"""Install, diagnose and serve local tools. Never modifies host MCP settings."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys
from . import __version__
from .settings import Settings, get_settings, config_path, user_data_dir


def _print(value, *, stderr=False):
    print(json.dumps(value, indent=2, ensure_ascii=False), file=sys.stderr if stderr else sys.stdout)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="rtds-agent")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Create settings; execution remains inactive")
    init.add_argument("--rscad-home", type=Path)
    init.add_argument("--data-dir", type=Path, default=user_data_dir())
    init.add_argument("--source-root", type=Path, action="append")
    init.add_argument("--document-root", type=Path, action="append")
    init.add_argument("--vector-store-id", default="")
    sub.add_parser("extensions", help="Read installed extension API declarations; no connection")
    sub.add_parser("doctor", help="Static checks; no RSCAD connection")
    sub.add_parser("mcp-config", help="Print a Codex TOML entry")
    rulepacks = sub.add_parser('rulepacks', help='Read optional domain criterion templates; no model or native operation')
    rulepacks.add_argument('action', choices=['list'])
    diagnostic = sub.add_parser('diagnostics', help='Inspect supplied Compile parser evidence; no native action')
    ds = diagnostic.add_subparsers(dest='action', required=True)
    ds.add_parser('list', help='List bounded observed parser formats and taxonomy')
    corpus = ds.add_parser('corpus', help='Check an existing source-bound parser corpus without writing')
    corpus.add_argument('manifest')
    mcp = sub.add_parser("mcp")
    mcp.add_argument("action", choices=["serve"])
    mcp.add_argument("--profile", choices=["core", "engineering", "full"], default="full")
    knowledge = sub.add_parser("knowledge")
    ks = knowledge.add_subparsers(dest="action", required=True)
    ks.add_parser("index")
    params = ks.add_parser("parameters")
    params.add_argument("--project", required=True)
    ks.add_parser("migrate-parameters", help="Explicitly copy verified legacy parameter evidence into an immutable snapshot")
    graph = ks.add_parser("graph", help="Build or query a local component knowledge graph")
    gs = graph.add_subparsers(dest="graph_action", required=True)
    graph_build = gs.add_parser("build", help="Index installed definitions and explicitly selected saved projects; no native calls")
    graph_build.add_argument("--project", action="append", default=[])
    graph_build.add_argument("--annotations", help="Optional source-bound advisory annotations JSON")
    gs.add_parser("status", help="List published graph identities without building")
    graph_query = gs.add_parser("query", help="Read a current source-checked graph")
    graph_query.add_argument("--graph-id", required=True)
    graph_query.add_argument("--mode", choices=["search", "get", "neighbors"], default="search")
    graph_query.add_argument("--query")
    graph_query.add_argument("--node-id")
    graph_query.add_argument("--depth", type=int)
    graph_query.add_argument("--edge-kind", action="append")
    graph_query.add_argument("--offset", type=int, default=0)
    graph_query.add_argument("--limit", type=int, default=20)
    upload = ks.add_parser("upload")
    upload.add_argument("paths", nargs="+")
    upload.add_argument("--allow-upload", action="store_true")
    policy = sub.add_parser("policy")
    ps = policy.add_subparsers(dest="action", required=True)
    ps.add_parser("show")
    disable = ps.add_parser("disable")
    disable.add_argument("--operator", required=True)
    enable = ps.add_parser("enable")
    enable.add_argument("--actions", nargs="+", choices=["compile", "offline_test", "runtime_start_stop", "runtime_controls"], required=True)
    enable.add_argument("--racks", nargs="+", type=int, required=True)
    enable.add_argument("--operator", required=True)
    enable.add_argument("--acknowledge-simulation-control", action="store_true")
    skills = sub.add_parser("skills", help="List or explicitly export the bundled skill catalog")
    ss = skills.add_subparsers(dest="action", required=True)
    ss.add_parser("list", help="List packaged skills and resource hashes")
    export = ss.add_parser("export", help="Export to an explicit directory without overwriting")
    export.add_argument("--destination", type=Path, required=True)
    export.add_argument("--dry-run", action="store_true")
    from .skill_catalog import SKILL_NAMES
    export.add_argument("--skill", choices=SKILL_NAMES, action="append", dest="skill_names")
    sub.add_parser("demo", help="Synthetic mock workflow; no key or rack")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            path = config_path()
            if path.exists():
                raise ValueError("Configuration exists; edit it deliberately instead of overwriting")
            home = args.rscad_home.resolve() if args.rscad_home else None
            sources = args.source_root if args.source_root is not None else ([home / "Examples"] if home else [])
            documents = args.document_root if args.document_root is not None else ([home / "DOC"] if home else [])
            settings = Settings(args.data_dir.resolve(), home, tuple(p.resolve() for p in sources),
                                tuple(p.resolve() for p in documents), args.vector_store_id).validated()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as stream:
                json.dump(settings.as_dict(), stream, indent=2, ensure_ascii=False)
                stream.write("\n")
            settings.projects_root.mkdir(parents=True, exist_ok=True)
            _print({"config": str(path), "execution": "inactive until operator opt-in"})
        elif args.command == "extensions":
            from .extension_support import inspect_extension_support
            _print(inspect_extension_support())
        elif args.command == "doctor":
            from .policy import read_policy
            from .integrity import verify_release
            from .knowledge import get_knowledge_status
            settings = get_settings()
            result = {"version": __version__, "python": sys.version.split()[0], "platform": sys.platform,
                      "configuration": str(config_path()), "knowledge": get_knowledge_status(),
                      "poppler_available": bool(shutil.which("pdftoppm")), "policy": read_policy(settings),
                      "release_integrity": verify_release(), "live_calls_made": False}
            from .capabilities import get_capabilities
            result["capabilities"] = get_capabilities()
            audit = result["capabilities"]["runtime_api_inspection"]
            if audit["status"] == "passed":
                result["rscad_api"] = {"status": audit["status"], "checks": audit["checks"]}
            else:
                result["rscad_api"] = {"status": "not_ready", "reason": audit.get("reason", audit["status"])}
            _print(result)
        elif args.command == "mcp-config":
            print('[mcp_servers.rtds_agent]')
            print('command = ' + json.dumps(sys.executable))
            print('args = ["-m", "rtds_agent", "mcp", "serve"]')
            print('env_vars = ["OPENAI_API_KEY", "OPENAI_VECTOR_STORE_ID"]')
            print('[mcp_servers.rtds_agent.env]')
            print('RTDS_AGENT_CONFIG = ' + json.dumps(str(config_path())))
        elif args.command == "mcp":
            from .mcp_server import main as serve
            serve(profile=args.profile)
        elif args.command == "knowledge":
            from .knowledge import index_documents, index_parameters, upload_documents
            if args.action == "index":
                _print(index_documents())
            elif args.action == "parameters":
                _print(index_parameters(args.project))
            elif args.action == "migrate-parameters":
                from .core.parameter_catalog import migrate_legacy
                _print(migrate_legacy())
            elif args.action == "graph":
                from .component_knowledge import build_component_knowledge, query_component_knowledge
                if args.graph_action == "build":
                    _print(build_component_knowledge(args.project, args.annotations))
                elif args.graph_action == "status":
                    from .core.component_graph_store import status
                    _print(status())
                else:
                    request = {'graph_id': args.graph_id, 'mode': args.mode, 'offset': args.offset, 'limit': args.limit}
                    for name, value in (('query', args.query), ('node_id', args.node_id), ('depth', args.depth), ('edge_kinds', args.edge_kind)):
                        if value is not None:
                            request[name] = value
                    _print(query_component_knowledge(request))
            else:
                result = upload_documents(args.paths, allow_upload=args.allow_upload)
                _print(result)
                return 0 if result["all_indexed"] else 1
        elif args.command == "policy":
            from .policy import read_policy, configure_policy, execution_lock
            settings = get_settings()
            if args.action == "show":
                _print(read_policy(settings))
            else:
                if args.action == "enable" and not args.acknowledge_simulation_control:
                    raise ValueError("Read docs/SAFETY.md and provide --acknowledge-simulation-control for one-time operator consent")
                with execution_lock(settings):
                    _print(configure_policy(settings, args.actions if args.action == "enable" else [],
                                            args.racks if args.action == "enable" else [], args.operator))
        elif args.command == "skills":
            from .skill_catalog import list_skills, export_skills
            if args.action == "list":
                _print(list_skills())
            else:
                _print(export_skills(args.destination, dry_run=args.dry_run, names=args.skill_names))
        elif args.command == 'rulepacks':
            from .core.power_system_rules import rulepack_catalog
            _print(rulepack_catalog())
        elif args.command == 'diagnostics':
            if args.action == 'list':
                from .core.compile_diagnostics import parser_catalog
                _print(parser_catalog())
            else:
                from .compile_corpus import inspect_compile_corpus
                result = inspect_compile_corpus(args.manifest)
                _print(result)
                return 0 if result['status'] == 'passed' else 1
        elif args.command == "demo":
            from .demo import run_demo
            _print(run_demo())
        return 0
    except Exception as exc:
        if type(exc).__module__.startswith("openai"):
            _print({"error": type(exc).__name__, "message": "OpenAI request failed; check project permissions, store ID, quota and network. No key is logged."})
        else:
            _print({"error": type(exc).__name__, "message": str(exc)}, stderr=args.command == "mcp")
        return 1
