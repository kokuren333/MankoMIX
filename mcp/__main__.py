"""``python -m mankomix.mcp --root <workspace>``: the MCP server over stdio.

Same server as ``mankomix mcp --root <workspace>``.
"""

from __future__ import annotations

import argparse
import json
import sys

from mankomix import ENGINE_VERSION
from mankomix.core.errors import MankoError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mankomix-mcp",
                                     description="MankoMIX MCP server (JSON-RPC 2.0 over stdio).")
    parser.add_argument("--root", default=".",
                        help="workspace folder; every path argument must stay inside it (default: current folder)")
    parser.add_argument("--version", action="version", version=f"mankomix {ENGINE_VERSION}")
    args = parser.parse_args(argv)
    from .server import run_stdio
    try:
        return run_stdio(args.root)
    except MankoError as e:
        # Startup failure (bad root): nothing has been served, report on stderr.
        sys.stderr.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")
        return e.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
