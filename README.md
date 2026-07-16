# Crawl4AI RAG Markdown Service

A small FastAPI service that crawls a URL with [Crawl4AI](https://github.com/unclecode/crawl4ai)
and returns clean, chunk-ready Markdown for a RAG pipeline (e.g. n8n).

It wraps Crawl4AI's content filters and produces:

- `markdown` — the full, verbatim page content after filtering
- `sections` — the content split on `##` / `###` headings, with a `level`
  so downstream chunkers keep document structure
- `success` / `error_message` / `filter_used` — so n8n can branch on failures

## Why not just use the LLM filter?

The `LLMContentFilter` is the weakest part of Crawl4AI and is unreliable with
Mistral: when the LLM call errors or returns unexpected content, it silently
produces empty output (Crawl4AI issues #603, #966). For a RAG pipeline you
almost always want a **deterministic** filter that keeps the full text of dense
content nodes.

This service therefore defaults to the deterministic `PruningContentFilter`
and exposes LLM-based filtering only as an opt-in mode.

## Filter modes

Set `CRAWL4AI_FILTER_MODE` (env var / docker-compose):

| Mode     | Filter                     | Best for                                  |
|----------|----------------------------|-------------------------------------------|
| `prune`  | `PruningContentFilter`     | Default. Keeps full article text.         |
| `bm25`   | `BM25ContentFilter`        | When you have a user query (`CRAWL4AI_QUERY`). |
| `llm`    | `LLMContentFilter` (Mistral/OpenAI via LiteLLM) | Polishing/rewriting. Best-effort. |

`bm25` falls back to `prune` if no `CRAWL4AI_QUERY` is provided.

## Configuration (env vars)

| Variable                          | Default                          | Notes |
|-----------------------------------|----------------------------------|-------|
| `CRAWL4AI_FILTER_MODE`            | `prune`                          | `prune` \| `bm25` \| `llm` |
| `CRAWL4AI_QUERY`                  | _(empty)_                        | Used by `bm25` mode |
| `CRAWL4AI_PRUNE_THRESHOLD`        | `0.48`                           | Lower = more content kept |
| `CRAWL4AI_PRUNE_THRESHOLD_TYPE`   | `fixed`                          | `fixed` \| `dynamic` |
| `CRAWL4AI_PRUNE_MIN_WORDS`        | `5`                              | Min words per node |
| `CRAWL4AI_BM25_THRESHOLD`         | `1.0`                            | Higher = stricter |
| `CRAWL4AI_LLM_PROVIDER`           | `mistral/mistral-small-latest`   | LiteLLM provider string |
| `CRAWL4AI_LLM_TOKEN`              | `$MISTRAL_API_KEY`               | LLM API key |
| `CRAWL4AI_LLM_BASE_URL`           | `https://api.mistral.ai/v1`      | Custom endpoint |
| `CRAWL4AI_IGNORE_LINKS`           | `False`                          | `True` to strip links |
| `CRAWL4AI_IGNORE_IMAGES`          | `False`                          | `True` to strip images |
| `PORT`                            | `11236`                          | HTTP port |

## Run with Docker

```bash
export MISTRAL_API_KEY=your-key
# optional:
export CRAWL4AI_FILTER_MODE=prune
export CRAWL4AI_PORT=11236

docker compose up --build
```

## Usage

```bash
curl -X POST http://localhost:11236/markdown \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/docs", "debug": true}'
```

Query-focused (BM25):

```bash
curl -X POST http://localhost:11236/markdown \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/docs", "query": "authentication setup"}'
```

### Response shape

```json
{
  "url": "https://example.com/docs",
  "success": true,
  "error_message": null,
  "filter_used": "prune",
  "title": "Example Docs",
  "description": "...",
  "markdown": "# Example Docs\n\n## Section\n\n...",
  "sections": [
    { "heading": "Introduction", "level": 0, "content": "..." },
    { "heading": "Section", "level": 2, "content": "..." }
  ],
  "word_count": 1234,
  "char_count": 8123
}
```

## n8n

Import `n8n-http-node.json` (or copy its contents) as an n8n workflow / HTTP
Request node. It POSTs a URL (+ optional query) to this service and forwards
`markdown` + `sections` into your RAG ingestion step.

## Notes

- `requirements.txt` pins `crawl4ai==0.9.2`. Do **not** pin `litellm`
  separately: `crawl4ai` vendors its own fork (`unclecode-litellm`) with a
  different `openai` requirement, and an explicit `litellm` pin causes a
  dependency conflict at build time.
- The LLM filter is best-effort: if it fails, the response still returns the
  pruned/raw markdown and reports `filter_used` so you can detect the fallback.
