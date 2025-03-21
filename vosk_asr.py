import os
import numpy as np
import vosk
import logging
import json
import webrtcvad

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# Global models (loaded once)
MODELS = {
    "en": vosk.Model("vosk-model/vosk-model-en-us-0.22"),
    "ja": vosk.Model("vosk-model/vosk-model-small-ja-0.22")
}

# Default configuration
DEFAULT_CONFIG = {
    "use_vad": True,
    "vad_aggressiveness": 3,
    "max_gap": 0.5,
    "rms_threshold": 0.0025,
    "min_buffer_duration": 0.2,
    "confidence_threshold": 0.7,
    "target_rate": 48000,
    "bytes_per_sample": 2,
    "chunk_size": 1920  # 960 samples at 48kHz
}

# Load config
CONFIG_FILE = 'config.json'

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    else:
        raise FileNotFoundError(f"Config file [{CONFIG_FILE}] not found")

CONFIG = load_config()


class VoskASR:
    def __init__(self):
        self.sessions = {}
        self.buffers = {}
        self._load_config()

    def _load_config(self):
        """Apply current configuration to instance."""
        self.target_rate = CONFIG["target_rate"]
        self.bytes_per_sample = CONFIG["bytes_per_sample"]
        self.min_buffer_duration = CONFIG["min_buffer_duration"]
        self.rms_threshold = CONFIG["rms_threshold"]
        self.use_vad = CONFIG["use_vad"]
        self.vad = webrtcvad.Vad(CONFIG["vad_aggressiveness"]) if self.use_vad else None
        self.vad_frame_bytes = int(self.target_rate * 20 / 1000 * self.bytes_per_sample)
        self.chunk_size = CONFIG["chunk_size"]
        self.max_gap = CONFIG["max_gap"]
        logger.info(f"Vosk ASR initialized with config: {CONFIG}")

    def __get_recognizer(self, language):
        """Create a new recognizer instance with current config."""
        if language not in MODELS:
            logger.error(f"Unsupported language: {language}. Supported: en, ja")
            return None
        model = MODELS[language]
        recognizer = vosk.KaldiRecognizer(model, self.target_rate)
        recognizer.SetWords(True)  # Enable word-level metadata
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
            self.buffers[call_id] = {caller: b'', callee: b''}
            logger.info(f"Started Vosk session for call {call_id} caller_lang: {caller_language}, callee_lang:{callee_language}")

    def split_into_phrases(self, words, max_gap=CONFIG["max_gap"]):
        """Group words into phrases based on timing gaps."""
        phrases = []
        current_phrase = []
        for i, word in enumerate(words):
            if not current_phrase:
                current_phrase.append(word)
            elif word["start"] - words[i-1]["end"] <= max_gap:
                current_phrase.append(word)
            else:
                phrases.append(current_phrase)
                current_phrase = [word]
        if current_phrase:
            phrases.append(current_phrase)
        return phrases

    def is_valid_phrase(self, tokens, language):
        """Reject invalid phrases (language-specific)."""

        if language == "en":
            if len(tokens) > 1 and tokens[0] == tokens[1]:  # No repeats like "the the"
                logger.info(f"Rejected repeat phrase: {tokens}")
                return False
            if " ".join(tokens) in ["the", "uh um", "the uh"]:  # Known junk
                logger.info(f"Rejected junk phrase: {tokens}")
                return False
        elif language == "ja":
            fillers = {"えっと", "あの", "うーん"}
            if len(tokens) == 1 and tokens[0] in fillers:  # Reject standalone fillers
                return False
        return True

    def filter_transcription(self, result_json, language, min_confidence=CONFIG['confidence_threshold'], min_length=1):
        """Filter transcription by confidence and phrases, handle language-specific concatenation."""
        result = json.loads(result_json)
        if "result" not in result:
            return ""
        
        phrases = self.split_into_phrases(result["result"])
        filtered_phrases = []
        
        for phrase in phrases:
            logger.debug(f"Phrase: {phrase}")
            tokens = [w["word"] for w in phrase]
            avg_conf = sum(w["conf"] for w in phrase) / len(phrase)            
            logger.debug(f"Phrase: {tokens}, avg_conf: {avg_conf}")
            if avg_conf >= min_confidence and len(tokens) >= min_length and self.is_valid_phrase(tokens, language):
                separator = " " if language == "en" else ""
                filtered_phrases.append(separator.join(tokens))
        
        return (" " if language == "en" else "").join(filtered_phrases)

    def is_speech_by_rms(self, audio_chunk, call_id, username):
        """Check if audio chunk contains speech based on RMS."""
        audio_array = np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32)
        rms = np.sqrt(np.mean(audio_array**2)) / 32768.0  # Normalize to [-1, 1]
        logger.debug(f"RMS for {call_id} ({username}): {rms}")
        return rms >= self.rms_threshold

    async def process_audio(self, call_id, audio_chunk, username):
        try:
            if username is None:
                raise Exception("Username can't be none.")
            if call_id not in self.sessions:
                logger.warning(f"No session for {call_id}")
                return "", False
            
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

            # Log chunk size for debugging, no modification
            if len(audio_chunk) != self.chunk_size:
                logger.warning(f"Unexpected chunk size: {len(audio_chunk)} bytes, expected {self.chunk_size}")

            # Speech detection
            is_speech = False
            if self.use_vad and self.vad:
                try:
                    is_speech = self.vad.is_speech(audio_chunk, self.target_rate)
                except webrtcvad.Error as e:
                    logger.error(f"VAD error for {call_id} ({username}): {e}")
                    is_speech = self.is_speech_by_rms(audio_chunk, call_id, username)  # Fallback to RMS
            else:
                is_speech = self.is_speech_by_rms(audio_chunk, call_id, username)  # RMS-only mode

            # Inject silence if no speech (match chunk size)
            if not is_speech:
                audio_chunk = bytes(self.chunk_size)  # 1920 bytes of silence
                logger.debug(f"Injected silence chunk for {call_id} ({username})")

            # Buffer and process
            self.buffers[call_id][username] += audio_chunk
            min_buffer_size = int(self.target_rate * self.bytes_per_sample * self.min_buffer_duration)  # 19200 bytes
            if len(self.buffers[call_id][username]) < min_buffer_size:
                return "", False
            
            pcm_data = self.buffers[call_id][username][:min_buffer_size]
            self.buffers[call_id][username] = self.buffers[call_id][username][min_buffer_size:]
            
            if recognizer:
                logger.debug(f"Processing for {call_id} ({username}), lang: {language}")
                if recognizer.AcceptWaveform(pcm_data):
                    result = recognizer.Result()
                    raw_text = json.loads(result).get("text", "")
                    transcript = self.filter_transcription(result, language)
                    logger.info(f"Final transcript for {call_id} ({username}): '{transcript}' (raw: '{raw_text}')")
                    return transcript, True
                else:
                    partial = json.loads(recognizer.PartialResult())
                    transcript = partial.get("partial", "")
                    logger.debug(f"Partial transcript for {call_id} ({username}): '{transcript}'")
                    return transcript, False
            raise Exception(f"Couldn't locate recognizer for call id: {call_id}")
        except Exception as e:
            logger.error(f"Error processing audio for {call_id}: {e}", exc_info=True)
            return "", False

    def end_session(self, call_id):
        if call_id in self.sessions:
            transcript = ""
            caller = self.sessions[call_id]['caller']
            callee = self.sessions[call_id]['callee']
            recognizers = [(caller["username"], caller['recognizer']), (callee["username"], callee['recognizer'])]
            for username, recognizer in recognizers:
                if self.buffers[call_id][username]:
                    pcm_data = self.buffers[call_id][username]
                    if recognizer.AcceptWaveform(pcm_data):
                        result = json.loads(recognizer.Result())
                    else:
                        result = json.loads(recognizer.FinalResult())
                    transcript = result.get("text", "")
                    if transcript:
                        logger.info(f"Final transcript at end for {call_id} ({username}): '{transcript}'")
            del self.sessions[call_id]
            self.buffers.pop(call_id, None)
            return transcript, True if transcript else False
        return "", False