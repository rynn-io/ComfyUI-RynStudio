"""Validation for the portable Ryn H3 Director state v1 contract."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

FORMAT = "ryn.h3-director-project"
SCHEMA_VERSION = 1
_REFERENCE_LIMITS = {"images": 9, "videos": 3, "audio": 3}
_REFERENCE_KINDS = {"images": "image", "videos": "video", "audio": "audio"}
_CONTEXT_FRAMES = {5, 22, 39, 56}
_CONTEXT_MODES = {"guide", "continue"}


class StateValidationError(ValueError):
    """Raised when portable Director state violates the v1 contract."""


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StateValidationError(f"{path} must be an object")
    return value


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise StateValidationError(f"{path} must be an array")
    return value


def _nonempty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StateValidationError(f"{path} must be a non-empty string")
    return value


def _unique_ids(items: list[Any], path: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(items):
        item = _mapping(raw, f"{path}[{index}]")
        item_id = _nonempty_string(item.get("id"), f"{path}[{index}].id")
        if item_id in indexed:
            raise StateValidationError(f"duplicate id {item_id!r} in {path}")
        indexed[item_id] = item
    return indexed


def _validate_loras(settings: dict[str, Any], path: str) -> None:
    stack = _list(settings.get("loraStack", []), f"{path}.loraStack")
    ids: set[str] = set()
    orders: set[int] = set()
    for index, raw in enumerate(stack):
        entry_path = f"{path}.loraStack[{index}]"
        entry = _mapping(raw, entry_path)
        entry_id = _nonempty_string(entry.get("id"), f"{entry_path}.id")
        filename = _nonempty_string(entry.get("filename"), f"{entry_path}.filename")
        del filename
        if entry_id in ids:
            raise StateValidationError(f"duplicate LoRA id {entry_id!r}")
        ids.add(entry_id)
        strength = entry.get("strength")
        if isinstance(strength, bool) or not isinstance(strength, (int, float)):
            raise StateValidationError(f"{entry_path}.strength must be a number")
        if not isinstance(entry.get("enabled"), bool):
            raise StateValidationError(f"{entry_path}.enabled must be a boolean")
        order = entry.get("order")
        if isinstance(order, bool) or not isinstance(order, int):
            raise StateValidationError(f"{entry_path}.order must be an integer")
        if order in orders:
            raise StateValidationError(f"LoRA order values must be unique; duplicate {order}")
        orders.add(order)
        extra = set(entry) - {"id", "filename", "strength", "enabled", "order"}
        if extra:
            raise StateValidationError(f"{entry_path} has unsupported fields: {sorted(extra)}")


def _validate_settings(settings: dict[str, Any], path: str) -> None:
    fps = settings.get("frameRate")
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or fps <= 0:
        raise StateValidationError(f"{path}.frameRate must be positive")
    for key in ("width", "height"):
        value = settings.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 32 or value % 32:
            raise StateValidationError(f"{path}.{key} must be an integer multiple of 32")
    if settings.get("referenceImageSize") not in {"match", "max", "720", "1080"}:
        raise StateValidationError(f"{path}.referenceImageSize is unsupported")
    if settings.get("audioMode") not in {"generate", "mute"}:
        raise StateValidationError(f"{path}.audioMode is unsupported")
    continuity = _mapping(settings.get("continuityDefaults"), f"{path}.continuityDefaults")
    if continuity.get("contextFrames") not in _CONTEXT_FRAMES:
        raise StateValidationError(f"{path}.continuityDefaults.contextFrames must be one of {sorted(_CONTEXT_FRAMES)}")
    if continuity.get("mode") not in _CONTEXT_MODES:
        raise StateValidationError(f"{path}.continuityDefaults.mode must be guide or continue")
    redraw = continuity.get("redrawStrength")
    if isinstance(redraw, bool) or not isinstance(redraw, (int, float)) or not 0 <= redraw <= 1:
        raise StateValidationError(f"{path}.continuityDefaults.redrawStrength must be between 0 and 1")
    if not isinstance(continuity.get("keepAlignmentTail"), bool):
        raise StateValidationError(f"{path}.continuityDefaults.keepAlignmentTail must be a boolean")
    sampling = _mapping(settings.get("sampling"), f"{path}.sampling")
    for key in ("steps",):
        if isinstance(sampling.get(key), bool) or not isinstance(sampling.get(key), int) or sampling[key] < 1:
            raise StateValidationError(f"{path}.sampling.{key} must be a positive integer")
    for key in ("cfg", "shiftVideo", "shiftAudio"):
        if isinstance(sampling.get(key), bool) or not isinstance(sampling.get(key), (int, float)):
            raise StateValidationError(f"{path}.sampling.{key} must be a number")
    _nonempty_string(sampling.get("sampler"), f"{path}.sampling.sampler")
    _nonempty_string(sampling.get("scheduler"), f"{path}.sampling.scheduler")
    _validate_loras(settings, path)


def _validate_references(segment: dict[str, Any], path: str, assets: dict[str, dict[str, Any]]) -> None:
    refs = _mapping(segment.get("references"), f"{path}.references")
    for media_type, limit in _REFERENCE_LIMITS.items():
        entries = _list(refs.get(media_type, []), f"{path}.references.{media_type}")
        if len(entries) > limit:
            raise StateValidationError(f"{path}.references.{media_type} allows at most {limit}")
        slots: set[int] = set()
        for index, raw in enumerate(entries):
            ref_path = f"{path}.references.{media_type}[{index}]"
            ref = _mapping(raw, ref_path)
            slot = ref.get("slot")
            if isinstance(slot, bool) or not isinstance(slot, int) or not 1 <= slot <= limit:
                raise StateValidationError(f"{ref_path}.slot must be between 1 and {limit}")
            if slot in slots:
                raise StateValidationError(f"duplicate slot {slot} in {path}.references.{media_type}")
            slots.add(slot)
            asset_id = _nonempty_string(ref.get("assetId"), f"{ref_path}.assetId")
            asset = assets.get(asset_id)
            if asset is None:
                raise StateValidationError(f"{ref_path} refers to unknown asset {asset_id!r}")
            if asset.get("kind") != _REFERENCE_KINDS[media_type]:
                raise StateValidationError(
                    f"{ref_path} requires {_REFERENCE_KINDS[media_type]} asset, got {asset.get('kind')!r}"
                )


def validate_project(raw: Any) -> dict[str, Any]:
    """Validate and return an isolated v1 document suitable for adaptation."""
    document = deepcopy(_mapping(raw, "project document"))
    if document.get("format") != FORMAT:
        raise StateValidationError(f"format must be {FORMAT!r}")
    if document.get("schemaVersion") != SCHEMA_VERSION:
        raise StateValidationError(f"schemaVersion must be {SCHEMA_VERSION}")
    project = _mapping(document.get("project"), "project")
    _nonempty_string(project.get("id"), "project.id")
    _nonempty_string(project.get("name"), "project.name")

    assets_list = _list(document.get("assets"), "assets")
    assets = _unique_ids(assets_list, "assets")
    for asset_id, asset in assets.items():
        if asset.get("kind") not in set(_REFERENCE_KINDS.values()):
            raise StateValidationError(f"asset {asset_id!r} has unsupported kind {asset.get('kind')!r}")
        _nonempty_string(asset.get("name"), f"asset {asset_id!r}.name")
        storage = _mapping(asset.get("storage"), f"asset {asset_id!r}.storage")
        if storage.get("scheme") != "comfy-input":
            raise StateValidationError(f"asset {asset_id!r} must use comfy-input storage in the ComfyUI Director")
        key = _nonempty_string(storage.get("key"), f"asset {asset_id!r}.storage.key")
        if key.startswith(("/", "\\")) or ".." in key.replace("\\", "/").split("/"):
            raise StateValidationError(f"asset {asset_id!r} has unsafe storage key")

    scenes_list = _list(document.get("scenes"), "scenes")
    _unique_ids(scenes_list, "scenes")
    if not scenes_list:
        raise StateValidationError("scenes must contain at least one scene")
    for scene_index, scene_raw in enumerate(scenes_list):
        scene_path = f"scenes[{scene_index}]"
        scene = _mapping(scene_raw, scene_path)
        _nonempty_string(scene.get("name"), f"{scene_path}.name")
        _validate_settings(_mapping(scene.get("settings"), f"{scene_path}.settings"), f"{scene_path}.settings")
        segments = _list(scene.get("segments"), f"{scene_path}.segments")
        _unique_ids(segments, f"{scene_path}.segments")
        if not segments:
            raise StateValidationError(f"{scene_path}.segments must not be empty")
        for segment_index, segment_raw in enumerate(segments):
            segment_path = f"{scene_path}.segments[{segment_index}]"
            segment = _mapping(segment_raw, segment_path)
            if not isinstance(segment.get("prompt"), str) or not isinstance(segment.get("negativePrompt"), str):
                raise StateValidationError(f"{segment_path} prompts must be strings")
            frames = segment.get("frameCount")
            if isinstance(frames, bool) or not isinstance(frames, int) or frames < 5 or frames > 512:
                raise StateValidationError(f"{segment_path}.frameCount must be between 5 and 512")
            _validate_references(segment, segment_path, assets)
            motion = _mapping(segment.get("motionContext"), f"{segment_path}.motionContext")
            if not isinstance(motion.get("enabled"), bool):
                raise StateValidationError(f"{segment_path}.motionContext.enabled must be a boolean")
            expected = segments[segment_index - 1]["id"] if segment_index else None
            source = motion.get("sourceSegmentId")
            if motion["enabled"]:
                if segment_index == 0 or source != expected:
                    raise StateValidationError(
                        f"{segment_path}.motionContext.sourceSegmentId must identify the immediately preceding segment"
                    )
            elif source is not None:
                raise StateValidationError(f"{segment_path}.motionContext.sourceSegmentId must be null when disabled")
        _list(scene.get("takes"), f"{scene_path}.takes")
    return document


def validate_scene_asset_files(
    document: dict[str, Any],
    *,
    scene_id: str,
    input_directory: str | Path,
) -> None:
    """Fail before model loading when a selected scene's assigned media is absent."""
    scene = next((item for item in document["scenes"] if item["id"] == scene_id), None)
    if scene is None:
        raise StateValidationError(f"unknown scene {scene_id!r}")
    assets = {item["id"]: item for item in document["assets"]}
    assigned_ids: list[str] = []
    for segment in scene["segments"]:
        refs = segment["references"]
        for media_type in ("images", "videos", "audio"):
            assigned_ids.extend(ref["assetId"] for ref in refs[media_type])
    root = Path(input_directory)
    for asset_id in dict.fromkeys(assigned_ids):
        asset = assets[asset_id]
        path = root.joinpath(*asset["storage"]["key"].replace("\\", "/").split("/"))
        if not path.is_file():
            raise StateValidationError(
                f"assigned asset {asset_id!r} is missing from the ComfyUI input directory: {path}"
            )
