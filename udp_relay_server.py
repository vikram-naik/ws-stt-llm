import asyncio
import json
import logging
import ssl
import websockets
from websockets import State
from queue import Queue

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

udp_clients = {}
calls = {}
audio_queue = Queue()

async def transcribe_audio():
    while True:
        call_id, client_ip, audio_data = await asyncio.to_thread(audio_queue.get)
        logging.info(f"Processing audio for transcription from {client_ip}: {len(audio_data)} bytes")
        await asyncio.sleep(1)
        sender = 'caller' if client_ip == calls[call_id]['caller_ip'] else 'callee'
        group = calls[call_id]['caller_group'] if sender == 'caller' else calls[call_id]['callee_group']
        text = f"Hello from transcription server ({group})"
        # Filter sales IPs only
        sales_ips = [
            calls[call_id]['caller_ip'] if calls[call_id]['caller_group'] == 'sales' else None,
            calls[call_id]['callee_ip'] if calls[call_id]['callee_group'] == 'sales' else None
        ]
        for ip in set(filter(None, sales_ips)):  # Unique sales IPs
            sales_ws = udp_clients.get(ip)
            if sales_ws and sales_ws.state == State.OPEN:
                try:
                    await sales_ws.send(json.dumps({
                        'event': 'transcription',
                        'call_id': call_id,
                        'group': group,
                        'text': text
                    }))
                    logging.info(f"Sent transcription to sales peer {ip}: {text}")
                except Exception as e:
                    logging.error(f"Failed to send transcription to {ip}: {e}")
        audio_queue.task_done()

async def udp_relay(websocket):
    client_ip = websocket.remote_address[0]
    logging.info(f"UDP relay WebSocket connected from {client_ip}")
    udp_clients[client_ip] = websocket
    try:
        async for message in websocket:
            if isinstance(message, str):
                data = json.loads(message)
                event = data.get('event')
                logging.info(f"Received control message from {client_ip}: {data}")
                if event == 'call_accepted':
                    call_id = data['call_id']
                    calls[call_id] = {
                        'caller_ip': data['caller_ip'],
                        'callee_ip': data['callee_ip'],
                        'caller_group': data['caller_group'],
                        'callee_group': data['callee_group']
                    }
                elif event == 'call_ended':
                    call_id = data.get('call_id')
                    if call_id and call_id in calls:
                        del calls[call_id]
                elif event == 'logout':
                    ip = data.get('ip')
                    if ip and ip in udp_clients:
                        del udp_clients[ip]
            elif isinstance(message, (bytes, bytearray)):
                logging.info(f"Received audio from {client_ip}: {len(message)} bytes")
                call_id = next((cid for cid, call in calls.items() if client_ip in (call['caller_ip'], call['callee_ip'])), None)
                if call_id:
                    sender = 'caller' if client_ip == calls[call_id]['caller_ip'] else 'callee'
                    peer_ip = calls[call_id]['callee_ip'] if sender == 'caller' else calls[call_id]['caller_ip']
                    peer_ws = udp_clients.get(peer_ip)
                    if peer_ws and peer_ws.state == State.OPEN:
                        await peer_ws.send(message)
                        logging.info(f"Relayed audio to {peer_ip}: {len(message)} bytes")
                        audio_queue.put((call_id, client_ip, message))
                    else:
                        logging.warning(f"No active peer WebSocket for {peer_ip}")
                else:
                    logging.warning(f"No call_id found for {client_ip} in calls: {list(calls.keys())}")
            else:
                logging.debug(f"Ignoring unexpected message from {client_ip}: {message}")
    except Exception as e:
        logging.error(f"UDP relay error: {e}", exc_info=True)
    finally:
        if client_ip in udp_clients:
            del udp_clients[client_ip]
            logging.info(f"UDP relay WebSocket disconnected from {client_ip}")

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