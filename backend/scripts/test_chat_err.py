import asyncio, sys
sys.path.insert(0, '.')
from backend.app.gemini_agent import run_chat
from backend.app.mcp_client import mcp_client

async def main():
    await mcp_client.connect()
    try:
        result = await run_chat([{"role": "user", "content": "매출 데이터에서 제품명별 매출금액을 알려줘"}])
        print("REPLY:", result["reply"])
        print("TOOLS:", result["tool_calls"])
    except Exception as e:
        print("EXC:", type(e), e)
    finally:
        await mcp_client.close()

asyncio.run(main())
