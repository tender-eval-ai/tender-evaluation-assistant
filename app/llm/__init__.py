"""Every model call, and what it costs.

    client.py      the OpenAI-compatible client: fallback chains, JSON-validated chat, page OCR
    gateway.py     what every pipeline call goes through: endpoint policy by data class, cache,
                   per-project daily budget, one shared pace per provider (memory backends)
    gateway_pg.py  the gateway's Postgres backends, shared by every worker
    usage.py       tokens, calls, seconds and dollars per call, and the price table
    gcp.py         Vertex AI's OAuth tokens over Application Default Credentials
"""
