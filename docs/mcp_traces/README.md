# MCP experiment traces (synthetic data only)

`mcp_server/local_client.py` runs on the `--buried` synthetic project (12-page
scan-only offers, first pass cached pages 1–4, pipeline agent off), question
*"Does this offer include the Non-collusive Tendering Certificate? Cite the page."*
See `docs/plan.md` §3 rows 12–13 and the README's MCP section for the table.

| file | driver | cache | outcome |
| --- | --- | --- | --- |
| `trace_Tenderer_01_cloud.json` | DeepSeek (`--allow-cloud-model`) | cold | found p.11, 3 steps |
| `trace_Tenderer_03_cloud.json` | DeepSeek | cold | not found (correct), 7 steps |
| `trace_Tenderer_02_local.json` | `qwen3:8b` | cold | found p.11, 4 steps |
| `trace_Tenderer_03_local.json` | `qwen3:8b` | warm (after the cloud run) | not found (correct), 3 steps |
| `trace_Tenderer_01_local.json` | `qwen3:8b`, before the clearer rejection message | warm | budget exhausted, no fabricated citation |
