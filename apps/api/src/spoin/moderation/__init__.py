"""Report-a-card and the operator repair lane (ADR-0076).

Deliberately outside `spoin.feed` and `api/routers/feed.py` (the LLM-free feed
read path): a report is a DB write, and the admin triage endpoints only enqueue
`GenerationJob` rows -- the actual repair LLM call runs in the worker, never in a
request.
"""
