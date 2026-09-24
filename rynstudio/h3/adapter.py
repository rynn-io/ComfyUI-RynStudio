"""Deterministic adapter from Ryn Director state v1 to the proven R2V planner input."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from .state import StateValidationError

_R2V_TASK = "r2v — Reference to Video"


@dataclass(frozen=True)
class AdaptedScene:
    timeline: dict[str, Any]
    segment_ids: tuple[str, ...]
    lora_stack: tuple[dict[str, Any], ...]
    sampling: dict[str, Any]


def _asset_meta(asset: dict[str, Any]) -> dict[str, Any]:
    key = str(asset["storage"]["key"]).replace("\\", "/")
    path = PurePosixPath(key)
    subfolder = "" if str(path.parent) == "." else str(path.parent)
    return {
        "fileName": asset.get("name") or path.name,
        "type": "input",
        "subfolder": subfolder,
    }


def _image_ref(ref: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any]:
    meta = _asset_meta(asset)
    return {"index": ref["slot"] - 1, "imageFile": asset["storage"]["key"], **meta}


def _video_ref(ref: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any]:
    meta = _asset_meta(asset)
    return {"index": ref["slot"] - 1, "videoFile": asset["storage"]["key"], **meta}


def _audio_ref(ref: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any]:
    meta = _asset_meta(asset)
    return {"index": ref["slot"] - 1, "audioFile": asset["storage"]["key"], **meta}


def _selection(segment_ids: tuple[str, ...], scene_id: str, command: dict[str, Any] | None) -> tuple[bool, list[int], str]:
    if command is None:
        return False, [], "all"
    if command.get("sceneId") != scene_id:
        raise StateValidationError("runtime command sceneId does not match selected scene")
    output_mode = command.get("outputMode", "segments")
    if output_mode not in {"segments", "all"}:
        raise StateValidationError("runtime command outputMode must be segments or all")
    requested = command.get("segmentIds")
    if not isinstance(requested, list) or not requested:
        raise StateValidationError("runtime command segmentIds must be a non-empty array")
    by_id = {segment_id: index for index, segment_id in enumerate(segment_ids)}
    selected: list[int] = []
    seen: set[str] = set()
    for segment_id in requested:
        if segment_id in seen:
            raise StateValidationError(f"runtime command repeats segment id {segment_id!r}")
        if segment_id not in by_id:
            raise StateValidationError(f"runtime command refers to unknown segment {segment_id!r}")
        seen.add(segment_id)
        selected.append(by_id[segment_id])
    return True, sorted(selected), output_mode


def adapt_scene_to_timeline(
    document: dict[str, Any],
    *,
    scene_id: str,
    command: dict[str, Any] | None = None,
    live_preview: bool = False,
) -> AdaptedScene:
    """Compile one validated scene into upstream's private R2V timeline representation."""
    scene = next((item for item in document["scenes"] if item["id"] == scene_id), None)
    if scene is None:
        raise StateValidationError(f"unknown scene {scene_id!r}")
    assets = {asset["id"]: asset for asset in document["assets"]}
    segment_ids = tuple(segment["id"] for segment in scene["segments"])
    selected_enabled, selected_indices, output_mode = _selection(segment_ids, scene_id, command)
    settings = scene["settings"]
    continuity = settings["continuityDefaults"]

    cursor = 0
    segments: list[dict[str, Any]] = []
    for segment in scene["segments"]:
        refs = segment["references"]
        frame_count = segment["frameCount"]
        segments.append(
            {
                "id": segment["id"],
                "start": cursor,
                "length": frame_count,
                "frameCount": frame_count,
                "durationSec": frame_count / float(settings["frameRate"]),
                "prompt": segment["prompt"],
                "negativePrompt": segment["negativePrompt"],
                "taskType": _R2V_TASK,
                "refs": [_image_ref(ref, assets[ref["assetId"]]) for ref in refs["images"]],
                "refVideos": [_video_ref(ref, assets[ref["assetId"]]) for ref in refs["videos"]],
                "refAudios": [_audio_ref(ref, assets[ref["assetId"]]) for ref in refs["audio"]],
                "continuityFromPrev": segment["motionContext"]["enabled"],
                "refImageSize": settings["referenceImageSize"],
                "genImage": {"imageFile": "", "fileName": ""},
            }
        )
        cursor += frame_count

    timeline = {
        "version": 5,
        "timelineMode": "prompt_batch",
        "editMode": "segment",
        "frameRate": settings["frameRate"],
        "totalFrames": cursor,
        "width": settings["width"],
        "height": settings["height"],
        "refMaxSize": max(settings["width"], settings["height"]),
        "global": {
            "taskType": _R2V_TASK,
            "prompt": "",
            "commonEnabled": False,
            "refs": [],
            "refVideos": [],
            "refAudios": [],
            "continuousReference": False,
        },
        "output": {
            "mode": "fixed",
            "width": settings["width"],
            "height": settings["height"],
            "longEdge": max(settings["width"], settings["height"]),
            "exportMode": output_mode,
            "audioMode": settings["audioMode"],
            "refImageSize": settings["referenceImageSize"],
            "continuityEnabled": any(segment["motionContext"]["enabled"] for segment in scene["segments"]),
            "continuityOverlapFrames": continuity["contextFrames"],
            "continuityMode": continuity["mode"],
            "continuityRedraw": continuity["redrawStrength"],
            "continuityKeepTail": continuity["keepAlignmentTail"],
            "maxExportFrames": 0,
        },
        "segments": segments,
        "runSelectEnabled": selected_enabled,
        "runSelection": selected_indices,
        "liveTaePreview": bool(live_preview),
    }
    stack = tuple(sorted((entry.copy() for entry in settings["loraStack"]), key=lambda entry: entry["order"]))
    return AdaptedScene(
        timeline=timeline,
        segment_ids=segment_ids,
        lora_stack=stack,
        sampling=settings["sampling"].copy(),
    )
