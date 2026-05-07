# core/scripts/sd_transcriber_app.py
import tkinter as tk
import threading
import shutil
import logging
from datetime import datetime
from pathlib import Path
from queue import Queue
from tkinter import ttk, scrolledtext, filedialog
from typing import Optional

from config import Config
from core.adapters.audio_recorder import SafeFlag
from core.adapters.batch_transcriber import BatchTranscriber
from core.adapters.sd_card_locator import SDCardLocator
from core.adapters.transcript_writer import TranscriptWriter
from core.scripts.theme import Theme


class SDTranscriberApp:
    """GUI for batch-transcribing audio files from an SD card."""

    def __init__(self, root: tk.Tk, config: Config):
        self.root = root
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)

        self.theme = Theme(config.default_theme)
        self.theme.register_callback(self.apply_theme)

        self.locator = SDCardLocator(config.sd_card_label, config.sd_source_subpath)
        self.transcriber = BatchTranscriber(config)

        self.processing = SafeFlag()
        self.cancel_flag = SafeFlag()
        self.source_path: Optional[Path] = None

        self.ui_queue = Queue()

        self.setup_window()
        self.create_menu_bar()
        self.create_widgets()
        self.apply_theme()

        self.root.after(100, self.process_ui_queue)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Auto-detect on startup
        self.root.after(200, self.detect_sd_card)

    def setup_window(self):
        self.root.title("SD Card Transcriber")
        self.root.geometry("700x750")
        self.root.configure(padx=20, pady=20)

    def create_menu_bar(self):
        colors = self.theme.current
        menubar = tk.Menu(
            self.root,
            bg=colors.menubar_bg,
            fg=colors.menubar_fg,
            activebackground=colors.bg_button_active,
            activeforeground=colors.fg_primary
        )
        self.root.config(menu=menubar)

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

        self.theme_var = tk.StringVar(value=self.theme.current_name)
        theme_menu.add_radiobutton(
            label="Light", variable=self.theme_var, value="light",
            command=lambda: self.change_theme("light")
        )
        theme_menu.add_radiobutton(
            label="Dark", variable=self.theme_var, value="dark",
            command=lambda: self.change_theme("dark")
        )

    def change_theme(self, theme_name: str):
        self.theme.set_theme(theme_name)
        self.theme_var.set(theme_name)

    def create_widgets(self):
        colors = self.theme.current

        # SD status row
        status_row = tk.Frame(self.root, bg=colors.bg_primary)
        status_row.pack(fill=tk.X, pady=(0, 10))

        self.sd_status_label = tk.Label(
            status_row,
            text="SD card: not detected",
            bg=colors.bg_primary,
            fg=colors.fg_primary,
            font=("Arial", 10, "bold"),
            anchor="w"
        )
        self.sd_status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.detect_button = tk.Button(
            status_row,
            text="Detect SD Card",
            bg=colors.accent_utility,
            activebackground=colors.accent_utility_active,
            fg=colors.fg_primary,
            activeforeground=colors.fg_primary,
            font=("Arial", 9),
            command=self.detect_sd_card
        )
        self.detect_button.pack(side=tk.RIGHT)

        # Source path row
        source_row = tk.Frame(self.root, bg=colors.bg_primary)
        source_row.pack(fill=tk.X, pady=(0, 5))

        tk.Label(
            source_row, text="Source:", bg=colors.bg_primary, fg=colors.fg_primary,
            font=("Arial", 9), width=10, anchor="w"
        ).pack(side=tk.LEFT)

        self.source_var = tk.StringVar()
        self.source_entry = tk.Entry(
            source_row,
            textvariable=self.source_var,
            bg=colors.bg_secondary,
            fg=colors.fg_primary,
            insertbackground=colors.fg_primary,
            font=("Arial", 9)
        )
        self.source_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        self.browse_source_button = tk.Button(
            source_row,
            text="Browse...",
            bg=colors.accent_action,
            activebackground=colors.accent_action_active,
            fg=colors.fg_primary,
            activeforeground=colors.fg_primary,
            font=("Arial", 9),
            command=self.browse_source
        )
        self.browse_source_button.pack(side=tk.RIGHT)

        # Destination paths (read-only display)
        dest_frame = tk.Frame(self.root, bg=colors.bg_primary)
        dest_frame.pack(fill=tk.X, pady=(0, 10))

        recordings_abs = Path(self.config.recordings_dir).resolve()
        transcripts_abs = Path(self.config.transcripts_dir).resolve()

        self.recordings_label = tk.Label(
            dest_frame,
            text=f"Recordings → {recordings_abs}",
            bg=colors.bg_primary, fg=colors.fg_secondary,
            font=("Arial", 8), anchor="w"
        )
        self.recordings_label.pack(fill=tk.X)

        self.transcripts_label = tk.Label(
            dest_frame,
            text=f"Transcripts → {transcripts_abs}",
            bg=colors.bg_primary, fg=colors.fg_secondary,
            font=("Arial", 8), anchor="w"
        )
        self.transcripts_label.pack(fill=tk.X)

        # File preview
        self.files_label = tk.Label(
            self.root,
            text="No files found.",
            bg=colors.bg_primary, fg=colors.fg_primary,
            font=("Arial", 10), anchor="w"
        )
        self.files_label.pack(fill=tk.X, pady=(5, 5))

        # Action buttons
        action_row = tk.Frame(self.root, bg=colors.bg_primary)
        action_row.pack(fill=tk.X, pady=(5, 10))

        self.start_button = tk.Button(
            action_row,
            text="Start Batch",
            bg=colors.accent_utility,
            activebackground=colors.accent_utility_active,
            fg=colors.fg_primary,
            activeforeground=colors.fg_primary,
            disabledforeground=colors.fg_disabled,
            font=("Arial", 11, "bold"),
            height=2,
            state=tk.DISABLED,
            command=self.on_start_click
        )
        self.start_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))

        self.cancel_button = tk.Button(
            action_row,
            text="Cancel",
            bg=colors.accent_record,
            activebackground=colors.accent_record_active,
            fg=colors.fg_primary,
            activeforeground=colors.fg_primary,
            disabledforeground=colors.fg_disabled,
            font=("Arial", 11),
            height=2,
            state=tk.DISABLED,
            command=self.on_cancel_click
        )
        self.cancel_button.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(2, 0))

        # Per-file status + progress
        self.file_status_label = tk.Label(
            self.root, text="", bg=colors.bg_primary, fg=colors.fg_primary,
            font=("Arial", 9), anchor="w"
        )
        self.file_status_label.pack(fill=tk.X, pady=(5, 0))

        self.file_progress = ttk.Progressbar(
            self.root, orient="horizontal", mode="indeterminate",
            style="Custom.Horizontal.TProgressbar"
        )
        self.file_progress.pack(fill=tk.X, pady=(2, 5))

        # Overall status + progress
        self.overall_status_label = tk.Label(
            self.root, text="", bg=colors.bg_primary, fg=colors.fg_primary,
            font=("Arial", 9, "bold"), anchor="w"
        )
        self.overall_status_label.pack(fill=tk.X, pady=(5, 0))

        self.overall_progress = ttk.Progressbar(
            self.root, orient="horizontal", mode="determinate",
            style="Custom.Horizontal.TProgressbar"
        )
        self.overall_progress.pack(fill=tk.X, pady=(2, 10))

        # Log area
        tk.Label(
            self.root, text="Log:", bg=colors.bg_primary, fg=colors.fg_primary,
            font=("Arial", 9, "bold"), anchor="w"
        ).pack(fill=tk.X)

        self.log_text = scrolledtext.ScrolledText(
            self.root, wrap=tk.WORD, height=12,
            bg=colors.bg_secondary, fg=colors.fg_primary,
            font=("Consolas", 9),
            insertbackground=colors.fg_primary,
            selectbackground=colors.text_select_bg,
            selectforeground=colors.text_select_fg
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def apply_theme(self):
        colors = self.theme.current
        self.root.configure(bg=colors.bg_primary)
        self.theme.configure_ttk_styles(self.root)

        try:
            menubar = self.root.nametowidget(self.root['menu'])
            menubar.configure(
                bg=colors.menubar_bg, fg=colors.menubar_fg,
                activebackground=colors.bg_button_active,
                activeforeground=colors.fg_primary
            )
            theme_menu = menubar.nametowidget(menubar.entrycget(0, 'menu'))
            theme_menu.configure(
                bg=colors.menubar_bg, fg=colors.menubar_fg,
                activebackground=colors.accent_action,
                activeforeground=colors.fg_primary,
                selectcolor=colors.accent_action
            )
        except Exception as e:
            self.logger.debug(f"Could not style menu bar: {e}")

        if not hasattr(self, 'start_button'):
            return

        # Recurse through frames and apply backgrounds
        for child in self.root.winfo_children():
            if isinstance(child, tk.Frame):
                child.configure(bg=colors.bg_primary)
                for sub in child.winfo_children():
                    if isinstance(sub, tk.Frame):
                        sub.configure(bg=colors.bg_primary)

        # Labels with primary fg
        for lbl in (self.sd_status_label, self.files_label, self.file_status_label,
                    self.overall_status_label):
            lbl.configure(bg=colors.bg_primary, fg=colors.fg_primary)

        # Labels with secondary fg
        for lbl in (self.recordings_label, self.transcripts_label):
            lbl.configure(bg=colors.bg_primary, fg=colors.fg_secondary)

        # Buttons
        self.detect_button.configure(
            bg=colors.accent_utility, activebackground=colors.accent_utility_active,
            fg=colors.fg_primary, activeforeground=colors.fg_primary
        )
        self.browse_source_button.configure(
            bg=colors.accent_action, activebackground=colors.accent_action_active,
            fg=colors.fg_primary, activeforeground=colors.fg_primary
        )
        self._theme_button(self.start_button, colors.accent_utility, colors.accent_utility_active)
        self._theme_button(self.cancel_button, colors.accent_record, colors.accent_record_active)

        # Entry
        self.source_entry.configure(
            bg=colors.bg_secondary, fg=colors.fg_primary,
            insertbackground=colors.fg_primary
        )

        # Log area
        self.log_text.configure(
            bg=colors.bg_secondary, fg=colors.fg_primary,
            insertbackground=colors.fg_primary,
            selectbackground=colors.text_select_bg,
            selectforeground=colors.text_select_fg
        )

    def _theme_button(self, button, bg, active_bg):
        """Apply colors to a button, working around the disabled state."""
        colors = self.theme.current
        was_disabled = str(button['state']) == 'disabled'
        if was_disabled:
            button.configure(state=tk.NORMAL)
        button.configure(
            bg=bg, activebackground=active_bg,
            fg=colors.fg_primary, activeforeground=colors.fg_primary,
            disabledforeground=colors.fg_disabled
        )
        if was_disabled:
            button.configure(state=tk.DISABLED)

    # ------------- UI queue plumbing -------------

    def process_ui_queue(self):
        try:
            while not self.ui_queue.empty():
                func, args, kwargs = self.ui_queue.get_nowait()
                func(*args, **kwargs)
        except Exception as e:
            self.logger.error(f"Error processing UI queue: {e}")
        finally:
            self.root.after(100, self.process_ui_queue)

    def queue_ui_update(self, func, *args, **kwargs):
        self.ui_queue.put((func, args, kwargs))

    def log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}\n"
        self.queue_ui_update(self._append_log, line)
        self.logger.info(message)

    def _append_log(self, line: str):
        self.log_text.insert(tk.END, line)
        self.log_text.see(tk.END)

    # ------------- Detection / browsing -------------

    def detect_sd_card(self):
        if self.processing.get():
            return
        self.log(f"Detecting SD card '{self.config.sd_card_label}'...")
        path = self.locator.find_source_path()
        if path:
            self.source_var.set(str(path))
            self.sd_status_label.config(text=f"SD card: detected at {path}")
            self.log(f"SD card detected at {path}")
        else:
            self.sd_status_label.config(text="SD card: not detected (use Browse...)")
            self.log("SD card not detected")
        self.refresh_file_preview()

    def browse_source(self):
        if self.processing.get():
            return
        initial = self.source_var.get() or str(Path.home())
        chosen = filedialog.askdirectory(
            title="Select source folder containing audio files",
            initialdir=initial
        )
        if chosen:
            self.source_var.set(chosen)
            self.refresh_file_preview()

    def refresh_file_preview(self):
        source_str = self.source_var.get().strip()
        if not source_str:
            self.files_label.config(text="No source selected.")
            self.start_button.config(state=tk.DISABLED)
            return

        source = Path(source_str)
        if not source.is_dir():
            self.files_label.config(text="Source folder does not exist.")
            self.start_button.config(state=tk.DISABLED)
            return

        files = self.locator.list_audio_files(source)
        if not files:
            self.files_label.config(text="No audio files found in source folder.")
            self.start_button.config(state=tk.DISABLED)
            return

        names = [f.name for f in files]
        if len(names) <= 4:
            preview = ", ".join(names)
        else:
            preview = f"{names[0]} … {names[-1]}"
        self.files_label.config(text=f"Found {len(files)} file(s): {preview}")
        self.start_button.config(state=tk.NORMAL)

    # ------------- Batch processing -------------

    def on_start_click(self):
        source_str = self.source_var.get().strip()
        if not source_str:
            return
        source = Path(source_str)
        if not source.is_dir():
            self.log(f"Source folder does not exist: {source}")
            return

        files = self.locator.list_audio_files(source)
        if not files:
            self.log("No audio files to process.")
            return

        # We only delete from SD card if the source is the auto-detected SD path.
        # If the user manually selected a folder via Browse, we leave the originals.
        is_sd_source = self._is_sd_source(source)

        self.processing.set(True)
        self.cancel_flag.set(False)
        self._set_controls_processing(True)

        thread = threading.Thread(
            target=self.run_batch,
            args=(source, files, is_sd_source),
            daemon=True
        )
        thread.start()

    def on_cancel_click(self):
        if not self.processing.get():
            return
        self.log("Cancellation requested. Will stop after current file.")
        self.cancel_flag.set(True)
        self.queue_ui_update(self.cancel_button.config, state=tk.DISABLED)

    def _is_sd_source(self, source: Path) -> bool:
        """Check whether the selected source is the auto-detected SD path."""
        sd_path = self.locator.find_source_path()
        if sd_path is None:
            return False
        try:
            return source.resolve() == sd_path.resolve()
        except Exception:
            return False

    def _set_controls_processing(self, is_processing: bool):
        if is_processing:
            self.queue_ui_update(self.start_button.config, state=tk.DISABLED)
            self.queue_ui_update(self.cancel_button.config, state=tk.NORMAL)
            self.queue_ui_update(self.detect_button.config, state=tk.DISABLED)
            self.queue_ui_update(self.browse_source_button.config, state=tk.DISABLED)
            self.queue_ui_update(self.source_entry.config, state=tk.DISABLED)
        else:
            self.queue_ui_update(self.start_button.config, state=tk.NORMAL)
            self.queue_ui_update(self.cancel_button.config, state=tk.DISABLED)
            self.queue_ui_update(self.detect_button.config, state=tk.NORMAL)
            self.queue_ui_update(self.browse_source_button.config, state=tk.NORMAL)
            self.queue_ui_update(self.source_entry.config, state=tk.NORMAL)

    def run_batch(self, source: Path, files: list[Path], is_sd_source: bool):
        """Batch flow: copy all → fast pass all → accurate pass all → delete originals."""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")

            recordings_dir = Path(self.config.recordings_dir) / timestamp
            transcripts_dir = Path(self.config.transcripts_dir)
            recordings_dir.mkdir(parents=True, exist_ok=True)
            transcripts_dir.mkdir(parents=True, exist_ok=True)

            fast_md = transcripts_dir / f"{timestamp}_fast.md"
            accurate_md = transcripts_dir / f"{timestamp}_accurate.md"

            fast_writer = TranscriptWriter(fast_md, timestamp)
            accurate_writer = TranscriptWriter(accurate_md, timestamp)
            fast_writer.initialize()
            accurate_writer.initialize()

            self.log(f"Batch started: {timestamp}")
            self.log(f"Recordings folder: {recordings_dir}")
            self.log(f"Fast transcript: {fast_md}")
            self.log(f"Accurate transcript: {accurate_md}")

            # ---------- Copy phase ----------
            copied: list[Path] = []
            self.queue_ui_update(self.overall_status_label.config, text="Copying files...")
            self.queue_ui_update(self.overall_progress.config,
                                 maximum=len(files), value=0, mode="determinate")

            for i, src_file in enumerate(files, start=1):
                if self.cancel_flag.get():
                    self.log("Cancelled during copy phase.")
                    break

                self.queue_ui_update(self.file_status_label.config,
                                     text=f"Copying {src_file.name} ({i}/{len(files)})")
                dst_file = recordings_dir / src_file.name
                try:
                    shutil.copy2(src_file, dst_file)
                    copied.append(dst_file)
                    self.log(f"Copied {src_file.name}")
                except Exception as e:
                    self.log(f"Failed to copy {src_file.name}: {e}")

                self.queue_ui_update(self.overall_progress.config, value=i)

            if self.cancel_flag.get():
                self._finalize_cancelled(copied, is_sd_source)
                return

            if not copied:
                self.log("No files were successfully copied. Aborting batch.")
                self._finalize_done()
                return

            # ---------- Fast pass ----------
            self.queue_ui_update(self.overall_status_label.config, text="Fast pass...")
            self.queue_ui_update(self.overall_progress.config,
                                 maximum=len(copied), value=0)
            self.queue_ui_update(self.file_progress.start)

            for i, audio in enumerate(copied, start=1):
                if self.cancel_flag.get():
                    self.log("Cancelled during fast pass.")
                    break
                self.queue_ui_update(self.file_status_label.config,
                                     text=f"Fast: {audio.name} ({i}/{len(copied)})")
                try:
                    text = self.transcriber.transcribe_fast(str(audio))
                    fast_writer.append_section(audio.name, text, audio_path=audio)
                    self.log(f"Fast pass done: {audio.name}")
                except Exception as e:
                    self.log(f"Fast pass failed on {audio.name}: {e}")
                    fast_writer.append_error(audio.name, str(e))
                self.queue_ui_update(self.overall_progress.config, value=i)

            self.queue_ui_update(self.file_progress.stop)

            if self.cancel_flag.get():
                self._finalize_cancelled(copied, is_sd_source)
                return

            # Free fast model memory before loading large-v3
            self.transcriber.unload_fast_model()

            # ---------- Accurate pass ----------
            self.queue_ui_update(self.overall_status_label.config, text="Accurate pass...")
            self.queue_ui_update(self.overall_progress.config,
                                 maximum=len(copied), value=0)
            self.queue_ui_update(self.file_progress.start)

            for i, audio in enumerate(copied, start=1):
                if self.cancel_flag.get():
                    self.log("Cancelled during accurate pass.")
                    break
                self.queue_ui_update(self.file_status_label.config,
                                     text=f"Accurate: {audio.name} ({i}/{len(copied)})")
                try:
                    text = self.transcriber.transcribe_accurate(str(audio))
                    accurate_writer.append_section(audio.name, text, audio_path=audio)
                    self.log(f"Accurate pass done: {audio.name}")
                except Exception as e:
                    self.log(f"Accurate pass failed on {audio.name}: {e}")
                    accurate_writer.append_error(audio.name, str(e))
                self.queue_ui_update(self.overall_progress.config, value=i)

            self.queue_ui_update(self.file_progress.stop)

            if self.cancel_flag.get():
                self._finalize_cancelled(copied, is_sd_source)
                return

            # ---------- Delete originals from SD ----------
            if is_sd_source:
                self.queue_ui_update(self.overall_status_label.config,
                                     text="Removing originals from SD card...")
                deleted = 0
                for src_file in files:
                    try:
                        src_file.unlink()
                        deleted += 1
                    except Exception as e:
                        self.log(f"Failed to delete {src_file.name} from SD: {e}")
                self.log(f"Deleted {deleted}/{len(files)} files from SD card")
            else:
                self.log("Source was not the auto-detected SD card; originals left in place.")

            self.queue_ui_update(self.overall_status_label.config, text="Batch complete.")
            self.queue_ui_update(self.file_status_label.config, text="Done.")
            self.log("Batch complete.")
            self._finalize_done()

        except Exception as e:
            self.logger.exception("Batch failed")
            self.log(f"Batch failed: {e}")
            self.queue_ui_update(self.overall_status_label.config, text=f"Error: {e}")
            self.queue_ui_update(self.file_progress.stop)
            self._finalize_done()

    def _finalize_cancelled(self, copied: list[Path], is_sd_source: bool):
        self.queue_ui_update(self.file_progress.stop)
        self.queue_ui_update(self.overall_status_label.config, text="Cancelled.")
        self.queue_ui_update(self.file_status_label.config, text="")
        self.log(f"Cancellation finalized. {len(copied)} file(s) copied locally; "
                 f"SD originals left intact.")
        self._finalize_done()

    def _finalize_done(self):
        self.processing.set(False)
        self._set_controls_processing(False)
        self.queue_ui_update(self.refresh_file_preview)

    def on_closing(self):
        self.cancel_flag.set(True)
        self.root.destroy()
