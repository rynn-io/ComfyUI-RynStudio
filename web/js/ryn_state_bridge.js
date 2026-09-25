const FORMAT = "ryn.h3-director-project";
const SCHEMA_VERSION = 1;

function uid(prefix) {
    const raw = globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
    return `${prefix}-${raw}`;
}

export function isRynDirectorNode(node) {
    return (node?.comfyClass || node?.type || "") === "RynH3Director";
}

function widget(node, name) {
    return (node?.widgets || []).find((item) => item?.name === name) || null;
}

/**
 * Install a ComfyUI-compatible serializer for a hidden STRING widget.
 *
 * Frontend 1.51 passes the owning node as the first argument. Delegating to a
 * serializer from a different frontend contract can return that live node and
 * make prompt JSON serialization recurse through a circular graph. Hidden
 * state widgets already own their canonical string value, so serialize it
 * directly instead.
 */
export function installStringWidgetSerializer(target, transform = (_node, value) => value) {
    if (!target || target._rynStringSerializerInstalled) return;
    target._rynStringSerializerInstalled = true;
    target.serializeValue = function (node) {
        const value = typeof target.value === "string" ? target.value : String(target.value ?? "");
        const serialized = transform(node, value);
        return typeof serialized === "string" ? serialized : value;
    };
}

function parseJson(value, fallback = null) {
    try {
        const parsed = JSON.parse(String(value || ""));
        return parsed && typeof parsed === "object" ? parsed : fallback;
    } catch {
        return fallback;
    }
}

export function mediaPickerKey(picked, kind) {
    if (!picked || typeof picked !== "object") return "";
    return String(kind === "image"
        ? (picked.imageFile || picked.relPath || "")
        : (picked.videoFile || picked.relPath || ""));
}

function assetMeta(asset, index) {
    const key = String(asset?.storage?.key || "");
    const parts = key.split("/");
    const fileName = asset?.name || parts.at(-1) || key;
    const subfolder = parts.length > 1 ? parts.slice(0, -1).join("/") : "";
    const base = { index, fileName, type: "input", subfolder };
    if (asset.kind === "image") return { ...base, imageFile: key };
    if (asset.kind === "video") return { ...base, videoFile: key };
    return { ...base, audioFile: key };
}

export function rynStateToTimeline(document, sceneId = "") {
    if (document?.format !== FORMAT || document?.schemaVersion !== SCHEMA_VERSION) return null;
    const scene = document.scenes?.find((item) => item.id === sceneId) || document.scenes?.[0];
    if (!scene) return null;
    const assets = new Map((document.assets || []).map((asset) => [asset.id, asset]));
    const settings = scene.settings || {};
    const continuity = settings.continuityDefaults || {};
    let start = 0;
    const segments = (scene.segments || []).map((segment) => {
        const count = Number(segment.frameCount || 124);
        const refs = segment.references || {};
        const mapped = {
            id: segment.id,
            start,
            length: count,
            frameCount: count,
            durationSec: count / Number(settings.frameRate || 24),
            prompt: segment.prompt || "",
            negativePrompt: segment.negativePrompt || "",
            taskType: "r2v — Reference to Video",
            refs: (refs.images || []).map((ref) => assetMeta(assets.get(ref.assetId), Number(ref.slot) - 1)),
            refVideos: (refs.videos || []).map((ref) => assetMeta(assets.get(ref.assetId), Number(ref.slot) - 1)),
            refAudios: (refs.audio || []).map((ref) => assetMeta(assets.get(ref.assetId), Number(ref.slot) - 1)),
            continuityFromPrev: !!segment.motionContext?.enabled,
            refImageSize: settings.referenceImageSize || "match",
            genImage: { imageFile: "", fileName: "" },
        };
        start += count;
        return mapped;
    });
    return {
        version: 5,
        timelineMode: "prompt_batch",
        editMode: "segment",
        totalFrames: start,
        frameRate: Number(settings.frameRate || 24),
        width: Number(settings.width || 864),
        height: Number(settings.height || 480),
        refMaxSize: Math.max(Number(settings.width || 864), Number(settings.height || 480)),
        global: { taskType: "r2v — Reference to Video", prompt: "", commonEnabled: false, refs: [], refVideos: [], refAudios: [], continuousReference: false },
        output: {
            mode: "fixed", width: Number(settings.width || 864), height: Number(settings.height || 480),
            longEdge: Math.max(Number(settings.width || 864), Number(settings.height || 480)),
            exportMode: "all", audioMode: settings.audioMode || "generate",
            refImageSize: settings.referenceImageSize || "match",
            continuityEnabled: segments.some((segment) => segment.continuityFromPrev),
            continuityOverlapFrames: Number(continuity.contextFrames || 22),
            continuityMode: continuity.mode || "guide",
            continuityRedraw: Number(continuity.redrawStrength ?? 0.1),
            continuityKeepTail: continuity.keepAlignmentTail !== false,
            maxExportFrames: 0,
        },
        runSelectEnabled: false,
        runSelection: [],
        segments,
    };
}

function refKey(kind, ref) {
    const key = kind === "image" ? ref?.imageFile : kind === "video" ? ref?.videoFile : ref?.audioFile;
    return String(key || ref?.fileName || "").replaceAll("\\", "/");
}

function collectAssets(previous, timeline) {
    const assets = [...(previous?.assets || [])].map((asset) => structuredClone(asset));
    const byKey = new Map(assets.map((asset) => [`${asset.kind}:${asset.storage?.key}`, asset]));
    const register = (kind, ref) => {
        const key = refKey(kind, ref);
        if (!key) return null;
        const identity = `${kind}:${key}`;
        let asset = byKey.get(identity);
        if (!asset) {
            asset = {
                id: uid("asset"), kind, name: ref.fileName || key.split("/").at(-1),
                storage: { scheme: "comfy-input", key }, contentHash: null,
                metadata: { mimeType: null, width: null, height: null, durationSeconds: null },
            };
            assets.push(asset);
            byKey.set(identity, asset);
        }
        return asset.id;
    };
    for (const segment of timeline.segments || []) {
        for (const ref of segment.refs || []) register("image", ref);
        for (const ref of segment.refVideos || []) register("video", ref);
        for (const ref of segment.refAudios || []) register("audio", ref);
    }
    return { assets, register };
}

export function timelineToRynState(editor, timeline) {
    const stateWidget = widget(editor.node, "ryn_state");
    const previous = parseJson(stateWidget?.value, {});
    const project = previous.project || { id: uid("project"), name: "Ryn H3 Director Project" };
    const sceneWidget = widget(editor.node, "scene_id");
    const sceneId = String(sceneWidget?.value || previous.scenes?.[0]?.id || uid("scene"));
    if (sceneWidget) sceneWidget.value = sceneId;
    const previousScene = previous.scenes?.find((scene) => scene.id === sceneId) || previous.scenes?.[0] || {};
    const { assets, register } = collectAssets(previous, timeline);
    const output = timeline.output || {};
    const sampling = previousScene.settings?.sampling || {};
    const valueOf = (name, fallback) => widget(editor.node, name)?.value ?? fallback;
    const segments = (timeline.segments || []).map((segment, index, all) => ({
        id: String(segment.id || uid("segment")),
        prompt: String(segment.prompt || ""),
        negativePrompt: String(segment.negativePrompt || ""),
        frameCount: Number(segment.frameCount || segment.length || 124),
        references: {
            images: (segment.refs || []).map((ref) => ({ slot: Number(ref.index ?? ref.slot ?? 0) + 1, assetId: register("image", ref) })).filter((ref) => ref.assetId),
            videos: (segment.refVideos || []).map((ref) => ({ slot: Number(ref.index ?? ref.slot ?? 0) + 1, assetId: register("video", ref) })).filter((ref) => ref.assetId),
            audio: (segment.refAudios || []).map((ref) => ({ slot: Number(ref.index ?? ref.slot ?? 0) + 1, assetId: register("audio", ref) })).filter((ref) => ref.assetId),
        },
        motionContext: {
            enabled: index > 0 && !!segment.continuityFromPrev,
            sourceSegmentId: index > 0 && segment.continuityFromPrev ? String(all[index - 1].id) : null,
        },
        selectedTakeId: segment.selectedTakeId ?? null,
    }));
    const updatedScene = {
        id: sceneId,
        name: previousScene.name || "Scene 1",
        settings: {
            frameRate: Number(timeline.frameRate || valueOf("frame_rate", 24)),
            width: Number(timeline.width || output.width || valueOf("width", 864)),
            height: Number(timeline.height || output.height || valueOf("height", 480)),
            referenceImageSize: output.refImageSize || "match",
            audioMode: output.audioMode || "generate",
            continuityDefaults: {
                contextFrames: Number(output.continuityOverlapFrames || 22),
                mode: output.continuityMode || "guide",
                redrawStrength: Number(output.continuityRedraw ?? 0.1),
                keepAlignmentTail: output.continuityKeepTail !== false,
            },
            sampling: {
                steps: Number(valueOf("steps", sampling.steps || 25)),
                sampler: String(valueOf("sampler", sampling.sampler || "res_multistep")),
                scheduler: String(valueOf("scheduler", sampling.scheduler || "simple")),
                cfg: Number(valueOf("cfg", sampling.cfg ?? 1)),
                shiftVideo: Number(valueOf("shift_video", sampling.shiftVideo ?? 12)),
                shiftAudio: Number(valueOf("shift_audio", sampling.shiftAudio ?? 3)),
            },
            loraStack: [...(previousScene.settings?.loraStack || [])]
                .map(({ id, filename, strength, enabled, order }) => ({ id, filename, strength: Number(strength), enabled: !!enabled, order: Number(order) }))
                .sort((a, b) => a.order - b.order),
        },
        segments,
        takes: previousScene.takes || [],
    };
    const previousScenes = Array.isArray(previous.scenes) ? previous.scenes : [];
    const found = previousScenes.some((scene) => scene.id === sceneId);
    const scenes = found
        ? previousScenes.map((scene) => scene.id === sceneId ? updatedScene : structuredClone(scene))
        : [...previousScenes.map((scene) => structuredClone(scene)), updatedScene];
    return {
        format: FORMAT,
        schemaVersion: SCHEMA_VERSION,
        project,
        assets,
        scenes,
    };
}

export function initializeRynEditor(editor) {
    if (!isRynDirectorNode(editor.node)) return;
    const stateWidget = widget(editor.node, "ryn_state");
    const sceneWidget = widget(editor.node, "scene_id");
    const document = parseJson(stateWidget?.value);
    const timeline = rynStateToTimeline(document, String(sceneWidget?.value || ""));
    if (timeline && editor.timelineWidget) editor.timelineWidget.value = JSON.stringify(timeline);
    if (editor.taskTypeWidget) {
        const values = editor.taskTypeWidget.options?.values || [];
        editor.taskTypeWidget.value = values.find((value) => String(value).toLowerCase().startsWith("r2v")) || "r2v — Reference to Video";
    }
    const scene = document?.scenes?.find((item) => item.id === sceneWidget?.value) || document?.scenes?.[0];
    const sampling = scene?.settings?.sampling;
    if (sampling) {
        for (const [name, key] of [["steps", "steps"], ["sampler", "sampler"], ["scheduler", "scheduler"], ["cfg", "cfg"], ["shift_video", "shiftVideo"], ["shift_audio", "shiftAudio"]]) {
            const target = widget(editor.node, name);
            if (target && sampling[key] != null) target.value = sampling[key];
        }
    }
}

export function syncRynStateWidgets(editor, timeline) {
    if (!isRynDirectorNode(editor.node)) return;
    const document = timelineToRynState(editor, timeline);
    const stateWidget = widget(editor.node, "ryn_state");
    if (stateWidget) stateWidget.value = JSON.stringify(document);
    const commandWidget = widget(editor.node, "runtime_command");
    if (commandWidget) {
        const sceneId = String(widget(editor.node, "scene_id")?.value || document.scenes[0]?.id || "");
        const scene = document.scenes.find((item) => item.id === sceneId) || document.scenes[0];
        const selected = timeline.runSelectEnabled
            ? (timeline.runSelection || []).map((index) => scene.segments[index]?.id).filter(Boolean)
            : [];
        commandWidget.value = selected.length
            ? JSON.stringify({ sceneId: scene.id, segmentIds: selected, outputMode: timeline.output?.exportMode === "all" ? "all" : "segments" })
            : "";
    }
}

function nextSlot(list, limit) {
    const used = new Set((list || []).map((ref) => Number(ref.index ?? ref.slot ?? 0)));
    for (let index = 0; index < limit; index++) if (!used.has(index)) return index;
    return -1;
}

function assignAsset(editor, asset) {
    const segment = editor.timeline?.segments?.[editor.selectedIndex || 0];
    if (!segment) return;
    const map = assetMeta(asset, 0);
    if (asset.kind === "image") {
        const slot = nextSlot(segment.refs, 9); if (slot < 0) return;
        segment.refs = [...(segment.refs || []), { ...map, index: slot }];
    } else if (asset.kind === "video") {
        const slot = nextSlot(segment.refVideos, 3); if (slot < 0) return;
        segment.refVideos = [...(segment.refVideos || []), { ...map, index: slot }];
    } else {
        const slot = nextSlot(segment.refAudios, 3); if (slot < 0) return;
        segment.refAudios = [...(segment.refAudios || []), { ...map, index: slot }];
    }
    editor.render?.();
    editor.commit?.();
}

export function mountRynControls(editor) {
    if (!isRynDirectorNode(editor.node) || !editor.root || editor._rynControlsMounted) return;
    editor._rynControlsMounted = true;
    const panel = document.createElement("details");
    panel.className = "bd-section";
    panel.open = true;
    panel.innerHTML = `<summary>Ryn shared asset pool & MODEL LoRAs</summary><div data-ryn-assets></div><div class="bd-row"><button data-add-image>Add existing image</button><button data-add-video>Add existing video</button></div><div data-ryn-loras></div><button data-add-lora>Add MODEL LoRA</button>`;
    editor.root.prepend(panel);
    if (editor.globalTask) {
        const r2vOption = [...editor.globalTask.options].find((option) => String(option.value).toLowerCase().startsWith("r2v"));
        if (r2vOption) editor.globalTask.value = r2vOption.value;
        editor.globalTask.disabled = true;
        editor.globalTask.title = "Ryn H3 Director 0.1 is R2V-only";
    }
    if (editor.timeline?.global) {
        editor.timeline.global.commonEnabled = false;
        editor.timeline.global.refs = [];
        editor.timeline.global.refVideos = [];
        editor.timeline.global.refAudios = [];
    }
    const render = () => {
        const documentState = timelineToRynState(editor, editor.timeline);
        const activeSceneId = String(widget(editor.node, "scene_id")?.value || documentState.scenes[0]?.id || "");
        const scene = documentState.scenes.find((item) => item.id === activeSceneId) || documentState.scenes[0];
        const assetBox = panel.querySelector("[data-ryn-assets]");
        assetBox.innerHTML = documentState.assets.length ? "" : `<div class="bd-muted">No shared assets yet. Segment uploads are registered automatically.</div>`;
        for (const asset of documentState.assets) {
            const row = document.createElement("div"); row.className = "bd-row";
            row.innerHTML = `<span>${asset.kind}: ${asset.name}</span><button>Assign to selected segment</button>`;
            row.querySelector("button").onclick = () => assignAsset(editor, asset);
            assetBox.append(row);
        }
        const loraBox = panel.querySelector("[data-ryn-loras]"); loraBox.innerHTML = "";
        for (const entry of scene.settings.loraStack) {
            const row = document.createElement("div"); row.className = "bd-row";
            row.innerHTML = `<input data-file placeholder="LoRA filename" value="${String(entry.filename || "").replaceAll('"', '&quot;')}"><input data-strength type="number" step="0.05" value="${entry.strength}"><label><input data-enabled type="checkbox" ${entry.enabled ? "checked" : ""}> enabled</label><button>Remove</button>`;
            const save = () => {
                entry.filename = row.querySelector("[data-file]").value;
                entry.strength = Number(row.querySelector("[data-strength]").value || 0);
                entry.enabled = row.querySelector("[data-enabled]").checked;
                const current = parseJson(widget(editor.node, "ryn_state")?.value, documentState);
                const target = current.scenes?.find((item) => item.id === scene.id) || current.scenes?.[0];
                target.settings.loraStack = scene.settings.loraStack;
                widget(editor.node, "ryn_state").value = JSON.stringify(current);
            };
            row.onchange = save;
            row.querySelector("button").onclick = () => { scene.settings.loraStack = scene.settings.loraStack.filter((item) => item.id !== entry.id); const current = parseJson(widget(editor.node, "ryn_state")?.value, documentState); const target = current.scenes.find((item) => item.id === scene.id) || current.scenes[0]; target.settings.loraStack = scene.settings.loraStack.map((item, order) => ({ ...item, order })); widget(editor.node, "ryn_state").value = JSON.stringify(current); render(); };
            loraBox.append(row);
        }
        syncRynStateWidgets(editor, editor.timeline);
    };
    panel.querySelector("[data-add-image]").onclick = async () => {
        const picked = await editor.chooseImageInput?.({ title: "Add image to shared asset pool" });
        const key = mediaPickerKey(picked, "image");
        if (!key) return;
        const current = timelineToRynState(editor, editor.timeline);
        current.assets.push({ id: uid("asset"), kind: "image", name: picked.fileName || key.split("/").at(-1), storage: { scheme: "comfy-input", key }, contentHash: null, metadata: {} });
        widget(editor.node, "ryn_state").value = JSON.stringify(current); render();
    };
    panel.querySelector("[data-add-video]").onclick = async () => {
        const picked = await editor.chooseVideoInput?.({ title: "Add video to shared asset pool" });
        const key = mediaPickerKey(picked, "video");
        if (!key) return;
        const current = timelineToRynState(editor, editor.timeline);
        current.assets.push({ id: uid("asset"), kind: "video", name: picked.fileName || key.split("/").at(-1), storage: { scheme: "comfy-input", key }, contentHash: null, metadata: {} });
        widget(editor.node, "ryn_state").value = JSON.stringify(current); render();
    };
    panel.querySelector("[data-add-lora]").onclick = () => {
        const current = timelineToRynState(editor, editor.timeline);
        const activeSceneId = String(widget(editor.node, "scene_id")?.value || current.scenes[0]?.id || "");
        const target = current.scenes.find((item) => item.id === activeSceneId) || current.scenes[0];
        const stack = target.settings.loraStack;
        stack.push({ id: uid("lora"), filename: "", strength: 1, enabled: true, order: stack.length });
        widget(editor.node, "ryn_state").value = JSON.stringify(current); render();
    };
    render();
}
