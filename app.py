from fastapi import FastAPI
from pydantic import BaseModel
import os

from crawl4ai import (
    AsyncWebCrawler,
    CrawlerRunConfig,
    DefaultMarkdownGenerator,
    LLMConfig,
    LLMContentFilter,
    BrowserConfig
)


app = FastAPI()


class CrawlRequest(BaseModel):
    url: str
    debug: bool = False



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
Extract the complete useful content from this webpage for a retrieval augmented generation knowledge base.

Do not summarize.

Keep:

- article text
- explanations
- examples
- headings
- lists
- tables
- technical details
- important links
- code blocks

Remove only:

- navigation menus
- cookie banners
- advertisements
- login/signup prompts
- unrelated recommendations
- social media widgets

If this is a guide, tutorial, documentation page, or reference article:
preserve the full content and structure.

Maintain the original meaning.
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

        if line.strip().startswith("#"):

            if current_content:

                content = "\n".join(
                    current_content
                ).strip()

                if content:
                    sections.append({
                        "heading": current_heading,
                        "content": content
                    })


            current_heading = (
                line
                .lstrip("#")
                .strip()
            )

            current_content = []

        else:
            current_content.append(line)


    if current_content:

        content = "\n".join(
            current_content
        ).strip()

        if content:
            sections.append({
                "heading": current_heading,
                "content": content
            })


    return sections



@app.on_event("startup")
async def startup_check():

    print("Crawl4AI configuration")
    print(
        "Provider:",
        os.getenv(
            "CRAWL4AI_LLM_PROVIDER",
            "mistral/mistral-small-latest"
        )
    )

    print(
        "LLM Token configured:",
        bool(
            os.getenv(
                "CRAWL4AI_LLM_TOKEN"
            )
        )
    )



@app.post("/markdown")
async def markdown(req: CrawlRequest):

    config = create_config()


    async with AsyncWebCrawler(
        config=BrowserConfig(
            headless=True,
            java_script_enabled=True
        )
    ) as crawler:


        result = await crawler.arun(

            url=req.url,

            config=config,

            wait_for="body"

        )


    raw_markdown = (
        result.markdown.raw_markdown
        if result.markdown
        else ""
    )


    fit_markdown = (
        result.markdown.fit_markdown
        if result.markdown
        else ""
    )


    # Prefer LLM cleaned markdown
    markdown = fit_markdown.strip()


    # Fallback if filter removes everything
    if not markdown:
        markdown = raw_markdown.strip()



    response = {

        "url": req.url,

        "title": (
            result.metadata.get("title")
            if result.metadata
            else None
        ),

        "description": (
            result.metadata.get("description")
            if result.metadata
            else None
        ),

        "markdown": markdown,

        "sections": extract_sections(markdown),

        "word_count": len(
            markdown.split()
        )

    }


    if req.debug:

        response["debug"] = {

            "raw_length": len(
                raw_markdown
            ),

            "fit_length": len(
                fit_markdown
            ),

            "success": result.success

        }


    return response