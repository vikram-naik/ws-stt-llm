import asyncio
import json
import logging
import ssl
import websockets
from websockets import State

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

udp_clients = {}
calls = {}

async def udp_relay(websocket):
    client_ip = websocket.remote_address[0]
    username = None
    audio_buffer = []
    try:
        async for message in websocket:
            if isinstance(message, str):
                data = json.loads(message)
                event = data.get('event')
                logger.info(f"Received control message from {client_ip}: {data}")
                if event == 'register':
                    group = data['group']
                    username = data['username']
                    udp_clients[username] = {'ws': websocket}
                    logger.info(f"Registered client {username} from {client_ip}")
                elif event == 'call_accepted':
                    call_id = data['call_id']
                    calls[call_id] = {
                        'caller': data['from_user'],
                        'callee': data['to_user'],
                        'caller_group': data['caller_group'],
                        'callee_group': data['callee_group']
                    }
                    logger.info(f"Call accepted: {call_id}")
                elif event == 'call_ended':
                    call_id = data.get('call_id')
                    if call_id in calls:
                        del calls[call_id]
                        logger.info(f"Ended call {call_id}")
            elif isinstance(message, (bytes, bytearray)):
                if username:
                    call_id = next((cid for cid, call in calls.items() if username in (call['caller'], call['callee'])), None)
                    if call_id:
                        peer = calls[call_id]['callee'] if username == calls[call_id]['caller'] else calls[call_id]['caller']
                        peer_ws = udp_clients.get(peer, {}).get('ws')
                        if peer_ws and peer_ws.state == State.OPEN:
                            await peer_ws.send(message)
                            logger.debug(f"Relayed WebM Opus to {peer}: {len(message)} bytes")
                        else:
                            if len(audio_buffer) < 50:
                                audio_buffer.append(message)
                            else:
                                logger.error(f"Buffer overflow for {username}—dropping chunk")
                    else:
                        if len(audio_buffer) < 50:
                            audio_buffer.append(message)
                        else:
                            logger.error(f"Buffer overflow for {username}—dropping chunk")
                else:
                    logger.warning(f"Client {client_ip} not registered—discarding audio")
    except Exception as e:
        logger.error(f"UDP relay error: {e}", exc_info=True)
    finally:
        if username and username in udp_clients:
            del udp_clients[username]
            logger.warning(f"Disconnected {username} ({client_ip})")

async def udp_server():
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(certfile='cert.pem', keyfile='key.pem')
    server = websockets.serve(udp_relay, '0.0.0.0', 8002, ssl=ssl_context)
    async with server:
        logger.info("UDP relay WebSocket started on wss://0.0.0.0:8002")
        await asyncio.Future()

if __name__ == '__main__':
    asyncio.run(udp_server())