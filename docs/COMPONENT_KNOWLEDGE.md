# Component knowledge graph

The component knowledge graph is a local, read-only index of configured RSCAD definitions and explicitly supplied project inputs. Build and inspect it with the CLI:

```text
rtds-agent knowledge graph build [--project PATH ...] [--annotations PATH]
rtds-agent knowledge graph status
rtds-agent knowledge graph query --graph-id SHA --mode search|get|neighbors --query TEXT | --node-id ID [--depth 1|2] [--edge-kind KIND ...] [--offset 0] [--limit 20]
```

The build command accepts up to 16 project paths. Query limits are 0-based offsets, a default limit of 20 and a maximum of 100; neighbor depth is 1 or 2. Querying and status are read-only and never build automatically. The MCP surface exposes only `query_component_knowledge(request)` with `graph_id`, `mode`, and the mode-specific query/node, depth, edge-kind, offset and limit fields; there is no MCP graph builder.

The graph schema is version 1.0. Its eight edge kinds are `IS_A`, `CONNECTS_TO`, `REQUIRES`, `ALTERNATIVE_TO`, `USED_IN`, `INITIALIZED_BY`, `CONTROLLED_BY`, and `MEASURED_BY`. Automatically observed `CONNECTS_TO` edges mean definition-to-project-specific net membership and retain exact saved UUID, context and ports. Automatically observed `USED_IN` edges record usage. Literal fields, ports and manual references are observed from their sources; role, typical-use, compatibility and semantic relations are explicit source-hash-bound assertions and remain unverified interpretations.

Every assertion must identify the current exact source definition path and SHA, plus cited supporting manual or other source references. Definition edges and `compatible_neighbors` assertions must also identify the target definition path and SHA. An explicit rebuild after a definition change rejects old assertions; reauthor bound claims deliberately against the new hashes. Mixed fact values carry `evidence_kind`: `observed`, `derived`, or `asserted`. Project evidence retains each source's snapshot, coverage, warnings and limitations, while project nodes aggregate the same model content SHA across paths rather than treating requested case paths as unique models.

A valid assertion shape uses placeholders for source and target provenance, for example:

```json
{
  "schema_version": "1.0",
  "field_assertions": [],
  "edge_assertions": [{
    "kind": "ALTERNATIVE_TO",
    "source_definition_id": "<source-definition-id>",
    "target_kind": "definition",
    "target_id": "<target-definition-id>",
    "scope": "<scope>",
    "provenance": [
      {"source_path": "<source-definition-path>", "source_sha256": "0000000000000000000000000000000000000000000000000000000000000000", "locator": "<source-definition-locator>"},
      {"source_path": "<target-definition-path>", "source_sha256": "0000000000000000000000000000000000000000000000000000000000000000", "locator": "<target-definition-locator>"},
      {"source_path": "<manual-or-source-ref>", "source_sha256": "0000000000000000000000000000000000000000000000000000000000000000", "locator": "<supporting-locator>"}
    ]
  }]
}
```

Index generations are stored under `data_dir/knowledge/component_graphs/<graph_sha>/graph.json` as immutable, atomically published cache data. A query verifies the graph hash and current source, settings and implementation hashes. Any change requires an explicit rebuild; hashes provide change detection, not signatures or semantic authenticity. The catalog remains a separate capability.

The bounded index covers the whole local configured definition set plus explicit project inputs, with literal description, keyword, class and `HELP` references. A component-builder header is not evidence of the installed version. Limits are 128 MiB per graph, 20,000 nodes, 100,000 edges and 2 MiB per response. Detailed parsing is limited to 500 parameters and 2,000 active ports per definition. Oversized detailed schemas and unsupported encodings retain identity and available literal metadata, with unresolved detail and explicit warnings. Source files are bounded to 256 MiB each and 512 MiB collectively; an annotation file is limited to 1 MiB and 1,000 combined assertions. Parser coverage is partial and must remain explicit.

Failed staging is retained for inspection and is not cleaned automatically. Inspect the writer lock and failed generation manually before recovery. No vendor files are committed, and graph indexing does not import the SDK or call the GUI, Compile, load flow, Runtime or rack.

The read-only graph query brings the profiles to 50 full, 10 core and 30 engineering tools; the nine packaged skills remain available.
