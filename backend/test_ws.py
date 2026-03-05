import asyncio, websockets
async def main():
    try:
        async with websockets.connect('wss://stream.aisstream.io/v0/stream') as ws:
            print('Connected to AIS Stream!')
    except Exception as e:
        print(f"Error: {e}")
asyncio.run(main())
