# core/scripts/speech_to_text_app.py
import tkinter as tk
import threading
import os
import tempfile
import pyperclip
import time
import logging
from tkinter import ttk, scrolledtext
from typing import Optional, Callable
from queue import Queue
from config import Config
from core.adapters.audio_recorder import AudioRecorder, SafeFlag
from core.adapters.audio_transcriber import AudioTranscriber


class SpeechToTextApp:
    """Main application GUI"""

    def __init__(self, root: tk.Tk, config: Config):
        self.root = root
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)

        # Initialize components
        self.recorder = AudioRecorder(config)
        self.transcriber = AudioTranscriber(config)

        # State management
        self.processing = SafeFlag()
        self.cancel_second_pass = SafeFlag()
        self.last_button_press = 0
        self.temp_file: Optional[str] = None

        # UI update queue
        self.ui_queue = Queue()

        # Setup window
        self.setup_window()
        self.create_widgets()

        # Start UI update loop
        self.root.after(100, self.process_ui_queue)

        # Cleanup on close
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def setup_window(self):
        """Configure main window"""
        self.root.title(self.config.window_title)
        self.root.geometry(self.config.window_geometry)
        self.root.configure(padx=20, pady=20)

    def create_widgets(self):
        """Create all GUI widgets"""
        # Button frame
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
        self.record_button.bind("<ButtonPress-1>", self.on_record_start)
        self.record_button.bind("<ButtonRelease-1>", self.on_record_stop)

        # Status label
        self.status_label = tk.Label(
            self.root,
            text="Ready",
            font=("Arial", 10, "italic"),
            anchor="w"
        )
        self.status_label.pack(fill=tk.X, pady=(5, 5))

        # Paned window for transcription areas
        self.paned_window = tk.PanedWindow(self.root, orient=tk.VERTICAL)
        self.paned_window.pack(fill=tk.BOTH, expand=True)

        # Fast transcription section
        self.fast_frame = self._create_transcription_section(
            "Quick Transcription (Faster):",
            self.copy_fast_to_clipboard
        )
        self.paned_window.add(self.fast_frame, height=250)

        # Accurate transcription section
        self.accurate_frame = self._create_transcription_section(
            "Enhanced Transcription (More Accurate):",
            self.copy_accurate_to_clipboard
        )
        self.paned_window.add(self.accurate_frame, height=250)

    def _create_transcription_section(self, title: str, copy_callback: Callable):
        """Create a transcription section with header, progress, and text area"""
        frame = tk.Frame(self.paned_window)

        # Header with copy button
        header_frame = tk.Frame(frame)
        header_frame.pack(fill=tk.X, pady=(5, 5))

        label = tk.Label(
            header_frame,
            text=title,
            font=("Arial", 10, "bold"),
            anchor="w"
        )
        label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        copy_button = tk.Button(
            header_frame,
            text="Copy to Clipboard",
            bg="lightblue",
            activebackground="skyblue",
            font=("Arial", 10, "bold"),
            padx=10,
            pady=5,
            command=copy_callback
        )
        copy_button.pack(side=tk.RIGHT, padx=(5, 0))

        # Progress bar
        progress = ttk.Progressbar(
            frame,
            orient="horizontal",
            length=100,
            mode="indeterminate"
        )
        progress.pack(fill=tk.X, pady=(0, 5))

        # Text area
        text_area = scrolledtext.ScrolledText(
            frame,
            wrap=tk.WORD,
            height=8,
            font=("Arial", 11)
        )
        text_area.pack(fill=tk.BOTH, expand=True)

        # Status label
        status = tk.Label(
            frame,
            text="",
            font=("Arial", 8, "italic"),
            fg="gray",
            anchor="w"
        )
        status.pack(fill=tk.X)

        # Store references
        if "Quick" in title:
            self.fast_progress = progress
            self.fast_output_text = text_area
            self.fast_status_label = status
        else:
            self.accurate_progress = progress
            self.accurate_output_text = text_area
            self.accurate_status_label = status

        return frame

    def process_ui_queue(self):
        """Process UI updates from queue"""
        try:
            while not self.ui_queue.empty():
                func, args, kwargs = self.ui_queue.get_nowait()
                func(*args, **kwargs)
        except Exception as e:
            self.logger.error(f"Error processing UI queue: {e}")
        finally:
            self.root.after(100, self.process_ui_queue)

    def queue_ui_update(self, func, *args, **kwargs):
        """Queue UI update for main thread"""
        self.ui_queue.put((func, args, kwargs))

    def on_record_start(self, event):
        """Handle record button press"""
        # Debounce check
        current_time = int(time.time() * 1000)
        if current_time - self.last_button_press < self.config.debounce_time:
            return
        self.last_button_press = current_time

        if self.processing.get():
            self.logger.warning("Cannot start recording while processing")
            return

        # Cancel any ongoing second pass
        self.cancel_second_pass.set(True)
        time.sleep(0.1)

        # Start recording
        if self.recorder.start_recording():
            self.record_button.config(text="Recording... Release to Stop", bg="red")
            self.status_label.config(text="Recording audio...")
            self.reset_ui()

    def on_record_stop(self, event):
        """Handle record button release"""
        # Debounce check
        current_time = int(time.time() * 1000)
        if current_time - self.last_button_press < self.config.debounce_time:
            return
        self.last_button_press = current_time

        # Stop recording and get frames
        frames = self.recorder.stop_recording()

        if not frames:
            self.status_label.config(text="No audio recorded")
            self.record_button.config(text="Press and Hold to Record", bg="lightcoral")
            return

        # Update UI
        self.processing.set(True)
        self.record_button.config(text="Press and Hold to Record", bg="lightcoral")
        self.status_label.config(text="Processing audio...")
        self.fast_progress.start()

        # Process in background
        thread = threading.Thread(target=self.process_audio, args=(frames,))
        thread.daemon = True
        thread.start()

    def process_audio(self, frames: list):
        """Process recorded audio with two-pass transcription"""
        try:
            # Create temp file
            fd, self.temp_file = tempfile.mkstemp(suffix='.wav', dir=self.config.temp_dir)
            os.close(fd)

            # Save audio
            if not self.recorder.save_to_file(frames, self.temp_file):
                raise Exception("Failed to save audio file")

            # Fast transcription
            self.queue_ui_update(self.fast_status_label.config, text="Transcribing...")
            text = self.transcriber.transcribe_fast(self.temp_file)

            self.queue_ui_update(self.fast_progress.stop)
            self.queue_ui_update(self.fast_status_label.config, text="Complete!")
            self.queue_ui_update(self.fast_output_text.delete, 1.0, tk.END)
            self.queue_ui_update(self.fast_output_text.insert, tk.END, text)

            # Accurate transcription (if not cancelled)
            self.cancel_second_pass.set(False)
            if not self.cancel_second_pass.get():
                self.queue_ui_update(self.accurate_progress.start)
                self.queue_ui_update(self.accurate_status_label.config, text="Processing...")

                text = self.transcriber.transcribe_accurate(self.temp_file)

                if not self.cancel_second_pass.get():
                    self.queue_ui_update(self.accurate_progress.stop)
                    self.queue_ui_update(self.accurate_status_label.config, text="Complete!")
                    self.queue_ui_update(self.accurate_output_text.delete, 1.0, tk.END)
                    self.queue_ui_update(self.accurate_output_text.insert, tk.END, text)

        except Exception as e:
            self.logger.error(f"Error processing audio: {e}")
            self.queue_ui_update(self.status_label.config, text=f"Error: {str(e)}")
            self.queue_ui_update(self.fast_progress.stop)
            self.queue_ui_update(self.accurate_progress.stop)
        finally:
            self.processing.set(False)
            self.cleanup_temp_file()
            self.queue_ui_update(self.status_label.config, text="Ready")

    def cleanup_temp_file(self):
        """Clean up temporary file"""
        if self.temp_file and os.path.exists(self.temp_file):
            try:
                os.remove(self.temp_file)
                self.logger.debug(f"Removed temp file: {self.temp_file}")
            except Exception as e:
                self.logger.error(f"Error removing temp file: {e}")
            finally:
                self.temp_file = None

    def reset_ui(self):
        """Reset UI elements"""
        self.fast_status_label.config(text="")
        self.accurate_status_label.config(text="")
        self.fast_output_text.delete(1.0, tk.END)
        self.accurate_output_text.delete(1.0, tk.END)
        self.fast_progress.stop()
        self.accurate_progress.stop()

    def copy_fast_to_clipboard(self):
        """Copy fast transcription to clipboard"""
        self._copy_to_clipboard(self.fast_output_text, self.fast_status_label, "Quick")

    def copy_accurate_to_clipboard(self):
        """Copy accurate transcription to clipboard"""
        self._copy_to_clipboard(self.accurate_output_text, self.accurate_status_label, "Enhanced")

    def _copy_to_clipboard(self, text_widget, status_label, prefix):
        """Helper to copy text to clipboard"""
        text = text_widget.get(1.0, tk.END).strip()
        if text:
            try:
                pyperclip.copy(text)
                status_label.config(text=f"{prefix} transcription copied!")
            except Exception as e:
                self.logger.error(f"Copy error: {e}")
                status_label.config(text=f"Copy error: {str(e)}")
        else:
            status_label.config(text="No text to copy!")

    def on_closing(self):
        """Clean up on window close"""
        self.logger.info("Shutting down...")
        self.cancel_second_pass.set(True)
        self.recorder.cleanup()
        self.cleanup_temp_file()
        self.root.destroy()
