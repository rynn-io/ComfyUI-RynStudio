import ast
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_registry_metadata_is_complete():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["name"] == "ryn-h3-director"
    assert metadata["project"]["version"] == "0.1.0"
    assert metadata["project"]["urls"]["Repository"] == "https://github.com/rynn-io/ComfyUI-RynStudio"
    assert metadata["project"]["urls"]["Documentation"].endswith("#readme")
    assert metadata["project"]["urls"]["Bug Tracker"].endswith("/issues")
    assert metadata["tool"]["comfy"]["PublisherId"] == "rynn-io"
    assert metadata["tool"]["comfy"]["DisplayName"] == "Ryn H3 Director"
    assert metadata["tool"]["comfy"]["requires-comfyui"] == ">=0.35.0"
    assert "Icon" not in metadata["tool"]["comfy"]


def test_private_readme_has_authenticated_manual_installation():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "repository is private" in readme
    assert "Authenticate Git" in readme
    assert "git clone https://github.com/rynn-io/ComfyUI-RynStudio.git" in readme
    assert "python_embeded" in readme
    assert "## Required models" in readme
    assert "## Manual installation" in readme
    assert "../baselines" not in readme
    assert "authorized validation environment" not in readme


def test_registry_archive_excludes_development_only_files():
    ignored = (ROOT / ".comfyignore").read_text(encoding="utf-8").splitlines()

    assert "tests/" in ignored
    assert "docs/" in ignored
    assert "package.json" in ignored


def test_ryn_director_exposes_only_supported_outputs():
    tree = ast.parse((ROOT / "nodes" / "ryn_director.py").read_text(encoding="utf-8"))
    director = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "RynH3Director")
    names_assignment = next(
        node for node in director.body
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "RETURN_NAMES" for target in node.targets)
    )
    assert ast.literal_eval(names_assignment.value) == (
        "images", "audio", "fps", "frame_count", "source_images", "report",
    )
    assignments = {
        target.id: node.value
        for node in director.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert ast.literal_eval(assignments["RETURN_TYPES"]) == (
        "IMAGE", "AUDIO", "FLOAT", "INT", "IMAGE", "STRING",
    )
    assert ast.literal_eval(assignments["OUTPUT_IS_LIST"]) == (True, True, False, False, True, False)


def test_active_ui_warning_and_report_strings_are_english_only():
    han = re.compile(r"[\u4e00-\u9fff]")
    paths = [
        ROOT / "nodes" / "ryn_director.py",
        ROOT / "nodes" / "director.py",
        ROOT / "nodes" / "director_common.py",
        ROOT / "director" / "plan.py",
        ROOT / "director" / "gen_timeline.py",
        ROOT / "director" / "executor_core.py",
        ROOT / "director" / "progress.py",
        ROOT / "director" / "audio_export.py",
        ROOT / "director" / "segment_mp4_export.py",
        ROOT / "director" / "segment_runtime.py",
    ]
    failures = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            ast.get_docstring(node, clean=False)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value not in docstrings
                and han.search(node.value)
            ):
                failures.append(f"{path.relative_to(ROOT)}:{node.lineno}: {node.value[:80]}")
    assert failures == []
