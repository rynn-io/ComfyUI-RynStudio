"""Ryn H3 Director node: canonical Ryn state over the proven upstream R2V engine.

Adapted from AIMixer/ComfyUI_MiniMaxH3_Director at
576424fb252b2b4a538e792027f7db1a5ef376e4. Modified for Ryn Studio.
"""

from __future__ import annotations

import json

from ..director.executor_core import execute_director_plan_core
from ..director.plan import build_director_plan
from ..rynstudio.h3.adapter import adapt_scene_to_timeline
from ..rynstudio.h3.loras import apply_model_lora_stack
from ..rynstudio.h3.model_optimizations import apply_h3_optimizations
from ..rynstudio.h3.state import (
    StateValidationError,
    validate_project,
    validate_scene_asset_files,
)
from .director import MiniMaxH3Director
from .director_common import finalize_director_outputs


class RynH3Director:
    """R2V Director whose sole creative-state authority is Ryn state v1."""

    @classmethod
    def INPUT_TYPES(cls):
        upstream = MiniMaxH3Director.INPUT_TYPES()
        required = dict(upstream["required"])
        required.update(
            {
                "ryn_state": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "tooltip": "Canonical ryn.h3-director-project state v1. Managed by the Director UI.",
                    },
                ),
                "scene_id": (
                    "STRING",
                    {"default": "", "tooltip": "Stable scene ID selected for execution."},
                ),
                "runtime_command": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "tooltip": "Transient selective-generation command; not portable project state.",
                    },
                ),
                "live_preview": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "Stream approximate TAE preview frames to the requesting client.",
                    },
                ),
            }
        )
        optional = {
            key: value
            for key, value in upstream.get("optional", {}).items()
            if key
            in {
                "bd_grp_advanced",
                "steps",
                "sampler",
                "scheduler",
                "shift_video",
                "shift_audio",
                "bd_grp_perf",
                "clear_vram_between_segments",
                "export_source_images",
                "sigmas",
            }
        }
        optional.update(
            {
                "low_vram_attention": (
                    "BOOLEAN",
                    {"default": False, "tooltip": "Split MiniMax H3 attention heads to reduce peak VRAM."},
                ),
                "attention_head_chunks": (
                    "INT",
                    {"default": 4, "min": 1, "max": 64, "step": 1},
                ),
                "chunk_feed_forward": (
                    "BOOLEAN",
                    {"default": False, "tooltip": "Process long MiniMax H3 feed-forward sequences in chunks."},
                ),
                "feed_forward_chunks": (
                    "INT",
                    {"default": 2, "min": 1, "max": 64, "step": 1},
                ),
                "feed_forward_sequence_threshold": (
                    "INT",
                    {"default": 4096, "min": 1, "max": 1048576, "step": 1},
                ),
                "fp16_accumulation": (
                    "BOOLEAN",
                    {"default": False, "tooltip": "Enable CUDA FP16 matmul accumulation only while this model runs."},
                ),
                "comfy_kitchen_attention": (
                    "BOOLEAN",
                    {"default": False, "tooltip": "Use ComfyUI's Comfy Kitchen INT8 attention backend when available."},
                ),
            }
        )
        return {"required": required, "optional": optional, "hidden": {"unique_id": "UNIQUE_ID"}}

    @classmethod
    def VALIDATE_INPUTS(cls, input_types=None, **_kwargs):
        if input_types is None:
            return True
        for name, expected in {
            "model": "MODEL",
            "video_vae": "VAE",
            "audio_vae": "VAE",
            "clip": "CLIP",
        }.items():
            actual = input_types.get(name)
            if actual is not None and actual != expected:
                return f"{name}: expected {expected}, linked node returns {actual}."
        return True

    RETURN_TYPES = MiniMaxH3Director.RETURN_TYPES
    RETURN_NAMES = MiniMaxH3Director.RETURN_NAMES
    OUTPUT_IS_LIST = MiniMaxH3Director.OUTPUT_IS_LIST
    FUNCTION = "execute"
    CATEGORY = "Ryn Studio/H3"
    DESCRIPTION = (
        "Ryn H3 Director (R2V MVP): canonical Ryn state v1, explicit per-segment references, "
        "Motion Context continuity, selective generation, and ordered MODEL-only LoRAs."
    )

    def execute(
        self,
        model,
        video_vae,
        audio_vae,
        clip,
        ryn_state,
        scene_id,
        runtime_command,
        live_preview=True,
        unique_id=None,
        seed=0,
        sigmas=None,
        clear_vram_between_segments=True,
        export_source_images=False,
        low_vram_attention=False,
        attention_head_chunks=4,
        chunk_feed_forward=False,
        feed_forward_chunks=2,
        feed_forward_sequence_threshold=4096,
        fp16_accumulation=False,
        comfy_kitchen_attention=False,
        **_legacy_widgets,
    ):
        try:
            raw_state = json.loads(ryn_state)
        except (TypeError, json.JSONDecodeError) as exc:
            raise StateValidationError(f"ryn_state is not valid JSON: {exc}") from exc
        document = validate_project(raw_state)
        command = None
        if isinstance(runtime_command, str) and runtime_command.strip():
            try:
                command = json.loads(runtime_command)
            except json.JSONDecodeError as exc:
                raise StateValidationError(f"runtime_command is not valid JSON: {exc}") from exc
        selected_scene_id = scene_id.strip() if isinstance(scene_id, str) else ""
        if not selected_scene_id:
            if len(document["scenes"]) != 1:
                raise StateValidationError("scene_id is required when the project contains multiple scenes")
            selected_scene_id = document["scenes"][0]["id"]
        import folder_paths

        validate_scene_asset_files(
            document,
            scene_id=selected_scene_id,
            input_directory=folder_paths.get_input_directory(),
        )
        adapted = adapt_scene_to_timeline(
            document,
            scene_id=selected_scene_id,
            command=command,
            live_preview=bool(live_preview),
        )
        sampling = adapted.sampling
        timeline_json = json.dumps(adapted.timeline, ensure_ascii=False, separators=(",", ":"))
        plan = build_director_plan(
            timeline_json,
            global_task_type="r2v — Reference to Video",
            global_prompt="",
            total_frames=adapted.timeline["totalFrames"],
            frame_rate=adapted.timeline["frameRate"],
            width=adapted.timeline["width"],
            height=adapted.timeline["height"],
            ref_max_size=adapted.timeline["refMaxSize"],
        )
        plan.ryn_segment_ids = adapted.segment_ids
        for segment, stable_id in zip(plan.segments, adapted.segment_ids):
            segment.ryn_id = stable_id
        plan.ryn_lora_stack = tuple(entry.copy() for entry in adapted.lora_stack)
        model, unchanged_clip, applied_loras = apply_model_lora_stack(model, clip, adapted.lora_stack)
        model = apply_h3_optimizations(
            model,
            low_vram_attention=bool(low_vram_attention),
            attention_head_chunks=int(attention_head_chunks),
            chunk_feed_forward=bool(chunk_feed_forward),
            feed_forward_chunks=int(feed_forward_chunks),
            feed_forward_sequence_threshold=int(feed_forward_sequence_threshold),
            fp16_accumulation=bool(fp16_accumulation),
            comfy_kitchen_attention=bool(comfy_kitchen_attention),
        )
        plan.ryn_applied_loras = applied_loras
        try:
            (
                combined,
                segment_outputs,
                segment_audios,
                report,
                export_frame_counts,
                pre_combined,
                pre_segments,
                held_for_confirmation,
                pre_face_combined,
                pre_face_segments,
            ) = execute_director_plan_core(
                plan,
                node_id=unique_id,
                model=model,
                vae=video_vae,
                audio_vae=audio_vae,
                clip=unchanged_clip,
                cfg=float(sampling["cfg"]),
                seed=int(seed),
                steps=int(sampling["steps"]),
                sampler=str(sampling["sampler"]),
                scheduler=str(sampling["scheduler"]),
                sigmas=sigmas,
                shift_video=float(sampling["shiftVideo"]),
                shift_audio=float(sampling["shiftAudio"]),
                clear_vram_between_segments=bool(clear_vram_between_segments),
                clear_vram_before_refine=False,
                clear_vram_before_face_refine=False,
                export_pre_face_refine=False,
            )
            return finalize_director_outputs(
                plan,
                combined,
                segment_outputs,
                report,
                export_source_images=bool(export_source_images),
                segment_audios=segment_audios,
                segment_frame_counts=export_frame_counts,
                pre_refine_combined=pre_combined,
                pre_refine_segments=pre_segments,
                pre_face_combined=pre_face_combined,
                pre_face_segments=pre_face_segments,
                export_pre_face_refine=False,
                block_final_images=held_for_confirmation,
            )
        finally:
            cache = getattr(plan, "audio_decode_cache", None)
            if isinstance(cache, dict):
                cache.clear()
            for item in getattr(plan, "global_ref_audios", None) or []:
                if getattr(item, "audio_path", ""):
                    item.audio = None
