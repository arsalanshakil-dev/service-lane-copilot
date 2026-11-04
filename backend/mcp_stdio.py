"""Simple stdio entry point for MCP hosts that launch a local subprocess."""

from app.mcp_server import mcp_server


if __name__ == "__main__":
    mcp_server.run(transport="stdio")
