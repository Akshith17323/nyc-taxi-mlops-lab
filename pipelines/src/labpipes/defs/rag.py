"""The wiki RAG branch: wiki_pages -> wiki_chunks -> wiki_embeddings, on a daily schedule.

wiki_pages       conditional GETs: a page whose ETag hasn't changed costs a 304 and keeps its stored body
wiki_chunks      re-chunks only pages whose body changed; a chunk's id is the hash of its content
wiki_embeddings  embeds only chunks without a vector, so an unchanged chunk is never embedded twice
embeddings_complete  blocking: every chunk has a vector of the right size, or the app would retrieve holes

Everything lives in the `rag` database on RDS (pgvector): rag.pages and rag.chunks.
Decision records: 015 (chunk size, overlap and top-k), 016 (HNSW or IVFFlat).
"""

import dagster as dg

from ..chunking import chunk_markdown
from ..resources import LlmEmbed, RagStore, WikiApi

# Decision 015: 200-token chunks, which keeps every page of this wiki whole (pages are 66-188 tokens), so a
# rule never loses its number to a chunk boundary; 30 tokens of overlap for longer pages. Measured on the
# wiki's Q/A pairs: top-3 finds the answer's page 20/20 at ~314 context tokens; 100-token chunks also hit
# 20/20 at ~263 but split pages. Each retrieved chunk costs ~11 s of prompt processing on m8g.large.
CHUNK_TOKENS = 200
OVERLAP_TOKENS = 30
DIMENSIONS = 768  # nomic-embed-text-v1.5

SCHEMA = f"""
create extension if not exists vector;
create schema if not exists rag;
create table if not exists rag.pages (
  id text primary key, title text not null, updated_at text not null, etag text not null,
  body text not null, chunked_etag text, fetched_at timestamptz not null default now());
create table if not exists rag.chunks (
  id text primary key, page_id text not null references rag.pages(id) on delete cascade,
  idx int not null, heading text not null, content text not null, tokens int not null,
  embedding vector({DIMENSIONS}));
-- Decision 016: HNSW. Builds as rows arrive and needs no training; IVFFlat must be built after the data,
-- with lists sized to it, and recall drops if it isn't rebuilt as the wiki changes.
create index if not exists chunks_embedding_hnsw on rag.chunks using hnsw (embedding vector_cosine_ops);
"""


def _connect(rag: RagStore):
    conn = rag.connect()
    with conn.cursor() as cur:
        cur.execute(SCHEMA)
    conn.commit()
    return conn


@dg.asset(group_name="rag", kinds={"postgres"})
def wiki_pages(context: dg.AssetExecutionContext, wiki: WikiApi, rag: RagStore) -> dg.MaterializeResult:
    client = wiki.client()
    listed = client.pages()
    conn = _connect(rag)
    fetched = unchanged = 0
    with conn, conn.cursor() as cur:
        cur.execute("select id, etag from rag.pages")
        known = dict(cur.fetchall())
        for ref in listed:
            page = client.page(ref.id, known.get(ref.id))
            if page is None:
                unchanged += 1
                continue
            fetched += 1
            cur.execute(
                """insert into rag.pages (id, title, updated_at, etag, body) values (%s, %s, %s, %s, %s)
                   on conflict (id) do update set title = excluded.title, updated_at = excluded.updated_at,
                   etag = excluded.etag, body = excluded.body, fetched_at = now()""",
                (page.id, page.title, page.updated_at, page.etag, page.body))
        removed = sorted(set(known) - {r.id for r in listed})
        if removed:
            cur.execute("delete from rag.pages where id = any(%s)", (removed,))
    conn.close()
    context.log.info(f"{len(listed)} pages: {fetched} fetched, {unchanged} unchanged (304), {len(removed)} removed")
    return dg.MaterializeResult(metadata={"pages": len(listed), "fetched": fetched, "unchanged": unchanged, "removed": len(removed)})


@dg.asset(group_name="rag", deps=[wiki_pages], kinds={"postgres"})
def wiki_chunks(context: dg.AssetExecutionContext, rag: RagStore) -> dg.MaterializeResult:
    conn = _connect(rag)
    rechunked = new = dropped = 0
    with conn, conn.cursor() as cur:
        cur.execute("select id, title, body, etag from rag.pages where chunked_etag is distinct from etag")
        for page_id, title, body, etag in cur.fetchall():
            chunks = chunk_markdown(title, body, CHUNK_TOKENS, OVERLAP_TOKENS)
            ids = [c.content_hash(page_id) for c in chunks]
            cur.execute("select id from rag.chunks where page_id = %s", (page_id,))
            before = {r[0] for r in cur.fetchall()}
            for cid, c in zip(ids, chunks, strict=True):
                # Unchanged text keeps its id and its vector; only its position may move.
                cur.execute(
                    """insert into rag.chunks (id, page_id, idx, heading, content, tokens) values (%s, %s, %s, %s, %s, %s)
                       on conflict (id) do update set idx = excluded.idx""",
                    (cid, page_id, c.index, c.heading, c.text, c.tokens))
            gone = sorted(before - set(ids))
            if gone:
                cur.execute("delete from rag.chunks where id = any(%s)", (gone,))
            cur.execute("update rag.pages set chunked_etag = %s where id = %s", (etag, page_id))
            rechunked, new, dropped = rechunked + 1, new + len(set(ids) - before), dropped + len(gone)
        cur.execute("select count(*) from rag.chunks")
        total = cur.fetchone()[0]
    conn.close()
    context.log.info(f"{rechunked} page(s) re-chunked: {new} new chunks, {dropped} dropped; {total} in total")
    return dg.MaterializeResult(metadata={"pages_rechunked": rechunked, "new_chunks": new, "dropped_chunks": dropped, "chunks": total,
                                          "chunk_tokens": CHUNK_TOKENS, "overlap_tokens": OVERLAP_TOKENS})


@dg.asset(group_name="rag", deps=[wiki_chunks], kinds={"postgres"})
def wiki_embeddings(context: dg.AssetExecutionContext, rag: RagStore, embed: LlmEmbed) -> dg.MaterializeResult:
    conn = _connect(rag)
    with conn, conn.cursor() as cur:
        cur.execute("select id, content from rag.chunks where embedding is null order by page_id, idx")
        todo = cur.fetchall()
        vectors = embed.embed_documents([content for _, content in todo]) if todo else []
        for (cid, _), v in zip(todo, vectors, strict=True):
            cur.execute("update rag.chunks set embedding = %s::vector where id = %s", ("[" + ",".join(f"{x:.7g}" for x in v) + "]", cid))
        cur.execute("select count(*) from rag.chunks")
        total = cur.fetchone()[0]
    conn.close()
    context.log.info(f"embedded {len(todo)} chunk(s); {total - len(todo)} already had a vector")
    return dg.MaterializeResult(metadata={"embedded": len(todo), "reused": total - len(todo), "chunks": total})


@dg.asset_check(asset=wiki_embeddings, blocking=True)
def embeddings_complete(rag: RagStore) -> dg.AssetCheckResult:
    conn = rag.connect()
    with conn, conn.cursor() as cur:
        cur.execute("select count(*), count(*) filter (where embedding is null), count(*) filter (where vector_dims(embedding) <> %s) from rag.chunks",
                    (DIMENSIONS,))
        total, missing, wrong = cur.fetchone()
    conn.close()
    return dg.AssetCheckResult(passed=total > 0 and missing == 0 and wrong == 0,
                               metadata={"chunks": total, "without_vector": missing, "wrong_dimensions": wrong})


ingest_wiki = dg.define_asset_job("ingest_wiki", selection=dg.AssetSelection.groups("rag"))

# Daily at 06:00 UTC, plus `scripts/dagster-run.sh ingest_wiki` whenever the wiki changes during the lab.
wiki_schedule = dg.ScheduleDefinition(job=ingest_wiki, cron_schedule="0 6 * * *", default_status=dg.DefaultScheduleStatus.RUNNING)
