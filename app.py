from fastapi import FastAPI
from pydantic import BaseModel
import os

from crawl4ai import (
    AsyncWebCrawler,
    CrawlerRunConfig,
    DefaultMarkdownGenerator,
    LLMConfig,
    LLMContentFilter
)

app = FastAPI()


class CrawlRequest(BaseModel):
    url: str


def create_config():

    provider = os.getenv(
        "CRAWL4AI_LLM_PROVIDER",
        "mistral/mistral-small-latest"
    )

    api_token = os.getenv(
        "CRAWL4AI_LLM_TOKEN"
    )

    base_url = os.getenv(
        "CRAWL4AI_LLM_BASE_URL",
        "https://api.mistral.ai/v1"
    )

    return CrawlerRunConfig(

        markdown_generator=DefaultMarkdownGenerator(

            content_filter=LLMContentFilter(

                llm_config=LLMConfig(
                    provider=provider,
                    api_token=api_token,
                    base_url=base_url
                ),

                instruction="""
You are cleaning content for a RAG knowledge base.

Keep:

- Main article/documentation content
- Titles
- Headings
- Paragraphs
- Lists
- Tables
- Code blocks
- Important links

Remove:

- Navigation menus
- Headers
- Footers
- Cookie banners
- Login/signup prompts
- Advertisements
- Social media widgets
- Related article suggestions

Do not summarize.
Preserve the original meaning and structure.
""",

                chunk_token_threshold=4096
            )
        )
    )


def extract_sections(markdown):

    sections = []

    current_heading = "Introduction"
    current_content = []

    for line in markdown.split("\n"):

        if line.startswith("#"):

            if current_content:
                sections.append({
                    "heading": current_heading,
                    "content": "\n".join(current_content).strip()
                })

            current_heading = line.lstrip("#").strip()
            current_content = []

        else:
            current_content.append(line)


    if current_content:
        sections.append({
            "heading": current_heading,
            "content": "\n".join(current_content).strip()
        })

    return sections



@app.post("/markdown")
async def markdown(req: CrawlRequest):

    config = create_config()

    async with AsyncWebCrawler() as crawler:

        result = await crawler.arun(
            url=req.url,
            config=config
        )


    markdown = result.markdown.fit_markdown

    return {

        "url": req.url,

        "title": (
            result.metadata.get("title")
            if result.metadata else None
        ),

        "description": (
            result.metadata.get("description")
            if result.metadata else None
        ),

        "markdown": markdown,

        "sections": extract_sections(markdown),

        "word_count": len(markdown.split())

    }