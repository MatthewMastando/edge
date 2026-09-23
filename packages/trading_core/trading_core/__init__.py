"""Trading Research Workspace core library.

Subpackages:

- ``domain``   Pydantic v2 models shared by the API, worker and web app (via OpenAPI).
- ``data``     Market data adapter interface and the fixture implementation.
- ``ta``       Deterministic TA interfaces (detector protocol, registry). Logic lands in Stage 1A.
- ``research`` Research source interfaces (search, fetch, official data). Implemented in Stage 3.
- ``harness``  LLM provider interface, recorded provider, tool specs. Job runner lands in Stage 1B.
- ``storage``  Object store interface with a local Parquet backend and a Supabase Storage stub.
- ``fixtures`` Deterministic, seeded fixture generator for contract-shaped market data.

Nothing in this package may submit, modify or cancel broker orders; the MVP is research only.
"""

__version__ = "0.1.0"
