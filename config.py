# config.py
import os.path

import pyaudio
import tempfile
import logging
from typing import Optional
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    """Application configuration"""
    PROJECT_DIR = os.path.dirname(__file__)
    TEST_GALLERY_DIR = os.path.join(PROJECT_DIR, 'data', 'test_gallery')
    # Audio settings
    chunk_size: int = 1024
    audio_format: int = pyaudio.paInt16
    channels: int = 1
    sample_rate: int = 44100
    # Model settings
    fast_model_name: str = 'tiny.en'
    accurate_model_name: str = 'turbo'
    # UI settings
    window_title: str = "Speech-to-Text App"
    window_geometry: str = "600x900"
    debounce_time: int = 500  # milliseconds
    # Logging
    log_file: str = 'speech_to_text.log'
    log_level: int = logging.DEBUG
    # Paths
    temp_dir: Optional[Path] = None

    def __post_init__(self):
        if self.temp_dir is None:
            self.temp_dir = Path(tempfile.gettempdir())
