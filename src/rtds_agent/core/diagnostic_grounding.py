"""Ground saved exception categories in exact installed SDK class declarations."""
from rtds_agent.api_discovery import lookup_rscad_api
from rtds_agent.knowledge import search_rtds_local

KNOWN_EXCEPTIONS = {
    "CommunicationError": ("rtds.error.CommunicationError", "Communication failure reported by the installed SDK", "Inspect transport/setup evidence and the exact local connection settings"),
    "ConnectionSetupError": ("rtds.error.ConnectionSetupError", "Connection setup failure reported by the installed SDK", "Review the installed setup API and local application state before an authorized retry"),
    "RSCADError": ("rtds.error.RSCADError", "Remote command or surrounding SDK processing failed; exact cause unresolved", "Inspect the complete native message and exact operation before proposing a model edit"),
}


def ground_diagnostic(row, component, document):
    result = {"likely_causes":[],"suggested_recovery":[],"automatic_repair":False,
              "native_log_grammar":"unqualified","native_message_code":"unresolved","component_evidence":None}
    if component is not None:
        result["component_evidence"] = {"context":component["context"],"uuid":component["uuid"],
            "component_type":component["component_type"],"snapshot_id":document["snapshot_id"],
            "definition":document["definition_evidence"].get(component["component_type"])}
    kind = row.get("type")
    if kind in KNOWN_EXCEPTIONS:
        symbol,cause,recovery = KNOWN_EXCEPTIONS[kind]
        evidence = lookup_rscad_api(symbol)
        result["api_evidence"] = evidence
        if evidence["status"] == "found":
            result["likely_causes"] = [{"rank":1,"cause":cause,"basis":"reported exception type plus installed class declaration",
                                         "confidence":"category_only; root cause not established"}]
            result["suggested_recovery"] = [recovery]
    # Bounded local-only discovery. Results are references, never instructions.
    query = kind if kind in KNOWN_EXCEPTIONS else component["component_type"] if component else None
    if query:
        try:
            result["manual_evidence"] = search_rtds_local(query,top_k=3)
        except (ValueError,OSError) as exc:
            result["manual_evidence"] = {"status":"unresolved","reason":str(exc)}
    return result
