"""AskAI: answer a reader's question about one card (ADR-0077).

Outside `spoin.feed` / `api/routers/feed.py` -- this path makes an LLM call, so
it can never be part of the feed read path. One deterministic retrieval query,
one streamed flash-lite call, an embedding pre-check and an `OFF_TOPIC` sentinel
holding off-topic questions, a 200/user/day counter, and a `card_qa` cache.
"""
