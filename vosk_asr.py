import vosk
import logging
import asyncio
from collections import defaultdict
import json

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class VoskASR:
    def __init__(self):
        self.models = {
            "en": vosk.Model("vosk-model/vosk-model-en-us-0.22"),
            "ja": vosk.Model("vosk-model/vosk-model-small-ja-0.22")
        }
        self.sessions = {}
        self.buffers = defaultdict(bytes)
        self.target_rate = 16000
        logger.info("Vosk ASR initialized with models: en (large), ja")

    def start_session(self, call_id, language):
        if language not in self.models:
            logger.error(f"Unsupported language: {language}. Supported: en, ja")
            return
        if call_id not in self.sessions:
            self.sessions[call_id] = vosk.KaldiRecognizer(self.models[language], self.target_rate)
            logger.info(f"Started Vosk session for call {call_id} with language {language}")

    async def process_audio(self, call_id, audio_chunk):
        if call_id not in self.sessions:
            logger.warning(f"No Vosk session for {call_id}")
            return "", False
        self.buffers[call_id] += audio_chunk
        if len(self.buffers[call_id]) < 4000:  # ~0.25s at 16kHz, 16-bit
            return "", False
        pcm_data = self.buffers[call_id][:4000]
        self.buffers[call_id] = self.buffers[call_id][4000:]
        recognizer = self.sessions[call_id]
        if recognizer.AcceptWaveform(pcm_data):
            result = json.loads(recognizer.Result())
            transcript = result.get("text", "")
            logger.info(f"Final transcript for {call_id}: '{transcript}'")
            return transcript, True
        else:
            partial = json.loads(recognizer.PartialResult())
            transcript = partial.get("partial", "")
            logger.info(f"Partial transcript for {call_id}: '{transcript}'")
            return transcript, False

    def end_session(self, call_id):
        if call_id in self.sessions:
            del self.sessions[call_id]
            self.buffers.pop(call_id, None)
            logger.info(f"Ended Vosk session for {call_id}")