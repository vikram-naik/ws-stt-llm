import vosk
import logging
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
            self.sessions[call_id] = {
                'recognizer': vosk.KaldiRecognizer(self.models[language], self.target_rate, '{"max_silence": 0.1, "min_speech_duration": 0.2, "silence_probability_threshold": 0.99}'),
                'language': language
            }
            logger.info(f"Started Vosk session for call {call_id} with language {language}")

    async def process_audio(self, call_id, audio_chunk, username=None):
        try:
            if call_id not in self.sessions:
                logger.warning(f"No session for {call_id}")
                return "", False
            self.buffers[call_id] += audio_chunk
            logger.debug(f"Buffer len for {call_id}: [{len(self.buffers[call_id])}]")
            if len(self.buffers[call_id]) < 32000:  # ~1s at 16kHz, 16-bit
                return "", False
            
            pcm_data = self.buffers[call_id][:32000]  # Slice ~1s
            self.buffers[call_id] = self.buffers[call_id][32000:]  # Keep remainder

            username = username or "unknown"

            # Vosk transcription
            recognizer = self.sessions[call_id]['recognizer']
            if recognizer.AcceptWaveform(pcm_data):
                result = json.loads(recognizer.Result())
                transcript = result.get("text", "")
                logger.info(f"Final transcript for {call_id} ({username}): '{transcript}'")
                return transcript, True
            else:
                partial = json.loads(recognizer.PartialResult())
                transcript = partial.get("partial", "")
                logger.info(f"Partial transcript for {call_id} ({username}): '{transcript}'")
                return transcript, False
        except Exception as e:
            logger.error(f"Error processing audio for {call_id}: {e}", exc_info=True)
            return "", False

    def end_session(self, call_id):
        if call_id in self.sessions:
            transcript = ""
            recognizer = self.sessions[call_id]['recognizer']
            if self.buffers[call_id]:
                pcm_data = self.buffers[call_id]
                username = "unknown"
                if recognizer.AcceptWaveform(pcm_data):
                    result = json.loads(recognizer.Result())
                else:
                    result = json.loads(recognizer.FinalResult())  # Force final result
                transcript = result.get("text", "")
                if transcript:
                    logger.info(f"Final transcript at end for {call_id} ({username}): '{transcript}'")
            del self.sessions[call_id]
            self.buffers.pop(call_id, None)
            return transcript, True if transcript else False
        return "", False