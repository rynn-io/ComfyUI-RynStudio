"""End-to-end backend verification: shared references reach every segment.

Exercises the real path used at queue time:
  canonical Ryn state -> validate -> adapt to timeline -> build DirectorPlan.

Fails if the plan emits the "no reference media" warning or if a segment is
missing the shared image.
"""
import logging
import os
import sys
import types
from pathlib import Path

ROOT = Path("/projects/ComfyUI-RynStudio-public")
# The ComfyUI custom node is a package whose directory name is not a valid
# identifier, so register an import alias without executing __init__.py.
_pkg = types.ModuleType("rynpkg")
_pkg.__path__ = [str(ROOT)]
sys.modules["rynpkg"] = _pkg


def _stub_comfy():
    """Minimal stand-in for the parts of ComfyUI that plan building touches.

    Plan construction never decodes or samples, so a permissive stub is enough
    to exercise the real adapter and plan code without a ComfyUI install.
    """

    class _Stub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            child = _Stub(f"{self.__name__}.{name}")
            setattr(self, name, child)
            sys.modules[child.__name__] = child
            return child

        def __call__(self, *args, **kwargs):
            return None

    comfy = _Stub("comfy")
    comfy.__path__ = []
    utils = _Stub("comfy.utils")
    utils.common_upscale = lambda *args, **kwargs: args[0] if args else None
    comfy.utils = utils
    sys.modules["comfy"] = comfy
    sys.modules["comfy.utils"] = utils


try:
    import comfy.utils  # noqa: F401
except ModuleNotFoundError:
    _stub_comfy()

INPUT_DIR = Path("/tmp/ryn-e2e-input")
OUTPUT_DIR = Path("/tmp/ryn-e2e-output")
TEMP_DIR = Path("/tmp/ryn-e2e-temp")


def _stub_folder_paths():
    """Point ComfyUI's folder lookups at a scratch tree holding the shared image."""
    for directory in (INPUT_DIR, OUTPUT_DIR, TEMP_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    target = INPUT_DIR / "ryn-e2e" / "character.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(
            bytes.fromhex(
                "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                "1f15c4890000000a49444154789c6300010000050001"
                "0d0a2db40000000049454e44ae426082"
            )
        )
    module = types.ModuleType("folder_paths")
    module.get_input_directory = lambda: str(INPUT_DIR)
    module.get_output_directory = lambda: str(OUTPUT_DIR)
    module.get_temp_directory = lambda: str(TEMP_DIR)
    module.get_full_path = lambda *args, **kwargs: None
    module.get_filename_list = lambda *args, **kwargs: []
    module.get_folder_paths = lambda *args, **kwargs: []
    sys.modules["folder_paths"] = module


try:
    import folder_paths  # noqa: F401
except ModuleNotFoundError:
    _stub_folder_paths()

from rynpkg.rynstudio.h3.adapter import adapt_scene_to_timeline
from rynpkg.rynstudio.h3.state import validate_project
from rynpkg.director.gen_timeline import build_gen_director_plan

WARNINGS = []


class Capture(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.WARNING:
            WARNINGS.append(record.getMessage())


logging.getLogger().addHandler(Capture())
logging.getLogger().setLevel(logging.DEBUG)


def state_with_shared_reference():
    return {
        "format": "ryn.h3-director-project",
        "schemaVersion": 1,
        "project": {"id": "project-1", "name": "Shared ref e2e"},
        "assets": [
            {
                "id": "character",
                "kind": "image",
                "name": "character.png",
                "storage": {"scheme": "comfy-input", "key": "ryn-e2e/character.png"},
                "contentHash": None,
                "metadata": {"mimeType": "image/png", "width": 1024, "height": 1024, "durationSeconds": None},
            }
        ],
        "scenes": [
            {
                "id": "scene-1",
                "name": "Scene 1",
                "sharedReferences": {
                    "images": [{"slot": 1, "assetId": "character"}],
                    "videos": [],
                    "audio": [],
                },
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
                        "steps": 2,
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
                        "prompt": "Character waves.",
                        "negativePrompt": "",
                        "frameCount": 51,
                        "references": {"images": [], "videos": [], "audio": []},
                        "motionContext": {"enabled": False, "sourceSegmentId": None},
                        "selectedTakeId": None,
                    },
                    {
                        "id": "segment-2",
                        "prompt": "Character turns.",
                        "negativePrompt": "",
                        "frameCount": 51,
                        "references": {"images": [], "videos": [], "audio": []},
                        "motionContext": {"enabled": True, "sourceSegmentId": "segment-1"},
                        "selectedTakeId": None,
                    },
                ],
                "takes": [],
            }
        ],
    }


document = validate_project(state_with_shared_reference())
adapted = adapt_scene_to_timeline(document, scene_id="scene-1")
timeline = adapted.timeline

# Negative control: without shared references the timeline must behave like t2v
# and the segment-level warning must fire, so the positive run proves the fix.
NEGATIVE_CONTROL = os.environ.get("RYN_E2E_NEGATIVE") == "1"
if NEGATIVE_CONTROL:
    timeline["global"]["refs"] = []
    timeline["global"]["commonEnabled"] = False

print("global.commonEnabled =", timeline["global"]["commonEnabled"])
print("global.refs          =", [ref.get("imageFile") for ref in timeline["global"]["refs"]])

plan = build_gen_director_plan(
    timeline,
    global_task_type=timeline["global"]["taskType"],
    global_prompt=timeline["global"]["prompt"],
    total_frames=timeline["totalFrames"],
    frame_rate=timeline["frameRate"],
    width=timeline["width"],
    height=timeline["height"],
    ref_max_size=timeline["refMaxSize"],
)

failures = []
shared_expected = "ryn-e2e/character.png"
for seg in plan.segments:
    names = [getattr(ref, "image_file", getattr(ref, "path", "")) for ref in (seg.refs or [])]
    print(f"segment #{seg.index + 1} task={seg.task_key} refs={names}")
    if not any(shared_expected in str(name).replace("\\", "/") for name in names):
        failures.append(f"segment #{seg.index + 1} is missing the shared image reference")

hits = [msg for msg in WARNINGS if "no reference media" in msg]
if hits:
    failures.append(f"unexpected missing-reference warning(s): {hits}")

print("\nwarnings captured:", WARNINGS or "none")
print("\nRESULT:", "FAIL -> " + "; ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
