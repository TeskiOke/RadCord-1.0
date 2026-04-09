import asyncio
import sys

async def main():
    try:
        from core.network_scanner import NetworkScanner
        print("Starting scan...")
        res = await NetworkScanner().scan(4.0)
        print("Scan finished!", res)
    except Exception as e:
        print("ERROR:", type(e), e)

if __name__ == "__main__":
    asyncio.run(main())
