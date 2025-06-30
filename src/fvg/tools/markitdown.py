from langchain_core.tools import BaseTool
import markitdown


class MarkItDown(BaseTool):
    """Tool for parsing the document into Markdown format."""

    name: str = "markitdown"
    description: str = (
        "Convert a resource described by an http:, https:, file: or data: URI "
        "to markdown."
    )
    parser: markitdown.MarkItDown

    def _run(self, query: str, run_manager=None):
        return self.parser.convert_uri(query).markdown
