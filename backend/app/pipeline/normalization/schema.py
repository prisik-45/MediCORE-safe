"""Unified output schema for document extraction pipeline."""

from dataclasses import asdict, dataclass, field
from typing import Literal

BlockType = Literal["text", "table", "figure"]
EngineName = Literal["pymupdf", "rapidocr", "img2table", "mammoth", "openpyxl", "xlrd", "openrouter-vision"]
SourceType = Literal["pdf", "image", "docx", "xlsx"]


@dataclass
class ExtractedBlock:
    type: BlockType
    bbox: list[float]  # [x0, y0, x1, y1]
    content: str
    confidence: float
    engine: EngineName

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DocumentPageResult:
    page: int
    source: SourceType
    blocks: list[ExtractedBlock] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "page": self.page,
            "blocks": [block.to_dict() for block in self.blocks],
        }


@dataclass
class ExtractionResult:
    source: SourceType
    file_path: str
    pages: list[DocumentPageResult] = field(default_factory=list)

    def full_text(self) -> str:
        parts: list[str] = []
        for p in self.pages:
            page_text = "\n".join(b.content.strip() for b in p.blocks if b.content and b.content.strip())
            if page_text:
                parts.append(page_text)
        return "\n\n".join(parts)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "file_path": self.file_path,
            "pages": [p.to_dict() for p in self.pages],
        }
