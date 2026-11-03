"""Process-wide owner of the loaded embedding model.

The model is loaded on first use (GPU in fp16 when available) and unloaded after
``ai_idle_unload_s`` seconds without use, so VRAM is only held while needed.
"""

from __future__ import annotations

import importlib.util
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from lumen.ai.encoders import Encoder, create_encoder
from lumen.ai.models import ModelSpec, get_spec

logger = logging.getLogger(__name__)

# Files needed to run a model (skips duplicate checkpoints, e.g. .bin next to .safetensors).
DOWNLOAD_PATTERNS = ["*.json", "*.safetensors", "*.model", "*.txt", "tokenizer*", "*.tiktoken"]


@dataclass(frozen=True)
class DeviceInfo:
    available: bool  # torch importable
    device: str  # "cuda" | "cpu"
    name: str | None
    memory_gb: float | None
    reason: str | None = None


def torch_installed() -> bool:
    return importlib.util.find_spec("torch") is not None


def device_info(preference: str = "auto") -> DeviceInfo:
    if not torch_installed():
        return DeviceInfo(False, "cpu", None, None, "AI components are not installed")
    import torch

    if preference != "cpu" and torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        return DeviceInfo(True, "cuda", props.name, round(props.total_memory / 1024**3, 1))
    return DeviceInfo(True, "cpu", None, None)


def _hub() -> Any:
    import huggingface_hub

    return huggingface_hub


def model_downloaded(spec: ModelSpec) -> bool:
    if spec.backend != "siglip2":
        # open_clip downloads on first load (into the HuggingFace cache as well).
        return importlib.util.find_spec("open_clip") is not None
    if importlib.util.find_spec("huggingface_hub") is None:
        return False
    try:
        _hub().snapshot_download(spec.name, allow_patterns=DOWNLOAD_PATTERNS, local_files_only=True)
        return True
    except Exception:
        return False


def download_size(spec: ModelSpec) -> int:
    """Total bytes of the files that will be downloaded (asks the hub)."""
    info = _hub().HfApi().model_info(spec.name, files_metadata=True)
    from fnmatch import fnmatch

    return sum(
        (sibling.size or 0)
        for sibling in info.siblings or []
        if any(fnmatch(sibling.rfilename, pattern) for pattern in DOWNLOAD_PATTERNS)
    )


def cache_dir() -> str:
    from huggingface_hub import constants

    return str(constants.HF_HUB_CACHE)


class AIEngine:
    def __init__(self, idle_unload_s: float = 600, device: str = "auto") -> None:
        self._lock = threading.RLock()
        self._encoder: Encoder | None = None
        self._last_used = 0.0
        self._idle_unload_s = idle_unload_s
        self._device_pref = device
        self._stop = threading.Event()
        self._reaper = threading.Thread(target=self._reap, name="ai-idle-unload", daemon=True)
        self._reaper.start()

    @property
    def loaded_model(self) -> str | None:
        encoder = self._encoder
        return encoder.spec.id if encoder else None

    def encoder(self, model_id: str) -> Encoder:
        """The encoder for ``model_id``, loading it (and unloading another) if needed."""
        with self._lock:
            if self._encoder is not None and self._encoder.spec.id != model_id:
                self._unload_locked()
            if self._encoder is None:
                spec = get_spec(model_id)
                device = device_info(self._device_pref).device
                started = time.monotonic()
                self._encoder = create_encoder(spec, device)
                logger.info(
                    "model loaded",
                    extra={
                        "model": model_id,
                        "device": device,
                        "dim": self._encoder.dim,
                        "seconds": round(time.monotonic() - started, 1),
                    },
                )
            self._last_used = time.monotonic()
            return self._encoder

    def touch(self) -> None:
        self._last_used = time.monotonic()

    def unload(self) -> None:
        with self._lock:
            self._unload_locked()

    def _unload_locked(self) -> None:
        if self._encoder is not None:
            model_id = self._encoder.spec.id
            self._encoder.close()
            self._encoder = None
            logger.info("model unloaded", extra={"model": model_id})

    def _reap(self) -> None:
        while not self._stop.wait(30):
            if (
                self._encoder is not None
                and time.monotonic() - self._last_used > self._idle_unload_s
            ):
                with self._lock:
                    if time.monotonic() - self._last_used > self._idle_unload_s:
                        self._unload_locked()

    def close(self) -> None:
        self._stop.set()
        self.unload()


_engine: AIEngine | None = None
_engine_lock = threading.Lock()


def get_engine(idle_unload_s: float = 600, device: str = "auto") -> AIEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = AIEngine(idle_unload_s, device)
        return _engine


def set_engine(engine: AIEngine | None) -> None:
    """Replace the process-wide engine (used by tests)."""
    global _engine
    with _engine_lock:
        _engine = engine
