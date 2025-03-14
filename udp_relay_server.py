import asyncio
import json
import logging
import ssl
import websockets
from websockets import State

logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')

udp_clients = {}  # {username: ws}
calls = {}  # {call_id: {caller, callee, caller_group, callee_group, queue}}

async def transcribe_audio():
    while True:
        await asyncio.sleep(0.1)  # Yield to other tasks
        for call_id, call in list(calls.items()):
            queue = call.get('queue')
            if queue and not queue.empty():
                try:
                    group, audio_data = await asyncio.wait_for(queue.get(), timeout=0.1)
                    logging.info(f"Processing audio for transcription from call {call_id}: {len(audio_data)} bytes")
                    await asyncio.sleep(1)  # Dummy delay
                    text = f"Hello from transcription server ({group})"
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
                    queue.task_done()
                except asyncio.TimeoutError:
                    continue  # Move to next call if queue empty

async def udp_relay(websocket):
    client_ip = websocket.remote_address[0]
    username = None
    audio_buffer = []
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
                    if username and audio_buffer:
                        call_id = next((cid for cid, call in calls.items() if username in (call['caller'], call['callee'])), None)
                        if call_id:
                            peer = calls[call_id]['callee'] if username == calls[call_id]['caller'] else calls[call_id]['caller']
                            peer_ws = udp_clients.get(peer)
                            if peer_ws and peer_ws.state == State.OPEN:
                                for buffered_chunk in audio_buffer:
                                    await peer_ws.send(buffered_chunk)
                                    logging.info(f"Relayed buffered audio to peer {peer} for call {call_id}: {len(buffered_chunk)} bytes")
                            audio_buffer.clear()
                elif event == 'call_accepted':
                    call_id = data['call_id']
                    calls[call_id] = {
                        'caller': data['from_user'],
                        'callee': data['to_user'],
                        'caller_group': data['caller_group'],
                        'callee_group': data['callee_group'],
                        'queue': asyncio.Queue()
                    }
                elif event == 'call_ended':
                    call_id = data.get('call_id')
                    if call_id and call_id in calls:
                        del calls[call_id]  # Queue auto-garbage collected
                elif event == 'logout':
                    username_to_remove = data.get('username')
                    if username_to_remove and username_to_remove in udp_clients:
                        del udp_clients[username_to_remove]
            elif isinstance(message, (bytes, bytearray)):
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
                            await calls[call_id]['queue'].put((group, message))
                        else:
                            logging.warning(f"No active peer WebSocket for {peer}—buffering audio")
                            audio_buffer.append(message)
                    else:
                        logging.warning(f"No call_id found for {username} in calls: {list(calls.keys())}—buffering audio")
                        audio_buffer.append(message)
                else:
                    logging.warning(f"Client {client_ip} not registered—buffering audio")
                    audio_buffer.append(message)
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