"""
# Setting Up Local Whisper Speech Recognition

## Prerequisites
1. Python 3.8 or higher
2. pip (Python package manager)
3. Virtual environment (recommended)

## Installation Steps

### 1. Install System Dependencies
#### For Windows:
```bash
# Install Microsoft Visual C++ Redistributable (if not already installed)
# Download from: https://aka.ms/vs/17/release/vc_redist.x64.exe

# Install Microsoft Visual Studio Build Tools
# Download from: https://visualstudio.microsoft.com/visual-cpp-build-tools/
```

#### For Linux (Ubuntu/Debian):
```bash
sudo apt update
sudo apt install -y ffmpeg python3-pip python3-venv
```

#### For macOS:
```bash
# Install Homebrew if not already installed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install dependencies
brew install ffmpeg python
```

### 2. Create and Activate Virtual Environment
```bash
# Navigate to your project directory
cd path/to/your/project

# Create virtual environment
python -m venv whisper_env

# Activate virtual environment
# Windows
whisper_env\Scripts\activate

# macOS/Linux
source whisper_env/bin/activate
```

### 3. Install Whisper and Dependencies
```bash
# Upgrade pip
pip install --upgrade pip

# Install PyTorch (choose version based on your system)
# Visit https://pytorch.org/get-started/locally/ for exact command

# For CUDA-enabled GPU (recommended for faster processing)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# For CPU-only
pip install torch torchvision torchaudio

# Install Whisper
pip install git+https://github.com/openai/whisper.git

# Additional required packages
pip install numpy scipy pandas pyaudio wave sounddevice
```

### 4. Install Additional System Tools
- **FFmpeg**: Required for audio processing
  - Windows: Download from https://ffmpeg.org/download.html
  - macOS: `brew install ffmpeg`
  - Linux: `sudo apt-get install ffmpeg`

### 5. Modify `speech_to_text.py`
Replace the speech recognition logic with Whisper implementation:


"""

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
from tkinter import ttk, scrolledtext
from typing import Optional
import warnings

warnings.filterwarnings("ignore", category=UserWarning)


def log_audio_devices():
    """Log all available audio input devices to console before startup"""
    print("\n=== AVAILABLE AUDIO INPUT DEVICES ===")
    p = pyaudio.PyAudio()

    try:
        default_device_index = p.get_default_input_device_info()['index']
        default_device_name = p.get_device_info_by_index(default_device_index)['name']

        print(f"Default Input Device: {default_device_name} (index: {default_device_index})")
    except Exception as e:
        print(f"Error getting default device: {str(e)}")
        print("No default input device found. Please check your audio settings.")
        default_device_index = None

    print("\nAll Available Input Devices:")

    try:
        info = p.get_host_api_info_by_index(0)
        num_devices = info.get('deviceCount')

        for i in range(num_devices):
            try:
                device_info = p.get_device_info_by_index(i)
                if device_info.get('maxInputChannels') > 0:  # if it has input channels, it's an input device
                    print(f"  - Device {i}: {device_info['name']}")
                    print(f"      Input channels: {device_info['maxInputChannels']}")
                    print(f"      Default sample rate: {device_info['defaultSampleRate']}")
                    if default_device_index is not None and i == default_device_index:
                        print("      ** DEFAULT DEVICE **")
                    print("")
            except Exception as e:
                print(f"  - Error retrieving device {i} info: {str(e)}")
    except Exception as e:
        print(f"Error listing audio devices: {str(e)}")

    print("======================================\n")
    p.terminate()


# Log audio devices at import time
log_audio_devices()


class SpeechToTextApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Speech-to-Text App")
        self.root.geometry("600x600")  # Larger window to accommodate both panels
        self.root.configure(padx=20, pady=20)

        # Variables
        self.recording = False
        self.audio = None
        self.stream = None
        self.frames = []
        self.temp_file: Optional[str] = None
        self.fast_transcribed_text = ""
        self.accurate_transcribed_text = ""
        self.recording_lock = threading.Lock()
        self.last_button_press = 0
        self.debounce_time = 500  # milliseconds
        self.processing = False

        # New variables for two-pass transcription
        self.second_pass_running = False
        self.second_pass_thread = None
        self.second_pass_lock = threading.Lock()
        self.cancel_second_pass = False

        # Whisper model setup
        try:
            # Fast model for first pass
            self.fast_model = whisper.load_model('tiny.en')  # Tiny model is fastest
            # High-quality model for second pass
            self.accurate_model = whisper.load_model('small.en')  # Base model is more accurate but slower
        except Exception as e:
            print(f"Error loading Whisper models: {e}")
            self.fast_model = None
            self.accurate_model = None

        # Punctuation command mapping
        self.punctuation_commands = {
            # Basic punctuation
            "dot": ".",
            "period": ".",
            "comma": ",",
            "question mark": "?",
            "double quote": '"',
            "quote": "'",
            "hyphen": "-",
            "back slash": "\\",
            "backslash": "\\",
            "slash": "/",
            "exclamation point": "!",
            "new paragraph": "\n\n",
            "new line": "\n",

            # Additional punctuation
            "semicolon": ";",
            "colon": ":",
            "ellipsis": "...",
            "underscore": "_",
            "at sign": "@",
            "hash": "#",
            "percent": "%",
            "ampersand": "&",
            "asterisk": "*",
            "plus": "+",
            "equals": "=",
            "dollar sign": "$",
            "euro sign": "€",
            "pound sign": "£",
            "yen sign": "¥",

            # Brackets and parentheses
            "open parenthesis": "(",
            "close parenthesis": ")",
            "open bracket": "[",
            "close bracket": "]",
            "open brace": "{",
            "close brace": "}",
            "open angle bracket": "<",
            "close angle bracket": ">",

            # Formatting commands
            "tab": "\t",
            "indent": "    ",
            "bullet point": "• ",
            "dash": "– ",

            # Special characters
            "caret": "^",
            "tilde": "~",
            "backtick": "`",
            "pipe": "|",
            "degree sign": "°",
            "copyright": "©",
            "trademark": "™",
            "registered trademark": "®"
        }

        # Create GUI elements
        self.create_widgets()

        # Set up cleanup on window close
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_widgets(self):
        # Top frame for buttons
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

        # Bind press and release events
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

        # Paned window to divide the interface into two sections
        self.paned_window = tk.PanedWindow(self.root, orient=tk.VERTICAL)
        self.paned_window.pack(fill=tk.BOTH, expand=True)

        # ===== FAST TRANSCRIPTION SECTION =====
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

        # ===== ACCURATE TRANSCRIPTION SECTION =====
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

    def start_recording(self, event):
        # Debounce check - prevent too rapid clicking
        current_time = int(time.time() * 1000)
        if current_time - self.last_button_press < self.debounce_time:
            print(f"Debouncing button press (time since last press: {current_time - self.last_button_press}ms)")
            return

        self.last_button_press = current_time

        # Prevent starting a new recording if we're still processing the first pass
        if self.processing:
            print("Cannot start new recording while processing previous one")
            return

        # Cancel any ongoing second pass transcription
        with self.second_pass_lock:
            self.cancel_second_pass = True

        # Wait briefly for the second pass to acknowledge cancellation
        time.sleep(0.1)

        # Thread-safe recording state change
        with self.recording_lock:
            # Don't start a new recording if we're already recording
            if self.recording:
                print("Already recording, ignoring start request")
                return

            self.recording = True
            self.frames = []

        self.record_button.config(text="Recording... Release to Stop", bg="red")
        self.status_label.config(text="Recording audio...")

        # Reset UI elements for both sections
        self.fast_status_label.config(text="")
        self.accurate_status_label.config(text="")
        self.fast_output_text.delete(1.0, tk.END)
        self.accurate_output_text.delete(1.0, tk.END)

        # Reset progress bars
        self.fast_progress.stop()
        self.accurate_progress.stop()

        # Start recording in a separate thread
        try:
            self.record_thread = threading.Thread(target=self.record_audio)
            self.record_thread.daemon = True
            self.record_thread.start()
        except Exception as e:
            print(f"Error starting recording thread: {e}")
            with self.recording_lock:
                self.recording = False
            self.record_button.config(text="Press and Hold to Record", bg="lightcoral")
            self.status_label.config(text=f"Error: {str(e)}")

    def record_audio(self):
        CHUNK = 1024
        FORMAT = pyaudio.paInt16
        CHANNELS = 1
        RATE = 44100

        try:
            self.audio = pyaudio.PyAudio()

            # Open audio stream
            self.stream = self.audio.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                frames_per_buffer=CHUNK
            )

            # Record audio
            while True:
                # Thread-safe check of recording state
                with self.recording_lock:
                    if not self.recording:
                        break

                try:
                    data = self.stream.read(CHUNK, exception_on_overflow=False)
                    self.frames.append(data)
                except Exception as e:
                    print(f"Error reading audio data: {e}")
                    # Break the loop if there's an error
                    with self.recording_lock:
                        self.recording = False
                    self.root.after(0, lambda: self.status_label.config(text=f"Recording error: {str(e)}"))
                    break

        except Exception as e:
            print(f"Error in record_audio: {e}")
            with self.recording_lock:
                self.recording = False
            self.root.after(0, lambda: self.status_label.config(text=f"Recording setup error: {str(e)}"))

    def stop_recording(self, event):
        # Debounce check
        current_time = int(time.time() * 1000)
        if current_time - self.last_button_press < self.debounce_time:
            print(f"Debouncing button release (time since last press: {current_time - self.last_button_press}ms)")
            return

        self.last_button_press = current_time

        # Thread-safe recording state change
        recording_was_active = False
        with self.recording_lock:
            if self.recording:
                self.recording = False
                recording_was_active = True

        # Only process if recording was actually active
        if recording_was_active:
            self.record_button.config(text="Press and Hold to Record", bg="lightcoral")
            self.status_label.config(text="Processing audio...")
            self.fast_progress.start()
            self.fast_status_label.config(text="Processing...")

            # Set the processing flag to prevent new recordings
            self.processing = True

            # Properly close the audio resources
            self.cleanup_audio_resources()

            # Check if we have any frames to process
            if not self.frames:
                print("No audio data recorded")
                self.status_label.config(text="No audio data recorded")
                self.fast_progress.stop()
                self.fast_status_label.config(text="No audio recorded")
                self.processing = False
                return

            # Process the recorded audio in a separate thread
            try:
                process_thread = threading.Thread(target=self.process_audio_two_pass)
                process_thread.daemon = True
                process_thread.start()
            except Exception as e:
                print(f"Error starting processing thread: {e}")
                self.status_label.config(text=f"Error: {str(e)}")
                self.fast_progress.stop()
                self.fast_status_label.config(text=f"Error: {str(e)}")
                self.processing = False

    def cleanup_audio_resources(self):
        """Safely clean up audio resources"""
        try:
            if self.stream:
                try:
                    self.stream.stop_stream()
                except Exception as e:
                    print(f"Error stopping stream: {e}")

                try:
                    self.stream.close()
                except Exception as e:
                    print(f"Error closing stream: {e}")

                self.stream = None

            if self.audio:
                try:
                    self.audio.terminate()
                except Exception as e:
                    print(f"Error terminating PyAudio: {e}")

                self.audio = None
        except Exception as e:
            print(f"Error in cleanup_audio_resources: {e}")

    def process_audio_two_pass(self):
        """Process recorded audio with a two-pass approach for speed and accuracy"""
        try:
            # Create a temporary file
            fd, self.temp_file = tempfile.mkstemp(suffix='.wav')
            os.close(fd)

            try:
                # Save recorded audio to the temporary file
                wf = wave.open(self.temp_file, 'wb')
                wf.setnchannels(1)
                wf.setsampwidth(pyaudio.PyAudio().get_sample_size(pyaudio.paInt16))
                wf.setframerate(44100)
                wf.writeframes(b''.join(self.frames))
                wf.close()

                # Check if models are loaded
                if self.fast_model is None or self.accurate_model is None:
                    raise RuntimeError("One or both Whisper models failed to load")

                # FIRST PASS - Use fast model
                self.root.after(0, lambda: self.status_label.config(text="Transcribing with fast model..."))
                self.root.after(0, lambda: self.fast_status_label.config(text="Transcribing with fast model..."))

                # Transcribe with fast model
                result_fast = self.fast_model.transcribe(self.temp_file)
                self.fast_transcribed_text = result_fast['text']

                # Update UI with fast results
                self.root.after(0, self.update_ui_with_fast_results)

                # # SECOND PASS - Use accurate model in background
                # # Reset the cancellation flag
                # with self.second_pass_lock:
                #     self.cancel_second_pass = False
                #     self.second_pass_running = True
                #
                # # Start the second pass in a separate thread
                # self.second_pass_thread = threading.Thread(
                #     target=self.run_second_pass_transcription,
                #     args=(self.temp_file,)
                # )
                # self.second_pass_thread.daemon = True
                # self.second_pass_thread.start()

            except Exception as e:
                error_msg = f"Transcription error: {e}"
                print(error_msg)
                self.root.after(0, lambda: self.status_label.config(text=error_msg))
                self.root.after(0, lambda: self.fast_status_label.config(text=error_msg))
                self.root.after(0, self.fast_progress.stop)
                self.root.after(0, self.accurate_progress.stop)

        except Exception as e:
            error_msg = f"Error creating temporary file: {e}"
            print(error_msg)
            self.root.after(0, lambda: self.status_label.config(text=error_msg))
            self.root.after(0, lambda: self.fast_status_label.config(text=error_msg))
            self.root.after(0, self.fast_progress.stop)
            self.root.after(0, self.accurate_progress.stop)

        finally:
            # Clear the processing flag for the first pass
            self.processing = False

    def run_second_pass_transcription(self, audio_file):
        """Run the more accurate transcription in the background"""
        try:
            # Start the second progress bar
            self.root.after(0, self.accurate_progress.start)
            self.root.after(0, lambda: self.accurate_status_label.config(
                text="Enhanced transcription running..."
            ))

            # Transcribe with accurate model
            result_accurate = self.accurate_model.transcribe(audio_file)

            # Check if cancellation was requested
            with self.second_pass_lock:
                if self.cancel_second_pass:
                    print("Second pass transcription was cancelled")
                    self.root.after(0, lambda: self.accurate_status_label.config(
                        text="Enhanced transcription cancelled"
                    ))
                    self.root.after(0, self.accurate_progress.stop)
                    self.second_pass_running = False
                    return

            self.accurate_transcribed_text = result_accurate['text']
            # Update UI with more accurate results
            self.root.after(0, self.update_ui_with_accurate_results)

        except Exception as e:
            print(f"Error in second pass transcription: {e}")
            self.root.after(0, lambda: self.accurate_status_label.config(
                text=f"Enhanced transcription failed: {str(e)}"
            ))
        finally:
            # Clean up temporary file if it exists
            if audio_file and os.path.exists(audio_file):
                try:
                    os.remove(audio_file)
                except Exception as e:
                    print(f"Error removing temporary file: {e}")

            # Reset the temporary file reference
            self.temp_file = None

            # Clear the second pass flag
            with self.second_pass_lock:
                self.second_pass_running = False

            # Stop the second progress bar
            self.root.after(0, self.accurate_progress.stop)

    def process_punctuation_commands(self, text):
        """
        Process punctuation commands in the transcribed text
        Performs case-insensitive matching for commands and prevents partial word matches

        Args:
            text (str): Raw transcribed text

        Returns:
            str: Processed text with punctuation commands replaced
        """
        # Convert to lowercase for matching but keep original for replacing
        processed_text = text
        text_lower = text.lower()

        # Replace the explicit "command X" format first
        for command, symbol in self.punctuation_commands.items():
            command_phrase = f"command {command}"
            # Find all occurrences of the command phrase
            start_idx = 0
            while True:
                idx = text_lower.find(command_phrase, start_idx)
                if idx == -1:
                    break

                # Check if it's a whole word match by checking boundaries
                before_char = text_lower[idx - 1] if idx > 0 else ' '
                after_char = text_lower[idx + len(command_phrase)] if idx + len(command_phrase) < len(
                    text_lower) else ' '

                if before_char.isalpha() or after_char.isalpha():
                    # Not a whole word match, continue searching
                    start_idx = idx + 1
                    continue

                # It's a whole word match, replace it in the original text
                processed_text = processed_text[:idx] + symbol + processed_text[idx + len(command_phrase):]

                # Update lowercase text to match the changes
                text_lower = text_lower[:idx] + symbol + text_lower[idx + len(command_phrase):]

                # Adjust the start index for the next search
                start_idx = idx + len(symbol)

        # Now handle standalone command words
        for command, symbol in self.punctuation_commands.items():
            # Find all occurrences of the command
            start_idx = 0
            while True:
                idx = text_lower.find(command, start_idx)
                if idx == -1:
                    break

                # Check if it's a whole word match by checking boundaries
                before_char = text_lower[idx - 1] if idx > 0 else ' '
                after_char = text_lower[idx + len(command)] if idx + len(command) < len(text_lower) else ' '

                if before_char.isalpha() or after_char.isalpha():
                    # Not a whole word match, continue searching
                    start_idx = idx + 1
                    continue

                # It's a whole word match, replace it in the original text
                processed_text = processed_text[:idx] + symbol + processed_text[idx + len(command):]

                # Update lowercase text to match the changes
                text_lower = text_lower[:idx] + symbol + text_lower[idx + len(command):]

                # Adjust the start index for the next search
                start_idx = idx + len(symbol)

        return processed_text

    def update_ui_with_fast_results(self):
        """Update UI with results from the fast first pass"""
        self.fast_progress.stop()
        self.status_label.config(text="Quick transcription complete!")
        self.fast_status_label.config(text="Quick transcription complete!")
        self.fast_output_text.delete(1.0, tk.END)
        self.fast_output_text.insert(tk.END, self.fast_transcribed_text)

    def update_ui_with_accurate_results(self):
        """Update UI with results from the more accurate second pass"""
        self.accurate_progress.stop()
        self.accurate_status_label.config(text="Enhanced transcription complete!")
        self.accurate_output_text.delete(1.0, tk.END)
        self.accurate_output_text.insert(tk.END, self.accurate_transcribed_text)

    def copy_fast_to_clipboard(self):
        """Copy the fast transcription results to clipboard"""
        text = self.fast_output_text.get(1.0, tk.END).strip()
        if text:
            try:
                pyperclip.copy(text)
                self.fast_status_label.config(text="Quick transcription copied to clipboard!")
            except Exception as e:
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
                self.accurate_status_label.config(text=f"Error copying to clipboard: {str(e)}")
        else:
            self.accurate_status_label.config(text="No text to copy!")

    def on_closing(self):
        """Clean up resources when the window is closed"""
        print("Cleaning up resources...")

        # Stop recording if active
        with self.recording_lock:
            self.recording = False

        # Signal any ongoing second pass to cancel
        with self.second_pass_lock:
            self.cancel_second_pass = True

        # Clean up audio resources
        self.cleanup_audio_resources()

        # Remove temp file if it exists
        if self.temp_file and os.path.exists(self.temp_file):
            try:
                os.remove(self.temp_file)
            except Exception as e:
                print(f"Error removing temporary file: {e}")

        # Destroy the window
        self.root.destroy()


if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = SpeechToTextApp(root)
        root.mainloop()
    except Exception as e:
        # Get the full traceback
        error_traceback = traceback.format_exc()
        # Print to console
        print("\n=== APPLICATION ERROR ===")
        print(error_traceback)
        time.sleep(100000)
