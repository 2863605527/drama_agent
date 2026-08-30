import asyncio
from mcp.server import Server
from mcp.types import TextContent
from tools.rag_tool import retrieve_lens_knowledge

app = Server("rag-mcp-server")

@app.tool()
async def rag_retrieve_lens(query_vector: list, top_k:int=3):
    items = retrieve_lens_knowledge(query_vector, top_k)
    return [TextContent(type="text", text=str(items))]

async def main():
    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
