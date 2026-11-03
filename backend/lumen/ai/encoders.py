"""Image/text encoders. Every encoder returns L2-normalized float32 vectors."""

from __future__ import annotations

import logging
from typing import Any, Protocol

import numpy as np
from PIL import Image

from lumen.ai.models import ModelSpec

logger = logging.getLogger(__name__)


class Encoder(Protocol):
    spec: ModelSpec
    device: str
    dim: int
    #: Multiplier turning cosine similarities into logits (for softmax over candidates).
    logit_scale: float

    def encode_images(self, images: list[Image.Image]) -> np.ndarray: ...

    def encode_texts(self, texts: list[str]) -> np.ndarray: ...

    def probabilities(self, similarities: np.ndarray) -> np.ndarray | None:
        """Calibrated match probabilities (SigLIP's sigmoid); None if the model has none."""
        ...

    def close(self) -> None: ...


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    normalized: np.ndarray = (vectors / np.maximum(norms, 1e-12)).astype(np.float32)
    return normalized


def _features(output: Any) -> Any:
    """transformers may return a tensor or a model output, depending on the version."""
    if hasattr(output, "pooler_output") and output.pooler_output is not None:
        return output.pooler_output
    return output


class Siglip2Encoder:
    """google/siglip2-* via transformers. Multilingual (Gemma tokenizer)."""

    TEXT_LENGTH = 64  # SigLIP was trained with padding="max_length", max_length=64

    def __init__(self, spec: ModelSpec, device: str) -> None:
        import torch
        from transformers import AutoModel, AutoProcessor

        self.spec = spec
        self.device = device
        self._torch = torch
        self._dtype = torch.float16 if device.startswith("cuda") else torch.float32
        self._processor = AutoProcessor.from_pretrained(spec.name)
        self._model = AutoModel.from_pretrained(spec.name, dtype=self._dtype).to(device).eval()
        self._scale = float(self._model.logit_scale.exp().item())
        self._bias = float(self._model.logit_bias.item())
        self.logit_scale = self._scale
        self.dim = int(self.encode_texts(["probe"]).shape[1])

    def encode_images(self, images: list[Image.Image]) -> np.ndarray:
        inputs = self._processor(images=[i.convert("RGB") for i in images], return_tensors="pt")
        pixel_values = inputs["pixel_values"].to(self.device, self._dtype)
        with self._torch.inference_mode():
            features = _features(self._model.get_image_features(pixel_values=pixel_values))
        return _normalize(features.float().cpu().numpy())

    def encode_texts(self, texts: list[str]) -> np.ndarray:
        inputs = self._processor(
            text=[text.lower() for text in texts],  # SigLIP's training text was lowercased
            padding="max_length",
            max_length=self.TEXT_LENGTH,
            truncation=True,
            return_tensors="pt",
        )
        input_ids = inputs["input_ids"].to(self.device)
        with self._torch.inference_mode():
            features = _features(self._model.get_text_features(input_ids=input_ids))
        return _normalize(features.float().cpu().numpy())

    def probabilities(self, similarities: np.ndarray) -> np.ndarray | None:
        logits = similarities * self._scale + self._bias
        return 1.0 / (1.0 + np.exp(-logits))

    def close(self) -> None:
        del self._model
        if self.device.startswith("cuda"):
            self._torch.cuda.empty_cache()


class OpenClipEncoder:
    """OpenCLIP models (optional dependency ``open_clip_torch``)."""

    def __init__(self, spec: ModelSpec, device: str) -> None:
        import open_clip
        import torch

        self.spec = spec
        self.device = device
        self._torch = torch
        precision = "fp16" if device.startswith("cuda") else "fp32"
        self._dtype = torch.float16 if precision == "fp16" else torch.float32
        model, _, preprocess = open_clip.create_model_and_transforms(
            spec.name, pretrained=spec.pretrained, device=device, precision=precision
        )
        self._model = model.eval()
        self._preprocess = preprocess
        self.logit_scale = float(model.logit_scale.exp().item())
        self._tokenizer = open_clip.get_tokenizer(spec.name)
        self.dim = int(self.encode_texts(["probe"]).shape[1])

    def encode_images(self, images: list[Image.Image]) -> np.ndarray:
        batch = self._torch.stack([self._preprocess(i.convert("RGB")) for i in images])
        batch = batch.to(self.device, self._dtype)
        with self._torch.inference_mode():
            features = self._model.encode_image(batch)
        return _normalize(features.float().cpu().numpy())

    def encode_texts(self, texts: list[str]) -> np.ndarray:
        tokens = self._tokenizer(texts).to(self.device)
        with self._torch.inference_mode():
            features = self._model.encode_text(tokens)
        return _normalize(features.float().cpu().numpy())

    def probabilities(self, similarities: np.ndarray) -> np.ndarray | None:
        return None  # contrastive softmax models have no absolute calibration

    def close(self) -> None:
        del self._model
        if self.device.startswith("cuda"):
            self._torch.cuda.empty_cache()


def create_encoder(spec: ModelSpec, device: str) -> Encoder:
    if spec.backend == "siglip2":
        return Siglip2Encoder(spec, device)
    return OpenClipEncoder(spec, device)
