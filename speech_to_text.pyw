import tkinter as tk
import pyaudio
import wave
import threading
import os
import tempfile
import whisper
import pyperclip
import sys
import time
import logging
import traceback
from tkinter import ttk, scrolledtext
from typing import Optional
import warnings
from dataclasses import dataclass
from queue import Queue
from contextlib import contextmanager


# Hide console window on Windows
if os.name == 'nt':  # Windows
    try:
        import ctypes
        # Get the handle of the console window
        console_window = ctypes.windll.kernel32.GetConsoleWindow()
        if console_window != 0:
            # Hide the console window
            ctypes.windll.user32.ShowWindow(console_window, 0)
    except Exception:
        pass  # If anything goes wrong, just continue normally

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('speech_to_text.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


# Global exception handler
def global_exception_handler(exc_type, exc_value, exc_traceback):
    logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))


sys.excepthook = global_exception_handler

# Suppress unnecessary warnings
warnings.filterwarnings("ignore", category=UserWarning)


@dataclass
class AudioConfig:
    """Audio recording configuration"""
    CHUNK: int = 1024
    FORMAT: int = pyaudio.paInt16
    CHANNELS: int = 1
    RATE: int = 44100


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


class AudioDeviceManager:
    """Manages audio device initialization and logging"""

    @staticmethod
    def log_audio_devices():
        """Log all available audio input devices"""
        logger.info("\n=== AVAILABLE AUDIO INPUT DEVICES ===")
        p = pyaudio.PyAudio()

        try:
            default_device_index = p.get_default_input_device_info()['index']
            default_device_name = p.get_device_info_by_index(default_device_index)['name']
            logger.info(f"Default Input Device: {default_device_name} (index: {default_device_index})")
        except Exception as e:
            logger.error(f"Error getting default device: {str(e)}")
            logger.warning("No default input device found. Please check your audio settings.")
            default_device_index = None

        logger.info("\nAll Available Input Devices:")

        try:
            info = p.get_host_api_info_by_index(0)
            num_devices = info.get('deviceCount')

            for i in range(num_devices):
                try:
                    device_info = p.get_device_info_by_index(i)
                    if device_info.get('maxInputChannels') > 0:
                        logger.info(f"  - Device {i}: {device_info['name']}")
                        logger.info(f"      Input channels: {device_info['maxInputChannels']}")
                        logger.info(f"      Default sample rate: {device_info['defaultSampleRate']}")
                        if default_device_index is not None and i == default_device_index:
                            logger.info("      ** DEFAULT DEVICE **")
                except Exception as e:
                    logger.error(f"  - Error retrieving device {i} info: {str(e)}")
        except Exception as e:
            logger.error(f"Error listing audio devices: {str(e)}")
        finally:
            p.terminate()


class AudioResourceManager:
    """Manages audio resources with proper cleanup"""

    def __init__(self):
        self.audio = None
        self.stream = None
        self._lock = threading.Lock()

    @contextmanager
    def create_audio_session(self, config: AudioConfig):
        """Context manager for audio session"""
        try:
            with self._lock:
                self.audio = pyaudio.PyAudio()
                self.stream = self.audio.open(
                    format=config.FORMAT,
                    channels=config.CHANNELS,
                    rate=config.RATE,
                    input=True,
                    frames_per_buffer=config.CHUNK
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
                    logger.error(f"Error closing stream: {e}")
                finally:
                    self.stream = None

            if self.audio:
                try:
                    self.audio.terminate()
                except Exception as e:
                    logger.error(f"Error terminating PyAudio: {e}")
                finally:
                    self.audio = None


class TranscriptionManager:
    """Manages whisper model loading and transcription"""

    def __init__(self):
        self.fast_model = None
        self.accurate_model = None
        self._load_models()

    def _load_models(self):
        """Load whisper models with proper error handling"""
        try:
            logger.info("Loading fast model...")
            self.fast_model = whisper.load_model('tiny.en')
            logger.info("Fast model loaded successfully")

            logger.info("Loading accurate model...")
            self.accurate_model = whisper.load_model('small.en')
            logger.info("Accurate model loaded successfully")
        except Exception as e:
            logger.error(f"Error loading whisper models: {e}")
            raise RuntimeError("Failed to load required models")

    def transcribe_fast(self, audio_file: str) -> str:
        """Transcribe with fast model"""
        try:
            result = self.fast_model.transcribe(audio_file)
            return result['text']
        except Exception as e:
            logger.error(f"Error in fast transcription: {e}")
            raise

    def transcribe_accurate(self, audio_file: str) -> str:
        """Transcribe with accurate model"""
        try:
            result = self.accurate_model.transcribe(audio_file)
            return result['text']
        except Exception as e:
            logger.error(f"Error in accurate transcription: {e}")
            raise


class SpeechToTextApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Speech-to-Text App")
        self.root.geometry("600x600")
        self.root.configure(padx=20, pady=20)

        # Initialize managers
        self.audio_config = AudioConfig()
        self.audio_manager = AudioResourceManager()
        self.transcription_manager = TranscriptionManager()

        # Thread-safe flags
        self.recording = SafeFlag()
        self.processing = SafeFlag()
        self.second_pass_running = SafeFlag()
        self.cancel_second_pass = SafeFlag()

        # State variables
        self.frames = []
        self.temp_file: Optional[str] = None
        self.fast_transcribed_text = ""
        self.accurate_transcribed_text = ""
        self.last_button_press = 0
        self.debounce_time = 500  # milliseconds

        # Thread synchronization
        self.recording_lock = threading.Lock()
        self.second_pass_lock = threading.Lock()
        self.frames_lock = threading.Lock()

        # Event queue for UI updates
        self.ui_queue = Queue()

        # Create GUI
        self.create_widgets()

        # Start UI update loop
        self.root.after(100, self.process_ui_queue)

        # Set up cleanup on window close
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_widgets(self):
        """Create all GUI widgets"""
        try:
            # Create button frame
            button_frame = tk.Frame(self.root)
            button_frame.pack(fill=tk.X, pady=(0, 10))

            # Record button
            self.record_button = tk.Button(
                button_frame,
                text="Press and Hold to Record",
                bg="lightcoral",
                activebackground="red",
                font=("Arial", 12),
                height=2
            )
            self.record_button.pack(fill=tk.X, pady=(0, 10))

            # Bind button events
            self.record_button.bind("<ButtonPress-1>", self.start_recording)
            self.record_button.bind("<ButtonRelease-1>", self.stop_recording)

            # Status label
            self.status_label = tk.Label(
                self.root,
                text="Ready",
                font=("Arial", 10, "italic"),
                anchor="w"
            )
            self.status_label.pack(fill=tk.X, pady=(5, 5))

            # Create paned window
            self.paned_window = tk.PanedWindow(self.root, orient=tk.VERTICAL)
            self.paned_window.pack(fill=tk.BOTH, expand=True)

            # Fast transcription section
            self.fast_frame = tk.Frame(self.paned_window)
            self.paned_window.add(self.fast_frame, height=250)

            # Fast section header with copy button
            fast_header_frame = tk.Frame(self.fast_frame)
            fast_header_frame.pack(fill=tk.X, pady=(5, 5))

            fast_label = tk.Label(
                fast_header_frame,
                text="Quick Transcription (Faster):",
                font=("Arial", 10, "bold"),
                anchor="w"
            )
            fast_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

            self.fast_copy_button = tk.Button(
                fast_header_frame,
                text="Copy to Clipboard",
                bg="lightblue",
                activebackground="skyblue",
                font=("Arial", 10, "bold"),
                padx=10,
                pady=5,
                command=self.copy_fast_to_clipboard
            )
            self.fast_copy_button.pack(side=tk.RIGHT, padx=(5, 0))

            # Progress bar for fast transcription
            self.fast_progress = ttk.Progressbar(
                self.fast_frame,
                orient="horizontal",
                length=100,
                mode="indeterminate"
            )
            self.fast_progress.pack(fill=tk.X, pady=(0, 5))

            # Fast output text area
            self.fast_output_text = scrolledtext.ScrolledText(
                self.fast_frame,
                wrap=tk.WORD,
                height=8,
                font=("Arial", 11)
            )
            self.fast_output_text.pack(fill=tk.BOTH, expand=True)

            # Fast status label
            self.fast_status_label = tk.Label(
                self.fast_frame,
                text="",
                font=("Arial", 8, "italic"),
                fg="gray",
                anchor="w"
            )
            self.fast_status_label.pack(fill=tk.X)

            # Accurate transcription section
            self.accurate_frame = tk.Frame(self.paned_window)
            self.paned_window.add(self.accurate_frame, height=250)

            # Accurate section header with copy button
            accurate_header_frame = tk.Frame(self.accurate_frame)
            accurate_header_frame.pack(fill=tk.X, pady=(5, 5))

            accurate_label = tk.Label(
                accurate_header_frame,
                text="Enhanced Transcription (More Accurate):",
                font=("Arial", 10, "bold"),
                anchor="w"
            )
            accurate_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

            self.accurate_copy_button = tk.Button(
                accurate_header_frame,
                text="Copy to Clipboard",
                bg="lightblue",
                activebackground="skyblue",
                font=("Arial", 10, "bold"),
                padx=10,
                pady=5,
                command=self.copy_accurate_to_clipboard
            )
            self.accurate_copy_button.pack(side=tk.RIGHT, padx=(5, 0))

            # Progress bar for accurate transcription
            self.accurate_progress = ttk.Progressbar(
                self.accurate_frame,
                orient="horizontal",
                length=100,
                mode="indeterminate"
            )
            self.accurate_progress.pack(fill=tk.X, pady=(0, 5))

            # Accurate output text area
            self.accurate_output_text = scrolledtext.ScrolledText(
                self.accurate_frame,
                wrap=tk.WORD,
                height=8,
                font=("Arial", 11)
            )
            self.accurate_output_text.pack(fill=tk.BOTH, expand=True)

            # Accurate status label
            self.accurate_status_label = tk.Label(
                self.accurate_frame,
                text="",
                font=("Arial", 8, "italic"),
                fg="gray",
                anchor="w"
            )
            self.accurate_status_label.pack(fill=tk.X)

        except Exception as e:
            logger.error(f"Error creating widgets: {e}")
            raise

    def copy_fast_to_clipboard(self):
        """Copy the fast transcription results to clipboard"""
        text = self.fast_output_text.get(1.0, tk.END).strip()
        if text:
            try:
                pyperclip.copy(text)
                self.fast_status_label.config(text="Quick transcription copied to clipboard!")
            except Exception as e:
                logger.error(f"Error copying to clipboard: {e}")
                self.fast_status_label.config(text=f"Error copying to clipboard: {str(e)}")
        else:
            self.fast_status_label.config(text="No text to copy!")

    def copy_accurate_to_clipboard(self):
        """Copy the accurate transcription results to clipboard"""
        text = self.accurate_output_text.get(1.0, tk.END).strip()
        if text:
            try:
                pyperclip.copy(text)
                self.accurate_status_label.config(text="Enhanced transcription copied to clipboard!")
            except Exception as e:
                logger.error(f"Error copying to clipboard: {e}")
                self.accurate_status_label.config(text=f"Error copying to clipboard: {str(e)}")
        else:
            self.accurate_status_label.config(text="No text to copy!")

    def process_ui_queue(self):
        """Process UI updates from the queue"""
        try:
            while not self.ui_queue.empty():
                function, args, kwargs = self.ui_queue.get_nowait()
                function(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error processing UI queue: {e}")
        finally:
            self.root.after(100, self.process_ui_queue)

    def queue_ui_update(self, function, *args, **kwargs):
        """Queue a UI update to be processed in the main thread"""
        self.ui_queue.put((function, args, kwargs))

    def start_recording(self, event):
        """Start audio recording with improved error handling"""
        try:
            # Debounce check
            current_time = int(time.time() * 1000)
            if current_time - self.last_button_press < self.debounce_time:
                logger.debug(
                    f"Debouncing button press (time since last press: {current_time - self.last_button_press}ms)")
                return

            self.last_button_press = current_time

            # Check if we can start recording
            if self.processing.get():
                logger.warning("Cannot start new recording while processing previous one")
                return

            if self.recording.get():
                logger.warning("Already recording, ignoring start request")
                return

            # Cancel any ongoing second pass
            self.cancel_second_pass.set(True)
            time.sleep(0.1)  # Brief pause for cancellation to take effect

            # Start new recording
            self.recording.set(True)
            self.frames = []

            # Update UI
            self.record_button.config(text="Recording... Release to Stop", bg="red")
            self.status_label.config(text="Recording audio...")

            # Reset UI elements
            self.reset_ui_elements()

            # Start recording thread
            recording_thread = threading.Thread(target=self.record_audio)
            recording_thread.daemon = True
            recording_thread.start()

        except Exception as e:
            logger.error(f"Error in start_recording: {e}")
            self.recording.set(False)
            self.record_button.config(text="Press and Hold to Record", bg="lightcoral")
            self.status_label.config(text=f"Error: {str(e)}")

    def record_audio(self):
        """Record audio with improved error handling and resource management"""
        logger.debug("Starting audio recording")
        try:
            with self.audio_manager.create_audio_session(self.audio_config) as audio_session:
                while self.recording.get():
                    try:
                        data = audio_session.stream.read(self.audio_config.CHUNK, exception_on_overflow=False)
                        with self.frames_lock:
                            self.frames.append(data)
                    except Exception as e:
                        logger.error(f"Error reading audio data: {e}")
                        self.recording.set(False)
                        self.queue_ui_update(
                            self.status_label.config,
                            text=f"Recording error: {str(e)}"
                        )
                        break
        except Exception as e:
            logger.error(f"Error in record_audio: {e}")
            self.recording.set(False)
            self.queue_ui_update(
                self.status_label.config,
                text=f"Recording setup error: {str(e)}"
            )

    def stop_recording(self, event):
        """Stop recording and initiate processing with improved error handling"""
        try:
            # Debounce check
            current_time = int(time.time() * 1000)
            if current_time - self.last_button_press < self.debounce_time:
                logger.debug(f"Debouncing button release")
                return

            self.last_button_press = current_time

            # Check if we were actually recording
            if not self.recording.get():
                logger.debug("Stop recording called but not recording")
                return

            # Stop recording and update UI
            self.recording.set(False)
            self.processing.set(True)
            self.record_button.config(text="Press and Hold to Record", bg="lightcoral")
            self.status_label.config(text="Processing audio...")
            self.fast_progress.start()
            self.fast_status_label.config(text="Processing...")

            # Check if we have any frames
            with self.frames_lock:
                if not self.frames:
                    logger.warning("No audio data recorded")
                    self.status_label.config(text="No audio data recorded")
                    self.fast_progress.stop()
                    self.fast_status_label.config(text="No audio recorded")
                    self.processing.set(False)
                    return

            # Process the recorded audio
            process_thread = threading.Thread(target=self.process_audio_two_pass)
            process_thread.daemon = True
            process_thread.start()

        except Exception as e:
            logger.error(f"Error in stop_recording: {e}")
            self.status_label.config(text=f"Error: {str(e)}")
            self.fast_progress.stop()
            self.fast_status_label.config(text=f"Error: {str(e)}")
            self.processing.set(False)

    def process_audio_two_pass(self):
        """Process audio with two-pass approach and improved error handling"""
        logger.debug("Starting two-pass audio processing")
        try:
            # Create temporary file
            fd, self.temp_file = tempfile.mkstemp(suffix='.wav')
            os.close(fd)

            try:
                # Save audio to file
                with wave.open(self.temp_file, 'wb') as wf:
                    wf.setnchannels(self.audio_config.CHANNELS)
                    wf.setsampwidth(pyaudio.PyAudio().get_sample_size(self.audio_config.FORMAT))
                    wf.setframerate(self.audio_config.RATE)
                    with self.frames_lock:
                        wf.writeframes(b''.join(self.frames))

                # First pass - fast transcription
                logger.debug("Starting fast transcription")
                self.queue_ui_update(self.status_label.config, text="Transcribing with fast model...")
                self.queue_ui_update(self.fast_status_label.config, text="Transcribing with fast model...")

                self.fast_transcribed_text = self.transcription_manager.transcribe_fast(self.temp_file)
                self.queue_ui_update(self.update_ui_with_fast_results)

                # Second pass - accurate transcription
                self.cancel_second_pass.set(False)
                self.second_pass_running.set(True)

                self.second_pass_thread = threading.Thread(
                    target=self.run_second_pass_transcription,
                    args=(self.temp_file,)
                )
                self.second_pass_thread.daemon = True
                self.second_pass_thread.start()

            except Exception as e:
                error_msg = f"Transcription error: {e}"
                logger.error(error_msg)
                self.queue_ui_update(self.status_label.config, text=error_msg)
                self.queue_ui_update(self.fast_status_label.config, text=error_msg)
                self.queue_ui_update(self.fast_progress.stop)
                self.queue_ui_update(self.accurate_progress.stop)

        except Exception as e:
            error_msg = f"Error creating temporary file: {e}"
            logger.error(error_msg)
            self.queue_ui_update(self.status_label.config, text=error_msg)
            self.queue_ui_update(self.fast_status_label.config, text=error_msg)
            self.queue_ui_update(self.fast_progress.stop)
            self.queue_ui_update(self.accurate_progress.stop)

        finally:
            self.processing.set(False)

    def run_second_pass_transcription(self, audio_file):
        """Run accurate transcription with improved error handling"""
        logger.debug("Starting accurate transcription")
        try:
            self.queue_ui_update(self.accurate_progress.start)
            self.queue_ui_update(
                self.accurate_status_label.config,
                text="Enhanced transcription running..."
            )

            if self.cancel_second_pass.get():
                logger.info("Second pass transcription cancelled before start")
                return

            self.accurate_transcribed_text = self.transcription_manager.transcribe_accurate(audio_file)

            if self.cancel_second_pass.get():
                logger.info("Second pass transcription cancelled after completion")
                return

            self.queue_ui_update(self.update_ui_with_accurate_results)

        except Exception as e:
            logger.error(f"Error in second pass transcription: {e}")
            self.queue_ui_update(
                self.accurate_status_label.config,
                text=f"Enhanced transcription failed: {str(e)}"
            )
        finally:
            self.cleanup_temp_file(audio_file)
            self.second_pass_running.set(False)
            self.queue_ui_update(self.accurate_progress.stop)

    def cleanup_temp_file(self, file_path):
        """Safely clean up temporary file"""
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.debug(f"Temporary file removed: {file_path}")
            except Exception as e:
                logger.error(f"Error removing temporary file: {e}")

    def reset_ui_elements(self):
        """Reset UI elements to initial state"""
        self.fast_status_label.config(text="")
        self.accurate_status_label.config(text="")
        self.fast_output_text.delete(1.0, tk.END)
        self.accurate_output_text.delete(1.0, tk.END)
        self.fast_progress.stop()
        self.accurate_progress.stop()

    def update_ui_with_fast_results(self):
        """Update UI with fast transcription results"""
        self.fast_progress.stop()
        self.status_label.config(text="Quick transcription complete!")
        self.fast_status_label.config(text="Quick transcription complete!")
        self.fast_output_text.delete(1.0, tk.END)
        self.fast_output_text.insert(tk.END, self.fast_transcribed_text)

    def update_ui_with_accurate_results(self):
        """Update UI with accurate transcription results"""
        self.accurate_progress.stop()
        self.accurate_status_label.config(text="Enhanced transcription complete!")
        self.accurate_output_text.delete(1.0, tk.END)
        self.accurate_output_text.insert(tk.END, self.accurate_transcribed_text)

    def on_closing(self):
        """Clean up resources when closing the application"""
        logger.info("Application shutting down...")

        # Stop all ongoing operations
        self.recording.set(False)
        self.cancel_second_pass.set(True)

        # Clean up audio resources
        self.audio_manager.cleanup()

        # Clean up temporary file
        if self.temp_file:
            self.cleanup_temp_file(self.temp_file)

        # Destroy the window
        self.root.destroy()


if __name__ == "__main__":
    try:
        # Log audio devices at startup
        AudioDeviceManager.log_audio_devices()

        # Create and run the application
        root = tk.Tk()
        app = SpeechToTextApp(root)
        root.mainloop()
    except Exception as e:
        logger.critical("Fatal application error", exc_info=True)
        time.sleep(5)  # Keep window open briefly to see error