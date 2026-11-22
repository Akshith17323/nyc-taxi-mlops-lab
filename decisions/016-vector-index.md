# 016: Vector index selection for pgvector

Stage: S6 · Date: 2026-11-22 · Author: Akshith · Drafted by agent: yes

## Choice

Use an HNSW (Hierarchical Navigable Small World) index with `vector_cosine_ops` on `rag.chunks (embedding)` in pgvector:
`CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);`

## Rejected alternative

IVFFlat (Inverted File Flat) index with cosine distance.

## Why

1. **Incremental Ingestion Without Re-indexing:** HNSW incrementally updates its multi-layer graph as new chunks and vectors are inserted. IVFFlat requires an existing dataset to cluster into Voronoi cells (`lists`); creating an IVFFlat index on an empty or small table (like our starting 16-page wiki) produces poor centroids, leading to severe recall degradation as chunks are added unless the index is dropped and rebuilt.
2. **Superior Recall Quality:** HNSW provides high recall (>98%) out of the box with standard `ef_search` parameters, without requiring periodic maintenance or manual list tuning.
3. **Resource Trade-off at Lab Scale:** While HNSW has higher index build time and memory usage compared to IVFFlat, our ops wiki contains fewer than 1,000 chunks. Memory usage is on the order of megabytes on RDS Postgres, making HNSW's memory trade-off negligible while giving faster and more accurate nearest-neighbor searches.

## What would show this was wrong

If the document corpus scales to millions of vectors where HNSW index memory exceeds RDS instance RAM, or if write latency during high-frequency real-time updates becomes a bottleneck, justifying IVFFlat or a dedicated vector database.
