"""Agent侧MCP Client，本demo暂时作为预留骨架，可替换原有tools调用"""
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

class DramaMcpClient:
    def __init__(self):
        self.session = None

    async def connect_llm_server(self):
        params = StdioServerParameters(command="python", args=["mcp_server/llm_mcp.py"])
        read, write = await stdio_client(params)
        session = ClientSession(read, write)
        await session.initialize()
        self.session = session
        return session

    async def call_llm_tool(self, messages, temperature=0.7):
        res = await self.session.call_tool("llm_chat_tool", {"messages":messages,"temperature":temperature})
        return res.content[0].text
