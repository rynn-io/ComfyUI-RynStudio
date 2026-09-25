import assert from "node:assert/strict";
import test from "node:test";

import {
    assignAsset,
    installStringWidgetSerializer,
    mediaPickerKey,
    rynStateToTimeline,
    timelineToRynState,
} from "../web/js/ryn_state_bridge.js";

function state() {
    return {
        format: "ryn.h3-director-project",
        schemaVersion: 1,
        project: { id: "project-1", name: "Test" },
        assets: [
            { id: "assigned", kind: "image", name: "assigned.png", storage: { scheme: "comfy-input", key: "ryn/assigned.png" }, metadata: {} },
            { id: "unused", kind: "image", name: "unused.png", storage: { scheme: "comfy-input", key: "ryn/unused.png" }, metadata: {} },
        ],
        scenes: [{
            id: "scene-1", name: "Scene 1",
            settings: {
                frameRate: 24, width: 864, height: 480, referenceImageSize: "match", audioMode: "generate",
                continuityDefaults: { contextFrames: 22, mode: "continue", redrawStrength: 0.1, keepAlignmentTail: true },
                sampling: { steps: 25, sampler: "res_multistep", scheduler: "simple", cfg: 1, shiftVideo: 12, shiftAudio: 3 },
                loraStack: [{ id: "lora-1", filename: "style.safetensors", strength: 0.8, enabled: true, order: 0 }],
            },
            segments: [
                { id: "s1", prompt: "one", negativePrompt: "", frameCount: 90, references: { images: [{ slot: 1, assetId: "assigned" }], videos: [], audio: [] }, motionContext: { enabled: false, sourceSegmentId: null }, selectedTakeId: null },
                { id: "s2", prompt: "two", negativePrompt: "", frameCount: 90, references: { images: [], videos: [], audio: [] }, motionContext: { enabled: true, sourceSegmentId: "s1" }, selectedTakeId: null },
            ], takes: [],
        }],
    };
}

function editorFor(document, timeline) {
    const widgets = [
        { name: "ryn_state", value: JSON.stringify(document) },
        { name: "scene_id", value: "scene-1" },
        { name: "steps", value: 25 }, { name: "sampler", value: "res_multistep" },
        { name: "scheduler", value: "simple" }, { name: "cfg", value: 1 },
        { name: "shift_video", value: 12 }, { name: "shift_audio", value: 3 },
    ];
    return { node: { widgets }, timeline };
}

test("canonical state projects to explicit zero-based R2V slots", () => {
    const timeline = rynStateToTimeline(state(), "scene-1");
    assert.equal(timeline.global.commonEnabled, false);
    assert.deepEqual(timeline.global.refs, []);
    assert.equal(timeline.segments[0].refs[0].index, 0);
    assert.equal(timeline.segments[1].continuityFromPrev, true);
    assert.equal(timeline.output.continuityMode, "continue");
});

test("shared references survive canonical state and timeline round trips", () => {
    const document = state();
    document.scenes[0].sharedReferences = {
        images: [{ slot: 1, assetId: "assigned" }], videos: [], audio: [],
    };
    const timeline = rynStateToTimeline(document, "scene-1");
    assert.equal(timeline.global.commonEnabled, true);
    assert.equal(timeline.global.refs[0].imageFile, "ryn/assigned.png");

    const result = timelineToRynState(editorFor(document, timeline), timeline);
    assert.deepEqual(result.scenes[0].sharedReferences, document.scenes[0].sharedReferences);
});

test("media picker outputs map to portable Comfy input keys", () => {
    assert.equal(mediaPickerKey({ imageFile: "pool/character.png" }, "image"), "pool/character.png");
    assert.equal(mediaPickerKey({ videoFile: "pool/motion.mp4" }, "video"), "pool/motion.mp4");
    assert.equal(mediaPickerKey({ audioFile: "pool/voice.wav" }, "audio"), "pool/voice.wav");
});

test("asset assignment supports shared and selected-segment targets", () => {
    const timeline = rynStateToTimeline(state(), "scene-1");
    const editor = { timeline, selectedIndex: 1, render() {}, commit() {} };
    const asset = state().assets[1];

    assignAsset(editor, asset, "shared");
    assignAsset(editor, asset, "segment");

    assert.equal(timeline.global.commonEnabled, true);
    assert.equal(timeline.global.refs.at(-1).imageFile, "ryn/unused.png");
    assert.equal(timeline.segments[1].refs.at(-1).imageFile, "ryn/unused.png");
});

test("string widget serialization never forwards the ComfyNode into an older serializer", () => {
    const node = { widgets: [] };
    const widget = {
        value: "timeline-json",
        serializeValue(targetNode) {
            return targetNode;
        },
    };
    node.widgets.push(widget);

    installStringWidgetSerializer(widget, (targetNode, raw) => {
        assert.equal(targetNode, node);
        return `${raw}:witness`;
    });

    assert.equal(widget.serializeValue(node, 0), "timeline-json:witness");
    assert.doesNotThrow(() => JSON.stringify({ timeline_data: widget.serializeValue(node, 0) }));
});


test("UI round trip preserves unused assets, all scenes, and MODEL-only LoRA state", () => {
    const document = state();
    const second = structuredClone(document.scenes[0]);
    second.id = "scene-2";
    second.name = "Scene 2";
    document.scenes.push(second);
    const timeline = rynStateToTimeline(document, "scene-1");
    const result = timelineToRynState(editorFor(document, timeline), timeline);
    assert.deepEqual(result.assets.map((asset) => asset.id), ["assigned", "unused"]);
    assert.deepEqual(result.scenes[0].settings.loraStack, document.scenes[0].settings.loraStack);
    assert.equal(result.scenes.length, 2);
    assert.equal(result.scenes[1].id, "scene-2");
});
