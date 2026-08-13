"""Coherra — structured memory auditor and repair engine for Sibyl Memory.

An MCP server + CLI that writes clean, versioned entities to Sibyl Memory
and continuously audits for drift: contradictions, duplicates, and stale facts.

Usage (MCP server, add to your .mcp.json or Claude Code settings):
    {
      "mcpServers": {
        "coherra": { "command": "coherra-mcp" }
      }
    }

Usage (CLI):
    coherra health     -- show last audit result or "no audits run yet"
    coherra scan       -- run a full audit (checkpoint 2)
    coherra issues     -- list flagged problems (checkpoint 2)
    coherra fix <id>   -- apply a repair (checkpoint 2)
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("coherra")
except PackageNotFoundError:  # pragma: no cover — editable / source-tree dev
    __version__ = "0.0.0+source"

__all__ = ["__version__"]
