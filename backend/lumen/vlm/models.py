"""The local vision-language models LUMEN knows how to run (files and llama-server settings).

llama-server's ``--fit`` (on by default) decides what goes on the GPU: on a 12 GB GPU
with 64 GB of RAM the 8B model fits entirely; the 35B mixture-of-experts keeps attention
on the GPU and experts in RAM (only ~3B parameters are active per token); the dense 27B
runs the layers that do not fit on the CPU. Thinking is off: a photo needs no reasoning.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lumen.vlm.server import ModelFiles


@dataclass(frozen=True)
class VlmSpec:
    id: str
    label: str
    folder: str
    model: str
    mmproj: str
    args: tuple[str, ...]
    licence: str
    repo: str  # Hugging Face repository the files come from
    size_gb: float  # download size, all files
    context: int = 8192
    # Multi-token-prediction head for speculative decoding (faster output), if any.
    draft: str | None = None

    def files(self, models_dir: Path) -> ModelFiles:
        folder = models_dir / self.folder
        args = (*_COMMON, *self.args)
        if self.draft is not None and (folder / self.draft).is_file():
            args = (*args, "--spec-type", "draft-mtp", "--model-draft", str(folder / self.draft))
        return ModelFiles(
            name=self.id,
            model=folder / self.model,
            mmproj=folder / self.mmproj,
            args=args,
            context=self.context,
        )

    def file_names(self) -> list[str]:
        return [self.model, self.mmproj, *([self.draft] if self.draft else [])]

    def downloaded(self, models_dir: Path) -> bool:
        files = self.files(models_dir)
        return files.model.is_file() and files.mmproj.is_file()


_COMMON = ("--reasoning", "off", "--flash-attn", "on")

MODELS: dict[str, VlmSpec] = {
    spec.id: spec
    for spec in (
        VlmSpec(
            id="qwen3.6-35b-a3b",
            label="Qwen3.6-35B-A3B (MoE, Q4_K_M)",
            folder="Qwen3.6-35B-A3B",
            model="Qwen3.6-35B-A3B-Q4_K_M.gguf",
            mmproj="mmproj-Qwen3.6-35B-A3B-BF16.gguf",
            args=(),
            licence="Apache-2.0",
            repo="ggml-org/Qwen3.6-35B-A3B-GGUF",
            size_gb=23.4,
            draft="mtp-Qwen3.6-35B-A3B-Q8_0.gguf",
        ),
        VlmSpec(
            id="qwen3.8-27b",
            label="Qwen3.8-27B (dense, Q4_K_M)",
            folder="Qwen3.8-27B",
            model="Qwen3.8-27B-UD-Q4_K_M.gguf",
            mmproj="mmproj-BF16.gguf",
            args=(),
            licence="Apache-2.0",
            repo="unsloth/Qwen3.8-27B-GGUF",
            size_gb=17.4,
        ),
        VlmSpec(
            id="qwen3-vl-8b",
            label="Qwen3-VL-8B-Instruct (Q8_0)",
            folder="Qwen3-VL-8B",
            model="Qwen3VL-8B-Instruct-Q8_0.gguf",
            mmproj="mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf",
            args=(),
            licence="Apache-2.0",
            repo="Qwen/Qwen3-VL-8B-Instruct-GGUF",
            size_gb=9.5,
        ),
    )
}


# What LUMEN uses: the default model reads the library; "fine" re-reads chosen photos
# with the slower, more careful dense model (ADR-038; compared on the user's library).
DEFAULT_MODEL = "qwen3.6-35b-a3b"
FINE_MODEL = "qwen3.8-27b"

# llama.cpp build run by LUMEN (Windows, CUDA 13), from its GitHub releases.
LLAMA_BUILD = "b12207"
LLAMA_DOWNLOADS = (
    f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_BUILD}/"
    f"llama-{LLAMA_BUILD}-bin-win-cuda-13.5-x64.zip",
    f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_BUILD}/"
    "cudart-llama-bin-win-cuda-13.5-x64.zip",
)


def llama_dir(folder: Path) -> Path:
    return folder / "tools" / "llama.cpp" / LLAMA_BUILD


def llama_server(folder: Path) -> Path:
    return llama_dir(folder) / "llama-server.exe"


def models_dir(folder: Path) -> Path:
    return folder / "models"
