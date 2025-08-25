# core/adapters/audio_transcriber.py
import whisper
import logging
from config import Config


class AudioTranscriber:
    """Handles audio transcription using Whisper models"""

    def __init__(self, config: Config):
        self.config = config
        self.fast_model = None
        self.accurate_model = None
        self.logger = logging.getLogger(self.__class__.__name__)
        self._load_models()

    def _load_models(self):
        """Load whisper models"""
        try:
            self.logger.info(f"Loading fast model: {self.config.fast_model_name}")
            self.fast_model = whisper.load_model(self.config.fast_model_name)

            self.logger.info(f"Loading accurate model: {self.config.accurate_model_name}")
            self.accurate_model = whisper.load_model(self.config.accurate_model_name)

            self.logger.info("Models loaded successfully")
        except Exception as e:
            self.logger.error(f"Error loading models: {e}")
            raise RuntimeError("Failed to load required models")

    def transcribe_fast(self, audio_file: str) -> str:
        """Transcribe with fast model"""
        try:
            result = self.fast_model.transcribe(audio_file)
            return result['text']
        except Exception as e:
            self.logger.error(f"Fast transcription error: {e}")
            raise

    def transcribe_accurate(self, audio_file: str) -> str:
        """Transcribe with accurate model"""
        try:
            result = self.accurate_model.transcribe(audio_file)
            return result['text']
        except Exception as e:
            self.logger.error(f"Accurate transcription error: {e}")
            raise
