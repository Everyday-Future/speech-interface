import os
import sys
import time
import logging
import warnings
import tkinter as tk
from config import Config
from core.adapters.audio_recorder import AudioRecorder
from core.scripts.speech_to_text_app import SpeechToTextApp

# Hide console window on Windows
if os.name == 'nt':
    try:
        import ctypes

        console_window = ctypes.windll.kernel32.GetConsoleWindow()
        if console_window != 0:
            ctypes.windll.user32.ShowWindow(console_window, 0)
    except Exception:
        pass


def setup_logging(config: Config):
    """Configure logging"""
    logging.basicConfig(
        level=config.log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(config.log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )

    # Suppress warnings
    warnings.filterwarnings("ignore", category=UserWarning)

    # Global exception handler
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logging.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_exception


def main():
    """Main entry point"""
    # Create configuration
    config = Config()

    # Setup logging
    setup_logging(config)
    logger = logging.getLogger("Main")

    try:
        # Log audio devices
        AudioRecorder.log_audio_devices()

        # Create and run application
        root = tk.Tk()
        app = SpeechToTextApp(root, config)
        root.mainloop()

    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        time.sleep(5)


if __name__ == "__main__":
    main()