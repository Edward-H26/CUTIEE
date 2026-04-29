"""Local Qwen helper for localhost development.

Mirrors the MIRA pattern: cache Hugging Face weights inside the repo,
load lazily on first use, and keep production Gemini behavior intact.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agent.harness.env_utils import envBool, envStr

logger = logging.getLogger("cutiee.local_llm")

_MODEL: Any = None
_TOKENIZER: Any = None
_LOAD_LOCK = threading.Lock()
_DOWNLOAD_LOCK = threading.Lock()
_CACHE_READY: bool | None = None
_LOAD_FAILED = False

MODEL_ID = envStr("CUTIEE_LOCAL_LLM_MODEL", "Qwen/Qwen3.5-0.8B")


def cacheRoot() -> Path:
    override = envStr("CUTIEE_LOCAL_LLM_CACHE_DIR", "")
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parents[2] / ".cache" / "huggingface-models"


def cachePaths() -> tuple[Path, ...]:
    repoId = MODEL_ID.split("/", 1)
    owner = repoId[0]
    name = repoId[1] if len(repoId) == 2 else repoId[0]
    flattened = f"{owner}__{name}".replace("-", "_").replace(".", "_")
    hubStyle = f"models--{owner}--{name}"
    root = cacheRoot()
    return (root / flattened, root / hubStyle)


def shouldUseLocalLlmForUrl(url: str = "") -> bool:
    if not envBool("CUTIEE_ENABLE_LOCAL_LLM", True):
        return False
    if os.environ.get("CUTIEE_ENV") != "local":
        return False
    if envBool("CUTIEE_FORCE_LOCAL_LLM", False):
        return True
    host = (urlparse(url).hostname or "").strip().lower()
    return host in {"localhost", "127.0.0.1"}


def isAvailable() -> bool:
    if _MODEL is not None and _TOKENIZER is not None:
        return True
    if _LOAD_FAILED:
        return False
    if any(path.exists() and any(path.iterdir()) for path in cachePaths()):
        return True
    try:
        ensureModelCached()
    except Exception:  # noqa: BLE001
        logger.warning("Local Qwen cache warmup failed", exc_info = True)
        return False
    return any(path.exists() and any(path.iterdir()) for path in cachePaths())


def ensureModelCached() -> Path:
    global _CACHE_READY
    root = cacheRoot()
    root.mkdir(parents = True, exist_ok = True)
    if _CACHE_READY is True:
        return root
    if any(path.exists() and any(path.iterdir()) for path in cachePaths()):
        _CACHE_READY = True
        return root
    with _DOWNLOAD_LOCK:
        if _CACHE_READY is True:
            return root
        if any(path.exists() and any(path.iterdir()) for path in cachePaths()):
            _CACHE_READY = True
            return root
        from huggingface_hub import snapshot_download

        logger.info("Downloading local model %s into %s", MODEL_ID, root)
        snapshot_download(
            repo_id = MODEL_ID,
            cache_dir = str(root),
            resume_download = True,
        )
        _CACHE_READY = True
    return root


def generateText(
    *,
    systemInstruction: str,
    userPrompt: str,
    maxInputTokens: int = 2048,
    maxNewTokens: int = 512,
) -> str | None:
    trimmedPrompt = (userPrompt or "").strip()
    if not trimmedPrompt:
        return None
    try:
        import torch

        model, tokenizer = _getModelAndTokenizer()
        messages = [
            {"role": "system", "content": (systemInstruction or "").strip()},
            {"role": "user", "content": trimmedPrompt},
        ]
        fullInput = tokenizer.apply_chat_template(
            messages,
            tokenize = False,
            add_generation_prompt = True,
        )
        inputs = tokenizer(
            fullInput,
            return_tensors = "pt",
            truncation = True,
            max_length = maxInputTokens,
        )
        modelDevice = next(model.parameters()).device
        inputs = {key: value.to(modelDevice) for key, value in inputs.items()}
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens = maxNewTokens,
                do_sample = False,
                pad_token_id = tokenizer.pad_token_id,
                eos_token_id = tokenizer.eos_token_id,
            )
        generated = outputs[0][inputs["input_ids"].shape[1]:]
        text = tokenizer.decode(generated, skip_special_tokens = True).strip()
        return _stripThinkTags(text) or None
    except Exception:  # noqa: BLE001
        logger.warning("Local Qwen generation failed", exc_info = True)
        return None


def _getModelAndTokenizer() -> tuple[Any, Any]:
    global _MODEL, _TOKENIZER, _LOAD_FAILED
    if _MODEL is not None and _TOKENIZER is not None:
        return _MODEL, _TOKENIZER
    with _LOAD_LOCK:
        if _MODEL is not None and _TOKENIZER is not None:
            return _MODEL, _TOKENIZER
        if _LOAD_FAILED:
            raise RuntimeError("Local Qwen load previously failed")

        root = ensureModelCached()
        lastError: Exception | None = None
        for device in _candidateDevices():
            try:
                _MODEL, _TOKENIZER = _loadModelForDevice(device, root)
                return _MODEL, _TOKENIZER
            except Exception as exc:  # noqa: BLE001
                lastError = exc
                logger.warning("Local Qwen load failed on %s", device, exc_info = True)
        _LOAD_FAILED = True
        raise RuntimeError("Failed to load local Qwen model") from lastError


def _candidateDevices() -> tuple[str, ...]:
    import torch

    devices: list[str] = []
    if torch.cuda.is_available():
        devices.append("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        devices.append("mps")
    devices.append("cpu")
    return tuple(devices)


def _loadModelForDevice(device: str, root: Path) -> tuple[Any, Any]:
    from transformers import AutoModelForCausalLM, AutoTokenizer

    loadKwargs: dict[str, Any] = {
        "trust_remote_code": True,
        "cache_dir": str(root),
        "local_files_only": True,
    }
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, **loadKwargs)
    modelKwargs: dict[str, Any] = {
        **loadKwargs,
        "torch_dtype": _torchDtype(device),
    }
    if device == "cuda":
        modelKwargs["device_map"] = "auto"
    model = AutoModelForCausalLM.from_pretrained(MODEL_ID, **modelKwargs)
    if device != "cuda":
        model = model.to(device)
    model.eval()
    if tokenizer.pad_token_id is None and tokenizer.eos_token is not None:
        tokenizer.pad_token = tokenizer.eos_token
    return model, tokenizer


def _torchDtype(device: str) -> Any:
    import torch

    if device in {"cuda", "mps"}:
        return torch.float16
    if envBool("CUTIEE_LOCAL_LLM_FP16_CPU", False):
        return torch.float16
    return torch.float32


def _stripThinkTags(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text or "", flags = re.DOTALL).strip()
