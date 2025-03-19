import numpy as np
import vosk
import logging
import json

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class VoskASR:
    def __init__(self):
        self.models = {
            "en": { 
                'model': vosk.Model("vosk-model/vosk-model-en-us-0.22")
            },
            "ja": { 
                'model': vosk.Model("vosk-model/vosk-model-small-ja-0.22"),
                'config': '{"max_silence": 0.05, "min_speech_duration": 0.2, "silence_probability_threshold": 0.9}'
            }
        }
        self.sessions = {}
        self.buffers = {}
        self.target_rate = 48000
        self.bytes_per_sample = 2
        self.min_buffer_duration = 0.2 # in seconds.
        self.rms_threshold = 0.0025 # Adjustable—tune for noise
        logger.info("Vosk ASR initialized with models: en (large), ja (small)")

    def __get_recognizer(self, language):        
        recognizer = None
        if language not in self.models:
            logger.error(f"Unsupported language: {language}. Supported: en, ja")
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
            self.buffers[call_id] = {}
            self.buffers[call_id][caller] = b''
            self.buffers[call_id][callee] = b''
            logger.info(f"Started Vosk session for call {call_id} caller_lang: {caller_language}, callee_lang:{callee_language}")

    async def process_audio(self, call_id, audio_chunk, username):
        try:
            if username is None:
                raise Exception("Username can't be none.")
            if call_id not in self.sessions:
                logger.warning(f"No session for {call_id}")
                return "", False

            # Calculate RMS
            audio_array = np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32)
            rms = np.sqrt(np.mean(audio_array**2)) / 32768.0  # Normalize to [-1, 1]
            logger.debug(f"RMS for chunk {call_id} ({username}): {rms}")
            # Filter or silence
            if rms < self.rms_threshold:
                # Manufacture silence—same length as input chunk
                audio_chunk = bytes(len(audio_chunk))  # Zero-filled bytes
                logger.debug(f"Injected silence chunk for {call_id} ({username})")            

            self.buffers[call_id][username] += audio_chunk
            min_buffer_size = int(self.target_rate * self.bytes_per_sample * self.min_buffer_duration)  # ~96000 at 48kHz
            if len(self.buffers[call_id][username]) < min_buffer_size:
                return "", False
            pcm_data = self.buffers[call_id][username][:min_buffer_size]
            self.buffers[call_id][username] = self.buffers[call_id][username][min_buffer_size:]
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
            if recognizer:
                logger.debug(f"Processing for {call_id} ({username}), lang: {language}")
                if recognizer.AcceptWaveform(pcm_data):
                    result = json.loads(recognizer.Result())
                    transcript = result.get("text", "")
                    # dumb logic for now...
                    if transcript == "the":
                        transcript = ""
                    logger.info(f"Final transcript for {call_id} ({username}): '{transcript}'")
                    return transcript, True
                else:
                    partial = json.loads(recognizer.PartialResult())
                    transcript = partial.get("partial", "")
                    logger.info(f"Partial transcript for {call_id} ({username}): '{transcript}'")                    
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
            recognizers = [(caller["username"],caller['recognizer']),(callee["username"],callee['recognizer'])]            
            for username, recognizer in recognizers:                
                if self.buffers[call_id][username]:
                    pcm_data = self.buffers[call_id][username]
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