"""S6: the wiki RAG branch, in the `rag` database on RDS (pgvector), on a daily schedule.

- wiki_pages: the published pages from the ops wiki (resource `wiki`: labpipes/wiki.py). Store each
  page's ETag and send it next time: an unchanged page then costs a 304 and no body.
- wiki_chunks: split changed pages with labpipes.chunking.chunk_markdown (chunk size and overlap are
  decision 015) and store the chunks; use Chunk.content_hash as the id so unchanged text keeps it.
- wiki_embeddings: embed only the chunks that have no vector yet (resource `embed`: nomic-embed-text,
  768 dimensions) and store them as pgvector `vector(768)`, with an index (HNSW: decision 016).
- A blocking check that every chunk has a vector, and a schedule (and a job you can run by hand with
  scripts/dagster-run.sh) for the three.
"""

import dagster as dg

from ..chunking import chunk_markdown
from ..resources import LlmEmbed, RagStore, WikiApi

# Decision 015: 250 words (~325 tokens) with 40 words (~50 tokens) overlap
CHUNK_MAX_TOKENS = 325
CHUNK_OVERLAP_TOKENS = 50


@dg.asset(group_name="rag", kinds={"postgres", "wiki"})
def wiki_pages(context: dg.AssetExecutionContext, wiki: WikiApi, rag: RagStore) -> dg.MaterializeResult:
    with rag.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS pages (
                    page_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    etag TEXT NOT NULL,
                    body TEXT NOT NULL
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    page_id TEXT NOT NULL REFERENCES pages(page_id) ON DELETE CASCADE,
                    chunk_index INT NOT NULL,
                    heading TEXT NOT NULL,
                    text TEXT NOT NULL,
                    tokens INT NOT NULL,
                    embedding vector(768)
                );
                """
            )
            cur.execute("SELECT page_id, etag FROM pages;")
            existing_etags = dict(cur.fetchall())

            client = wiki.client()
            refs = client.pages()
            ref_ids = {r.id for r in refs}

            pages_fetched = 0
            pages_unchanged = 0

            for ref in refs:
                etag = existing_etags.get(ref.id)
                page = client.page(ref.id, etag)
                if page is None:
                    pages_unchanged += 1
                else:
                    pages_fetched += 1
                    cur.execute(
                        """
                        INSERT INTO pages (page_id, title, updated_at, etag, body)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (page_id) DO UPDATE SET
                            title = EXCLUDED.title,
                            updated_at = EXCLUDED.updated_at,
                            etag = EXCLUDED.etag,
                            body = EXCLUDED.body;
                        """,
                        (page.id, page.title, page.updated_at, page.etag, page.body),
                    )

            if ref_ids:
                cur.execute(
                    "DELETE FROM pages WHERE page_id NOT IN %s;",
                    (tuple(ref_ids),),
                )

        conn.commit()

    return dg.MaterializeResult(
        metadata={
            "pages_fetched": dg.MetadataValue.int(pages_fetched),
            "pages_unchanged": dg.MetadataValue.int(pages_unchanged),
            "total_pages": dg.MetadataValue.int(len(refs)),
        }
    )


@dg.asset(deps=[wiki_pages], group_name="rag", kinds={"postgres"})
def wiki_chunks(context: dg.AssetExecutionContext, rag: RagStore) -> dg.MaterializeResult:
    with rag.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT page_id, title, body FROM pages ORDER BY page_id;")
            pages = cur.fetchall()

            cur.execute("SELECT chunk_id FROM chunks;")
            existing_chunk_ids = {r[0] for r in cur.fetchall()}

            all_active_chunk_ids = set()
            chunks_created = 0

            for page_id, title, body in pages:
                chunks = chunk_markdown(title, body, max_tokens=CHUNK_MAX_TOKENS, overlap_tokens=CHUNK_OVERLAP_TOKENS)
                page_chunk_ids = set()
                for c in chunks:
                    cid = c.content_hash(page_id)
                    page_chunk_ids.add(cid)
                    all_active_chunk_ids.add(cid)
                    if cid not in existing_chunk_ids:
                        chunks_created += 1

                    cur.execute(
                        """
                        INSERT INTO chunks (chunk_id, page_id, chunk_index, heading, text, tokens)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (chunk_id) DO UPDATE SET
                            page_id = EXCLUDED.page_id,
                            chunk_index = EXCLUDED.chunk_index,
                            heading = EXCLUDED.heading,
                            text = EXCLUDED.text,
                            tokens = EXCLUDED.tokens;
                        """,
                        (cid, page_id, c.index, c.heading, c.text, c.tokens),
                    )

                if page_chunk_ids:
                    cur.execute(
                        "DELETE FROM chunks WHERE page_id = %s AND chunk_id NOT IN %s;",
                        (page_id, tuple(page_chunk_ids)),
                    )
                else:
                    cur.execute("DELETE FROM chunks WHERE page_id = %s;", (page_id,))

            cur.execute("SELECT count(*) FROM chunks;")
            total_chunks = cur.fetchone()[0]

        conn.commit()

    return dg.MaterializeResult(
        metadata={
            "chunks_created": dg.MetadataValue.int(chunks_created),
            "total_chunks": dg.MetadataValue.int(total_chunks),
        }
    )


@dg.asset(deps=[wiki_chunks], group_name="rag", kinds={"postgres", "llama.cpp"})
def wiki_embeddings(context: dg.AssetExecutionContext, rag: RagStore, embed: LlmEmbed) -> dg.MaterializeResult:
    with rag.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT chunk_id, text FROM chunks WHERE embedding IS NULL ORDER BY chunk_id;")
            missing = cur.fetchall()

            chunks_embedded = len(missing)
            if missing:
                texts = [r[1] for r in missing]
                vectors = embed.embed_documents(texts)
                for (cid, _), vec in zip(missing, vectors, strict=True):
                    vec_literal = "[" + ",".join(f"{x:.7g}" for x in vec) + "]"
                    cur.execute(
                        "UPDATE chunks SET embedding = %s::vector WHERE chunk_id = %s;",
                        (vec_literal, cid),
                    )

            # Decision 016: HNSW index on pgvector
            cur.execute(
                "CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);"
            )
            cur.execute("SELECT count(*) FROM chunks WHERE embedding IS NOT NULL;")
            total_vectors = cur.fetchone()[0]

        conn.commit()

    return dg.MaterializeResult(
        metadata={
            "chunks_embedded": dg.MetadataValue.int(chunks_embedded),
            "total_vectors": dg.MetadataValue.int(total_vectors),
        }
    )


@dg.asset_check(asset=wiki_embeddings, blocking=True, description="Every chunk has an embedding vector.")
def wiki_embeddings_complete(context: dg.AssetCheckExecutionContext, rag: RagStore) -> dg.AssetCheckResult:
    with rag.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM chunks WHERE embedding IS NULL;")
            missing = cur.fetchone()[0]
    return dg.AssetCheckResult(
        passed=int(missing) == 0,
        severity=dg.AssetCheckSeverity.ERROR,
        description=f"{missing} chunk(s) without an embedding vector",
        metadata={"missing_embeddings": dg.MetadataValue.int(int(missing))},
    )


ingest_wiki = dg.define_asset_job(
    "ingest_wiki",
    selection=dg.AssetSelection.assets("wiki_pages", "wiki_chunks", "wiki_embeddings"),
    description="Daily ingestion of the ops wiki into pgvector.",
)

daily_wiki_schedule = dg.ScheduleDefinition(
    name="daily_wiki_schedule",
    job=ingest_wiki,
    cron_schedule="0 0 * * *",
)
