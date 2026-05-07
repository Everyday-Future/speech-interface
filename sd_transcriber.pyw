import os
import sys

# Under pythonw.exe, sys.stdout/stderr are None, which breaks Whisper's tqdm
# progress bars ("'NoneType' object has no attribute 'write'"). Redirect to
# devnull BEFORE importing whisper or anything that uses logging.StreamHandler.
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

import time
import logging
import warnings
import tkinter as tk
from config import Config
from core.scripts.sd_transcriber_app import SDTranscriberApp

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
    logging.basicConfig(
        level=config.log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('sd_transcriber.log'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    warnings.filterwarnings("ignore", category=UserWarning)

    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logging.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_exception


def main():
    config = Config()
    setup_logging(config)
    logger = logging.getLogger("Main")

    try:
        root = tk.Tk()
        app = SDTranscriberApp(root, config)
        root.mainloop()
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        time.sleep(5)


if __name__ == "__main__":
    main()
