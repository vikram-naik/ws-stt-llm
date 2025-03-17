import vosk
import logging
from collections import defaultdict
import json

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class VoskASR:
    def __init__(self):
        self.models = {
            "en": { 
                'model': vosk.Model("vosk-model/vosk-model-en-us-0.22"),
                'config': '{"max_silence": 0.1, "min_speech_duration": 0.2, "silence_probability_threshold": 0.99}' 
            },
            "ja": { 
                'model': vosk.Model("vosk-model/vosk-model-small-ja-0.22") 
            }
        }
        self.sessions = {}
        self.buffers = defaultdict(bytes)
        self.target_rate = 16000
        logger.info("Vosk ASR initialized with models: en (large), ja")

    def __get_recognizer(self, language):        
        recognizer = None
        if language not in self.models:
            logger.error(f"Unsupported caller language: {language}. Supported: en, ja")
        else:
            model = self.models[language]['model']
            config = self.models[language]['config'] if 'config' in self.models[language] else None            
            if config:
                recognizer = vosk.KaldiRecognizer(model, self.target_rate, config)
            else:
                recognizer = vosk.KaldiRecognizer(model, self.target_rate)
        return recognizer

    def start_session(self, call_id, caller, caller_language, callee, callee_language):
        
        if call_id not in self.sessions:
            self.sessions[call_id] = {
                'caller': {
                    'username': caller,
                    'recognizer': self.__get_recognizer(language=caller_language),
                    'language': caller_language
                },
                'callee': {
                    'username': callee,
                    'recognizer': self.__get_recognizer(language=callee_language),
                    'language': callee_language
                }
            }
            logger.info(f"Started Vosk session for call {call_id} caller_lang: {caller_language}, callee_lang:{callee_language}")

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

            caller = self.sessions[call_id]['caller']
            callee = self.sessions[call_id]['callee']
            recognizer = None
            language = None
            if caller['username'] == username:
                recognizer = caller['recognizer']
                language = caller['language']
            elif callee['username'] == username:
                recognizer = callee['recognizer']
                language = callee['language']
            # Vosk transcription
            if recognizer:
                logger.info(f"recognizer: [{recognizer}], lang: [{language}]")
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
            raise Exception(f"Couldn't locate recogniner for call id:[{call_id}]")
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