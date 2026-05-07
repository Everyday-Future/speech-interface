# core/adapters/batch_transcriber.py
import whisper
import logging
from typing import Optional
from config import Config
from core.adapters.text_corrections import apply_corrections


class BatchTranscriber:
    """Two-pass offline transcriber for batch processing.

    Models are loaded lazily on first use to keep app startup fast.
    """

    def __init__(self, config: Config):
        self.config = config
        self._fast_model = None
        self._accurate_model = None
        self.logger = logging.getLogger(self.__class__.__name__)

    def _ensure_fast_model(self):
        if self._fast_model is None:
            self.logger.info(f"Loading fast model: {self.config.batch_fast_model_name}")
            self._fast_model = whisper.load_model(self.config.batch_fast_model_name)
            self.logger.info("Fast model loaded")

    def _ensure_accurate_model(self):
        if self._accurate_model is None:
            self.logger.info(f"Loading accurate model: {self.config.batch_accurate_model_name}")
            self._accurate_model = whisper.load_model(self.config.batch_accurate_model_name)
            self.logger.info("Accurate model loaded")

    def transcribe_fast(self, audio_file: str) -> str:
        """Transcribe with fast model. Loads model on first call."""
        self._ensure_fast_model()
        try:
            result = self._fast_model.transcribe(audio_file)
            return apply_corrections(result['text'].strip())
        except Exception as e:
            self.logger.error(f"Fast transcription error on {audio_file}: {e}")
            raise

    def transcribe_accurate(self, audio_file: str) -> str:
        """Transcribe with accurate model. Loads model on first call."""
        self._ensure_accurate_model()
        try:
            result = self._accurate_model.transcribe(audio_file)
            return apply_corrections(result['text'].strip())
        except Exception as e:
            self.logger.error(f"Accurate transcription error on {audio_file}: {e}")
            raise

    def unload_fast_model(self):
        """Free fast model memory after fast pass completes."""
        self._fast_model = None
