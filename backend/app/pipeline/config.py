"""Configuration for document extraction pipeline engines and parameters."""

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class PipelineConfig:
    # Target DPI for PDF page rendering (Phase 3 requirement: 300-400 DPI)
    target_dpi: int = 300
    min_image_dpi_upscale: int = 200
    max_image_dpi_downsample: int = 400

    # Image tiling threshold (Phase 3 requirement: split >3000px)
    tile_max_dimension: int = 3000
    tile_overlap_px: int = 200
    max_ocr_tiles_per_page: int = 4

    # RapidOCR tuning (Phase 3 requirement)
    ocr_box_thresh: float = 0.3
    ocr_unclip_ratio: float = 1.6
    ocr_use_angle_cls: bool = True

    # Preprocessing options
    enable_deskew: bool = True
    enable_adaptive_binarization: bool = True
    denoise_kernel_size: int = 3

    # Confidence fallback threshold (Phase 3 requirement)
    min_block_confidence: float = 0.60

    # Engine mapping per source file type
    engine_mapping: Dict[str, str] = field(
        default_factory=lambda: {
            "pdf": "pymupdf_rapidocr_img2table",
            "image": "rapidocr_img2table",
            "docx": "mammoth",
            "xlsx": "openpyxl_xlrd",
            "xls": "openpyxl_xlrd",
            "csv": "openpyxl_xlrd",
        }
    )


# Singleton default config instance
default_config = PipelineConfig()
