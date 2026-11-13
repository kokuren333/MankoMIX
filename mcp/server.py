"""MankoMIX MCP server over stdio (SPEC 10.3), without third-party MCP libraries.

Transport: JSON-RPC 2.0, one JSON message per line on stdin/stdout, UTF-8.
Only protocol messages are written to stdout; logs go to stderr.

Methods: ``initialize``, ``notifications/initialized``, ``ping``,
``tools/list``, ``tools/call`` (plus no-op handling of other notifications).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from typing import IO, Any

from mankomix import ENGINE_VERSION

from .tools import Toolbox
from .workspace import Workspace

log = logging.getLogger("mankomix.mcp")

SERVER_NAME = "mankomix"
# Newest first; the first entry is offered when the client asks for a version we do not know.
SUPPORTED_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

INSTRUCTIONS = (
    "MankoMIX: deterministic mixing and mastering. All paths are relative to the workspace folder the "
    "server was started with; a 'project' argument names a project folder inside it (default '.'). "
    "Results are measurement summaries by default; pass detail='full' only when you need everything. "
    "Long tools accept async=true and return a job_id (poll job_status, then job_result). "
    "Project changes made through this server are journaled with actor 'agent' and can be undone "
    "(history_undo)."
)


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


class Server:
    def __init__(self, root: str | os.PathLike[str]):
        self.workspace = Workspace(root)
        self.toolbox = Toolbox(self.workspace)
        self.protocol_version: str | None = None
        self.client_info: dict | None = None
        self.initialized = False

    # -- dispatch ------------------------------------------------------------

    def handle(self, msg: Any) -> dict | list | None:
        """Handle one decoded JSON-RPC message (or batch); returns the response or None."""
        if isinstance(msg, list):
            if not msg:
                return _error(None, INVALID_REQUEST, "empty batch")
            out = [r for r in (self._handle_one(m) for m in msg) if r is not None]
            return out or None
        return self._handle_one(msg)

    def handle_line(self, line: str | bytes) -> str | None:
        """Handle one raw line; returns the serialized response line (without newline) or None."""
        if isinstance(line, bytes):
            try:
                line = line.decode("utf-8")
            except UnicodeDecodeError:
                return _dump(_error(None, PARSE_ERROR, "message is not valid UTF-8"))
        line = line.lstrip("﻿").strip()
        if not line:
            return None
        try:
            msg = json.loads(line)
        except ValueError as e:
            return _dump(_error(None, PARSE_ERROR, f"parse error: {e}"))
        resp = self.handle(msg)
        return None if resp is None else _dump(resp)

    def _handle_one(self, msg: Any) -> dict | None:
        if not isinstance(msg, dict):
            return _error(None, INVALID_REQUEST, "message must be a JSON object")
        has_id = "id" in msg
        mid = msg.get("id")
        if "method" not in msg:
            # A response from the client (we never send requests) or garbage.
            if has_id and ("result" in msg or "error" in msg):
                return None
            return _error(mid if _valid_id(mid) else None, INVALID_REQUEST, "missing method")
        method = msg.get("method")
        if msg.get("jsonrpc") != "2.0" or not isinstance(method, str) or (has_id and not _valid_id(mid)):
            return _error(mid if _valid_id(mid) else None, INVALID_REQUEST, "invalid JSON-RPC 2.0 request")
        params = msg.get("params")
        if params is not None and not isinstance(params, (dict, list)):
            if not has_id:
                return None
            return _error(mid, INVALID_PARAMS, "params must be an object")
        if not has_id:
            self._notification(method, params or {})
            return None
        try:
            result = self._request(method, params if isinstance(params, dict) else {})
            return {"jsonrpc": "2.0", "id": mid, "result": result}
        except RpcError as e:
            return _error(mid, e.code, e.message, e.data)
        except Exception as e:  # noqa: BLE001 - the loop must survive anything
            log.exception("internal error in %s", method)
            return _error(mid, INTERNAL_ERROR, f"internal error: {type(e).__name__}")

    def _notification(self, method: str, params: Any) -> None:
        if method == "notifications/initialized":
            self.initialized = True
        elif method == "notifications/cancelled":
            log.info("client cancelled request %s (calls run to completion)", (params or {}).get("requestId"))
        else:
            log.debug("ignored notification %s", method)

    def _request(self, method: str, params: dict) -> dict:
        if method == "initialize":
            return self._initialize(params)
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": self.toolbox.list()}
        if method == "tools/call":
            return self._tools_call(params)
        # resources/* and prompts/* are not offered (capabilities announce tools only).
        raise RpcError(METHOD_NOT_FOUND, f"method not found: {method}")

    def _initialize(self, params: dict) -> dict:
        requested = params.get("protocolVersion")
        if not isinstance(requested, str):
            raise RpcError(INVALID_PARAMS, "protocolVersion is required")
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else SUPPORTED_PROTOCOL_VERSIONS[0]
        self.protocol_version = version
        self.client_info = params.get("clientInfo") if isinstance(params.get("clientInfo"), dict) else None
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "title": "MankoMIX", "version": ENGINE_VERSION},
            "instructions": INSTRUCTIONS,
        }

    def _tools_call(self, params: dict) -> dict:
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise RpcError(INVALID_PARAMS, "tools/call needs a tool name")
        args = params.get("arguments", {})
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise RpcError(INVALID_PARAMS, "tools/call arguments must be an object")
        payload, is_error = self.toolbox.call(name, args)
        text = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        return {"content": [{"type": "text", "text": text}], "structuredContent": payload, "isError": is_error}

    # -- stdio loop ------------------------------------------------------------

    def serve(self, instream: IO[bytes], outstream: IO[bytes]) -> int:
        lock = threading.Lock()
        log.info("mankomix MCP server ready (workspace '%s')", self.workspace.root.name)
        for raw in instream:
            out = self.handle_line(raw)
            if out is None:
                continue
            with lock:
                outstream.write(out.encode("utf-8") + b"\n")
                outstream.flush()
        return 0


def _valid_id(mid: Any) -> bool:
    return isinstance(mid, (str, int)) and not isinstance(mid, bool)


def _error(mid: Any, code: int, message: str, data: Any = None) -> dict:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": mid, "error": err}


def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _setup_logging() -> None:
    level = os.environ.get("MANKOMIX_MCP_LOG", "WARNING").upper()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("mankomix-mcp %(levelname)s %(message)s"))
    root = logging.getLogger("mankomix")
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, level, logging.WARNING))
    root.propagate = False


def run_stdio(root: str | os.PathLike[str]) -> int:
    """Serve MCP over the process's stdin/stdout until stdin closes."""
    _setup_logging()
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if reconf is not None:
            try:
                reconf(encoding="utf-8", errors="replace" if stream is not sys.stdin else "strict")
            except (ValueError, OSError):
                pass
    server = Server(root)       # raises InputError for a bad root before anything is written
    instream = sys.stdin.buffer
    outstream = sys.stdout.buffer
    # Anything that prints (a library warning, a stray print) must not corrupt the protocol stream.
    real_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        return server.serve(instream, outstream)
    except KeyboardInterrupt:
        return 0
    finally:
        sys.stdout = real_stdout
