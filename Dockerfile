# Multi-stage build for smaller image (REQ-01-28)

# --- Build stage ---
FROM python:3.11-slim AS builder

WORKDIR /build

COPY pyproject.toml ./
COPY odoo_mcp/ ./odoo_mcp/

RUN pip install --no-cache-dir --prefix=/install .

# --- Runtime stage ---
FROM python:3.11-slim

WORKDIR /app

COPY --from=builder /install /usr/local

# Default to streamable HTTP transport on port 8080
ENV ODOO_MCP_TRANSPORT=http
ENV ODOO_MCP_HOST=0.0.0.0
ENV ODOO_MCP_PORT=8080

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/mcp')" || exit 1

ENTRYPOINT ["odoo-mcp"]
