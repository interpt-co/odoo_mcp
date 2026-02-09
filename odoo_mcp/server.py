"""MCP server initialization, transport setup, and startup sequence.

REQ-01-08 through REQ-01-11, REQ-01-14 through REQ-01-18, REQ-01-21 through REQ-01-27.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server

from odoo_mcp import __version__
from odoo_mcp.config import OdooMcpConfig, load_config
from odoo_mcp.connection.manager import ConnectionManager

logger = logging.getLogger("odoo_mcp")


def _setup_logging(level: str) -> None:
    """Configure logging (REQ-01-21, REQ-01-22, REQ-01-23)."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


# ---------------------------------------------------------------------------
# Stub registration points (to be filled by Groups 3-5 after merge)
# ---------------------------------------------------------------------------

async def _register_toolsets(
    server: Server, connection: ConnectionManager, config: OdooMcpConfig
) -> None:
    """Stub: Register toolsets with the MCP server."""
    logger.debug("Toolset registration stub (Group 4 implements)")


async def _register_resources(
    server: Server, connection: ConnectionManager, config: OdooMcpConfig
) -> None:
    """Stub: Register resources with the MCP server."""
    logger.debug("Resource registration stub (Group 3 implements)")


async def _register_prompts(
    server: Server, connection: ConnectionManager, config: OdooMcpConfig
) -> None:
    """Stub: Register prompts with the MCP server."""
    logger.debug("Prompt registration stub (Group 3 implements)")


async def _build_registry(
    connection: ConnectionManager, config: OdooMcpConfig
) -> None:
    """Stub: Build model registry."""
    logger.debug("Registry build stub (Group 3 implements)")


# ---------------------------------------------------------------------------
# Server startup
# ---------------------------------------------------------------------------

async def run_server(cli_overrides: dict[str, Any] | None = None) -> None:
    """Main server startup sequence (REQ-01-14)."""

    # Step 1: Parse configuration
    config = load_config(cli_overrides)
    _setup_logging(config.log_level)

    if not config.odoo_verify_ssl:
        logger.warning(
            "SSL verification disabled. This is insecure and should only be used for development."
        )

    logger.info("odoo-mcp v%s starting...", __version__)

    # Step 2: Initialize MCP server (REQ-01-17)
    server = Server("odoo-mcp")

    # Step 3: Establish Odoo connection (REQ-01-15)
    connection = ConnectionManager(config)
    try:
        await connection.connect()
    except Exception as e:
        logger.error("Failed to connect to Odoo: %s", e)
        logger.error("Server cannot start without a valid Odoo connection.")
        sys.exit(1)

    # Step 4: Build model registry (REQ-01-16 — non-critical)
    try:
        await _build_registry(connection, config)
    except Exception as e:
        logger.warning("Registry build failed (non-critical): %s", e)

    # Step 5: Register toolsets (REQ-01-16 — non-critical)
    try:
        await _register_toolsets(server, connection, config)
    except Exception as e:
        logger.warning("Toolset registration failed (non-critical): %s", e)

    # Step 6: Register resources (REQ-01-16 — non-critical)
    try:
        await _register_resources(server, connection, config)
    except Exception as e:
        logger.warning("Resource registration failed (non-critical): %s", e)

    # Step 7: Register prompts (REQ-01-16 — non-critical)
    try:
        await _register_prompts(server, connection, config)
    except Exception as e:
        logger.warning("Prompt registration failed (non-critical): %s", e)

    # Step 8: Start transport (REQ-01-08, REQ-01-09, REQ-01-10)
    logger.info(
        "Starting transport: %s (version: %s, protocol: %s)",
        config.transport,
        connection.odoo_version,
        connection.protocol.protocol_name if connection.protocol else "none",
    )

    # Setup graceful shutdown (REQ-01-24)
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    try:
        if config.transport == "stdio":
            await _run_stdio(server, connection, shutdown_event)
        elif config.transport == "sse":
            await _run_sse(server, connection, config, shutdown_event)
        elif config.transport == "http":
            await _run_http(server, connection, config, shutdown_event)
        else:
            logger.error("Unknown transport: %s", config.transport)
            sys.exit(1)
    finally:
        # Graceful shutdown
        logger.info("Shutting down...")
        await connection.disconnect()
        logger.info("Shutdown complete")


# ---------------------------------------------------------------------------
# Transport runners
# ---------------------------------------------------------------------------

async def _run_stdio(
    server: Server,
    connection: ConnectionManager,
    shutdown_event: asyncio.Event,
) -> None:
    """Run MCP server over stdio (REQ-01-08)."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


async def _run_sse(
    server: Server,
    connection: ConnectionManager,
    config: OdooMcpConfig,
    shutdown_event: asyncio.Event,
) -> None:
    """Run MCP server over SSE (REQ-01-09, REQ-01-26)."""
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Route

    sse_transport = SseServerTransport("/sse")

    async def handle_sse(request: Any) -> Any:
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0],
                streams[1],
                server.create_initialization_options(),
            )

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
        ],
    )

    import uvicorn

    uvicorn_config = uvicorn.Config(
        app,
        host=config.host,
        port=config.port,
        log_level=config.log_level,
    )
    uvicorn_server = uvicorn.Server(uvicorn_config)
    await uvicorn_server.serve()


async def _run_http(
    server: Server,
    connection: ConnectionManager,
    config: OdooMcpConfig,
    shutdown_event: asyncio.Event,
) -> None:
    """Run MCP server over streamable HTTP (REQ-01-10, REQ-01-27)."""
    from mcp.server.streamable_http import StreamableHTTPServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Mount

    transport = StreamableHTTPServerTransport(config.mcp_path)

    async def handle_request(request: Any) -> Any:
        async with transport.connect(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0],
                streams[1],
                server.create_initialization_options(),
            )

    app = Starlette(
        routes=[
            Mount(config.mcp_path, app=handle_request),
        ],
    )

    import uvicorn

    uvicorn_config = uvicorn.Config(
        app,
        host=config.host,
        port=config.port,
        log_level=config.log_level,
    )
    uvicorn_server = uvicorn.Server(uvicorn_config)
    await uvicorn_server.serve()
