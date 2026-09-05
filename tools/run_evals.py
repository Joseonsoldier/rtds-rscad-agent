"""Score recorded tool traces against engineering benchmark contracts.

This does not run an LLM or authenticate an externally supplied trace. Scripted
test traces validate the scorer only, not model skill selection or task quality.
"""
import argparse
import json
from pathlib import Path

TASKS = Path(__file__).resolve().parents[1] / "evals/tasks.json"


def score(task,trace):
    if not isinstance(trace,dict) or set(trace) != {"calls","final_state","evidence"}:
        raise ValueError("Trace requires exactly calls, final_state and evidence")
    calls=trace["calls"]
    if not isinstance(calls,list) or len(calls)>500 or any(not isinstance(c,dict) or set(c)!={"tool","is_error","arguments"} or not isinstance(c["tool"],str) or type(c["is_error"]) is not bool or not isinstance(c["arguments"],dict) for c in calls):
        raise ValueError("Invalid bounded tool trace")
    if not isinstance(trace["evidence"],dict): raise ValueError("Trace evidence must be an object")
    names=[c["tool"] for c in calls]
    checks={"required_tools":set(task["required_tools"]) <= set(names),
            "forbidden_tools_absent":not set(names) & set(task["forbidden_tools"]),
            "final_state":trace["final_state"]==task["expected_final_state"],
            "required_evidence":all(key in trace["evidence"] and trace["evidence"][key] is not None for key in task["required_evidence"]),
            "rejection_observed":not task.get("requires_tool_error",False) or any(c["is_error"] and c["tool"] in task["required_tools"] for c in calls),
            "suite_modes":all(c["arguments"].get("request",{}).get("mode") in task.get("allowed_suite_modes",[]) for c in calls if c["tool"] == "run_experiment_suite"),
            "unsafe_suite_rejected":all(c["is_error"] for c in calls if c["tool"] == "run_experiment_suite" and c["arguments"].get("request",{}).get("mode") == "execute")}
    for key,value in task.get("evidence_assertions",{}).items():
        checks["evidence:"+key]=trace["evidence"].get(key)==value
    return {"task_id":task["task_id"],"status":"passed" if all(checks.values()) else "failed","checks":checks,
            "scope":"recorded trace contract only; authenticity and engineering meaning not independently verified",
            "llm_executed":False,"live_calls_made":False}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--case",required=True)
    parser.add_argument("--trace",type=Path,required=True)
    args=parser.parse_args()
    tasks=json.loads(TASKS.read_text(encoding="utf-8"))["tasks"]
    matches=[t for t in tasks if t["task_id"]==args.case]
    if len(matches)!=1: parser.error("Unknown benchmark case")
    if args.trace.stat().st_size>2*1024*1024: parser.error("Trace exceeds 2 MiB")
    result=score(matches[0],json.loads(args.trace.read_text(encoding="utf-8")))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result["status"]=="passed" else 1


if __name__=="__main__": raise SystemExit(main())
