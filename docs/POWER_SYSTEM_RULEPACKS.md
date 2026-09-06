# Power-system rule packs

`check_rscad_model(..., rulepacks=None)` accepts an optional schema 1.0 request for explicit, read-only mathematical checks. The request binds to the exact `input_project_sha256` and declares one or more typed packs with parameter bindings and rules. All checks are opt-in; existing `electrical_rules` behavior is preserved. The rule pack can report a check, but it does not edit a model, create Runtime authority, operate a rack, or establish physical acceptance.

The ten supported domains are `source`, `transformer`, `line`, `synchronous_machine`, `induction_machine`, `converter`, `gfm`, `gfl`, `bess`, and `protection`. Rule checks use fixed templates; arbitrary code and automatic component matching are unavailable. A binding records exact context, component ID and type, definition hash, parameter, expected raw value, stored-versus-definition-default origin, quantity, exact units, declared basis, optional per-unit base, and explicit selector conditions. Each rule carries its source reference, scope, severity, confidence and assumptions. Stale hashes, type/unit/selector mismatches and unsupported content are refused or reported inconclusive.

Every rule source must identify the used definition's current exact path and SHA plus a locator. Manual references may add grounding, but a hash alone does not establish an official RTDS claim. Installed-manual interpretation remains cautious: source frequency `0` can be allowed, transformer loss/resistance `0` can be allowed, `Tmva` may be a common 100 MVA base rather than a physical rating, and generator/transformer ratings have no universal order or equality. Do not assume line-to-line versus phase, RMS versus peak, or per-unit equivalence without an explicit supported unit family and declared assumption. Current/electrical math is limited to explicit supported units and assumptions, including balanced three-phase operation where declared.

A short schema-valid positive/nonnegative example, using placeholders rather than vendor data, is:

```json
{
  "schema_version": "1.0",
  "input_project_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "packs": [{
    "pack_id": "example",
    "domain": "source",
    "bindings": [{
      "binding_id": "v1",
      "context": "<exact-context>",
      "component_id": 1,
      "component_type": "<component-type>",
      "definition_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
      "parameter": "<parameter>",
      "expected_value": "<raw-value>",
      "origin": "stored",
      "quantity": "voltage_ll_rms",
      "units": "V",
      "basis": "<declared-basis>",
      "pu_base": null,
      "selectors": []
    }],
    "rules": [{
      "rule_id": "positive-v",
      "check": "positive_voltage",
      "inputs": {"value": "v1"},
      "limits": {},
      "source": [{"source_path": "<definition-or-manual-path>", "source_sha256": "0000000000000000000000000000000000000000000000000000000000000000", "locator": "<locator>"}],
      "scope": "<declared-scope>",
      "severity": "warning",
      "confidence": {"level": "low", "rationale": "<declared-rationale>"},
      "assumptions": []
    }]
  }]
}
```

`turns_ratio` evaluates only a declared numeric or rated-voltage ratio. Its result does not establish physical winding turns ratio, vector group, phase shift or tap effects. Pairwise checks require identical quantity, exact unit spelling, declared reference basis and per-unit base. Physical-unit three-phase power/current calculations explicitly report their SI factors and use a tolerance in VA; they require the declared balanced-three-phase sinusoidal assumption. Nonlinear power checks do not convert per-unit inputs.

The optional CLI is `rtds-agent rulepacks list`; there is no new MCP builder or rulepack tool. The full/core/engineering profiles remain 50/10/30 and the package retains nine skills. Rulepack source reads are bounded at 20 MiB per RTFX, 2 MiB per definition and 256 MiB per source (512 MiB aggregate); requests are capped at 100,000 JSON characters and responses at 2 MiB. Each request has at most ten packs, 32 bindings and 32 rules per pack, and 128 rules overall. Parser coverage and engineering interpretation remain partial and explicit. No physical qualification numbers are claimed here.
