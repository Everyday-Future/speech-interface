# core/adapters/transcript_writer.py
import wave
import logging
from pathlib import Path
from typing import Optional


class TranscriptWriter:
    """Incrementally writes a markdown transcript file for a batch."""

    def __init__(self, output_path: Path, batch_name: str):
        self.output_path = output_path
        self.batch_name = batch_name
        self.logger = logging.getLogger(self.__class__.__name__)
        self._initialized = False

    def initialize(self):
        """Create the file with the batch header. Overwrites if exists."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.output_path, 'w', encoding='utf-8') as f:
            f.write(f"# Batch {self.batch_name}\n\n")
        self._initialized = True
        self.logger.info(f"Initialized transcript: {self.output_path}")

    def append_section(self, filename: str, transcription: str, audio_path: Optional[Path] = None):
        """Append a section for a single file's transcription."""
        if not self._initialized:
            self.initialize()

        duration_str = self._get_duration_str(audio_path) if audio_path else None
        header = f"## {filename}"
        if duration_str:
            header += f" ({duration_str})"

        with open(self.output_path, 'a', encoding='utf-8') as f:
            f.write(f"{header}\n\n")
            f.write(f"{transcription}\n\n")

    def append_error(self, filename: str, error_message: str):
        """Append a section indicating a file failed to transcribe."""
        if not self._initialized:
            self.initialize()

        with open(self.output_path, 'a', encoding='utf-8') as f:
            f.write(f"## {filename}\n\n")
            f.write(f"*Transcription failed: {error_message}*\n\n")

    @staticmethod
    def _get_duration_str(audio_path: Path) -> Optional[str]:
        """Read duration from a WAV header. Returns None for non-WAV or on failure."""
        try:
            if audio_path.suffix.lower() != '.wav':
                return None
            with wave.open(str(audio_path), 'rb') as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate <= 0:
                    return None
                seconds = frames / rate
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            if minutes > 0:
                return f"{minutes}m {secs}s"
            return f"{secs}s"
        except Exception:
            return None
