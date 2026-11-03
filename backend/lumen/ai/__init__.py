"""AI engine: local image/text embeddings (SigLIP2, OpenCLIP), zero-shot labels,
vector search, and opt-in cloud analysis (DeepSeek).

Heavy dependencies (torch, transformers, open_clip) are optional (``pip install
-e .[ai]``) and imported lazily, so the rest of the backend works without them.
"""
