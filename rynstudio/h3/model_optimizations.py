"""Optional MiniMax H3 model patches used by Ryn H3 Director.

The implementations in this module are independent wrappers around ComfyUI's
public ModelPatcher and attention interfaces. They do not copy KJNodes code.
All optimizations are opt-in and leave the input model untouched when disabled.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _torch_cat(parts: list[Any], dim: int) -> Any:
    import torch

    return torch.cat(parts, dim=dim)


def make_chunked_forward(
    original: Callable[[Any], Any],
    *,
    chunks: int,
    sequence_threshold: int,
    concatenate: Callable[[list[Any], int], Any] | None = None,
) -> Callable[[Any], Any]:
    """Wrap an MLP forward call so long token sequences run in smaller pieces."""

    chunk_count = max(1, int(chunks))
    threshold = max(1, int(sequence_threshold))
    cat = concatenate or _torch_cat

    def chunked_forward(value: Any) -> Any:
        if chunk_count == 1 or int(value.shape[0]) <= threshold:
            return original(value)
        outputs = [original(piece) for piece in value.chunk(chunk_count, dim=0)]
        return cat(outputs, 0)

    return chunked_forward


def make_head_chunked_attention(
    original: Callable[..., Any],
    *,
    head_chunks: int,
    concatenate: Callable[[list[Any], int], Any] | None = None,
) -> Callable[..., Any]:
    """Split skip-reshape attention by heads and join its feature outputs."""

    chunk_count = max(1, int(head_chunks))
    cat = concatenate or _torch_cat

    def chunked_attention(q: Any, k: Any, v: Any, heads: int, *args: Any, **kwargs: Any) -> Any:
        if chunk_count == 1 or not kwargs.get("skip_reshape", False):
            return original(q, k, v, heads, *args, **kwargs)
        total_heads = int(heads)
        width = max(1, (total_heads + chunk_count - 1) // chunk_count)
        q_tensor = q.take() if callable(getattr(q, "take", None)) else q
        k_tensor = k.take() if callable(getattr(k, "take", None)) else k
        v_tensor = v.take() if callable(getattr(v, "take", None)) else v

        def part(container: Any, tensor: Any, start: int, stop: int) -> Any:
            sliced = tensor[:, start:stop]
            return type(container)(sliced) if callable(getattr(container, "take", None)) else sliced

        outputs = []
        for start in range(0, total_heads, width):
            stop = min(total_heads, start + width)
            outputs.append(
                original(
                    part(q, q_tensor, start, stop),
                    part(k, k_tensor, start, stop),
                    part(v, v_tensor, start, stop),
                    stop - start,
                    *args,
                    **kwargs,
                )
            )
        return cat(outputs, -1)

    # ComfyUI's attention wrapper calls this hook before consuming ownership of
    # AttentionTensorContainer inputs. Point it at this wrapper (not the base
    # backend), otherwise Comfy Kitchen would bypass head chunking entirely.
    if getattr(original, "container_function", None) is not None:
        setattr(chunked_attention, "container_function", chunked_attention)
    return chunked_attention


def _iter_mlp_blocks(diffusion_model: Any):
    for collection_name in ("blocks",):
        for index, block in enumerate(getattr(diffusion_model, collection_name, ())):
            mlp = getattr(block, "mlp", None)
            if mlp is not None and callable(getattr(mlp, "forward", None)):
                yield f"diffusion_model.{collection_name}.{index}.mlp.forward", mlp.forward


def _resolve_attention_function(*, comfy_kitchen_attention: bool) -> Callable[..., Any]:
    from comfy.ldm.modules.attention import get_attention_function

    name = "comfy_kitchen_int8" if comfy_kitchen_attention else "optimized"
    try:
        return get_attention_function(name)
    except KeyError as exc:
        raise RuntimeError(
            "Comfy Kitchen INT8 attention is not available in this ComfyUI/PyTorch environment."
        ) from exc


def _install_fp16_accumulation_callbacks(model: Any) -> None:
    import torch
    from comfy.patcher_extension import CallbacksMP

    state: list[bool] = []

    def enable(_patcher: Any) -> None:
        state.append(bool(torch.backends.cuda.matmul.allow_fp16_accumulation))
        torch.backends.cuda.matmul.allow_fp16_accumulation = True

    def restore(_patcher: Any) -> None:
        if state:
            torch.backends.cuda.matmul.allow_fp16_accumulation = state.pop()

    model.add_callback(CallbacksMP.ON_PRE_RUN, enable)
    model.add_callback(CallbacksMP.ON_CLEANUP, restore)


def apply_h3_optimizations(
    model: Any,
    *,
    low_vram_attention: bool = False,
    attention_head_chunks: int = 4,
    chunk_feed_forward: bool = False,
    feed_forward_chunks: int = 2,
    feed_forward_sequence_threshold: int = 4096,
    fp16_accumulation: bool = False,
    comfy_kitchen_attention: bool = False,
    attention_function: Callable[..., Any] | None = None,
    concatenate: Callable[[list[Any], int], Any] | None = None,
) -> Any:
    """Clone and patch a MODEL according to explicitly enabled H3 controls."""

    if not any((low_vram_attention, chunk_feed_forward, fp16_accumulation, comfy_kitchen_attention)):
        return model

    patched = model.clone()

    if chunk_feed_forward:
        diffusion_model = getattr(getattr(patched, "model", None), "diffusion_model", None)
        if diffusion_model is None:
            raise RuntimeError("Chunk FeedForward requires a MiniMax H3 diffusion model.")
        mlp_blocks = list(_iter_mlp_blocks(diffusion_model))
        if not mlp_blocks:
            raise RuntimeError("No MiniMax H3 feed-forward blocks were found to patch.")
        for path, original in mlp_blocks:
            patched.add_object_patch(
                path,
                make_chunked_forward(
                    original,
                    chunks=feed_forward_chunks,
                    sequence_threshold=feed_forward_sequence_threshold,
                    concatenate=concatenate,
                ),
            )

    if low_vram_attention or comfy_kitchen_attention:
        base_attention = attention_function or _resolve_attention_function(
            comfy_kitchen_attention=comfy_kitchen_attention
        )
        if low_vram_attention:
            base_attention = make_head_chunked_attention(
                base_attention,
                head_chunks=attention_head_chunks,
                concatenate=concatenate,
            )
        patched.set_model_optimized_attention(base_attention)

    if fp16_accumulation:
        _install_fp16_accumulation_callbacks(patched)

    return patched
