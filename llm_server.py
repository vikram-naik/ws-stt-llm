import asyncio
import websockets
import json
from llama_cpp import Llama
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load Q4_K_M with 6 threads
llm = Llama(model_path="./llm/llama-2-7b-chat.Q4_K_M.gguf", n_ctx=512, n_threads=6)

async def handle_llm(websocket):
    async for message in websocket:
        try:
            data = json.loads(message)
            transcript = data['text']
            call_id = data['call_id']
            prompt = f"Analyze this customer transcript: '{transcript}'\nProvide: Sentiment (Positive/Negative/Neutral), Key Point, Suggestion.\n Do not provide any explanations."
            insight = llm(prompt, max_tokens=100, temperature=0.4)
            insight_text = insight['choices'][0]['text'].strip()
            await websocket.send(json.dumps({
                'event': 'insight',
                'call_id': call_id,
                'text': insight_text
            }))
            logger.info(f"Generated insight for {call_id}: {insight_text}")
        except Exception as e:
            logger.error(f"LLM error: {e}", exc_info=True)

async def main():
    server = await websockets.serve(handle_llm, '0.0.0.0', 8004)
    logger.info("LLM WebSocket server started on ws://0.0.0.0:8004")
    await server.wait_closed()

if __name__ == "__main__":
    asyncio.run(main())