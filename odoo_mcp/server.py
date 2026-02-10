"""MCP server initialization, transport setup, and startup sequence.

REQ-01-08 through REQ-01-11, REQ-01-14 through REQ-01-18, REQ-01-21 through REQ-01-27.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
from typing import Any

from mcp import types
from mcp.server.fastmcp import FastMCP
from mcp.server.stdio import stdio_server

from odoo_mcp import __version__
from odoo_mcp.config import OdooMcpConfig, load_config
from odoo_mcp.connection.manager import ConnectionManager
from odoo_mcp.registry.model_registry import ModelRegistry
from odoo_mcp.resources.provider import ResourceContext, ResourceProvider
from odoo_mcp.prompts.provider import PromptContext, PromptProvider
from odoo_mcp.toolsets.registry import ToolsetRegistry

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
# Registration implementations
# ---------------------------------------------------------------------------

async def _build_registry(
    connection: ConnectionManager, config: OdooMcpConfig
) -> ModelRegistry:
    """Build model registry from live Odoo (REQ-01-16, REQ-07-09)."""
    model_registry = ModelRegistry()
    if connection.protocol is not None:
        await model_registry.build_dynamic(connection.protocol)
    else:
        logger.warning("No protocol available — registry will be empty")
    return model_registry


async def _register_toolsets(
    server: FastMCP, connection: ConnectionManager, config: OdooMcpConfig
) -> ToolsetRegistry:
    """Discover, filter, and register all eligible toolsets (REQ-03-04)."""
    toolset_registry = ToolsetRegistry(connection, config)
    report = await toolset_registry.discover_and_register(server)
    logger.info(
        "Toolset registration: %d/%d toolsets, %d tools total",
        report.registered_toolsets,
        report.total_toolsets,
        report.total_tools,
    )
    return toolset_registry


async def _register_resources(
    server: FastMCP,
    connection: ConnectionManager,
    config: OdooMcpConfig,
    model_registry: ModelRegistry | None,
    toolset_registry: ToolsetRegistry | None,
) -> ResourceProvider:
    """Register MCP resources and resource templates (REQ-06-02)."""
    conn_info = connection.get_connection_info()

    toolset_data = []
    if toolset_registry is not None:
        report = toolset_registry.get_report()
        if report is not None:
            for r in report.results:
                if r.status == "registered":
                    toolset_data.append({
                        "name": r.name,
                        "tools": r.tools_registered,
                    })

    context = ResourceContext(
        registry=model_registry,
        protocol=connection.protocol,
        server_version=conn_info.get("odoo_version", ""),
        server_edition=conn_info.get("edition", ""),
        database=conn_info.get("database", ""),
        url=conn_info.get("url", ""),
        protocol_name=conn_info.get("protocol", ""),
        user_uid=conn_info.get("uid", 0) or 0,
        user_name=conn_info.get("username", ""),
        mcp_server_version=__version__,
        toolsets=toolset_data,
        installed_modules=[
            {"name": m} for m in conn_info.get("installed_modules", [])
        ],
        model_blocklist=set(getattr(config, "model_blocklist", [])),
        field_blocklist=set(getattr(config, "field_blocklist", [])),
        readonly_mode=(getattr(config, "mode", "readonly") == "readonly"),
    )

    provider = ResourceProvider(context)
    low = server._mcp_server

    # Register list_resources handler
    @low.list_resources()
    async def handle_list_resources() -> list[types.Resource]:
        defs = provider.get_resource_definitions()
        return [
            types.Resource(
                uri=d["uri"],
                name=d["name"],
                mimeType=d.get("mimeType"),
                description=d.get("description"),
            )
            for d in defs
        ]

    # Register list_resource_templates handler
    @low.list_resource_templates()
    async def handle_list_resource_templates() -> list[types.ResourceTemplate]:
        defs = provider.get_resource_templates()
        return [
            types.ResourceTemplate(
                uriTemplate=d["uriTemplate"],
                name=d["name"],
                mimeType=d.get("mimeType"),
                description=d.get("description"),
            )
            for d in defs
        ]

    # Register read_resource handler
    @low.read_resource()
    async def handle_read_resource(uri: Any) -> str:
        result = await provider.read_resource(str(uri))
        return json.dumps(result, default=str)

    # Register subscription handlers
    @low.subscribe_resource()
    async def handle_subscribe(uri: Any) -> None:
        await provider.subscribe(str(uri))

    @low.unsubscribe_resource()
    async def handle_unsubscribe(uri: Any) -> None:
        await provider.unsubscribe(str(uri))

    resource_count = len(provider.get_resource_definitions())
    template_count = len(provider.get_resource_templates())
    logger.info(
        "Registered %d resources and %d resource templates",
        resource_count,
        template_count,
    )
    return provider


async def _register_prompts(
    server: FastMCP,
    connection: ConnectionManager,
    config: OdooMcpConfig,
    model_registry: ModelRegistry | None,
    toolset_registry: ToolsetRegistry | None,
) -> PromptProvider:
    """Register MCP prompts (REQ-06-17)."""
    conn_info = connection.get_connection_info()

    toolset_data = []
    if toolset_registry is not None:
        report = toolset_registry.get_report()
        if report is not None:
            for r in report.results:
                if r.status == "registered":
                    toolset_data.append({
                        "name": r.name,
                        "tools": r.tools_registered,
                    })

    context = PromptContext(
        registry=model_registry,
        server_version=conn_info.get("odoo_version", ""),
        server_edition=conn_info.get("edition", ""),
        url=conn_info.get("url", ""),
        database=conn_info.get("database", ""),
        username=conn_info.get("username", ""),
        uid=conn_info.get("uid", 0) or 0,
        toolsets=toolset_data,
    )

    provider = PromptProvider(context)
    low = server._mcp_server

    # Register list_prompts handler
    @low.list_prompts()
    async def handle_list_prompts() -> list[types.Prompt]:
        defs = provider.get_prompt_definitions()
        prompts = []
        for d in defs:
            args = None
            if "arguments" in d:
                args = [
                    types.PromptArgument(
                        name=a["name"],
                        description=a.get("description"),
                        required=a.get("required", False),
                    )
                    for a in d["arguments"]
                ]
            prompts.append(
                types.Prompt(
                    name=d["name"],
                    description=d.get("description"),
                    arguments=args,
                )
            )
        return prompts

    # Register get_prompt handler
    @low.get_prompt()
    async def handle_get_prompt(
        name: str, arguments: dict[str, str] | None
    ) -> types.GetPromptResult:
        messages_data = await provider.get_prompt(name, arguments)
        messages = [
            types.PromptMessage(
                role=m["role"],
                content=types.TextContent(
                    type="text",
                    text=m["content"]["text"],
                ),
            )
            for m in messages_data
        ]
        return types.GetPromptResult(messages=messages)

    prompt_count = len(provider.get_prompt_definitions())
    logger.info("Registered %d prompts", prompt_count)
    return provider


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
    # Use FastMCP because toolsets call server.tool(name=..., description=..., annotations=...)
    server = FastMCP("odoo-mcp")

    # Step 3: Establish Odoo connection (REQ-01-15)
    connection = ConnectionManager(config)
    try:
        await connection.connect()
    except Exception as e:
        logger.error("Failed to connect to Odoo: %s", e)
        logger.error("Server cannot start without a valid Odoo connection.")
        sys.exit(1)

    # Step 4: Build model registry (REQ-01-16 — non-critical)
    model_registry: ModelRegistry | None = None
    try:
        model_registry = await _build_registry(connection, config)
    except Exception as e:
        logger.warning("Registry build failed (non-critical): %s", e)

    # Step 5: Register toolsets (REQ-01-16 — non-critical)
    toolset_registry: ToolsetRegistry | None = None
    try:
        toolset_registry = await _register_toolsets(server, connection, config)
    except Exception as e:
        logger.warning("Toolset registration failed (non-critical): %s", e)

    # Step 6: Register resources (REQ-01-16 — non-critical)
    try:
        await _register_resources(
            server, connection, config, model_registry, toolset_registry
        )
    except Exception as e:
        logger.warning("Resource registration failed (non-critical): %s", e)

    # Step 7: Register prompts (REQ-01-16 — non-critical)
    try:
        await _register_prompts(
            server, connection, config, model_registry, toolset_registry
        )
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

    # Use the low-level Server for transport (it has the .run() with streams API)
    low = server._mcp_server

    try:
        if config.transport == "stdio":
            await _run_stdio(low, connection, shutdown_event)
        elif config.transport == "sse":
            await _run_sse(low, connection, config, shutdown_event)
        elif config.transport == "http":
            await _run_http(low, connection, config, shutdown_event)
        else:
            logger.error("Unknown transport: %s", config.transport)
            sys.exit(1)
    finally:
        # Graceful shutdown
        logger.info("Shutting down...")
        await connection.disconnect()
        logger.info("Shutdown complete")


# ---------------------------------------------------------------------------
# Transport runners (use low-level Server for stream-based transports)
# ---------------------------------------------------------------------------

async def _run_stdio(
    server: Any,
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
    server: Any,
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
    server: Any,
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
