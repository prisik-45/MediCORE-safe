"""Interfaces for extraction pipeline modules."""

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from backend.app.pipeline.normalization.schema import ExtractedBlock


@runtime_checkable
class BaseLoader(Protocol):
    """Rule: Only modules inside ingestion/ may open raw files."""

    def load(self, file_path: Path) -> Any:
        ...


@runtime_checkable
class BaseClassifier(Protocol):
    """Classifies document pages."""

    def classify_page(self, page_obj: Any) -> str:
        ...


@runtime_checkable
class BaseExtractor(Protocol):
    """Rule: Only modules inside extraction/ may call OCR or table engines."""

    def extract(self, page_obj: Any, **kwargs: Any) -> list[ExtractedBlock]:
        ...
