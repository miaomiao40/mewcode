"""JSON-RPC 2.0 message types and helpers."""

import json
from dataclasses import dataclass, field
from typing import Any

JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2024-11-05"


@dataclass
class JSONRPCRequest:
    method: str
    params: dict[str, Any] | None = None
    id: int = 0
    jsonrpc: str = JSONRPC_VERSION


@dataclass
class JSONRPCResponse:
    id: int
    result: Any = None
    error: dict | None = None
    jsonrpc: str = JSONRPC_VERSION


@dataclass
class JSONRPCNotification:
    method: str
    params: dict[str, Any] | None = None
    jsonrpc: str = JSONRPC_VERSION


def encode_message(msg: JSONRPCRequest | JSONRPCResponse | JSONRPCNotification) -> str:
    """Encode a JSON-RPC message to a JSON string (single line, no trailing newline)."""
    data: dict[str, Any] = {"jsonrpc": msg.jsonrpc}
    if isinstance(msg, JSONRPCRequest):
        data["id"] = msg.id
        data["method"] = msg.method
        if msg.params is not None:
            data["params"] = msg.params
    elif isinstance(msg, JSONRPCResponse):
        data["id"] = msg.id
        if msg.error is not None:
            data["error"] = msg.error
        else:
            data["result"] = msg.result
    elif isinstance(msg, JSONRPCNotification):
        data["method"] = msg.method
        if msg.params is not None:
            data["params"] = msg.params
    return json.dumps(data, ensure_ascii=False)


def decode_message(line: str) -> JSONRPCRequest | JSONRPCResponse | JSONRPCNotification | None:
    """Decode a JSON-RPC message from a JSON string."""
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    if "method" in data and "id" in data:
        return JSONRPCRequest(
            method=data["method"],
            params=data.get("params"),
            id=data["id"],
        )
    if "method" in data and "id" not in data:
        return JSONRPCNotification(
            method=data["method"],
            params=data.get("params"),
        )
    if "id" in data and ("result" in data or "error" in data):
        return JSONRPCResponse(
            id=data["id"],
            result=data.get("result"),
            error=data.get("error"),
        )
    return None
