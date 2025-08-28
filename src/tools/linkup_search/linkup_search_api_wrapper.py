from typing import Any, Literal, Optional, Type, Union
from langchain_core.tools import BaseTool
from linkup import LinkupClient
from pydantic import BaseModel, Field

class LinkupSearchInput(BaseModel):
    query: str = Field(description="The query for the Linkup API search.")

class EnhancedLinkupSearchAPIWrapper(BaseTool):
    """LinkupSearchTool tool.
    The LinkupSearchTool uses the Linkup API search entrypoint, making possible to perform
    search queries based on the Linkup API sources, that is the web and the Linkup Premium Partner
    sources, using natural language.
    """
    depth: Literal["standard"]
    output_type: Literal["sourcedAnswer"]
    linkup_api_key: Optional[str] = None
    include_domains: Optional[list] = None
    exclude_domains: Optional[list] = None
    name: str = "linkup"
    description: str = (
        "A tool to perform search queries based on the Linkup API sources, that is the web and the "
        "Linkup Premium Partner sources, using natural language."
    )

    args_schema: Type[BaseModel] = LinkupSearchInput
    return_direct: bool = False

    def _run(
        self,
        query: str,
    ) -> Any:
        client = LinkupClient(api_key=self.linkup_api_key)
        result = client.search(
            query=query,
            depth=self.depth,
            output_type=self.output_type,
            include_domains=self.include_domains,
            exclude_domains=self.exclude_domains,
        )
        return {
            "answer": getattr(result, "answer", ""),
            "sources": [
                {
                    "name": getattr(source, "name", ""),
                    "url": getattr(source, "url", ""),
                    "snippet": getattr(source, "snippet", ""),
                }
                for source in getattr(result, "sources", [])
            ],
        }

    async def _arun(
        self,
        query: str,
    ) -> Any:
        client = LinkupClient(api_key=self.linkup_api_key)
        result = await client.async_search(
            query=query,
            depth=self.depth,
            output_type=self.output_type,
            include_domains=self.include_domains,
            exclude_domains=self.exclude_domains,
        )
        return {
            "answer": getattr(result, "answer", ""),
            "sources": [
                {
                    "name": getattr(source, "name", ""),
                    "url": getattr(source, "url", ""),
                    "snippet": getattr(source, "snippet", ""),
                }
                for source in getattr(result, "sources", [])
            ],
        }
