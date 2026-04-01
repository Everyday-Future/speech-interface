# core/scripts/speech_to_text_app.py
import tkinter as tk
import threading
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime
import pyperclip
import time
import logging
from tkinter import ttk, scrolledtext
from typing import Optional, Callable
from queue import Queue
from config import Config
from core.adapters.audio_recorder import AudioRecorder, SafeFlag
from core.adapters.audio_transcriber import AudioTranscriber
from core.scripts.theme import Theme


class SpeechToTextApp:
    """Main application GUI"""

    def __init__(self, root: tk.Tk, config: Config):
        self.root = root
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.DEBUG)
        # create console handler and set level to debug
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        # create formatter
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        # add formatter to ch
        ch.setFormatter(formatter)
        # add ch to logger
        self.logger.addHandler(ch)
        # Initialize theme
        self.theme = Theme(config.default_theme)
        self.theme.register_callback(self.apply_theme)

        # Initialize components
        self.recorder = AudioRecorder(config)
        self.transcriber = AudioTranscriber(config)

        # State management
        self.processing = SafeFlag()
        self.cancel_second_pass = SafeFlag()
        self.cancel_processing = SafeFlag()
        self.cancel_timestamp = None
        self.current_operation = None
        self.last_button_press = 0
        self.temp_file: Optional[str] = None

        # Latching mode state
        self.latching_recording = SafeFlag()
        self.last_transcribed_frame_index = 0
        self.accumulated_fast_text = ""
        self.accumulated_accurate_text = ""

        # Clipboard history slots — slot 0 is always "current" (!), slots 1-7 are past recordings.
        # Each history entry: {'fast': str, 'accurate': str, 'timestamp': str}
        self.slot_history: list[dict] = []
        self.active_slot: int = 0  # which slot the text panels are currently showing

        # UI update queue
        self.ui_queue = Queue()

        # Setup window
        self.setup_window()
        self.create_menu_bar()
        self.create_widgets()

        # Apply initial theme
        self.apply_theme()

        # Bind spacebar to parse button
        self.root.bind('<space>', lambda event: self.on_parse_click())

        # Start UI update loop
        self.root.after(100, self.process_ui_queue)

        # Cleanup on close
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def setup_window(self):
        """Configure main window"""
        self.root.title(self.config.window_title)
        self.root.geometry(self.config.window_geometry)
        self.root.configure(padx=20, pady=20)

    def create_menu_bar(self):
        """Create menu bar with theme selector"""
        colors = self.theme.current

        menubar = tk.Menu(
            self.root,
            bg=colors.menubar_bg,
            fg=colors.menubar_fg,
            activebackground=colors.bg_button_active,
            activeforeground=colors.fg_primary
        )
        self.root.config(menu=menubar)

        # Theme menu
        theme_menu = tk.Menu(
            menubar,
            tearoff=0,
            bg=colors.menubar_bg,
            fg=colors.menubar_fg,
            activebackground=colors.accent_action,
            activeforeground=colors.fg_primary,
            selectcolor=colors.accent_action
        )
        menubar.add_cascade(label="Theme", menu=theme_menu)

        # Theme selection variable
        self.theme_var = tk.StringVar(value=self.theme.current_name)

        theme_menu.add_radiobutton(
            label="Light",
            variable=self.theme_var,
            value="light",
            command=lambda: self.change_theme("light")
        )
        theme_menu.add_radiobutton(
            label="Dark",
            variable=self.theme_var,
            value="dark",
            command=lambda: self.change_theme("dark")
        )

    def change_theme(self, theme_name: str):
        """Change application theme"""
        self.theme.set_theme(theme_name)
        self.theme_var.set(theme_name)

    def apply_theme(self):
        """Apply current theme to all widgets"""
        colors = self.theme.current

        # Configure root window
        self.root.configure(bg=colors.bg_primary)

        # Customize title bar
        # self.customize_title_bar()

        # Configure ttk styles
        self.theme.configure_ttk_styles(self.root)

        # Update menu bar colors
        try:
            menubar = self.root.nametowidget(self.root['menu'])
            menubar.configure(
                bg=colors.menubar_bg,
                fg=colors.menubar_fg,
                activebackground=colors.bg_button_active,
                activeforeground=colors.fg_primary
            )

            # Update theme submenu
            theme_menu = menubar.nametowidget(menubar.entrycget(0, 'menu'))
            theme_menu.configure(
                bg=colors.menubar_bg,
                fg=colors.menubar_fg,
                activebackground=colors.accent_action,
                activeforeground=colors.fg_primary,
                selectcolor=colors.accent_action
            )
        except Exception as e:
            self.logger.debug(f"Could not style menu bar: {e}")

        # Apply to all widgets if they exist
        if hasattr(self, 'press_hold_button'):
            self._apply_widget_theme()

    def _apply_widget_theme(self):
        """Apply theme to all existing widgets"""
        colors = self.theme.current

        # Button frames
        for widget in [self.root]:
            for child in widget.winfo_children():
                if isinstance(child, tk.Frame):
                    child.configure(bg=colors.bg_primary)

        # Recording buttons
        self.press_hold_button.configure(
            bg=colors.accent_record,
            activebackground=colors.accent_record_active,
            fg=colors.fg_primary,
            activeforeground=colors.fg_primary
        )
        self.toggle_button.configure(
            bg=colors.accent_record,
            activebackground=colors.accent_record_active,
            fg=colors.fg_primary,
            activeforeground=colors.fg_primary
        )

        # Parse button
        self.parse_button.configure(
            bg=colors.accent_action,
            activebackground=colors.accent_action_active,
            fg=colors.fg_primary,
            activeforeground=colors.fg_primary,
            disabledforeground=colors.fg_disabled
        )

        # If button is currently disabled, temporarily enable it to apply colors, then disable again
        current_state = str(self.parse_button['state'])
        if current_state == 'disabled':
            self.parse_button.configure(state=tk.NORMAL)
            self.parse_button.configure(
                bg=colors.accent_action,
                fg=colors.fg_primary
            )
            self.parse_button.configure(state=tk.DISABLED)

        # Status label
        self.status_label.configure(
            bg=colors.bg_primary,
            fg=colors.fg_secondary
        )

        # Paned window
        self.paned_window.configure(bg=colors.bg_primary)

        # Fast transcription section
        self._apply_section_theme(
            self.fast_frame,
            self.fast_copy_button,
            self.fast_progress,
            self.fast_output_text,
            self.fast_status_label
        )

        # Accurate transcription section
        self._apply_section_theme(
            self.accurate_frame,
            self.accurate_copy_button,
            self.accurate_progress,
            self.accurate_output_text,
            self.accurate_status_label
        )

        # Datetime button
        self.datetime_button.configure(
            bg=colors.accent_utility,
            activebackground=colors.accent_utility_active,
            fg=colors.fg_primary,
            activeforeground=colors.fg_primary
        )

        # Cancel button
        self.cancel_button.configure(
            bg=colors.accent_record,
            activebackground=colors.accent_record_active,
            fg=colors.fg_primary,
            activeforeground=colors.fg_primary,
            disabledforeground=colors.fg_disabled
        )

        # If cancel button is currently disabled, temporarily enable it to apply colors
        cancel_state = str(self.cancel_button['state'])
        if cancel_state == 'disabled':
            self.cancel_button.configure(state=tk.NORMAL)
            self.cancel_button.configure(
                bg=colors.accent_record,
                fg=colors.fg_primary
            )
            self.cancel_button.configure(state=tk.DISABLED)

        # History slot strip
        if hasattr(self, 'slot_strip_frame'):
            self.slot_strip_frame.configure(bg=colors.bg_primary)
            self._update_slot_buttons()

    def _apply_section_theme(self, frame, copy_button, progress, text_area, status_label):
        """Apply theme to a transcription section"""
        colors = self.theme.current

        # Frame
        frame.configure(bg=colors.bg_primary)
        for child in frame.winfo_children():
            if isinstance(child, tk.Frame):
                child.configure(bg=colors.bg_primary)

        # Copy button
        copy_button.configure(
            bg=colors.accent_action,
            activebackground=colors.accent_action_active,
            fg=colors.fg_primary,
            activeforeground=colors.fg_primary
        )

        # Progress bar
        progress.configure(style="Custom.Horizontal.TProgressbar")

        # Text area
        text_area.configure(
            bg=colors.bg_secondary,
            fg=colors.fg_primary,
            insertbackground=colors.fg_primary,
            selectbackground=colors.text_select_bg,
            selectforeground=colors.text_select_fg
        )

        # Try to style the scrollbar
        try:
            # Get the scrollbar widget
            for child in text_area.winfo_children():
                if isinstance(child, tk.Scrollbar):
                    child.configure(
                        bg=colors.scrollbar_bg,
                        troughcolor=colors.scrollbar_bg,
                        activebackground=colors.scrollbar_fg
                    )
        except Exception as e:
            self.logger.debug(f"Could not style scrollbar: {e}")

        # Status label
        status_label.configure(
            bg=colors.bg_primary,
            fg=colors.fg_secondary
        )

        # Section header labels
        for child in frame.winfo_children():
            if isinstance(child, tk.Frame):
                for subchild in child.winfo_children():
                    if isinstance(subchild, tk.Label):
                        subchild.configure(
                            bg=colors.bg_primary,
                            fg=colors.fg_primary
                        )

    @contextmanager
    def suppress_subprocess_window(self):
        """Context manager to suppress subprocess console windows on Windows"""
        if os.name == 'nt':  # Windows only
            import subprocess
            original_popen = subprocess.Popen

            def patched_popen(*args, **kwargs):
                # Add window suppression flags
                if 'startupinfo' not in kwargs:
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = subprocess.SW_HIDE
                    kwargs['startupinfo'] = startupinfo
                if 'creationflags' not in kwargs:
                    kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
                return original_popen(*args, **kwargs)

            subprocess.Popen = patched_popen
            try:
                yield
            finally:
                subprocess.Popen = original_popen
        else:
            yield

    def create_widgets(self):
        """Create all GUI widgets"""
        colors = self.theme.current

        # Button container frame
        button_container = tk.Frame(self.root, bg=colors.bg_primary)
        button_container.pack(fill=tk.X, pady=(0, 10))

        # Create two buttons side by side (50/50 split)
        button_left_frame = tk.Frame(button_container, bg=colors.bg_primary)
        button_left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 2))

        button_right_frame = tk.Frame(button_container, bg=colors.bg_primary)
        button_right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(2, 0))

        # Press-and-hold button (left)
        self.press_hold_button = tk.Button(
            button_left_frame,
            text="Press and Hold to Record",
            bg=colors.accent_record,
            activebackground=colors.accent_record_active,
            fg=colors.fg_primary,
            activeforeground=colors.fg_primary,
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
            bg=colors.accent_record,
            activebackground=colors.accent_record_active,
            fg=colors.fg_primary,
            activeforeground=colors.fg_primary,
            font=("Arial", 12),
            height=2,
            command=self.on_toggle_click
        )
        self.toggle_button.pack(fill=tk.BOTH, expand=True)

        # Parse button (below toggle button)
        self.parse_button = tk.Button(
            self.root,
            text="Parse Recording",
            bg=colors.accent_action,
            activebackground=colors.accent_action_active,
            fg=colors.fg_primary,
            activeforeground=colors.fg_primary,
            disabledforeground=colors.fg_disabled,
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
            bg=colors.bg_primary,
            fg=colors.fg_secondary,
            font=("Arial", 10, "italic"),
            anchor="w"
        )
        self.status_label.pack(fill=tk.X, pady=(5, 5))

        # Paned window for transcription areas
        self.paned_window = tk.PanedWindow(self.root, orient=tk.VERTICAL, bg=colors.bg_primary)
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
        self.paned_window.add(self.accurate_frame, height=300)

        # Copy datetime button
        self.datetime_button = tk.Button(
            self.root,
            text="Copy Datetime",
            bg=colors.accent_utility,
            activebackground=colors.accent_utility_active,
            fg=colors.fg_primary,
            activeforeground=colors.fg_primary,
            font=("Arial", 10),
            height=1,
            command=self.copy_datetime_to_clipboard
        )
        self.datetime_button.pack(fill=tk.X, pady=(10, 0))

        # Cancel parsing button
        self.cancel_button = tk.Button(
            self.root,
            text="Cancel Parsing",
            bg=colors.accent_record,
            activebackground=colors.accent_record_active,
            fg=colors.fg_primary,
            activeforeground=colors.fg_primary,
            disabledforeground=colors.fg_disabled,
            font=("Arial", 10),
            height=1,
            state=tk.DISABLED,
            command=self.on_cancel_click
        )
        self.cancel_button.pack(fill=tk.X, pady=(5, 0))

        # History slot strip (! = current, 1-7 = previous recordings newest-to-oldest)
        self._create_slot_strip()

    def _create_slot_strip(self):
        """Create the clipboard history button strip at the bottom of the window."""
        colors = self.theme.current

        self.slot_strip_frame = tk.Frame(self.root, bg=colors.bg_primary)
        self.slot_strip_frame.pack(fill=tk.X, pady=(8, 0))

        tk.Label(
            self.slot_strip_frame,
            text="History:",
            bg=colors.bg_primary,
            fg=colors.fg_secondary,
            font=("Arial", 8)
        ).pack(side=tk.LEFT, padx=(0, 4))

        self.slot_buttons: list[tk.Button] = []

        # Slot 0 = current recording (marked with !)
        btn = tk.Button(
            self.slot_strip_frame,
            text="!",
            width=4,
            font=("Arial", 10, "bold"),
            relief=tk.SUNKEN,
            bg=colors.accent_action,
            fg=colors.fg_primary,
            activebackground=colors.accent_action_active,
            activeforeground=colors.fg_primary,
            command=lambda: self._switch_slot(0)
        )
        btn.pack(side=tk.LEFT, padx=(0, 2))
        self.slot_buttons.append(btn)

        # Slots 1-7 = history, newest first
        for i in range(1, 8):
            btn = tk.Button(
                self.slot_strip_frame,
                text=str(i),
                width=4,
                font=("Arial", 8),
                relief=tk.FLAT,
                bg=colors.bg_tertiary,
                fg=colors.fg_disabled,
                activebackground=colors.bg_button_active,
                activeforeground=colors.fg_primary,
                command=lambda s=i: self._switch_slot(s)
            )
            btn.pack(side=tk.LEFT, padx=(0, 2))
            self.slot_buttons.append(btn)

    def _save_to_history(self):
        """Push the current text panel contents into history before a reset.

        Called by reset_ui() at the start of every new recording so no work is lost.
        """
        if not hasattr(self, 'fast_output_text'):
            return
        fast = self.fast_output_text.get(1.0, tk.END).strip()
        accurate = self.accurate_output_text.get(1.0, tk.END).strip()
        if not fast and not accurate:
            return

        self.slot_history.insert(0, {
            'fast': fast,
            'accurate': accurate,
            'timestamp': datetime.now().strftime("%H:%M:%S")
        })
        # Keep at most 7 history entries
        if len(self.slot_history) > 7:
            self.slot_history = self.slot_history[:7]

        self._update_slot_buttons()

    def _switch_slot(self, slot: int):
        """Display the text for the given slot in the transcription panels."""
        self.active_slot = slot
        self._update_slot_buttons()

        if slot == 0:
            fast = self.accumulated_fast_text
            accurate = self.accumulated_accurate_text
        else:
            idx = slot - 1
            if idx < len(self.slot_history):
                fast = self.slot_history[idx]['fast']
                accurate = self.slot_history[idx]['accurate']
            else:
                fast = accurate = ""

        self.fast_output_text.delete(1.0, tk.END)
        self.fast_output_text.insert(tk.END, fast)
        self.accurate_output_text.delete(1.0, tk.END)
        self.accurate_output_text.insert(tk.END, accurate)

    def _update_slot_buttons(self):
        """Refresh button appearance to reflect active slot and which slots have content."""
        if not hasattr(self, 'slot_buttons'):
            return
        colors = self.theme.current

        for i, btn in enumerate(self.slot_buttons):
            is_active = (i == self.active_slot)
            has_content = (i == 0) or (i - 1 < len(self.slot_history))

            if is_active:
                btn.configure(relief=tk.SUNKEN, bg=colors.accent_action,
                              fg=colors.fg_primary, activebackground=colors.accent_action_active)
            elif has_content:
                btn.configure(relief=tk.RAISED, bg=colors.bg_button_normal,
                              fg=colors.fg_primary, activebackground=colors.bg_button_active)
            else:
                btn.configure(relief=tk.FLAT, bg=colors.bg_tertiary,
                              fg=colors.fg_disabled, activebackground=colors.bg_tertiary)



    def _create_transcription_section(self, title: str, copy_callback: Callable):
        """Create a transcription section with header, progress, and text area"""
        colors = self.theme.current
        frame = tk.Frame(self.paned_window, bg=colors.bg_primary)

        # Header with copy button
        header_frame = tk.Frame(frame, bg=colors.bg_primary)
        header_frame.pack(fill=tk.X, pady=(5, 5))

        label = tk.Label(
            header_frame,
            text=title,
            bg=colors.bg_primary,
            fg=colors.fg_primary,
            font=("Arial", 10, "bold"),
            anchor="w"
        )
        label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        copy_button = tk.Button(
            header_frame,
            text="Copy to Clipboard",
            bg=colors.accent_action,
            activebackground=colors.accent_action_active,
            fg=colors.fg_primary,
            activeforeground=colors.fg_primary,
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
            mode="indeterminate",
            style="Custom.Horizontal.TProgressbar"
        )
        progress.pack(fill=tk.X, pady=(0, 5))

        # Text area
        text_area = scrolledtext.ScrolledText(
            frame,
            wrap=tk.WORD,
            height=8,
            bg=colors.bg_secondary,
            fg=colors.fg_primary,
            font=("Arial", 11),
            insertbackground=colors.fg_primary,
            selectbackground=colors.text_select_bg,
            selectforeground=colors.text_select_fg
        )
        text_area.pack(fill=tk.BOTH, expand=True)

        # Status label
        status = tk.Label(
            frame,
            text="",
            bg=colors.bg_primary,
            fg=colors.fg_secondary,
            font=("Arial", 8, "italic"),
            anchor="w"
        )
        status.pack(fill=tk.X)

        # Store references
        if "Quick" in title:
            self.fast_progress = progress
            self.fast_output_text = text_area
            self.fast_status_label = status
            self.fast_copy_button = copy_button
        else:
            self.accurate_progress = progress
            self.accurate_output_text = text_area
            self.accurate_status_label = status
            self.accurate_copy_button = copy_button

        return frame

    def _get_transcription_stats(self, text: str) -> tuple[int, int]:
        """Calculate word count and paragraph count from accumulated text

        Returns:
            tuple: (word_count, paragraph_count)
        """
        if not text:
            return (0, 0)

        # Count words by splitting on whitespace
        word_count = len(text.split())

        # Count paragraphs as number of \n\n separators + 1
        paragraph_count = text.count("\n\n") + 1

        return (word_count, paragraph_count)

    def _update_latching_status(self):
        """Update status label with current word and paragraph counts"""
        word_count, para_count = self._get_transcription_stats(self.accumulated_fast_text)
        status_text = f"Word count: {word_count}   Paragraph count: {para_count}"
        self.queue_ui_update(self.status_label.config, text=status_text)

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

    def on_cancel_click(self):
        """Handle cancel button click"""
        if not self.processing.get():
            return

        self.logger.info("Cancel requested by user")

        # Set cancellation flag and timestamp
        self.cancel_processing.set(True)
        self.cancel_timestamp = time.time()

        # Update UI
        colors = self.theme.current
        self.status_label.config(text="Cancelling...")
        self.cancel_button.config(state=tk.DISABLED, fg=colors.fg_disabled)

        # If in latching mode, exit it
        if self.latching_recording.get():
            self.latching_recording.set(False)
            self.recorder.stop_recording()
            self.toggle_button.config(
                text="Start Latching Record",
                bg=colors.accent_record
            )
            self.press_hold_button.config(state=tk.NORMAL)
            self.parse_button.config(state=tk.DISABLED, fg=colors.fg_disabled)

    def _check_cancellation(self) -> bool:
        """Check if processing should be cancelled

        Returns:
            True if should cancel, False otherwise
        """
        return self.cancel_processing.get()

    def _reset_cancellation_state(self):
        """Reset cancellation state after processing completes"""
        self.cancel_processing.set(False)
        self.cancel_timestamp = None
        self.current_operation = None
        colors = self.theme.current
        self.queue_ui_update(self.cancel_button.config, state=tk.DISABLED, fg=colors.fg_disabled)

    def _start_processing(self):
        """Mark start of processing and enable cancel button"""
        self.processing.set(True)
        self.cancel_processing.set(False)
        self.cancel_timestamp = None
        colors = self.theme.current
        self.queue_ui_update(self.cancel_button.config, state=tk.NORMAL, fg=colors.fg_primary)

    def _end_processing(self):
        """Mark end of processing and disable cancel button"""
        self.processing.set(False)
        self._reset_cancellation_state()

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
            colors = self.theme.current
            self.press_hold_button.config(
                text="Recording... Release to Stop",
                bg=colors.accent_record_active
            )
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

        colors = self.theme.current
        if not frames:
            self.status_label.config(text="No audio recorded")
            self.press_hold_button.config(
                text="Press and Hold to Record",
                bg=colors.accent_record
            )
            return

        # Update UI
        self._start_processing()
        self.press_hold_button.config(
            text="Press and Hold to Record",
            bg=colors.accent_record
        )
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

        colors = self.theme.current
        if not self.latching_recording.get():
            # Start latching recording
            self.cancel_second_pass.set(True)
            time.sleep(0.1)

            if self.recorder.start_recording():
                self.latching_recording.set(True)
                self.last_transcribed_frame_index = 0
                self.accumulated_fast_text = ""
                self.accumulated_accurate_text = ""

                self.toggle_button.config(
                    text="Stop Recording",
                    bg=colors.accent_record_active
                )
                self.press_hold_button.config(state=tk.DISABLED)
                self.parse_button.config(state=tk.NORMAL, fg=colors.fg_primary)
                self._update_latching_status()
                self.reset_ui()
        else:
            # Stop latching recording and process final segment
            self.latching_recording.set(False)
            self.parse_button.config(state=tk.DISABLED, fg=colors.fg_disabled)
            self.toggle_button.config(
                text="Start Latching Record",
                bg=colors.accent_record
            )
            self.press_hold_button.config(state=tk.NORMAL)

            # Stop recording
            frames = self.recorder.stop_recording()

            if frames:
                # Process final unparsed segment
                self._start_processing()
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
        self._start_processing()
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
            if self._check_cancellation():
                self.logger.info(f"Transcription cancelled before attempt {attempt + 1}")
                return None

            try:
                with self.suppress_subprocess_window():
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
        operation_start_time = time.time()

        try:
            # Check for cancellation before starting
            if self._check_cancellation():
                self.logger.info("Incremental transcription cancelled before start")
                self._handle_cancellation()
                return

            # Create temp file for this segment
            fd, temp_file = tempfile.mkstemp(suffix='.wav', dir=self.config.temp_dir)
            os.close(fd)

            # Save segment to file
            if not self.recorder.save_to_file(frames_segment, temp_file):
                raise Exception("Failed to save audio segment")

            # Fast transcription with retry
            self.current_operation = "fast"
            self.queue_ui_update(self.fast_status_label.config, text="Transcribing...")

            fast_text = self.transcribe_with_retry(
                self.transcriber.transcribe_fast,
                temp_file
            )

            # Check if cancelled during transcription
            if self._check_cancellation() or fast_text is None:
                self.logger.info("Incremental transcription cancelled after fast pass")
                self._handle_cancellation()
                return

            # Strip whitespace and append to accumulated text
            fast_text = fast_text.strip()
            if self.accumulated_fast_text:
                self.accumulated_fast_text += "\n\n"
            self.accumulated_fast_text += fast_text

            self.queue_ui_update(self.fast_progress.stop)
            self.queue_ui_update(self.fast_status_label.config, text="Complete!")
            self.queue_ui_update(self.fast_output_text.delete, 1.0, tk.END)
            self.queue_ui_update(self.fast_output_text.insert, tk.END, self.accumulated_fast_text)

            # Update status with word/paragraph counts
            self._update_latching_status()

            # Check cancellation before accurate transcription
            if self._check_cancellation():
                self.logger.info("Incremental transcription cancelled before accurate pass")
                self._handle_cancellation()
                return

            # Accurate transcription with retry
            self.current_operation = "accurate"
            self.queue_ui_update(self.accurate_status_label.config, text="Processing...")

            accurate_text = self.transcribe_with_retry(
                self.transcriber.transcribe_accurate,
                temp_file
            )

            # Check if cancelled during transcription
            if self._check_cancellation() or accurate_text is None:
                self.logger.info("Incremental transcription cancelled after accurate pass")
                self._handle_cancellation()
                return

            # Strip whitespace and append to accumulated text
            accurate_text = accurate_text.strip()
            if self.accumulated_accurate_text:
                self.accumulated_accurate_text += "\n\n"
            self.accumulated_accurate_text += accurate_text

            self.queue_ui_update(self.accurate_progress.stop)
            self.queue_ui_update(self.accurate_status_label.config, text="Complete!")
            self.queue_ui_update(self.accurate_output_text.delete, 1.0, tk.END)
            self.queue_ui_update(self.accurate_output_text.insert, tk.END, self.accumulated_accurate_text)

        except Exception as e:
            self.logger.error(f"Error in incremental transcription: {e}")
            self.queue_ui_update(self.status_label.config, text=f"Parse error: {str(e)}")
            self.queue_ui_update(self.fast_progress.stop)
            self.queue_ui_update(self.accurate_progress.stop)
        finally:
            self._end_processing()
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception as e:
                    self.logger.error(f"Error removing temp file: {e}")

    def process_final_segment(self, frames: list):
        """Process final unparsed segment when stopping latching recording"""
        temp_file = None

        try:
            # Check for cancellation before starting
            if self._check_cancellation():
                self.logger.info("Final segment processing cancelled before start")
                self._handle_cancellation()
                return

            # Get only unparsed frames
            unparsed_frames = frames[self.last_transcribed_frame_index:]

            if not unparsed_frames:
                # No new frames, show final status with counts if available
                if self.accumulated_fast_text:
                    word_count, para_count = self._get_transcription_stats(self.accumulated_fast_text)
                    final_status = f"Ready  (Word count: {word_count}   Paragraph count: {para_count - 1})"
                else:
                    final_status = "Ready"
                self.queue_ui_update(self.status_label.config, text=final_status)
                self._end_processing()
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
            self.current_operation = "fast"
            self.queue_ui_update(self.fast_status_label.config, text="Transcribing final segment...")

            fast_text = self.transcribe_with_retry(
                self.transcriber.transcribe_fast,
                temp_file
            )

            # Check if cancelled during transcription
            if self._check_cancellation() or fast_text is None:
                self.logger.info("Final segment cancelled after fast pass")
                self._handle_cancellation()
                return

            # Strip whitespace and append to accumulated text
            fast_text = fast_text.strip()
            if self.accumulated_fast_text:
                self.accumulated_fast_text += "\n\n"
            self.accumulated_fast_text += fast_text

            self.queue_ui_update(self.fast_progress.stop)
            self.queue_ui_update(self.fast_status_label.config, text="Complete!")
            self.queue_ui_update(self.fast_output_text.delete, 1.0, tk.END)
            self.queue_ui_update(self.fast_output_text.insert, tk.END, self.accumulated_fast_text)

            # Check cancellation before accurate transcription
            if self._check_cancellation():
                self.logger.info("Final segment cancelled before accurate pass")
                self._handle_cancellation()
                return

            # Accurate transcription with retry
            self.current_operation = "accurate"
            self.queue_ui_update(self.accurate_status_label.config, text="Processing final segment...")

            accurate_text = self.transcribe_with_retry(
                self.transcriber.transcribe_accurate,
                temp_file
            )

            # Check if cancelled during transcription
            if self._check_cancellation() or accurate_text is None:
                self.logger.info("Final segment cancelled after accurate pass")
                self._handle_cancellation()
                return

            # Strip whitespace and append to accumulated text
            accurate_text = accurate_text.strip()
            if self.accumulated_accurate_text:
                self.accumulated_accurate_text += "\n\n"
            self.accumulated_accurate_text += accurate_text

            self.queue_ui_update(self.accurate_progress.stop)
            self.queue_ui_update(self.accurate_status_label.config, text="Complete!")
            self.queue_ui_update(self.accurate_output_text.delete, 1.0, tk.END)
            self.queue_ui_update(self.accurate_output_text.insert, tk.END, self.accumulated_accurate_text)

            # Show counts in final status if we have accumulated text
            if self.accumulated_fast_text:
                word_count, para_count = self._get_transcription_stats(self.accumulated_fast_text)
                final_status = f"Ready  (Word count: {word_count}   Paragraph count: {para_count - 1})"
            else:
                final_status = "Ready"
            self.queue_ui_update(self.status_label.config, text=final_status)

        except Exception as e:
            self.logger.error(f"Error processing final segment: {e}")
            self.queue_ui_update(self.status_label.config, text=f"Error: {str(e)}")
            self.queue_ui_update(self.fast_progress.stop)
            self.queue_ui_update(self.accurate_progress.stop)
        finally:
            self._end_processing()
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception as e:
                    self.logger.error(f"Error removing temp file: {e}")

    def _handle_cancellation(self):
        """Handle cleanup after cancellation"""
        self.queue_ui_update(self.fast_progress.stop)
        self.queue_ui_update(self.accurate_progress.stop)

        # Show word/paragraph count if we have accumulated text
        if self.accumulated_fast_text:
            word_count, para_count = self._get_transcription_stats(self.accumulated_fast_text)
            final_status = f"Cancelled  (Word count: {word_count}   Paragraph count: {para_count})"
        else:
            final_status = "Cancelled"

        self.queue_ui_update(self.status_label.config, text=final_status)

    def process_audio(self, frames: list):
        """Process recorded audio with two-pass transcription"""
        try:
            # Check for cancellation before starting
            if self._check_cancellation():
                self.logger.info("Audio processing cancelled before start")
                self._handle_cancellation()
                return

            # Create temp file
            fd, self.temp_file = tempfile.mkstemp(suffix='.wav', dir=self.config.temp_dir)
            os.close(fd)

            # Save audio
            if not self.recorder.save_to_file(frames, self.temp_file):
                raise Exception("Failed to save audio file")

            # Fast transcription
            self.current_operation = "fast"
            self.queue_ui_update(self.fast_status_label.config, text="Transcribing...")
            text = self.transcriber.transcribe_fast(self.temp_file)

            # Check if cancelled during transcription
            if self._check_cancellation():
                self.logger.info("Audio processing cancelled after fast pass")
                # Display the fast result we got before cancelling
                self.accumulated_fast_text = text
                self.queue_ui_update(self.fast_progress.stop)
                self.queue_ui_update(self.fast_status_label.config, text="Complete!")
                self.queue_ui_update(self.fast_output_text.delete, 1.0, tk.END)
                self.queue_ui_update(self.fast_output_text.insert, tk.END, text)
                self._handle_cancellation()
                return

            self.accumulated_fast_text = text
            self.queue_ui_update(self.fast_progress.stop)
            self.queue_ui_update(self.fast_status_label.config, text="Complete!")
            self.queue_ui_update(self.fast_output_text.delete, 1.0, tk.END)
            self.queue_ui_update(self.fast_output_text.insert, tk.END, text)

            # Accurate transcription (if not cancelled)
            self.cancel_second_pass.set(False)
            if not self.cancel_second_pass.get() and not self._check_cancellation():
                self.current_operation = "accurate"
                self.queue_ui_update(self.accurate_progress.start)
                self.queue_ui_update(self.accurate_status_label.config, text="Processing...")

                text = self.transcriber.transcribe_accurate(self.temp_file)

                # Check if cancelled during transcription
                if self._check_cancellation():
                    self.logger.info("Audio processing cancelled after accurate pass")
                    # Display the accurate result we got before cancelling
                    self.accumulated_accurate_text = text
                    self.queue_ui_update(self.accurate_progress.stop)
                    self.queue_ui_update(self.accurate_status_label.config, text="Complete!")
                    self.queue_ui_update(self.accurate_output_text.delete, 1.0, tk.END)
                    self.queue_ui_update(self.accurate_output_text.insert, tk.END, text)
                    self._handle_cancellation()
                    return

                if not self.cancel_second_pass.get():
                    self.accumulated_accurate_text = text
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
            self._end_processing()
            self.cleanup_temp_file()
            if not self._check_cancellation():
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
        # Save current content to history before clearing, so no work is lost
        self._save_to_history()
        self.accumulated_fast_text = ""
        self.accumulated_accurate_text = ""
        self.active_slot = 0
        self._update_slot_buttons()

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

    def copy_datetime_to_clipboard(self):
        """Copy current datetime in ISO format to clipboard"""
        try:
            iso_datetime = datetime.now().strftime("%Y %B %d, %A at %I:%M %p")
            pyperclip.copy(iso_datetime)
            self.status_label.config(text=f"Datetime copied: {iso_datetime}")
        except Exception as e:
            self.logger.error(f"Error copying datetime: {e}")
            self.status_label.config(text=f"Error copying datetime: {str(e)}")

    def _copy_to_clipboard(self, text_widget, status_label, prefix):
        """Helper to copy text to clipboard"""
        text = text_widget.get(1.0, tk.END).strip()
        if text:
            try:
                pyperclip.copy(text)
                slot_hint = f" (slot {self.active_slot})" if self.active_slot > 0 else ""
                status_label.config(text=f"{prefix} transcription{slot_hint} copied!")
            except Exception as e:
                self.logger.error(f"Copy error: {e}")
                status_label.config(text=f"Copy error: {str(e)}")
        else:
            status_label.config(text="No text to copy!")

    def on_closing(self):
        """Clean up on window close"""
        self.logger.info("Shutting down...")
        self.cancel_second_pass.set(True)
        self.cancel_processing.set(True)
        self.latching_recording.set(False)
        self.recorder.cleanup()
        self.cleanup_temp_file()
        self.root.destroy()