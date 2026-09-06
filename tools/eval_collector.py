"""Reconcile independently recorded Codex JSONL and evaluation MCP replies.

This is a local consistency boundary, not authentication of externally supplied
files. Only the explicit runner can describe its own observed model process.
"""
import json
import math

SKILL_CATALOG_NOTICE = ("Skill descriptions were shortened to fit the skills context budget. Codex can still see every skill, "
                        "but some descriptions are shorter. Disable unused skills or plugins to leave more room for the rest.")


def loads(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("Non-finite JSON number")

    value = json.loads(raw, object_pairs_hook=unique, parse_constant=constant)
    budget = [0]

    def check(item, depth=0):
        budget[0] += 1
        if depth > 32 or budget[0] > 100000:
            raise ValueError("JSON tree exceeds bounds")
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("Non-finite JSON number")
        if isinstance(item, dict):
            for child in item.values():
                check(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                check(child, depth + 1)
    check(value)
    return value


def lines(raw):
    if not isinstance(raw, bytes) or len(raw) > 16 * 1024 * 1024:
        raise ValueError("Bounded JSONL bytes required")
    chunks = raw.decode("utf-8").splitlines()
    if len(chunks) > 4000 or any(not line.strip() or len(line) > 2 * 1024 * 1024 for line in chunks):
        raise ValueError("Invalid JSONL line/count bound")
    records = [loads(line) for line in chunks]
    if any(type(record) is not dict for record in records):
        raise ValueError("JSONL records must be objects")
    return records


def same(left, right):
    return json.dumps(left, sort_keys=True, allow_nan=False, separators=(",", ":")) == json.dumps(
        right, sort_keys=True, allow_nan=False, separators=(",", ":"))


def _envelope(result):
    if type(result) is not dict:
        raise ValueError("Missing MCP result")
    candidates = []
    for key in ("structured_content", "structuredContent"):
        if result.get(key) is not None:
            candidates.append(result[key])
    for block in result.get("content", []):
        if type(block) is dict and block.get("type") == "text":
            try:
                value = loads(block["text"])
            except (ValueError, KeyError, TypeError):
                continue
            if type(value) is dict and "call_id" in value:
                candidates.append(value)
    if not candidates or any(not same(candidates[0], value) for value in candidates[1:]):
        raise ValueError("Missing or conflicting MCP recording envelopes")
    return candidates[0]


def reconcile(events_raw, journal_raw, final_raw):
    """Require one completed model turn and one-to-one exact MCP event pairing."""
    events, journal = lines(events_raw), lines(journal_raw)
    pending, completed = {}, {}
    for row in journal:
        if row.get("schema_version") != "1.0" or type(row.get("call_id")) is not str:
            raise ValueError("Invalid MCP journal identity")
        ident = row["call_id"]
        if row.get("event") == "started":
            if ident in pending or ident in completed or len(pending) + len(completed) >= 32:
                raise ValueError("Duplicate or excessive MCP call")
            pending[ident] = row
        elif row.get("event") == "completed":
            start = pending.pop(ident, None)
            if start is None or not all(same(start.get(key), row.get(key)) for key in ("tool", "arguments")):
                raise ValueError("MCP completion has no matching intent")
            if any(type(row.get(key)) is not bool for key in ("is_error", "dispatched", "protected_unchanged")):
                raise ValueError("MCP completion flags are not booleans")
            completed[ident] = row
        else:
            raise ValueError("Unknown MCP journal record")
    if pending:
        raise ValueError("Unfinished MCP call")
    thread_ids, starts, finishes = [], 0, 0
    phase = "initial"
    host_started, host_finished, observed_ids, messages, unexpected = {}, set(), set(), [], {}
    notices = []
    for event in events:
        kind = event.get("type")
        if kind == "thread.started":
            if phase != "initial":
                raise ValueError("Out-of-order Codex thread")
            thread_ids.append(event.get("thread_id"))
            phase = "thread"
        elif kind == "turn.started":
            if phase != "thread":
                raise ValueError("Out-of-order model turn start")
            starts += 1
            phase = "active"
        elif kind == "turn.completed":
            if phase != "active" or host_started:
                raise ValueError("Model turn completed before tool completion")
            finishes += 1
            phase = "finished"
        elif kind in {"turn.failed", "error"}:
            raise ValueError("Codex reported a failed model turn")
        elif kind in {"item.started", "item.updated", "item.completed"}:
            item = event.get("item")
            if (kind == "item.completed" and phase in {"thread", "active"} and type(item) is dict and
                    item.get("type") == "error" and item.get("message") == SKILL_CATALOG_NOTICE):
                notices.append(item["message"])
                continue
            if phase != "active":
                raise ValueError("Codex item is outside the active turn")
            if type(item) is not dict or type(item.get("id")) is not str:
                raise ValueError("Invalid Codex item")
            ident, item_type = item["id"], item.get("type")
            if item_type == "mcp_tool_call":
                if kind == "item.started":
                    if ident in host_started or ident in host_finished:
                        raise ValueError("Duplicate host MCP identity")
                    host_started[ident] = item
                elif kind == "item.completed":
                    start = host_started.pop(ident, None)
                    if start is None or ident in host_finished:
                        raise ValueError("Host MCP completion lacks matching start")
                    if not all(same(start.get(key), item.get(key)) for key in ("server", "tool", "arguments")):
                        raise ValueError("Host MCP arguments changed")
                    if item.get("server") != "rtds_eval":
                        raise ValueError("Unexpected MCP server")
                    envelope = _envelope(item.get("result"))
                    call_id = envelope.get("call_id")
                    if call_id in observed_ids or call_id not in completed or not same(envelope, completed[call_id]):
                        raise ValueError("MCP host/server transcript mismatch")
                    if not same(item.get("arguments"), envelope["arguments"]) or item.get("tool") != envelope["tool"]:
                        raise ValueError("MCP host/server call identity mismatch")
                    if item.get("status") not in {"completed", "failed"}:
                        raise ValueError("Incomplete host MCP status")
                    observed_ids.add(call_id)
                    host_finished.add(ident)
            elif item_type == "agent_message":
                if kind == "item.completed":
                    messages.append(item.get("text"))
            elif item_type not in {"reasoning", "todo_list"}:
                if ident in unexpected and unexpected[ident] != str(item_type):
                    raise ValueError("Host item changed type")
                unexpected[ident] = str(item_type)
        else:
            raise ValueError("Unreviewed Codex event type: " + str(kind))
    if (len(thread_ids) != 1 or type(thread_ids[0]) is not str or not thread_ids[0] or
            starts != 1 or finishes != 1 or host_started or observed_ids != set(completed)):
        raise ValueError("Incomplete or mixed model/MCP run")
    if not isinstance(final_raw, bytes) or len(final_raw) > 65536:
        raise ValueError("Bounded final answer bytes required")
    text = final_raw.decode("utf-8").strip()
    if not messages or not isinstance(messages[-1], str) or messages[-1].strip() != text:
        raise ValueError("Saved final answer differs from Codex output")
    final = loads(text)
    calls = [{key: row[key] for key in ("call_id", "tool", "arguments", "is_error", "result", "dispatched")}
             for row in completed.values()]
    return {"calls": calls, "final": final, "thread_id": thread_ids[0], "host_notices": notices,
            "runner": {"model_completed": True, "tool_trace_matched": True,
                       "protected_unchanged": all(row["protected_unchanged"] for row in completed.values()),
                       "unexpected_host_tools": list(unexpected.values()), "cleanup_verified": False}}
