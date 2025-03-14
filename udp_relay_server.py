import asyncio
import json
import logging
import ssl
import websockets
from websockets import State

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

udp_clients = {}  # {username: ws}
calls = {}  # {call_id: {caller, callee, caller_group, callee_group}}
audio_queue = asyncio.Queue()

async def transcribe_audio():
    while True:
        call_id, group, audio_data = await audio_queue.get()
        logging.info(f"Processing audio for transcription from call {call_id}: {len(audio_data)} bytes")
        await asyncio.sleep(1)  # Dummy delay
        text = f"Hello from transcription server ({group})"
        if call_id in calls:
            call = calls[call_id]
            sales_users = []
            if call['caller_group'] == 'sales':
                sales_users.append(call['caller'])
            if call['callee_group'] == 'sales':
                sales_users.append(call['callee'])
            for username in sales_users:
                ws = udp_clients.get(username)
                if ws and ws.state == State.OPEN:
                    try:
                        await ws.send(json.dumps({
                            'event': 'transcription',
                            'call_id': call_id,
                            'group': group,
                            'text': text
                        }))
                        logging.info(f"Sent transcription to sales client {username}: {text}")
                    except Exception as e:
                        logging.error(f"Failed to send transcription to {username}: {e}")
        audio_queue.task_done()

async def udp_relay(websocket):
    client_ip = websocket.remote_address[0]
    username = None
    try:
        async for message in websocket:
            if isinstance(message, str):
                data = json.loads(message)
                event = data.get('event')
                logging.info(f"Received control message from {client_ip}: {data}")
                if event == 'register':
                    group = data['group']
                    username = data['username']
                    udp_clients[username] = websocket
                    logging.info(f"Registered client {username} from {client_ip}")
                elif event == 'call_accepted':
                    call_id = data['call_id']
                    calls[call_id] = {
                        'caller': data['from_user'],
                        'callee': data['to_user'],
                        'caller_group': data['caller_group'],
                        'callee_group': data['callee_group']
                    }
                elif event == 'call_ended':
                    call_id = data.get('call_id')
                    if call_id and call_id in calls:
                        del calls[call_id]
                elif event == 'logout':
                    username_to_remove = data.get('username')
                    if username_to_remove and username_to_remove in udp_clients:
                        del udp_clients[username_to_remove]
            elif isinstance(message, (bytes, bytearray)):
                logging.info(f"Received audio from {client_ip}: {len(message)} bytes")
                if username:
                    call_id = next((cid for cid, call in calls.items() if username in (call['caller'], call['callee'])), None)
                    if call_id:
                        sender = 'caller' if username == calls[call_id]['caller'] else 'callee'
                        peer = calls[call_id]['callee'] if sender == 'caller' else calls[call_id]['caller']
                        peer_ws = udp_clients.get(peer)
                        if peer_ws and peer_ws.state == State.OPEN:
                            await peer_ws.send(message)
                            logging.info(f"Relayed audio to peer {peer} for call {call_id}: {len(message)} bytes")
                            group = calls[call_id]['caller_group'] if sender == 'caller' else calls[call_id]['callee_group']
                            await audio_queue.put((call_id, group, message))
                        else:
                            logging.warning(f"No active peer WebSocket for {peer}")
                    else:
                        logging.warning(f"No call_id found for {username} in calls: {list(calls.keys())}")
                else:
                    logging.warning(f"Client {client_ip} not registered")
            else:
                logging.debug(f"Ignoring unexpected message from {client_ip}: {message}")
    except Exception as e:
        logging.error(f"UDP relay error: {e}", exc_info=True)
    finally:
        if username and username in udp_clients:
            del udp_clients[username]
            logging.info(f"UDP relay WebSocket disconnected from {username} ({client_ip})")

async def udp_server():
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        ssl_context.load_cert_chain(certfile='cert.pem', keyfile='key.pem')
        logging.info("SSL certificates loaded successfully for UDP relay")
    except Exception as e:
        logging.error(f"SSL cert load failed for UDP relay: {e}")
        return

    try:
        ws_server = await websockets.serve(udp_relay, '0.0.0.0', 8002, ssl=ssl_context)
        logging.info("UDP relay WebSocket started on wss://0.0.0.0:8002")
        asyncio.create_task(transcribe_audio())
        await ws_server.wait_closed()
    except Exception as e:
        logging.error(f"Failed to start UDP relay WebSocket on 8002: {e}")

if __name__ == '__main__':
    try:
        asyncio.run(udp_server())
    except Exception as e:
        logging.error(f"UDP server startup failed: {e}", exc_info=True)