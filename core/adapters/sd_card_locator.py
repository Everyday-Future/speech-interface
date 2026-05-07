# core/adapters/sd_card_locator.py
import os
import sys
import string
import logging
from pathlib import Path
from typing import Optional


class SDCardLocator:
    """Locates an SD card by its volume label and lists audio files on it."""

    AUDIO_EXTENSIONS = {'.wav', '.mp3'}

    def __init__(self, label: str, source_subpath: str):
        self.label = label
        self.source_subpath = source_subpath
        self.logger = logging.getLogger(self.__class__.__name__)

    def find_source_path(self) -> Optional[Path]:
        """Find the full source path on a mounted volume matching the label.

        Returns the Path to <mount>/<source_subpath> if the volume is found
        and the subpath exists, else None.
        """
        mount = self._find_mount_by_label(self.label)
        if mount is None:
            self.logger.info(f"Volume '{self.label}' not detected")
            return None

        source = mount / self.source_subpath
        if not source.exists():
            self.logger.warning(f"Volume '{self.label}' found at {mount}, but {source} does not exist")
            return None

        self.logger.info(f"Source path found: {source}")
        return source

    def _find_mount_by_label(self, label: str) -> Optional[Path]:
        """Find a mounted volume by its label. Cross-platform (Windows/Linux)."""
        if sys.platform == 'win32':
            return self._find_mount_windows(label)
        elif sys.platform.startswith('linux'):
            return self._find_mount_linux(label)
        else:
            self.logger.warning(f"Volume label detection not supported on {sys.platform}")
            return None

    def _find_mount_windows(self, label: str) -> Optional[Path]:
        """Enumerate Windows drive letters and check volume labels."""
        import ctypes

        kernel32 = ctypes.windll.kernel32
        volume_name_buf = ctypes.create_unicode_buffer(1024)
        fs_name_buf = ctypes.create_unicode_buffer(1024)

        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if not os.path.exists(drive):
                continue

            try:
                result = kernel32.GetVolumeInformationW(
                    ctypes.c_wchar_p(drive),
                    volume_name_buf,
                    ctypes.sizeof(volume_name_buf),
                    None, None, None,
                    fs_name_buf,
                    ctypes.sizeof(fs_name_buf)
                )
                if result and volume_name_buf.value == label:
                    return Path(drive)
            except Exception as e:
                self.logger.debug(f"Could not read volume info for {drive}: {e}")

        return None

    def _find_mount_linux(self, label: str) -> Optional[Path]:
        """Check common Linux mount points for a matching label.

        Looks under /media/<user>/<label>, /media/<label>, /run/media/<user>/<label>,
        and /mnt/<label>.
        """
        user = os.environ.get('USER', '')
        candidates = [
            Path(f"/media/{user}/{label}") if user else None,
            Path(f"/run/media/{user}/{label}") if user else None,
            Path(f"/media/{label}"),
            Path(f"/mnt/{label}"),
        ]

        for path in candidates:
            if path and path.is_dir():
                return path

        # Fallback: scan /media and /run/media subdirectories for a directory matching the label
        scan_roots = [Path("/media"), Path("/run/media")]
        for root in scan_roots:
            if not root.is_dir():
                continue
            try:
                for child in root.iterdir():
                    if not child.is_dir():
                        continue
                    # Direct match: /media/<label>
                    if child.name == label:
                        return child
                    # Per-user match: /media/<user>/<label>
                    try:
                        for sub in child.iterdir():
                            if sub.is_dir() and sub.name == label:
                                return sub
                    except PermissionError:
                        continue
            except PermissionError:
                continue

        return None

    def list_audio_files(self, source_path: Path) -> list[Path]:
        """List audio files in source_path, sorted by name."""
        if not source_path.is_dir():
            return []

        files = [
            p for p in source_path.iterdir()
            if p.is_file() and p.suffix.lower() in self.AUDIO_EXTENSIONS
        ]
        files.sort(key=lambda p: p.name.lower())
        return files
