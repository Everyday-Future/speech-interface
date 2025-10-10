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

        # Latching mode state
        self.latching_recording = SafeFlag()
        self.last_transcribed_frame_index = 0
        self.accumulated_fast_text = ""
        self.accumulated_accurate_text = ""

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
        # Button container frame
        button_container = tk.Frame(self.root)
        button_container.pack(fill=tk.X, pady=(0, 10))

        # Create two buttons side by side (50/50 split)
        button_left_frame = tk.Frame(button_container)
        button_left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 2))

        button_right_frame = tk.Frame(button_container)
        button_right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(2, 0))

        # Press-and-hold button (left)
        self.press_hold_button = tk.Button(
            button_left_frame,
            text="Press and Hold to Record",
            bg="lightcoral",
            activebackground="red",
            font=("Arial", 12),
            height=2
        )
        self.press_hold_button.pack(fill=tk.BOTH, expand=True)
        self.press_hold_button.bind("<ButtonPress-1>", self.on_record_start)
        self.press_hold_button.bind("<ButtonRelease-1>", self.on_record_stop)

        # Toggle/latching button (right)
        self.toggle_button = tk.Button(
            button_right_frame,
            text="Start Latching Record",
            bg="lightcoral",
            activebackground="red",
            font=("Arial", 12),
            height=2,
            command=self.on_toggle_click
        )
        self.toggle_button.pack(fill=tk.BOTH, expand=True)

        # Parse button (below toggle button)
        self.parse_button = tk.Button(
            self.root,
            text="Parse Recording",
            bg="lightblue",
            activebackground="skyblue",
            font=("Arial", 11),
            height=1,
            state=tk.DISABLED,
            command=self.on_parse_click
        )
        self.parse_button.pack(fill=tk.X, pady=(0, 10))

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
        self.paned_window.add(self.fast_frame, height=300)

        # Accurate transcription section
        self.accurate_frame = self._create_transcription_section(
            "Enhanced Transcription (More Accurate):",
            self.copy_accurate_to_clipboard
        )
        self.paned_window.add(self.accurate_frame, height=450)

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
            self.press_hold_button.config(text="Recording... Release to Stop", bg="red")
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
            self.press_hold_button.config(text="Press and Hold to Record", bg="lightcoral")
            return

        # Update UI
        self.processing.set(True)
        self.press_hold_button.config(text="Press and Hold to Record", bg="lightcoral")
        self.status_label.config(text="Processing audio...")
        self.fast_progress.start()

        # Process in background
        thread = threading.Thread(target=self.process_audio, args=(frames,))
        thread.daemon = True
        thread.start()

    def on_toggle_click(self):
        """Handle toggle button click for latching recording"""
        if self.processing.get():
            self.logger.warning("Cannot toggle recording while processing")
            return

        if not self.latching_recording.get():
            # Start latching recording
            self.cancel_second_pass.set(True)
            time.sleep(0.1)

            if self.recorder.start_recording():
                self.latching_recording.set(True)
                self.last_transcribed_frame_index = 0
                self.accumulated_fast_text = ""
                self.accumulated_accurate_text = ""

                self.toggle_button.config(text="Stop Recording", bg="red")
                self.press_hold_button.config(state=tk.DISABLED)
                self.parse_button.config(state=tk.NORMAL)
                self.status_label.config(text="Latching recording active...")
                self.reset_ui()
        else:
            # Stop latching recording and process final segment
            self.latching_recording.set(False)
            self.parse_button.config(state=tk.DISABLED)
            self.toggle_button.config(text="Start Latching Record", bg="lightcoral")
            self.press_hold_button.config(state=tk.NORMAL)

            # Stop recording
            frames = self.recorder.stop_recording()

            if frames:
                # Process final unparsed segment
                self.processing.set(True)
                self.status_label.config(text="Processing final segment...")
                thread = threading.Thread(target=self.process_final_segment, args=(frames,))
                thread.daemon = True
                thread.start()
            else:
                self.status_label.config(text="Ready")

    def on_parse_click(self):
        """Handle parse button click during latching recording"""
        if not self.latching_recording.get():
            return

        current_frame_count = self.recorder.get_frame_count()

        if current_frame_count <= self.last_transcribed_frame_index:
            self.status_label.config(text="No new audio to parse")
            return

        # Get new frames since last parse
        frames_segment = self.recorder.get_frames_from(self.last_transcribed_frame_index)

        if not frames_segment:
            self.status_label.config(text="No new audio to parse")
            return

        # Update index for next parse
        segment_start_index = self.last_transcribed_frame_index
        self.last_transcribed_frame_index = current_frame_count

        # Process in background
        self.status_label.config(text="Parsing recorded audio...")
        self.fast_progress.start()
        self.accurate_progress.start()

        thread = threading.Thread(
            target=self.process_incremental_transcription,
            args=(frames_segment, segment_start_index)
        )
        thread.daemon = True
        thread.start()

    def transcribe_with_retry(self, transcribe_func, audio_file, max_retries=3):
        """Attempt transcription with automatic retry"""
        for attempt in range(max_retries):
            try:
                return transcribe_func(audio_file)
            except Exception as e:
                if attempt == max_retries - 1:
                    self.logger.error(f"Transcription failed after {max_retries} attempts")
                    raise
                self.logger.warning(f"Transcription attempt {attempt + 1} failed: {e}, retrying...")
                time.sleep(0.5)

    def process_incremental_transcription(self, frames_segment: list, segment_start_index: int):
        """Process incremental transcription of a segment"""
        temp_file = None
        try:
            # Create temp file for this segment
            fd, temp_file = tempfile.mkstemp(suffix='.wav', dir=self.config.temp_dir)
            os.close(fd)

            # Save segment to file
            if not self.recorder.save_to_file(frames_segment, temp_file):
                raise Exception("Failed to save audio segment")

            # Fast transcription with retry
            self.queue_ui_update(self.fast_status_label.config, text="Transcribing...")
            fast_text = self.transcribe_with_retry(
                self.transcriber.transcribe_fast,
                temp_file
            )

            # Append to accumulated text
            if self.accumulated_fast_text:
                self.accumulated_fast_text += "\n\n"
            self.accumulated_fast_text += fast_text

            self.queue_ui_update(self.fast_progress.stop)
            self.queue_ui_update(self.fast_status_label.config, text="Complete!")
            self.queue_ui_update(self.fast_output_text.delete, 1.0, tk.END)
            self.queue_ui_update(self.fast_output_text.insert, tk.END, self.accumulated_fast_text)

            # Accurate transcription with retry
            self.queue_ui_update(self.accurate_status_label.config, text="Processing...")
            accurate_text = self.transcribe_with_retry(
                self.transcriber.transcribe_accurate,
                temp_file
            )

            # Append to accumulated text
            if self.accumulated_accurate_text:
                self.accumulated_accurate_text += "\n\n"
            self.accumulated_accurate_text += accurate_text

            self.queue_ui_update(self.accurate_progress.stop)
            self.queue_ui_update(self.accurate_status_label.config, text="Complete!")
            self.queue_ui_update(self.accurate_output_text.delete, 1.0, tk.END)
            self.queue_ui_update(self.accurate_output_text.insert, tk.END, self.accumulated_accurate_text)

            self.queue_ui_update(self.status_label.config, text="Latching recording active... (parsed)")

        except Exception as e:
            self.logger.error(f"Error in incremental transcription: {e}")
            self.queue_ui_update(self.status_label.config, text=f"Parse error: {str(e)}")
            self.queue_ui_update(self.fast_progress.stop)
            self.queue_ui_update(self.accurate_progress.stop)
            raise
        finally:
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception as e:
                    self.logger.error(f"Error removing temp file: {e}")

    def process_final_segment(self, frames: list):
        """Process final unparsed segment when stopping latching recording"""
        temp_file = None
        try:
            # Get only unparsed frames
            unparsed_frames = frames[self.last_transcribed_frame_index:]

            if not unparsed_frames:
                # No new frames, just update status
                self.queue_ui_update(self.status_label.config, text="Ready")
                self.processing.set(False)
                return

            # Create temp file
            fd, temp_file = tempfile.mkstemp(suffix='.wav', dir=self.config.temp_dir)
            os.close(fd)

            # Save unparsed segment
            if not self.recorder.save_to_file(unparsed_frames, temp_file):
                raise Exception("Failed to save final audio segment")

            self.queue_ui_update(self.fast_progress.start)
            self.queue_ui_update(self.accurate_progress.start)

            # Fast transcription with retry
            self.queue_ui_update(self.fast_status_label.config, text="Transcribing final segment...")
            fast_text = self.transcribe_with_retry(
                self.transcriber.transcribe_fast,
                temp_file
            )

            # Append to accumulated text
            if self.accumulated_fast_text:
                self.accumulated_fast_text += "\n\n"
            self.accumulated_fast_text += fast_text

            self.queue_ui_update(self.fast_progress.stop)
            self.queue_ui_update(self.fast_status_label.config, text="Complete!")
            self.queue_ui_update(self.fast_output_text.delete, 1.0, tk.END)
            self.queue_ui_update(self.fast_output_text.insert, tk.END, self.accumulated_fast_text)

            # Accurate transcription with retry
            self.queue_ui_update(self.accurate_status_label.config, text="Processing final segment...")
            accurate_text = self.transcribe_with_retry(
                self.transcriber.transcribe_accurate,
                temp_file
            )

            # Append to accumulated text
            if self.accumulated_accurate_text:
                self.accumulated_accurate_text += "\n\n"
            self.accumulated_accurate_text += accurate_text

            self.queue_ui_update(self.accurate_progress.stop)
            self.queue_ui_update(self.accurate_status_label.config, text="Complete!")
            self.queue_ui_update(self.accurate_output_text.delete, 1.0, tk.END)
            self.queue_ui_update(self.accurate_output_text.insert, tk.END, self.accumulated_accurate_text)

            self.queue_ui_update(self.status_label.config, text="Ready")

        except Exception as e:
            self.logger.error(f"Error processing final segment: {e}")
            self.queue_ui_update(self.status_label.config, text=f"Error: {str(e)}")
            self.queue_ui_update(self.fast_progress.stop)
            self.queue_ui_update(self.accurate_progress.stop)
            raise
        finally:
            self.processing.set(False)
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception as e:
                    self.logger.error(f"Error removing temp file: {e}")

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
        self.latching_recording.set(False)
        self.recorder.cleanup()
        self.cleanup_temp_file()
        self.root.destroy()