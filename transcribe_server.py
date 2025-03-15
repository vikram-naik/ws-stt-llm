import asyncio
import json
import logging
import ssl
import websockets
from websockets import State
from vosk_asr import VoskASR

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

transcribe_clients = {}
calls = {}
asr = VoskASR()

async def transcribe_audio(call_id):
    logger.info(f"Starting transcription task for {call_id}")
    while call_id in calls:
        queue = calls[call_id].get('queue')
        if queue:
            group, pcm_data = await queue.get()
            transcript, is_final = await asr.process_audio(call_id, pcm_data)
            if transcript:
                call = calls[call_id]
                sales_users = [call['caller']] if call['caller_group'] == 'sales' else []
                if call['callee_group'] == 'sales':
                    sales_users.append(call['callee'])
                for username in sales_users:
                    client = transcribe_clients.get(username)
                    if client and client['ws'].state == State.OPEN:
                        await client['ws'].send(json.dumps({
                            'event': 'transcription',
                            'call_id': call_id,
                            'group': group,  # Sender's group (sales/customers)
                            'text': transcript,
                            'is_final': is_final
                        }))
                        logger.info(f"Sent transcription to {username}: {transcript} (group: {group})")
            queue.task_done()
    logger.info(f"Stopped transcription for {call_id}")

async def transcribe(websocket):
    client_ip = websocket.remote_address[0]
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
                    calls[call_id] = {
                        'caller': data['from_user'],
                        'callee': data['to_user'],
                        'caller_group': data['caller_group'],
                        'callee_group': data['callee_group'],
                        'queue': asyncio.Queue()
                    }
                    asr.start_session(call_id, data.get('language', 'en'))
                    asyncio.create_task(transcribe_audio(call_id))
                    logger.info(f"Started transcription for {call_id}")
                elif event == 'call_ended':
                    call_id = data.get('call_id')
                    if call_id in calls:
                        asr.end_session(call_id)
                        del calls[call_id]
                        logger.info(f"Ended transcription for {call_id}")
            elif isinstance(message, (bytes, bytearray)):
                if username:
                    call_id = next((cid for cid, call in calls.items() if username in (call['caller'], call['callee'])), None)
                    if call_id:
                        group = transcribe_clients[username]['group']  # Use sender's registered group
                        await calls[call_id]['queue'].put((group, message))
                        logger.debug(f"Queued PCM for {call_id} from {username} (group: {group}): {len(message)} bytes")
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