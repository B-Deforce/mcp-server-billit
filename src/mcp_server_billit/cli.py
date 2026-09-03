"""Console entrypoint."""

from .server import mcp


def main() -> None:
    """Run the Billit MCP server over stdio."""
    mcp.run(transport="stdio")
