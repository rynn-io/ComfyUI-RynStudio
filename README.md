# ComfyUI-RynStudio

**Ryn H3 Director** is a focused MiniMax H3 Reference-to-Video director node for ComfyUI. It provides a timeline-oriented UI for reusable reference media, per-segment prompts, selective generation, continuity, Motion Context, and ordered MODEL-only LoRA application.

> This is an early `0.1.0` release. The current node intentionally targets MiniMax H3 R2V workflows only.

## Features

- canonical `ryn.h3-director-project` state with stable scene, segment, and asset IDs;
- reusable shared image, video, and audio assets;
- explicit per-segment assignments with limits of 9 images, 3 videos, and 3 audio references;
- complete-scene or selected-segment generation;
- Motion Context `guide` and `continue`/redraw modes;
- ordered scene-level LoRAs applied to MODEL only;
- MiniMax H3 conditioning, continuity, cache, AV decoding, and output paths;
- opt-in low-VRAM attention, chunked feed-forward, FP16 accumulation, and Comfy Kitchen INT8 attention controls;
- ComfyUI web UI for timeline editing and media assignment.

Refine, FaceRefine, SelfLift, Semantic Bridge, external Group execution, prompt enhancement, and non-R2V authoring are not included in this release.

## Requirements

- ComfyUI `0.35.0` or newer;
- ComfyUI frontend `1.51.10` or newer;
- Python 3.10 or newer;
- an NVIDIA CUDA environment capable of running MiniMax H3;
- FFmpeg available to ComfyUI for media probing and export;
- sufficient GPU VRAM, system RAM, and disk for the selected H3 models and output resolution.

No model weights are included in this repository or Registry package.

## Required models

Place compatible model files under the normal ComfyUI model directory:

| ComfyUI path | Validated filename |
|---|---|
| `models/diffusion_models/` | `minimax_h3_hybrid_fl2va_ref2va_b30-49-int8.safetensors` |
| `models/text_encoders/` | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` |
| `models/vae/` | `minimax_h3_video_vae_int8_convrot.safetensors` |
| `models/vae/` | `minimax_h3_audio_vae_fp32.safetensors` |

Validated upstream sources:

- hybrid model: [`smhfacct/Minimax-H3-fl2va-ref2va-hybrid-models`](https://huggingface.co/smhfacct/Minimax-H3-fl2va-ref2va-hybrid-models/tree/a36feb17fbd1f20ff4bdd509ccd07e2b7b585a38);
- text encoder and audio VAE: [`Comfy-Org/MiniMax-H3`](https://huggingface.co/Comfy-Org/MiniMax-H3/tree/7e75982b97cd5a41d2dcfa1904ee88d0686d6fd1);
- video VAE: [`Kijai/MiniMax-H3-experimental`](https://huggingface.co/Kijai/MiniMax-H3-experimental/tree/7f5705937cc106963a9dd77c322f7631e3610e89).

The video VAE has same-named variants with different contents. The validated `minimax_h3_video_vae_int8_convrot.safetensors` is 3,171,670,912 bytes with SHA-256 `9bb2d96f218c76babd85e0611b85ca8fb330a90546c01a0005e8a58a59593410`.

You are responsible for reviewing and complying with each model repository's license, access conditions, and usage terms.

## Manual installation

This repository is private. Authenticate Git for an authorized GitHub account before cloning it.

### Standard ComfyUI installation

Run these commands with the same Python environment that launches ComfyUI:

```bash
cd /path/to/ComfyUI/custom_nodes
git clone https://github.com/rynn-io/ComfyUI-RynStudio.git
cd ComfyUI-RynStudio
python -m pip install -r requirements.txt
```

Restart ComfyUI after installation. Installing this node does not upgrade ComfyUI or replace PyTorch.

### Windows ComfyUI Portable

Open PowerShell in `ComfyUI_windows_portable` and run:

```powershell
Set-Location .\ComfyUI\custom_nodes
git clone https://github.com/rynn-io/ComfyUI-RynStudio.git
Set-Location .\ComfyUI-RynStudio
..\..\python_embeded\python.exe -m pip install -r requirements.txt
```

Restart `run_nvidia_gpu.bat` afterward.

### Optional shot detection

PySceneDetect is optional. Install it into the same Python environment only if you need shot-detection helpers:

```bash
python -m pip install "scenedetect>=0.6.4,<0.8"
```

## Quick start

1. Add **Ryn H3 Director** from the node menu.
2. Connect the MiniMax H3 MODEL, video VAE, audio VAE, and MiniMax CLIP inputs.
3. Add reference media to the shared asset pool and assign it explicitly to segments.
4. Enter segment prompts and choose a complete-scene or selective run.
5. Connect the node's `images` and `audio` outputs to the normal `CreateVideo`/`SaveVideo` path.
6. Queue the workflow.

The hidden `ryn_state` widget is the canonical creative document. `timeline_data` is a UI/execution projection, while queue selection is stored separately in `runtime_command`.

## Optional H3 optimizations

All optimization controls are disabled by default and clone the incoming MODEL only when enabled:

- **MiniMax H3 low-VRAM attention** splits attention heads (`4` chunks by default);
- **Chunk MiniMax H3 feed-forward** chunks sequences longer than `4096` tokens (`2` chunks by default);
- **FP16 accumulation** enables CUDA FP16 matmul accumulation for the patched model run and restores the previous global value during cleanup;
- **Comfy Kitchen INT8 attention** selects ComfyUI's built-in backend and reports a clear error when the backend is unavailable.

Low-VRAM head chunking and chunked feed-forward are implemented directly in this package and do not require KJNodes.

## LoRAs

Enabled LoRAs are sorted by `order` and applied sequentially to the incoming MODEL. CLIP is passed through unchanged. An empty stack does not load or patch either input.

## Troubleshooting

- **Node does not appear:** confirm the repository is directly under `ComfyUI/custom_nodes/ComfyUI-RynStudio`, install `requirements.txt`, and inspect the ComfyUI console during restart.
- **Models are missing:** verify the exact filenames and folders in the table above.
- **Media routes return 404:** restart ComfyUI so the Ryn HTTP routes can register during startup.
- **Video export fails:** confirm `ffmpeg` and `ffprobe` are available to the ComfyUI process.
- **Frontend behavior differs:** update to the validated ComfyUI/frontend baseline before reporting a UI issue.

Authorized collaborators can report reproducible problems in the repository issue tracker. Do not include API keys, tokens, private media, or private workflows in issue reports.

## Development and tests

From the repository root:

```bash
PYTHONPATH=. python -m pytest tests -q --confcutdir=tests
npm run test:js
npm run check:js
python -m compileall -q .
```

GPU acceptance requires a compatible MiniMax H3 environment and is separate from the unit and syntax test suite.

## License and attribution

The package is distributed under the Apache License 2.0. The R2V execution path includes code adapted from [`AIMixer/ComfyUI_MiniMaxH3_Director`](https://github.com/AIMixer/ComfyUI_MiniMaxH3_Director) revision `576424fb252b2b4a538e792027f7db1a5ef376e4`.

See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE) for the complete terms and attribution.
