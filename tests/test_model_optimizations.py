from types import SimpleNamespace

from rynstudio.h3.model_optimizations import (
    apply_h3_optimizations,
    make_chunked_forward,
    make_head_chunked_attention,
)


class FakeTensor:
    def __init__(self, values, *, heads=None):
        self.values = list(values)
        self.shape = (1, heads, len(values), 1) if heads is not None else (len(values), 1)

    def __getitem__(self, key):
        head_slice = key[1]
        width = head_slice.stop - head_slice.start
        return FakeTensor(self.values, heads=width)

    def chunk(self, chunks, dim=0):
        assert dim == 0
        size = max(1, (len(self.values) + chunks - 1) // chunks)
        return [FakeTensor(self.values[i : i + size]) for i in range(0, len(self.values), size)]


class FakeContainer:
    def __init__(self, tensor):
        self.tensor = tensor

    def take(self):
        value = self.tensor
        self.tensor = None
        return value


class FakeModel:
    def __init__(self, blocks=2):
        self.model = SimpleNamespace(
            diffusion_model=SimpleNamespace(
                blocks=[SimpleNamespace(mlp=SimpleNamespace(forward=lambda x: x)) for _ in range(blocks)]
            )
        )
        self.object_patches = {}
        self.attention = None
        self.callbacks = []
        self.clone_count = 0

    def clone(self):
        cloned = FakeModel(0)
        cloned.model = self.model
        cloned.clone_count = self.clone_count + 1
        return cloned

    def add_object_patch(self, path, value):
        self.object_patches[path] = value

    def set_model_optimized_attention(self, value):
        self.attention = value

    def add_callback(self, kind, callback):
        self.callbacks.append((kind, callback))


def fake_cat(parts, dim):
    assert dim in (0, -1)
    return FakeTensor([value for part in parts for value in part.values])


def test_all_disabled_returns_original_model_without_importing_comfy():
    model = FakeModel()
    result = apply_h3_optimizations(model)
    assert result is model
    assert model.clone_count == 0


def test_chunked_forward_only_chunks_long_sequences():
    calls = []

    def original(value):
        calls.append(list(value.values))
        return value

    wrapped = make_chunked_forward(original, chunks=2, sequence_threshold=4, concatenate=fake_cat)
    short = FakeTensor(range(4))
    long = FakeTensor(range(5))

    assert wrapped(short) is short
    assert wrapped(long).values == list(range(5))
    assert calls == [list(range(4)), [0, 1, 2], [3, 4]]


def test_head_chunked_attention_splits_heads_and_restores_feature_axis():
    calls = []

    def base(q, k, v, heads, **kwargs):
        calls.append((q.take().shape[1], heads, kwargs["skip_reshape"]))
        return FakeTensor(range(heads))

    wrapped = make_head_chunked_attention(base, head_chunks=3, concatenate=fake_cat)
    result = wrapped(
        FakeContainer(FakeTensor([0], heads=8)),
        FakeContainer(FakeTensor([0], heads=8)),
        FakeContainer(FakeTensor([0], heads=8)),
        8,
        skip_reshape=True,
    )

    assert calls == [(3, 3, True), (3, 3, True), (2, 2, True)]
    assert result.values == list(range(3)) + list(range(3)) + list(range(2))


def test_enabled_optimizations_clone_and_patch_minimax_blocks():
    model = FakeModel()

    result = apply_h3_optimizations(
        model,
        chunk_feed_forward=True,
        feed_forward_chunks=2,
        feed_forward_sequence_threshold=4096,
        low_vram_attention=True,
        attention_head_chunks=4,
        attention_function=lambda *args, **kwargs: None,
        concatenate=fake_cat,
    )

    assert result is not model
    assert set(result.object_patches) == {
        "diffusion_model.blocks.0.mlp.forward",
        "diffusion_model.blocks.1.mlp.forward",
    }
    assert callable(result.attention)
