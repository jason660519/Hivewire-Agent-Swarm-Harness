"""Hivewire co-routing A1 demo — end-to-end MCP round-trip.

Launches the co-routing MCP server via stdio, connects as an MCP client
(the same protocol any AG-UI-compatible runtime uses), lists available tools,
then calls web_fetch with the mock-us-west egress pool.

Run from co-routing/:
    uv run python demo/demo.py [URL]

URL defaults to https://httpbin.org/get.
No API key required — the mock egress pool makes a direct connection
and clearly labels itself as mocked in the response metadata.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_ROOT = Path(__file__).parent.parent  # co-routing/


async def main(url: str) -> None:
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "python", "server.py"],
        cwd=str(_ROOT),
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("[demo] MCP server started. Available tools:")
            for tool in tools.tools:
                print(f"  • {tool.name}")

            print(f"\n[demo] Calling web_fetch({url!r}, egress_pool=mock-us-west) ...")
            result = await session.call_tool(
                "web_fetch",
                arguments={
                    "url": url,
                    "route_profile": {
                        "egress_pool": "mock-us-west",
                        "region": "us-west",
                        "session_policy": "rotating",
                    },
                },
            )

            payload = json.loads(result.content[0].text)

            print(f"\n[demo] HTTP {payload['status_code']} from {payload['url']}")
            print("[demo] Routing metadata:")
            for k, v in payload["routing"].items():
                print(f"         {k}: {v}")
            print(f"\n[demo] Body preview (first 500 chars):")
            print(payload["body"][:500])


if __name__ == "__main__":
    target_url = sys.argv[1] if len(sys.argv) > 1 else "https://httpbin.org/get"
    asyncio.run(main(target_url))
