"""Safe ZIP archive handling with decompression bomb, path traversal, and quota guards.

Used for validating and extracting Office OpenXML containers (.docx, .xlsx) safely.
"""

import zipfile
from pathlib import Path
from typing import BinaryIO


class SafeZipBombError(ValueError):
    """Raised when an archive exceeds compression ratio or size limits."""
    pass


class SafeZipTraversalError(ValueError):
    """Raised when an archive contains path traversal sequences."""
    pass


# Default container quotas
MAX_ZIP_ENTRIES = 500
MAX_ZIP_SINGLE_UNCOMPRESSED_BYTES = 25 * 1024 * 1024  # 25 MB
MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES = 60 * 1024 * 1024   # 60 MB
MAX_ZIP_COMPRESSION_RATIO = 100.0                     # 100:1


def inspect_and_validate_zip(
    zip_source: str | Path | BinaryIO,
    *,
    max_entries: int = MAX_ZIP_ENTRIES,
    max_single_bytes: int = MAX_ZIP_SINGLE_UNCOMPRESSED_BYTES,
    max_total_bytes: int = MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES,
    max_ratio: float = MAX_ZIP_COMPRESSION_RATIO,
) -> None:
    """Inspect all zip archive entries and assert safety bounds before decompression."""
    with zipfile.ZipFile(zip_source, "r") as zf:
        infolist = zf.infolist()
        if len(infolist) > max_entries:
            raise SafeZipBombError(f"ZIP archive contains {len(infolist)} entries, exceeding limit of {max_entries}")

        total_uncompressed = 0
        total_compressed = 0

        for info in infolist:
            name = info.filename

            # Path traversal check
            if name.startswith("/") or name.startswith("\\") or ".." in name.replace("\\", "/").split("/"):
                raise SafeZipTraversalError(f"Prohibited path traversal in ZIP entry: '{name}'")

            # Check individual uncompressed size
            if info.file_size > max_single_bytes:
                raise SafeZipBombError(
                    f"ZIP entry '{name}' uncompressed size ({info.file_size} bytes) exceeds limit of {max_single_bytes} bytes"
                )

            total_uncompressed += info.file_size
            total_compressed += info.compress_size

            # Check individual entry ratio if compressed
            if info.compress_size > 0:
                entry_ratio = info.file_size / info.compress_size
                if entry_ratio > max_ratio and info.file_size > 1024 * 1024:
                    raise SafeZipBombError(
                        f"ZIP entry '{name}' compression ratio ({entry_ratio:.1f}:1) exceeds limit of {max_ratio}:1"
                    )

        # Check total cumulative uncompressed size
        if total_uncompressed > max_total_bytes:
            raise SafeZipBombError(
                f"Total uncompressed ZIP size ({total_uncompressed} bytes) exceeds limit of {max_total_bytes} bytes"
            )

        # Overall ratio check
        if total_compressed > 0 and total_uncompressed > 1024 * 1024:
            overall_ratio = total_uncompressed / total_compressed
            if overall_ratio > max_ratio:
                raise SafeZipBombError(
                    f"Overall ZIP compression ratio ({overall_ratio:.1f}:1) exceeds limit of {max_ratio}:1"
                )


class SafeZipFile(zipfile.ZipFile):
    """A safe wrapper around zipfile.ZipFile that performs automatic safety validation upon opening."""

    def __init__(self, *args, **kwargs):
        max_entries = kwargs.pop("max_entries", MAX_ZIP_ENTRIES)
        max_single_bytes = kwargs.pop("max_single_bytes", MAX_ZIP_SINGLE_UNCOMPRESSED_BYTES)
        max_total_bytes = kwargs.pop("max_total_bytes", MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES)
        max_ratio = kwargs.pop("max_ratio", MAX_ZIP_COMPRESSION_RATIO)
        
        super().__init__(*args, **kwargs)
        
        # Validate immediately
        infolist = self.infolist()
        if len(infolist) > max_entries:
            raise SafeZipBombError(f"ZIP archive contains {len(infolist)} entries, exceeding limit of {max_entries}")

        total_uncompressed = 0
        total_compressed = 0

        for info in infolist:
            name = info.filename
            if name.startswith("/") or name.startswith("\\") or ".." in name.replace("\\", "/").split("/"):
                raise SafeZipTraversalError(f"Prohibited path traversal in ZIP entry: '{name}'")

            if info.file_size > max_single_bytes:
                raise SafeZipBombError(
                    f"ZIP entry '{name}' uncompressed size ({info.file_size} bytes) exceeds limit of {max_single_bytes} bytes"
                )

            total_uncompressed += info.file_size
            total_compressed += info.compress_size

            if info.compress_size > 0:
                entry_ratio = info.file_size / info.compress_size
                if entry_ratio > max_ratio and info.file_size > 1024 * 1024:
                    raise SafeZipBombError(
                        f"ZIP entry '{name}' compression ratio ({entry_ratio:.1f}:1) exceeds limit of {max_ratio}:1"
                    )

        if total_uncompressed > max_total_bytes:
            raise SafeZipBombError(
                f"Total uncompressed ZIP size ({total_uncompressed} bytes) exceeds limit of {max_total_bytes} bytes"
            )
