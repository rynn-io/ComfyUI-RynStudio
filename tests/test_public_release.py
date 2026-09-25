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
