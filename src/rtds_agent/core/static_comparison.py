"""Shared normalized parsed-net comparison; no engineering equivalence claim."""
import hashlib
import json
from typing import Any

def topology_signature(document: dict[str, Any]) -> str:
    net_rows = []
    for net in document["nets"]:
        members = []
        for member in net["members"]:
            if str(member["atom"]).startswith("port:"):
                members.append((
                    "port",
                    str(member["context"]),
                    int(member["component_id"]),
                    str(member["port"]),
                    str(member["domain"]),
                    str(member.get("phase")),
                ))
            else:
                start = tuple(member["start"])
                end = tuple(member["end"])
                endpoints = sorted((start, end))
                members.append((
                    "segment",
                    str(member["context"]),
                    int(member["component_id"]),
                    str(member["domain"]),
                    str(member.get("phase")),
                    endpoints[0],
                    endpoints[1],
                ))
        net_rows.append((
            str(net["domain"]),
            tuple(sorted(members, key=repr)),
        ))
    serialized = json.dumps(sorted(net_rows, key=repr), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
