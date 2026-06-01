"""OpenAI provider — SSE streaming with tool calling support."""

import json
from collections.abc import AsyncIterator

import httpx

from mewcode.config.models import ProviderConfig
from mewcode.providers.base import BaseProvider, Message, ToolCall


class OpenAIProvider(BaseProvider):
    """Provider for the OpenAI Chat Completions API."""

    async def chat_stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        system_blocks: list[dict] | None = None,
    ) -> AsyncIterator[str | ToolCall]:
        base = self.config.base_url.rstrip("/")
        url = f"{base}/v1/chat/completions"

        body: dict = {
            "model": self.config.model,
            "messages": messages,
            "stream": True,
        }

        if tools:
            body["tools"] = tools

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            async with client.stream("POST", url, json=body, headers=headers) as resp:
                if resp.status_code != 200:
                    error_text = await resp.aread()
                    yield f"<<ERROR:{resp.status_code}:{error_text.decode(errors='replace')[:500]}>>"
                    return

                # Accumulate tool call fragments (indexed by tool call index)
                tool_calls_acc: dict[int, dict] = {}

                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[len("data: "):]

                    if data_str.strip() == "[DONE]":
                        break

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    choices = data.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})

                    # Handle tool call deltas
                    tc_deltas = delta.get("tool_calls", [])
                    if tc_deltas:
                        for tc in tc_deltas:
                            idx = tc.get("index", 0)
                            if idx not in tool_calls_acc:
                                tool_calls_acc[idx] = {
                                    "id": tc.get("id", ""),
                                    "type": "function",
                                    "function": {
                                        "name": "",
                                        "arguments": "",
                                    },
                                }
                            acc = tool_calls_acc[idx]
                            if tc.get("id"):
                                acc["id"] = tc["id"]
                            func = tc.get("function", {})
                            if func.get("name"):
                                acc["function"]["name"] += func["name"]
                            if func.get("arguments"):
                                acc["function"]["arguments"] += func["arguments"]

                    # Handle text content
                    content = delta.get("content", "")
                    if content:
                        yield content

                # After stream ends, yield completed tool calls
                for tc_data in tool_calls_acc.values():
                    func = tc_data.get("function", {})
                    tool_name = func.get("name", "")
                    args_str = func.get("arguments", "")
                    try:
                        tool_input = json.loads(args_str) if args_str else {}
                    except json.JSONDecodeError:
                        tool_input = {}
                    yield ToolCall(
                        id=tc_data.get("id", ""),
                        name=tool_name,
                        input=tool_input,
                    )

    # -- tool message formatting (OpenAI style) --------------------------------

    def make_tool_calls_message(
        self, tool_calls: list[ToolCall], text_prefix: str = ""
    ) -> Message:
        return {
            "role": "assistant",
            "content": text_prefix or None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.input, ensure_ascii=False),
                    },
                }
                for tc in tool_calls
            ],
        }

    def make_tool_result_message(
        self, tool_call_id: str, tool_name: str, result_text: str
    ) -> Message:
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result_text,
        }
