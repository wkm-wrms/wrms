
# SSE endpoint - każdy klient dostaje swoją własną kolejkę, do której są wysyłane aktualizacje stanu. Dzięki temu można mieć wiele wyświetlaczy podłączonych jednocześnie, a każdy z nich będzie otrzymywał aktualizacje bez opóźnień.

@app.get("/api/sse")
async def sse_endpoint(request: Request):
    # Każde połączenie dostaje swoją własną kolejkę
    client_queue = asyncio.Queue()
    await manager.connect_sse(client_queue)

    async def event_generator():
        try:
            while True:
                # Sprawdź, czy klient nadal jest połączony
                if await request.is_disconnected():
                    break
                # Czekaj na nową wiadomość w kolejce dla tego klienta
                # Timeout pozwala na wysyłanie "pingów", żeby utrzymać połączenie
                try:
                    message = await asyncio.wait_for(client_queue.get(), timeout=20.0)
                    yield {
                        "event": "message",
                        "data": message
                    }
                except asyncio.TimeoutError:
                    yield {
                        "event": "ping",
                        "data": "heartbeat"
                    }
        finally:
            # Zawsze usuń klienta z rejestru po rozłączeniu
            await manager.disconnect_sse(client_queue)

    return EventSourceResponse(event_generator())
