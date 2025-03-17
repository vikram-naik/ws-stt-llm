import asyncio
import json
import logging
import socket
import ssl
import websockets
from websockets import State
from vosk_asr import VoskASR
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

transcribe_clients = {}
calls = {}
asr = VoskASR()

async def transcribe_audio(call_id):
    logger.info(f"Starting transcription task for {call_id}")
    last_partials = defaultdict(str)
    while call_id in calls:
        queue = calls[call_id].get('queue')
        if queue:
            group, pcm_data, username = await queue.get()
            if pcm_data is None:  # Signal to stop
                break
            logger.debug(f"Processing PCM for {call_id} (group: {group}, user: {username}): {len(pcm_data)} bytes")
            transcript, is_final = await asr.process_audio(call_id, pcm_data, username)
            if transcript and (is_final or transcript != last_partials[group]):
                call = calls[call_id]
                sales_users = [call['caller']] if call['caller_group'] == 'sales' else []
                if call['callee_group'] == 'sales':
                    sales_users.append(call['callee'])
                for user in sales_users:
                    client = transcribe_clients.get(user)
                    if client and client['ws'].state == State.OPEN:
                        await client['ws'].send(json.dumps({
                            'event': 'transcription',
                            'call_id': call_id,
                            'group': group,
                            'text': transcript,
                            'is_final': is_final
                        }))
                        logger.info(f"Sent transcription to {user}: {transcript} (group: {group})")
                last_partials[group] = transcript if not is_final else ""
            queue.task_done()
    logger.info(f"Stopped transcription for {call_id}")

async def transcribe(websocket):
    client_ip = websocket.remote_address[0]
    sock = websocket.transport.get_extra_info('socket')
    if sock:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    username = None
    try:
        async for message in websocket:
            if isinstance(message, str):
                data = json.loads(message)
                event = data.get('event')
                logger.info(f"Received control message from {client_ip}: {data}")
                if event == 'register':
                    group = data['group']
                    username = data['username']
                    language = data.get('language', 'en')
                    transcribe_clients[username] = {'ws': websocket, 'language': language, 'group': group}
                    logger.info(f"Registered {username} from {client_ip} as {group}")
                elif event == 'call_accepted':
                    call_id = data['call_id']
                    caller_language = transcribe_clients[data['from_user']]['language']
                    callee_language = transcribe_clients[data['to_user']]['language']
                    calls[call_id] = {
                        'caller': data['from_user'],
                        'callee': data['to_user'],
                        'caller_group': data['caller_group'],
                        'callee_group': data['callee_group'],
                        'caller_language': caller_language,
                        'callee_language': callee_language,
                        'queue': asyncio.Queue()
                    }
                    asr.start_session(call_id, data['from_user'], caller_language, data['to_user'], callee_language)
                    asyncio.create_task(transcribe_audio(call_id))
                    logger.info(f"Started transcription for {call_id}")
                elif event == 'call_ended':
                    call_id = data.get('call_id')
                    if call_id in calls:
                        asr.end_session(call_id)
                        await calls[call_id]['queue'].put((None, None, None))  # Signal task to stop
                        del calls[call_id]
                        logger.info(f"Ended transcription for {call_id}")
            elif isinstance(message, (bytes, bytearray)):
                if username:
                    call_id = next((cid for cid, call in calls.items() if username in (call['caller'], call['callee'])), None)
                    if call_id:
                        group = transcribe_clients[username]['group']
                        logger.debug(f"Queuing PCM for {call_id} from {username} (group: {group}): {len(message)} bytes")
                        await calls[call_id]['queue'].put((group, message, username))
    except Exception as e:
        logger.error(f"Transcription error: {e}", exc_info=True)
    finally:
        if username and username in transcribe_clients:
            del transcribe_clients[username]
            logger.warning(f"Disconnected {username} ({client_ip})")

async def transcribe_server():
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(certfile='cert.pem', keyfile='key.pem')
    server = websockets.serve(transcribe, '0.0.0.0', 8003, ssl=ssl_context)
    async with server:
        logger.info("Transcription WebSocket started on wss://0.0.0.0:8003")
        await asyncio.Future()

if __name__ == '__main__':
    asyncio.run(transcribe_server())