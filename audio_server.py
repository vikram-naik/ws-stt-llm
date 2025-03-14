import asyncio
import websockets
import json
import logging
import ssl
from aiohttp import web

logging.basicConfig(level=logging.INFO)

users = {'sales': {}, 'customers': {}}
calls = {}

async def broadcast_user_status():
    sales = list(users['sales'].keys())
    customers = list(users['customers'].keys())
    status = json.dumps({'event': 'user_status', 'sales': sales, 'customers': customers})
    for group in users:
        for ws in users[group].values():
            try:
                await ws.send(status)
            except Exception as e:
                logging.error(f"Error broadcasting user status: {e}")

async def recognize_audio(audio_data, call_id, group, sales_ws):
    await asyncio.sleep(1)  # Mock delay
    text = f"Hello from transcription server ({group})"
    if call_id in calls and sales_ws:
        try:
            await sales_ws.send(json.dumps({'event': 'transcription', 'group': group, 'text': text}))
        except Exception as e:
            logging.error(f"Error sending transcription: {e}")

async def handle_client(websocket):
    path = websocket.request.path
    logging.info(f"WebSocket connection attempt on path: {path}")
    try:
        async for message in websocket:
            if isinstance(message, str):
                data = json.loads(message)
                event = data.get('event')
                logging.info(f"Received control message: {data}")
                if event == 'register':
                    group = data['group']
                    username = data['username']
                    if username in users[group]:
                        await websocket.send(json.dumps({'event': 'error', 'message': 'Username already taken'}))
                        continue
                    users[group][username] = websocket
                    await websocket.send(json.dumps({'event': 'set_cookie', 'session_id': f'{group}_{username}'}))
                    await broadcast_user_status()

                elif event == 'call_user':
                    call_id = data['call_id']
                    to_user = data['to_user']
                    from_group = data['from_group']
                    from_user = data['from_user']
                    to_group = 'customers' if from_group == 'sales' else 'sales'
                    if to_group in users and to_user in users[to_group]:
                        if call_id in calls:
                            await websocket.send(json.dumps({'event': 'error', 'message': 'Call ID already in use'}))
                            continue
                        calls[call_id] = {
                            'caller_ws': websocket,
                            'callee_ws': users[to_group][to_user],
                            'caller_group': from_group,
                            'callee_group': to_group
                        }
                        await users[to_group][to_user].send(json.dumps({
                            'event': 'incoming_call',
                            'from_group': from_group,
                            'from_user': from_user,
                            'call_id': call_id
                        }))
                    else:
                        await websocket.send(json.dumps({'event': 'error', 'message': 'User not found'}))

                elif event == 'accept_call':
                    call_id = next((cid for cid, call in calls.items() if call['callee_ws'] == websocket), None)
                    if call_id:
                        await calls[call_id]['caller_ws'].send(json.dumps({'event': 'call_accepted'}))

                elif event == 'hang_up':
                    call_id = next((cid for cid, call in calls.items() if websocket in call.values()), None)
                    if call_id:
                        peer_ws = calls[call_id]['callee_ws'] if websocket == calls[call_id]['caller_ws'] else calls[call_id]['caller_ws']
                        del calls[call_id]
                        if peer_ws:
                            try:
                                await peer_ws.send(json.dumps({'event': 'call_ended'}))
                            except Exception as e:
                                logging.error(f"Error sending call_ended: {e}")

                elif event == 'logout':
                    for group in users:
                        if websocket in users[group].values():
                            username = next(u for u, ws in users[group].items() if ws == websocket)
                            del users[group][username]
                            await broadcast_user_status()
                            break

            elif isinstance(message, bytes):
                logging.info(f"Received audio chunk of size: {len(message)}")
                call_id = next((cid for cid, call in calls.items() if websocket in call.values()), None)
                if call_id:
                    peer_ws = calls[call_id]['callee_ws'] if websocket == calls[call_id]['caller_ws'] else calls[call_id]['caller_ws']
                    if peer_ws:
                        try:
                            logging.info(f"Relaying audio chunk of size: {len(message)} to peer")
                            await peer_ws.send(message)
                        except Exception as e:
                            logging.error(f"Error relaying audio: {e}")
                    # Transcribe and send only to sales user
                    caller_group = calls[call_id]['caller_group']
                    callee_group = calls[call_id]['callee_group']
                    sales_ws = calls[call_id]['caller_ws'] if caller_group == 'sales' else calls[call_id]['callee_ws'] if callee_group == 'sales' else None
                    if caller_group == 'sales' and websocket == calls[call_id]['caller_ws']:
                        await recognize_audio(message, call_id, 'sales', sales_ws)
                    elif callee_group == 'sales' and websocket == calls[call_id]['callee_ws']:
                        await recognize_audio(message, call_id, 'customers', sales_ws)

    except websockets.ConnectionClosed:
        for group in users:
            if websocket in users[group].values():
                username = next(u for u, ws in users[group].items() if ws == websocket)
                del users[group][username]
                await broadcast_user_status()
                break
        for call_id in list(calls.keys()):
            if websocket in calls[call_id].values():
                peer_ws = calls[call_id]['callee_ws'] if websocket == calls[call_id]['caller_ws'] else calls[call_id]['caller_ws']
                del calls[call_id]
                if peer_ws:
                    try:
                        await peer_ws.send(json.dumps({'event': 'call_ended'}))
                    except Exception as e:
                        logging.error(f"Error sending call_ended: {e}")
    except Exception as e:
        logging.error(f"Client handler error: {e}")
        logging.exception(e)

# HTTP server for static files
async def serve_index(request):
    return web.FileResponse('index.html')

async def init_app():
    app = web.Application()
    app.router.add_get('/', serve_index)
    app.router.add_static('/static/', path='static', name='static')
    app.router.add_static('/', path='.', name='root')
    return app

async def main():
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(certfile='cert.pem', keyfile='key.pem')

    ws_server = await websockets.serve(
        handle_client,
        '0.0.0.0',
        8000,
        ssl=ssl_context
    )
    
    app = await init_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080, ssl_context=ssl_context)
    await site.start()
    
    logging.info("WebSocket server running on wss://0.0.0.0:8000/ws")
    logging.info("HTTP server running on https://0.0.0.0:8080")
    
    await asyncio.Future()

if __name__ == '__main__':
    asyncio.run(main())