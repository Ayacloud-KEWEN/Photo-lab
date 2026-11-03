"""Registry of supported embedding models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Backend = Literal["siglip2", "open_clip"]


@dataclass(frozen=True)
class ModelSpec:
    id: str
    backend: Backend
    #: HuggingFace repository (SigLIP2) or open_clip architecture name.
    name: str
    #: open_clip pretrained tag; unused for SigLIP2.
    pretrained: str | None
    display_name: str
    multilingual: bool
    approx_download_gb: float


DEFAULT_MODEL = "siglip2-so400m-patch14-384"

MODELS: dict[str, ModelSpec] = {
    spec.id: spec
    for spec in (
        ModelSpec(
            id="siglip2-so400m-patch14-384",
            backend="siglip2",
            name="google/siglip2-so400m-patch14-384",
            pretrained=None,
            display_name="SigLIP2 so400m/14 @384",
            multilingual=True,
            approx_download_gb=4.5,
        ),
        ModelSpec(
            id="siglip2-base-patch16-256",
            backend="siglip2",
            name="google/siglip2-base-patch16-256",
            pretrained=None,
            display_name="SigLIP2 base/16 @256",
            multilingual=True,
            approx_download_gb=1.5,
        ),
        # OpenCLIP models: for comparison experiments (lumen.ai.bench) and as alternatives.
        ModelSpec(
            id="openclip-xlm-roberta-large-vit-h-14",
            backend="open_clip",
            name="xlm-roberta-large-ViT-H-14",
            pretrained="frozen_laion5b_s13b_b90k",
            display_name="OpenCLIP XLM-R large ViT-H/14 (multilingual)",
            multilingual=True,
            approx_download_gb=4.8,
        ),
        ModelSpec(
            id="openclip-vit-b-32",
            backend="open_clip",
            name="ViT-B-32",
            pretrained="laion2b_s34b_b79k",
            display_name="OpenCLIP ViT-B/32 (English, small)",
            multilingual=False,
            approx_download_gb=0.6,
        ),
        ModelSpec(
            id="openclip-vit-l-14",
            backend="open_clip",
            name="ViT-L-14",
            pretrained="laion2b_s32b_b82k",
            display_name="OpenCLIP ViT-L/14 (English)",
            multilingual=False,
            approx_download_gb=1.7,
        ),
    )
}


def get_spec(model_id: str) -> ModelSpec:
    try:
        return MODELS[model_id]
    except KeyError:
        raise ValueError(f"Unknown model: {model_id}") from None
