"""Run the TerraSentry MCP server: stdio by default, streamable HTTP with MCP_TRANSPORT."""

from __future__ import annotations

import logging

from terrasentry_mcp.client import TerraSentryApi
from terrasentry_mcp.server import build_server
from terrasentry_mcp.settings import get_mcp_settings


def main() -> None:
    # httpx logs every request at INFO; on stdio that noise lands in the host's log pane.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = get_mcp_settings()
    api = TerraSentryApi(settings.terrasentry_api_url, settings.terrasentry_api_token)
    server = build_server(api, settings)
    if settings.mcp_transport == "streamable-http":
        server.run("streamable-http", host=settings.mcp_host, port=settings.mcp_port)
    else:
        server.run()


if __name__ == "__main__":
    main()
