# 015: Wiki chunking parameters and retrieval top-k

Stage: S6 · Date: 2026-11-22 · Author: Akshith · Drafted by agent: yes

## Choice

Split ops wiki markdown into chunks of 250 words (~325 tokens) with 40 words (~50 tokens) overlap using section-aware markdown chunking (`chunk_markdown`), and retrieve top-k = 3 chunks by cosine similarity (`vector_cosine_ops`) for the support assistant prompt.

## Rejected alternative

- Smaller chunks (e.g., 100 words) with top-k = 6–8: section context is fragmented (headings separated from policy tables/rules), and retrieving more chunks increases prompt length without increasing information density.
- Large chunks (e.g., 500+ words) with top-k = 1–2: risks diluting specific policy answers with unrelated text, and wastes prompt processing time on CPU.
- Larger top-k (e.g., 5–10): adds ~11 seconds of CPU prompt ingestion per chunk on m8g.large, pushing response latency well over 60 seconds without improving answer accuracy.

## Why

1. **Wiki Page Length and Structure:** The ops wiki pages are brief and structured with Markdown headers (typically 200–800 words divided into 2–4 subsections). A 250-word chunk cleanly encapsulates an entire policy section (e.g., Harbor Line surcharge rules, toll adjustments, weekend hours).
2. **Title and Heading Preservation:** `chunk_markdown` prepends `{Title} > {Heading}` to every chunk. A 250-word window ensures that short pricing statements like "It is $4.50" remain connected to their parent conditions.
3. **CPU Latency Budget:** On the Graviton `m8g.large` LLM host, prompt processing runs at ~13 tokens/s (~11 s per chunk). Top-k = 3 chunks produces ~800–1,000 prompt tokens, taking ~35–45 s of prompt evaluation. With llama.cpp system prompt caching, the fixed system prompt prefix is evaluated once, leaving only the user turn to be processed.

## What would show this was wrong

If retrieval evaluation shows relevant context split across chunk boundaries (indicating need for larger overlap or semantic chunking), or if assistant latency breaches rider tolerance, requiring reduction to top-k = 2.
