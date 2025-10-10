# core/adapters/audio_recorder.py
import pyaudio
import wave
import threading
import time
import logging
from contextlib import contextmanager
from config import Config


class SafeFlag:
    """Thread-safe boolean flag"""

    def __init__(self, initial_value: bool = False):
        self._value = initial_value
        self._lock = threading.Lock()

    def set(self, value: bool) -> None:
        with self._lock:
            self._value = value

    def get(self) -> bool:
        with self._lock:
            return self._value

    def __bool__(self) -> bool:
        return self.get()


class AudioRecorder:
    """Handles audio recording functionality"""

    def __init__(self, config: Config):
        self.config = config
        self.audio = None
        self.stream = None
        self.frames = []
        self.frames_lock = threading.Lock()
        self.recording = SafeFlag()
        self._lock = threading.Lock()
        self.logger = logging.getLogger(self.__class__.__name__)

    @contextmanager
    def audio_session(self):
        """Context manager for audio session"""
        try:
            with self._lock:
                self.audio = pyaudio.PyAudio()
                self.stream = self.audio.open(
                    format=self.config.audio_format,
                    channels=self.config.channels,
                    rate=self.config.sample_rate,
                    input=True,
                    frames_per_buffer=self.config.chunk_size
                )
            yield self
        finally:
            self.cleanup()

    def cleanup(self):
        """Clean up audio resources"""
        with self._lock:
            if self.stream:
                try:
                    if self.stream.is_active():
                        self.stream.stop_stream()
                    self.stream.close()
                except Exception as e:
                    self.logger.error(f"Error closing stream: {e}")
                finally:
                    self.stream = None

            if self.audio:
                try:
                    self.audio.terminate()
                except Exception as e:
                    self.logger.error(f"Error terminating PyAudio: {e}")
                finally:
                    self.audio = None

    def start_recording(self):
        """Start recording audio"""
        if self.recording.get():
            self.logger.warning("Already recording")
            return False

        self.recording.set(True)
        self.frames = []

        recording_thread = threading.Thread(target=self._record_loop)
        recording_thread.daemon = True
        recording_thread.start()
        return True

    def stop_recording(self):
        """Stop recording and return frames"""
        if not self.recording.get():
            return []

        self.recording.set(False)
        time.sleep(0.1)  # Brief pause to ensure recording thread stops
        return self.frames.copy()

    def _record_loop(self):
        """Internal recording loop"""
        self.logger.debug("Starting audio recording loop")
        try:
            with self.audio_session():
                while self.recording.get():
                    try:
                        data = self.stream.read(
                            self.config.chunk_size,
                            exception_on_overflow=False
                        )
                        with self.frames_lock:
                            self.frames.append(data)
                    except Exception as e:
                        self.logger.error(f"Error reading audio data: {e}")
                        self.recording.set(False)
                        break
        except Exception as e:
            self.logger.error(f"Error in recording loop: {e}")
            self.recording.set(False)

    def save_to_file(self, frames: list, filepath: str) -> bool:
        """Save recorded frames to WAV file"""
        try:
            with wave.open(filepath, 'wb') as wf:
                wf.setnchannels(self.config.channels)
                wf.setsampwidth(
                    pyaudio.PyAudio().get_sample_size(self.config.audio_format)
                )
                wf.setframerate(self.config.sample_rate)
                wf.writeframes(b''.join(frames))
            return True
        except Exception as e:
            self.logger.error(f"Error saving audio file: {e}")
            return False

    @staticmethod
    def log_audio_devices():
        """Log all available audio input devices"""
        logger = logging.getLogger("AudioRecorder")
        logger.info("\n=== AVAILABLE AUDIO INPUT DEVICES ===")
        p = pyaudio.PyAudio()

        try:
            default_device = p.get_default_input_device_info()
            logger.info(f"Default: {default_device['name']} (index: {default_device['index']})")
        except Exception as e:
            logger.error(f"Error getting default device: {e}")

        try:
            info = p.get_host_api_info_by_index(0)
            for i in range(info.get('deviceCount')):
                try:
                    device_info = p.get_device_info_by_index(i)
                    if device_info.get('maxInputChannels') > 0:
                        logger.info(f"  Device {i}: {device_info['name']}")
                except Exception as e:
                    logger.error(f"  Error retrieving device {i}: {e}")
        finally:
            p.terminate()

    def get_frame_count(self) -> int:
        """Get current number of frames recorded"""
        with self.frames_lock:
            return len(self.frames)

    def get_frames_from(self, start_index: int) -> list:
        """Get frames from start_index to current (thread-safe copy)"""
        with self.frames_lock:
            if start_index < 0 or start_index >= len(self.frames):
                return []
            return self.frames[start_index:].copy()

    def is_recording(self) -> bool:
        """Check if currently recording"""
        return self.recording.get()
