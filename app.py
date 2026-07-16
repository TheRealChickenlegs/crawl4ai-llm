from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel
import os

from crawl4ai import (
    AsyncWebCrawler,
    CrawlerRunConfig,
    DefaultMarkdownGenerator,
    BrowserConfig,
)
from crawl4ai.content_filter_strategy import (
    PruningContentFilter,
    BM25ContentFilter,
    LLMContentFilter,
)
from crawl4ai import LLMConfig


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Crawl4AI configuration")
    print("Filter mode:", os.getenv("CRAWL4AI_FILTER_MODE", "prune"))
    print(
        "LLM Provider:",
        os.getenv("CRAWL4AI_LLM_PROVIDER", "mistral/mistral-small-latest"),
    )
    print(
        "LLM Token configured:",
        bool(os.getenv("CRAWL4AI_LLM_TOKEN") or os.getenv("MISTRAL_API_KEY")),
    )
    yield


app = FastAPI(lifespan=lifespan)


class CrawlRequest(BaseModel):
    url: str
    query: str | None = None
    debug: bool = False


def build_content_filter(mode: str, query: str | None):
    """Return (filter, filter_name) based on env-configured mode.

    Modes:
      - prune: deterministic PruningContentFilter (default, Mistral-proof)
      - bm25:  BM25ContentFilter focused on `query` (falls back to prune
               if no query is supplied)
      - llm:   LLMContentFilter via Mistral/OpenAI (best-effort, can fail)
    """

    mode = mode.lower()

    if mode == "bm25":
        if query:
            return (
                BM25ContentFilter(
                    user_query=query,
                    bm25_threshold=float(
                        os.getenv("CRAWL4AI_BM25_THRESHOLD", "1.0")
                    ),
                ),
                "bm25",
            )
        print("BM25 requested but no query given; falling back to prune")
        mode = "prune"

    if mode == "llm":
        provider = os.getenv(
            "CRAWL4AI_LLM_PROVIDER", "mistral/mistral-small-latest"
        )
        api_token = os.getenv("CRAWL4AI_LLM_TOKEN") or os.getenv(
            "MISTRAL_API_KEY"
        )
        base_url = os.getenv(
            "CRAWL4AI_LLM_BASE_URL", "https://api.mistral.ai/v1"
        )
        return (
            LLMContentFilter(
                llm_config=LLMConfig(
                    provider=provider,
                    api_token=api_token,
                    base_url=base_url,
                    extra_args={
                        "temperature": 0.0,
                        "max_tokens": 4096,
                    },
                ),
                instruction="""
Extract the complete useful content from this webpage for a retrieval
augmented generation knowledge base.

Do not summarize. Keep the full content and structure:
- article text, explanations, examples
- headings and subheadings
- lists and tables
- technical details and code blocks
- important links (as markdown)

Remove only boilerplate:
- navigation menus, cookie banners, advertisements
- login/signup prompts, unrelated recommendations
- social media widgets, footers

Return clean markdown only. Do not add commentary.
""",
                chunk_token_threshold=4096,
                verbose=False,
            ),
            "llm",
        )

    # Default: deterministic pruning (no LLM, works with any provider)
    return (
        PruningContentFilter(
            threshold=float(os.getenv("CRAWL4AI_PRUNE_THRESHOLD", "0.48")),
            threshold_type=os.getenv(
                "CRAWL4AI_PRUNE_THRESHOLD_TYPE", "fixed"
            ),
            min_word_threshold=int(
                os.getenv("CRAWL4AI_PRUNE_MIN_WORDS", "5")
            ),
        ),
        "prune",
    )


def create_config(mode: str, query: str | None):
    content_filter, _ = build_content_filter(mode, query)

    md_generator = DefaultMarkdownGenerator(
        content_filter=content_filter,
        options={
            # Keep links but strip tracking; no line wrapping so RAG
            # chunkers see logical paragraphs.
            "ignore_links": os.getenv("CRAWL4AI_IGNORE_LINKS", "False")
            == "True",
            "ignore_images": os.getenv("CRAWL4AI_IGNORE_IMAGES", "False")
            == "True",
            "escape_html": False,
            "body_width": 0,
        },
    )

    return CrawlerRunConfig(markdown_generator=md_generator)


def split_sections(markdown: str):
    """Split markdown into RAG-friendly chunks on headings.

    Levels ## and ### start a new section; the top-level (#) title is
    used as document title metadata, not a section. Everything before
    the first heading becomes a 'Introduction' section.
    """

    sections = []
    current_heading = "Introduction"
    current_level = 0
    current_content: list[str] = []

    def flush():
        content = "\n".join(current_content).strip()
        if content:
            sections.append(
                {
                    "heading": current_heading,
                    "level": current_level,
                    "content": content,
                }
            )

    for line in markdown.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            heading_text = stripped.lstrip("#").strip()
            # Treat only H2/H3 as new sections to avoid over-chunking
            if level >= 2:
                flush()
                current_heading = heading_text
                current_level = level
                current_content = []
            else:
                # H1: title line, keep it in current content
                current_content.append(line)
        else:
            current_content.append(line)

    flush()
    return sections


@app.post("/markdown")
async def markdown(req: CrawlRequest):
    mode = os.getenv("CRAWL4AI_FILTER_MODE", "prune")
    config = create_config(mode, req.query)

    async with AsyncWebCrawler(
        config=BrowserConfig(headless=True, java_script_enabled=True)
    ) as crawler:
        result = await crawler.arun(
            url=req.url,
            config=config,
            wait_for="body",
        )

    raw_markdown = result.markdown.raw_markdown if result.markdown else ""
    fit_markdown = result.markdown.fit_markdown if result.markdown else ""

    # Choose best available content
    content = fit_markdown.strip() or raw_markdown.strip()

    # Detect which filter actually produced output
    used_filter, filter_name = build_content_filter(mode, req.query)

    response = {
        "url": req.url,
        "success": result.success,
        "error_message": result.error_message if not result.success else None,
        "filter_used": filter_name,
        "title": (
            result.metadata.get("title") if result.metadata else None
        ),
        "description": (
            result.metadata.get("description") if result.metadata else None
        ),
        "markdown": content,
        "sections": split_sections(content),
        "word_count": len(content.split()),
        "char_count": len(content),
    }

    if req.debug:
        response["debug"] = {
            "raw_length": len(raw_markdown),
            "fit_length": len(fit_markdown),
            "success": result.success,
            "filter_name": filter_name,
        }

    return response
