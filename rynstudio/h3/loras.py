"""Sequential MODEL-only LoRA application for the Ryn H3 Director MVP."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any


def _default_resolve_path(filename: str) -> str:
    import folder_paths

    get_or_raise = getattr(folder_paths, "get_full_path_or_raise", None)
    if get_or_raise is not None:
        return get_or_raise("loras", filename)
    path = folder_paths.get_full_path("loras", filename)
    if not path:
        raise FileNotFoundError(f"LoRA not found in ComfyUI models/loras: {filename}")
    return path


def _default_load_weights(path: str):
    import comfy.utils

    return comfy.utils.load_torch_file(path, safe_load=True)


def _default_apply_weights(model, clip, weights, strength_model: float, strength_clip: float):
    import comfy.sd

    return comfy.sd.load_lora_for_models(model, clip, weights, strength_model, strength_clip)


def apply_model_lora_stack(
    model: Any,
    clip: Any,
    stack: Iterable[dict[str, Any]],
    *,
    resolve_path: Callable[[str], str] | None = None,
    load_weights: Callable[[str], Any] | None = None,
    apply_weights: Callable[[Any, Any, Any, float, float], tuple[Any, Any]] | None = None,
) -> tuple[Any, Any, tuple[dict[str, Any], ...]]:
    """Apply enabled entries to MODEL only; return the original CLIP unchanged."""
    enabled = tuple(sorted((entry for entry in stack if entry.get("enabled")), key=lambda entry: entry["order"]))
    if not enabled:
        return model, clip, ()
    resolve = resolve_path or _default_resolve_path
    load = load_weights or _default_load_weights
    apply = apply_weights or _default_apply_weights
    current_model = model
    for entry in enabled:
        path = resolve(str(entry["filename"]))
        weights = load(path)
        current_model, _ignored_clip = apply(
            current_model,
            None,
            weights,
            float(entry["strength"]),
            0.0,
        )
    return current_model, clip, tuple(entry.copy() for entry in enabled)
