"""Build LangChain MCP adapters for the project's configured data sources."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain.mcp import MCPAdapter

# Project root: ai-business-pilot/
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Load environment variables from .env
load_dotenv(PROJECT_ROOT / ".env")


def create_mcp_adapter(
    include_duckdb: bool = True,
    include_linear: bool = False,
    include_linear_write: bool = False,
) -> MCPAdapter:
    """Create an MCP adapter for the selected data-source capabilities."""

    if not include_duckdb and not include_linear and not include_linear_write:
        raise ValueError("At least one MCP server must be enabled")

    servers = {}

    # Local DuckDB MCP server
    if include_duckdb:
        servers["duckdb"] = {
            "transport": "stdio",
            "command": sys.executable,
            "args": ["-m", "mcp_servers.duckdb_server"],
            "cwd": str(PROJECT_ROOT),
        }

    # Remote Linear MCP server
    if include_linear:
        api_key = os.getenv("LINEAR_API_KEY")

        if not api_key:
            raise ValueError("LINEAR_API_KEY is missing from .env")

        servers["linear"] = {
            "url": os.getenv(
                "LINEAR_READ_MCP_URL",
                "https://mcp.linear.app/mcp/readonly",
            ),
            "auth": api_key,
        }

    # Remote Linear MCP server with explicit write credentials.
    if include_linear_write:
        write_api_key = os.getenv("LINEAR_WRITE_API_KEY")
        write_url = os.getenv("LINEAR_WRITE_MCP_URL")

        if not write_api_key:
            raise ValueError("LINEAR_WRITE_API_KEY is missing from .env")
        if not write_url:
            raise ValueError("LINEAR_WRITE_MCP_URL is missing from .env")

        servers["linear_write"] = {
            "url": write_url,
            "auth": write_api_key,
        }

    return MCPAdapter({"mcpServers": servers})
