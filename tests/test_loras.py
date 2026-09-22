from rynstudio.h3.loras import apply_model_lora_stack


def test_empty_stack_preserves_model_and_clip_identity():
    model = object()
    clip = object()
    result_model, result_clip, applied = apply_model_lora_stack(model, clip, [])
    assert result_model is model
    assert result_clip is clip
    assert applied == ()


def test_enabled_loras_apply_to_model_only_in_ascending_order():
    model = "base-model"
    clip = object()
    calls = []

    def resolve(filename):
        calls.append(("resolve", filename))
        return f"/loras/{filename}"

    def load(path):
        calls.append(("load", path))
        return f"weights:{path}"

    def apply(current_model, current_clip, weights, strength_model, strength_clip):
        calls.append(("apply", current_model, current_clip, weights, strength_model, strength_clip))
        assert current_clip is None
        assert strength_clip == 0.0
        return f"{current_model}+{strength_model}", "must-be-ignored"

    stack = [
        {"id": "second", "filename": "b.safetensors", "strength": 0.5, "enabled": True, "order": 20},
        {"id": "disabled", "filename": "skip.safetensors", "strength": 1.0, "enabled": False, "order": 0},
        {"id": "first", "filename": "a.safetensors", "strength": 1.25, "enabled": True, "order": 10},
    ]
    result_model, result_clip, applied = apply_model_lora_stack(
        model,
        clip,
        stack,
        resolve_path=resolve,
        load_weights=load,
        apply_weights=apply,
    )

    assert result_model == "base-model+1.25+0.5"
    assert result_clip is clip
    assert [entry["id"] for entry in applied] == ["first", "second"]
    assert [call[1] for call in calls if call[0] == "resolve"] == ["a.safetensors", "b.safetensors"]
    assert all(call[2] is None for call in calls if call[0] == "apply")
