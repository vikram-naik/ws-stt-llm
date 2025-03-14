import asyncio
import json
import logging
import ssl
import websockets
from aiohttp import web
import os
from websockets import State

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

users = {'sales': {}, 'customers': {}}
calls = {}
websocket_clients = {}
udp_relay_socket = None

async def broadcast_user_status():
    sales = list(users['sales'].keys())
    customers = list(users['customers'].keys())
    status = json.dumps({'event': 'user_status', 'sales': sales, 'customers': customers})
    logging.info(f"Broadcasting user status: {status}")
    for username, ws in list(websocket_clients.items()):
        if ws.state == State.OPEN:
            try:
                await ws.send(status)
            except Exception as e:
                logging.error(f"Error broadcasting to {username} ({ws.remote_address[0]}): {e}")
                del websocket_clients[username]

async def notify_udp_relay(event, data):
    global udp_relay_socket
    if udp_relay_socket and udp_relay_socket.state == State.OPEN:
        try:
            await udp_relay_socket.send(json.dumps({'event': event, **data}))
            logging.info(f"Notified UDP relay: {event} - {data}")
        except Exception as e:
            logging.error(f"Error notifying UDP relay: {e}")
            udp_relay_socket = None

async def handle_websocket(websocket):
    client_ip = websocket.remote_address[0]
    try:
        async for message in websocket:
            if isinstance(message, str):
                data = json.loads(message)
                event = data.get('event')
                logging.info(f"Received from {client_ip}: {data}")
                if event == 'register':
                    group = data.get('group')
                    username = data.get('username')
                    port = data.get('port')
                    if not all([group, username, port]):
                        await websocket.send(json.dumps({'event': 'error', 'message': 'Missing group, username, or port'}))
                        continue
                    users[group][username] = {'ws': websocket, 'ip': client_ip, 'port': port}
                    websocket_clients[username] = websocket
                    await websocket.send(json.dumps({'event': 'set_cookie', 'session_id': f'{group}_{username}', 'ip': client_ip}))
                    await broadcast_user_status()
                elif event == 'call_user':
                    call_id = data.get('call_id')
                    to_user = data.get('to_user')
                    from_group = data.get('from_group')
                    from_user = data.get('from_user', 'unknown')
                    to_group = 'customers' if from_group == 'sales' else 'sales'
                    if not all([call_id, to_user, from_group, from_user]):
                        await websocket.send(json.dumps({'event': 'error', 'message': 'Missing call_id, to_user, from_group, or from_user'}))
                        continue
                    if to_group in users and to_user in users[to_group]:
                        calls[call_id] = {
                            'caller_ws': websocket,
                            'callee_ws': users[to_group][to_user]['ws'],
                            'caller_ip': users[from_group][from_user]['ip'],
                            'callee_ip': users[to_group][to_user]['ip'],
                            'caller_port': users[from_group][from_user]['port'],
                            'callee_port': users[to_group][to_user]['port'],
                            'caller_group': from_group,
                            'callee_group': to_group
                        }
                        await users[to_group][to_user]['ws'].send(json.dumps({
                            'event': 'incoming_call',
                            'call_id': call_id,
                            'peer_ip': calls[call_id]['caller_ip'],
                            'peer_port': calls[call_id]['caller_port'],
                            'from_user': from_user
                        }))
                    else:
                        await websocket.send(json.dumps({'event': 'error', 'message': 'User not found'}))
                elif event == 'accept_call':
                    call_id = data.get('call_id')
                    if not call_id:
                        await websocket.send(json.dumps({'event': 'error', 'message': 'Missing call_id'}))
                        continue
                    if call_id in calls:
                        await calls[call_id]['caller_ws'].send(json.dumps({
                            'event': 'call_accepted',
                            'peer_ip': calls[call_id]['callee_ip'],
                            'peer_port': calls[call_id]['callee_port']
                        }))
                        await notify_udp_relay('call_accepted', {
                            'call_id': call_id,
                            'caller_ip': calls[call_id]['caller_ip'],
                            'callee_ip': calls[call_id]['callee_ip'],
                            'caller_group': calls[call_id]['caller_group'],
                            'callee_group': calls[call_id]['callee_group']
                        })
                    else:
                        await websocket.send(json.dumps({'event': 'error', 'message': 'Call not found'}))
                elif event == 'hang_up':
                    call_id = data.get('call_id')
                    if not call_id:
                        await websocket.send(json.dumps({'event': 'error', 'message': 'Missing call_id'}))
                        continue
                    if call_id in calls:
                        caller_ws = calls[call_id]['caller_ws']
                        callee_ws = calls[call_id]['callee_ws']
                        del calls[call_id]
                        for ws in [caller_ws, callee_ws]:
                            if ws and ws.state == State.OPEN:
                                await ws.send(json.dumps({'event': 'call_ended'}))
                        await notify_udp_relay('call_ended', {'call_id': call_id})
                elif event == 'logout':
                    for group in users:
                        if websocket in [u['ws'] for u in users[group].values()]:
                            username = next(u for u, d in users[group].items() if d['ws'] == websocket)
                            del users[group][username]
                            if username in websocket_clients:
                                del websocket_clients[username]
                            await broadcast_user_status()
                            await notify_udp_relay('logout', {'ip': client_ip})
                            break
            else:
                logging.debug(f"Ignoring non-JSON message from {client_ip}")
    except Exception as e:
        logging.error(f"WebSocket error: {e}", exc_info=True)
        for group in users:
            if websocket in [u['ws'] for u in users[group].values()]:
                username = next(u for u, d in users[group].items() if d['ws'] == websocket)
                del users[group][username]
                if username in websocket_clients:
                    del websocket_clients[username]
                await broadcast_user_status()
                await notify_udp_relay('logout', {'ip': client_ip})
                break
        for call_id in list(calls.keys()):
            if websocket in [calls[call_id]['caller_ws'], calls[call_id]['callee_ws']]:
                del calls[call_id]
                await notify_udp_relay('call_ended', {'call_id': call_id})

async def serve_index(request):
    logging.info(f"HTTP request from {request.remote} for /")
    if not os.path.exists('index.html'):
        logging.error("index.html not found in current directory")
        return web.Response(status=404, text="Not Found")
    return web.FileResponse('index.html')

async def init_app():
    app = web.Application()
    app.router.add_get('/', serve_index)
    app.router.add_static('/static/', path='static', name='static')
    app.router.add_static('/', path='.', name='root')
    return app

async def main():
    ssl_context_server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context_client = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_context_client.check_hostname = False
    ssl_context_client.verify_mode = ssl.CERT_NONE
    try:
        ssl_context_server.load_cert_chain(certfile='cert.pem', keyfile='key.pem')
        ssl_context_client.load_cert_chain(certfile='cert.pem', keyfile='key.pem')
        logging.info("SSL certificates loaded successfully")
    except Exception as e:
        logging.error(f"SSL cert load failed: {e}")
        return

    app = await init_app()
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        http_site = web.TCPSite(runner, '0.0.0.0', 8080, ssl_context=ssl_context_server)
        await http_site.start()
        logging.info("HTTP server started on https://0.0.0.0:8080")
    except Exception as e:
        logging.error(f"Failed to start HTTP server on 8080: {e}")
        return

    try:
        ws_server = await websockets.serve(handle_websocket, '0.0.0.0', 8001, ssl=ssl_context_server)
        logging.info("WebSocket server started on wss://0.0.0.0:8001")
    except Exception as e:
        logging.error(f"Failed to start WebSocket server on 8001: {e}")
        return

    global udp_relay_socket
    try:
        udp_relay_socket = await websockets.connect('wss://localhost:8002', ssl=ssl_context_client)
        logging.info("Connected to UDP relay server at wss://localhost:8002")
    except Exception as e:
        logging.error(f"Failed to connect to UDP relay server: {e}")

    await asyncio.Future()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as e:
        logging.error(f"Server startup failed: {e}", exc_info=True)