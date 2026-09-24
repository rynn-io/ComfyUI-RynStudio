import json
from pathlib import Path

import pytest

from rynstudio.h3.adapter import adapt_scene_to_timeline
from rynstudio.h3.state import (
    StateValidationError,
    validate_project,
    validate_scene_asset_files,
)


def project_state():
    return {
        "format": "ryn.h3-director-project",
        "schemaVersion": 1,
        "project": {"id": "project-1", "name": "Golden"},
        "assets": [
            {
                "id": "character",
                "kind": "image",
                "name": "character.png",
                "storage": {"scheme": "comfy-input", "key": "ryn-golden/character.png"},
                "contentHash": None,
                "metadata": {"mimeType": "image/png", "width": 1024, "height": 1024, "durationSeconds": None},
            },
            {
                "id": "room",
                "kind": "image",
                "name": "room.png",
                "storage": {"scheme": "comfy-input", "key": "ryn-golden/room.png"},
                "contentHash": None,
                "metadata": {"mimeType": "image/png", "width": 1024, "height": 1024, "durationSeconds": None},
            },
        ],
        "scenes": [
            {
                "id": "scene-1",
                "name": "Scene 1",
                "settings": {
                    "frameRate": 24,
                    "width": 864,
                    "height": 480,
                    "referenceImageSize": "match",
                    "audioMode": "generate",
                    "continuityDefaults": {
                        "contextFrames": 22,
                        "mode": "guide",
                        "redrawStrength": 0.1,
                        "keepAlignmentTail": True,
                    },
                    "sampling": {
                        "steps": 25,
                        "sampler": "res_multistep",
                        "scheduler": "simple",
                        "cfg": 1.0,
                        "shiftVideo": 12.0,
                        "shiftAudio": 3.0,
                    },
                    "loraStack": [],
                },
                "segments": [
                    {
                        "id": "segment-1",
                        "prompt": "Character enters the room.",
                        "negativePrompt": "",
                        "frameCount": 85,
                        "references": {"images": [{"slot": 1, "assetId": "character"}, {"slot": 2, "assetId": "room"}], "videos": [], "audio": []},
                        "motionContext": {"enabled": False, "sourceSegmentId": None},
                        "selectedTakeId": None,
                    },
                    {
                        "id": "segment-2",
                        "prompt": "Character continues to the window.",
                        "negativePrompt": "",
                        "frameCount": 85,
                        "references": {"images": [{"slot": 1, "assetId": "character"}], "videos": [], "audio": []},
                        "motionContext": {"enabled": True, "sourceSegmentId": "segment-1"},
                        "selectedTakeId": None,
                    },
                ],
                "takes": [],
            }
        ],
    }


def test_valid_state_adapts_to_explicit_r2v_timeline_without_inheritance():
    state = validate_project(project_state())
    adapted = adapt_scene_to_timeline(state, scene_id="scene-1")

    assert adapted.timeline["global"]["commonEnabled"] is False
    assert adapted.timeline["global"]["refs"] == []
    assert [ref["index"] for ref in adapted.timeline["segments"][0]["refs"]] == [0, 1]
    assert [ref["index"] for ref in adapted.timeline["segments"][1]["refs"]] == [0]
    assert adapted.timeline["segments"][1]["continuityFromPrev"] is True
    assert adapted.segment_ids == ("segment-1", "segment-2")


def test_live_preview_is_transient_adapter_state():
    state = validate_project(project_state())
    adapted = adapt_scene_to_timeline(state, scene_id="scene-1", live_preview=True)

    assert adapted.timeline["liveTaePreview"] is True
    assert "liveTaePreview" not in state


def test_selective_execution_uses_original_segment_indices():
    state = validate_project(project_state())
    adapted = adapt_scene_to_timeline(
        state,
        scene_id="scene-1",
        command={"sceneId": "scene-1", "segmentIds": ["segment-2"], "outputMode": "segments"},
    )

    assert adapted.timeline["runSelectEnabled"] is True
    assert adapted.timeline["runSelection"] == [1]
    assert [segment["id"] for segment in adapted.timeline["segments"]] == ["segment-1", "segment-2"]


@pytest.mark.parametrize("mode", ["guide", "continue"])
def test_motion_context_modes_are_preserved(mode):
    state = project_state()
    state["scenes"][0]["settings"]["continuityDefaults"]["mode"] = mode
    adapted = adapt_scene_to_timeline(validate_project(state), scene_id="scene-1")
    assert adapted.timeline["output"]["continuityMode"] == mode


def test_asset_pool_does_not_assign_unreferenced_assets():
    state = project_state()
    state["assets"].append({
        "id": "unused",
        "kind": "image",
        "name": "unused.png",
        "storage": {"scheme": "comfy-input", "key": "unused.png"},
        "contentHash": None,
        "metadata": {},
    })
    adapted = adapt_scene_to_timeline(validate_project(state), scene_id="scene-1")
    serialized = json.dumps(adapted.timeline)
    assert "unused.png" not in serialized


def test_rejects_non_predecessor_motion_source():
    state = project_state()
    state["scenes"][0]["segments"][1]["motionContext"]["sourceSegmentId"] = "not-the-predecessor"
    with pytest.raises(StateValidationError, match="immediately preceding"):
        validate_project(state)


def test_rejects_non_comfy_asset_scheme():
    state = project_state()
    state["assets"][0]["storage"]["scheme"] = "file"
    with pytest.raises(StateValidationError, match="comfy-input"):
        validate_project(state)


def test_rejects_wrong_asset_kind_and_duplicate_slots():
    state = project_state()
    refs = state["scenes"][0]["segments"][0]["references"]["videos"]
    refs.extend([{"slot": 1, "assetId": "character"}, {"slot": 1, "assetId": "character"}])
    with pytest.raises(StateValidationError):
        validate_project(state)


def test_rejects_more_than_nine_image_references():
    state = project_state()
    for index in range(10):
        asset_id = f"image-{index}"
        state["assets"].append({"id": asset_id, "kind": "image", "name": f"{asset_id}.png", "storage": {"scheme": "comfy-input", "key": f"{asset_id}.png"}, "metadata": {}})
    state["scenes"][0]["segments"][0]["references"]["images"] = [
        {"slot": index + 1, "assetId": f"image-{index}"} for index in range(10)
    ]
    with pytest.raises(StateValidationError, match="at most 9"):
        validate_project(state)


def test_golden_01_fixture_validates_and_compiles_three_stable_segments():
    fixture = Path(__file__).parent / "fixtures" / "h3-director-golden-01"
    document = validate_project(json.loads((fixture / "director-state.json").read_text(encoding="utf-8")))
    adapted = adapt_scene_to_timeline(document, scene_id="golden-scene-01")
    assert adapted.segment_ids == ("golden-segment-01", "golden-segment-02", "golden-segment-03")
    assert adapted.timeline["totalFrames"] == 270
    assert adapted.timeline["segments"][1]["continuityFromPrev"] is True
    assert (fixture / "assets" / "character.png").is_file()
    assert (fixture / "assets" / "room.png").is_file()


def test_selected_scene_fails_before_sampling_when_assigned_asset_is_missing(tmp_path):
    document = validate_project(project_state())
    present = tmp_path / "ryn-golden" / "character.png"
    present.parent.mkdir(parents=True)
    present.write_bytes(b"present")
    expected = tmp_path / "ryn-golden" / "room.png"
    with pytest.raises(StateValidationError, match="room.png") as raised:
        validate_scene_asset_files(document, scene_id="scene-1", input_directory=tmp_path)
    assert str(expected) in str(raised.value)
