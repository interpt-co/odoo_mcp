"""CLI entry point for odoo-mcp server."""

import argparse
import asyncio
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="odoo-mcp",
        description="MCP server for Odoo ERP",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "http"],
        default=None,
        help="Transport mode (default: stdio)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to JSON configuration file",
    )
    parser.add_argument(
        "--odoo-url",
        default=None,
        help="Odoo instance URL",
    )
    parser.add_argument(
        "--odoo-db",
        default=None,
        help="Odoo database name",
    )
    parser.add_argument(
        "--odoo-username",
        default=None,
        help="Odoo username",
    )
    parser.add_argument(
        "--odoo-password",
        default=None,
        help="Odoo password",
    )
    parser.add_argument(
        "--odoo-api-key",
        default=None,
        help="Odoo API key",
    )
    parser.add_argument(
        "--odoo-protocol",
        choices=["auto", "xmlrpc", "jsonrpc", "json2"],
        default=None,
        help="Force Odoo protocol (default: auto)",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Host to bind for SSE/HTTP transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to bind for SSE/HTTP transport (default: 8080)",
    )
    parser.add_argument(
        "--mode",
        choices=["readonly", "restricted", "full"],
        default=None,
        help="Operation mode (default: readonly)",
    )
    parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error", "critical"],
        default=None,
        help="Log level (default: info)",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Build CLI overrides dict (only non-None values)
    cli_overrides: dict = {}
    if args.transport is not None:
        cli_overrides["transport"] = args.transport
    if args.config is not None:
        cli_overrides["_config_path"] = args.config
    if args.odoo_url is not None:
        cli_overrides["odoo_url"] = args.odoo_url
    if args.odoo_db is not None:
        cli_overrides["odoo_db"] = args.odoo_db
    if args.odoo_username is not None:
        cli_overrides["odoo_username"] = args.odoo_username
    if args.odoo_password is not None:
        cli_overrides["odoo_password"] = args.odoo_password
    if args.odoo_api_key is not None:
        cli_overrides["odoo_api_key"] = args.odoo_api_key
    if args.odoo_protocol is not None:
        cli_overrides["odoo_protocol"] = args.odoo_protocol
    if args.host is not None:
        cli_overrides["host"] = args.host
    if args.port is not None:
        cli_overrides["port"] = args.port
    if args.mode is not None:
        cli_overrides["mode"] = args.mode
    if args.log_level is not None:
        cli_overrides["log_level"] = args.log_level

    from odoo_mcp.server import run_server

    try:
        asyncio.run(run_server(cli_overrides))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"Fatal: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
