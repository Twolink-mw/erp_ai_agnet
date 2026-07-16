import asyncio

from backend.app.mcp_client import mcp_client

async def main():
    try:
        await mcp_client.connect()
        tools = await mcp_client.list_tools()
        print('TOOLS:', [t.name for t in tools])
    except Exception as e:
        print('ERROR', type(e), e)
    finally:
        try:
            await mcp_client.close()
        except Exception:
            pass

if __name__ == '__main__':
    asyncio.run(main())
