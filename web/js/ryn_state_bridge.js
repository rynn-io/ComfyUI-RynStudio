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
    if (kind === "image") return String(picked.imageFile || picked.relPath || "");
    if (kind === "audio") return String(picked.audioFile || picked.relPath || "");
    return String(picked.videoFile || picked.relPath || "");
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
    const shared = scene.sharedReferences || { images: [], videos: [], audio: [] };
    const sharedImages = (shared.images || []).map((ref) => assetMeta(assets.get(ref.assetId), Number(ref.slot) - 1));
    const sharedVideos = (shared.videos || []).map((ref) => assetMeta(assets.get(ref.assetId), Number(ref.slot) - 1));
    const sharedAudio = (shared.audio || []).map((ref) => assetMeta(assets.get(ref.assetId), Number(ref.slot) - 1));
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
        global: {
            taskType: "r2v — Reference to Video",
            prompt: "",
            commonEnabled: !!(sharedImages.length || sharedVideos.length || sharedAudio.length),
            refs: sharedImages,
            refVideos: sharedVideos,
            refAudios: sharedAudio,
            continuousReference: false,
        },
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
    const global = timeline.global || {};
    for (const ref of global.refs || []) register("image", ref);
    for (const ref of global.refVideos || []) register("video", ref);
    for (const ref of global.refAudios || []) register("audio", ref);
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
        sharedReferences: {
            images: (timeline.global?.refs || []).map((ref) => ({ slot: Number(ref.index ?? ref.slot ?? 0) + 1, assetId: register("image", ref) })).filter((ref) => ref.assetId),
            videos: (timeline.global?.refVideos || []).map((ref) => ({ slot: Number(ref.index ?? ref.slot ?? 0) + 1, assetId: register("video", ref) })).filter((ref) => ref.assetId),
            audio: (timeline.global?.refAudios || []).map((ref) => ({ slot: Number(ref.index ?? ref.slot ?? 0) + 1, assetId: register("audio", ref) })).filter((ref) => ref.assetId),
        },
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

export function assignAsset(editor, asset, target = "segment") {
    const holder = target === "shared"
        ? editor.timeline?.global
        : editor.timeline?.segments?.[editor.selectedIndex || 0];
    if (!holder) return false;
    const map = assetMeta(asset, 0);
    if (asset.kind === "image") {
        if ((holder.refs || []).some((ref) => refKey("image", ref) === refKey("image", map))) return false;
        const slot = nextSlot(holder.refs, 9); if (slot < 0) return false;
        holder.refs = [...(holder.refs || []), { ...map, index: slot }];
    } else if (asset.kind === "video") {
        if ((holder.refVideos || []).some((ref) => refKey("video", ref) === refKey("video", map))) return false;
        const slot = nextSlot(holder.refVideos, 3); if (slot < 0) return false;
        holder.refVideos = [...(holder.refVideos || []), { ...map, index: slot }];
    } else {
        if ((holder.refAudios || []).some((ref) => refKey("audio", ref) === refKey("audio", map))) return false;
        const slot = nextSlot(holder.refAudios, 3); if (slot < 0) return false;
        holder.refAudios = [...(holder.refAudios || []), { ...map, index: slot }];
    }
    if (target === "shared") holder.commonEnabled = true;
    editor.render?.();
    editor.commit?.();
    return true;
}

function hideNativeWidget(target) {
    if (!target) return;
    target.hidden = true;
    target.options = { ...(target.options || {}), hidden: true };
    target.computeSize = () => [0, 0];
    if (target.element) target.element.style.display = "none";
}

function removeAssetAssignment(editor, asset, target) {
    const holder = target === "shared"
        ? editor.timeline?.global
        : editor.timeline?.segments?.[editor.selectedIndex || 0];
    if (!holder) return;
    const key = String(asset?.storage?.key || "").replaceAll("\\", "/");
    const remove = (kind, refs) => (refs || []).filter((ref) => refKey(kind, ref) !== key);
    holder.refs = remove("image", holder.refs);
    holder.refVideos = remove("video", holder.refVideos);
    holder.refAudios = remove("audio", holder.refAudios);
    if (target === "shared") {
        holder.commonEnabled = !!(holder.refs.length || holder.refVideos.length || holder.refAudios.length);
    }
    editor.renderImageBatchGroups?.();
    editor.commit?.();
}

function assetIsAssigned(editor, asset, target) {
    const holder = target === "shared"
        ? editor.timeline?.global
        : editor.timeline?.segments?.[editor.selectedIndex || 0];
    if (!holder) return false;
    const key = String(asset?.storage?.key || "").replaceAll("\\", "/");
    return (holder.refs || []).some((ref) => refKey("image", ref) === key)
        || (holder.refVideos || []).some((ref) => refKey("video", ref) === key)
        || (holder.refAudios || []).some((ref) => refKey("audio", ref) === key);
}

function mediaPreviewUrl(asset) {
    if (asset?.kind !== "image") return "";
    const key = String(asset.storage?.key || "").replaceAll("\\", "/");
    const parts = key.split("/");
    const filename = parts.pop() || "";
    const params = new URLSearchParams({ filename, subfolder: parts.join("/"), type: "input" });
    return `/view?${params}`;
}

function mountRynSettings(editor) {
    const panel = document.createElement("section");
    panel.className = "ryn-settings";
    panel.setAttribute("data-ryn-settings", "");
    panel.innerHTML = `<div class="ryn-panel-heading"><div><b>Generation settings</b><span>Controls are saved with this Director node.</span></div></div>`;

    const definitions = [
        {
            title: "Sampling settings", open: true,
            fields: [
                ["seed", "Seed"],
                ["control_after_generate", "After generation"],
                ["live_preview", "Live preview"],
            ],
        },
        {
            title: "Advanced sampling", open: false,
            fields: [
                ["steps", "Steps"], ["sampler", "Sampler"], ["scheduler", "Scheduler"],
                ["shift_video", "Video shift"], ["shift_audio", "Audio shift"],
            ],
        },
        {
            title: "Performance", open: false,
            fields: [
                ["clear_vram_between_segments", "Clear VRAM between segments"],
                ["export_source_images", "Export source images"],
                ["low_vram_attention", "Low-VRAM attention"],
                ["attention_head_chunks", "Attention head chunks", "low_vram_attention"],
                ["chunk_feed_forward", "Chunk feed-forward"],
                ["feed_forward_chunks", "Feed-forward chunks", "chunk_feed_forward"],
                ["feed_forward_sequence_threshold", "Sequence threshold", "chunk_feed_forward"],
                ["fp16_accumulation", "FP16 accumulation"],
                ["comfy_kitchen_attention", "Comfy Kitchen INT8 attention"],
            ],
        },
    ];

    const controls = new Map();
    const refreshDependencies = () => {
        for (const [name, record] of controls) {
            if (!record.parent) continue;
            const parentWidget = widget(editor.node, record.parent);
            record.row.classList.toggle("ryn-dependent-hidden", !parentWidget?.value);
        }
    };

    for (const section of definitions) {
        const details = document.createElement("details");
        details.className = "ryn-settings-group";
        details.open = section.open;
        details.innerHTML = `<summary>${section.title}</summary><div class="ryn-settings-grid"></div>`;
        const grid = details.querySelector(".ryn-settings-grid");
        for (const [name, label, parent] of section.fields) {
            const sourceWidget = widget(editor.node, name);
            if (!sourceWidget) continue;
            hideNativeWidget(sourceWidget);
            const row = document.createElement("label");
            row.className = "ryn-setting-row";
            const caption = document.createElement("span");
            caption.textContent = label;
            row.append(caption);
            const values = sourceWidget.options?.values;
            let input;
            if (Array.isArray(values)) {
                input = document.createElement("select");
                for (const value of values) {
                    const option = document.createElement("option");
                    option.value = String(value);
                    option.textContent = String(value);
                    input.append(option);
                }
                input.value = String(sourceWidget.value ?? "");
            } else if (typeof sourceWidget.value === "boolean") {
                input = document.createElement("input");
                input.type = "checkbox";
                input.checked = !!sourceWidget.value;
            } else {
                input = document.createElement("input");
                input.type = typeof sourceWidget.value === "number" ? "number" : "text";
                if (sourceWidget.options?.min != null) input.min = sourceWidget.options.min;
                if (sourceWidget.options?.max != null) input.max = sourceWidget.options.max;
                if (sourceWidget.options?.step != null) input.step = sourceWidget.options.step;
                input.value = String(sourceWidget.value ?? "");
            }
            input.dataset.widget = name;
            input.onchange = () => {
                const next = input.type === "checkbox"
                    ? input.checked
                    : input.type === "number" ? Number(input.value) : input.value;
                sourceWidget.value = next;
                sourceWidget.callback?.(next);
                editor.node?.setDirtyCanvas?.(true, true);
                syncRynStateWidgets(editor, editor.timeline);
                refreshDependencies();
            };
            row.append(input);
            grid.append(row);
            controls.set(name, { row, parent });
        }
        panel.append(details);
    }
    for (const name of ["bd_grp_sample", "bd_grp_advanced", "bd_grp_perf"]) hideNativeWidget(widget(editor.node, name));
    refreshDependencies();
    return panel;
}

export function mountRynControls(editor) {
    if (!isRynDirectorNode(editor.node) || !editor.root || editor._rynControlsMounted) return;
    editor._rynControlsMounted = true;

    const style = document.createElement("style");
    style.textContent = `
.ryn-workspace{display:grid;gap:10px;margin:0 0 10px}.ryn-resource-panel,.ryn-settings{border:1px solid var(--border,#454545);border-radius:10px;background:var(--card,#242424);padding:10px;box-sizing:border-box}.ryn-panel-heading{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:9px}.ryn-panel-heading>div{display:grid;gap:2px}.ryn-panel-heading span,.ryn-empty,.ryn-asset-meta{font-size:11px;color:var(--muted-foreground,#aaa)}.ryn-resource-columns{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(260px,.65fr);gap:10px}.ryn-resource-card{border:1px solid var(--border,#454545);border-radius:8px;padding:9px;background:rgba(0,0,0,.12)}.ryn-resource-title{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px}.ryn-actions{display:flex;gap:6px;flex-wrap:wrap}.ryn-actions button,.ryn-asset-actions button,.ryn-lora-actions button{border:1px solid var(--border,#555);border-radius:6px;padding:5px 8px;background:var(--card,#303030);color:var(--foreground,#eee);cursor:pointer}.ryn-actions button:hover,.ryn-asset-actions button:hover,.ryn-lora-actions button:hover{border-color:var(--accent,#4fff8f)}.ryn-asset-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:7px}.ryn-asset{display:grid;grid-template-columns:48px minmax(0,1fr);gap:8px;padding:7px;border:1px solid var(--border,#444);border-radius:7px}.ryn-asset-preview{width:48px;height:48px;border-radius:6px;object-fit:cover;background:rgba(0,0,0,.25);display:grid;place-items:center;font-size:20px}.ryn-asset-name{font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.ryn-kind{font-size:10px;text-transform:uppercase;color:var(--accent,#4fff8f)}.ryn-asset-actions{grid-column:1/-1;display:flex;gap:5px;flex-wrap:wrap}.ryn-asset-actions button.active{border-color:var(--accent,#4fff8f);color:var(--accent,#4fff8f)}.ryn-lora-list{display:grid;gap:7px}.ryn-lora{display:grid;grid-template-columns:minmax(110px,1fr) 78px auto;gap:6px;align-items:center}.ryn-lora input[type=text],.ryn-lora input[type=number],.ryn-setting-row input,.ryn-setting-row select{min-width:0;width:100%;box-sizing:border-box;border:1px solid var(--border,#555);border-radius:6px;padding:5px 7px;background:rgba(0,0,0,.2);color:var(--foreground,#eee)}.ryn-lora-actions{grid-column:1/-1;display:flex;gap:5px}.ryn-settings{display:grid;gap:7px}.ryn-settings-group{border:1px solid var(--border,#444);border-radius:8px;padding:0 9px}.ryn-settings-group summary{cursor:pointer;padding:8px 0;font-weight:650}.ryn-settings-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:7px;padding:0 0 9px}.ryn-setting-row{display:grid;grid-template-columns:minmax(0,1fr) minmax(90px,.8fr);align-items:center;gap:8px;padding:6px 7px;border-radius:7px;background:rgba(0,0,0,.12);font-size:11px}.ryn-setting-row input[type=checkbox]{justify-self:end;width:17px;height:17px;accent-color:var(--accent,#4fff8f)}.ryn-dependent-hidden{display:none!important}@media(max-width:760px){.ryn-resource-columns{grid-template-columns:1fr}.ryn-settings-grid{grid-template-columns:1fr}}`;

    const workspace = document.createElement("div");
    workspace.className = "ryn-workspace";
    workspace.append(style);

    const panel = document.createElement("section");
    panel.className = "ryn-resource-panel";
    panel.innerHTML = `<div class="ryn-panel-heading"><div><b>Project resources</b><span>Reuse media across the whole scene or assign it only to the selected segment.</span></div></div><div class="ryn-resource-columns"><div class="ryn-resource-card"><div class="ryn-resource-title"><b>Shared assets</b><div class="ryn-actions"><button data-add-image>+ Image</button><button data-add-video>+ Video</button><button data-add-audio>+ Audio</button></div></div><div class="ryn-asset-grid" data-ryn-assets></div></div><div class="ryn-resource-card"><div class="ryn-resource-title"><b>MODEL LoRAs</b><button data-add-lora>+ Add</button></div><div class="ryn-lora-list" data-ryn-loras></div></div></div>`;
    workspace.append(panel, mountRynSettings(editor));
    editor.root.prepend(workspace);

    if (editor.globalTask) {
        const r2vOption = [...editor.globalTask.options].find((option) => String(option.value).toLowerCase().startsWith("r2v"));
        if (r2vOption) editor.globalTask.value = r2vOption.value;
        editor.globalTask.disabled = true;
        editor.globalTask.title = "Ryn H3 Director is R2V-only";
    }

    const currentScene = (documentState) => {
        const activeSceneId = String(widget(editor.node, "scene_id")?.value || documentState.scenes[0]?.id || "");
        return documentState.scenes.find((item) => item.id === activeSceneId) || documentState.scenes[0];
    };
    const saveStack = (documentState, scene, stack) => {
        const current = parseJson(widget(editor.node, "ryn_state")?.value, documentState);
        const target = current.scenes.find((item) => item.id === scene.id) || current.scenes[0];
        target.settings.loraStack = stack.map((entry, order) => ({ ...entry, order }));
        widget(editor.node, "ryn_state").value = JSON.stringify(current);
    };
    const render = () => {
        const documentState = timelineToRynState(editor, editor.timeline);
        const scene = currentScene(documentState);
        const assetBox = panel.querySelector("[data-ryn-assets]");
        assetBox.replaceChildren();
        if (!documentState.assets.length) {
            const empty = document.createElement("div");
            empty.className = "ryn-empty";
            empty.textContent = "No assets yet. Add existing ComfyUI input media to reuse it here.";
            assetBox.append(empty);
        }
        for (const asset of documentState.assets) {
            const card = document.createElement("article");
            card.className = "ryn-asset";
            const previewUrl = mediaPreviewUrl(asset);
            const preview = previewUrl ? document.createElement("img") : document.createElement("div");
            preview.className = "ryn-asset-preview";
            if (previewUrl) { preview.src = previewUrl; preview.alt = ""; }
            else preview.textContent = asset.kind === "video" ? "▶" : asset.kind === "audio" ? "♪" : "▧";
            const info = document.createElement("div");
            const name = document.createElement("div"); name.className = "ryn-asset-name"; name.textContent = asset.name;
            const kind = document.createElement("div"); kind.className = "ryn-kind"; kind.textContent = asset.kind;
            info.append(name, kind);
            const actions = document.createElement("div"); actions.className = "ryn-asset-actions";
            const sharedOn = assetIsAssigned(editor, asset, "shared");
            const segmentOn = assetIsAssigned(editor, asset, "segment");
            const sharedButton = document.createElement("button");
            sharedButton.classList.toggle("active", sharedOn);
            sharedButton.textContent = sharedOn ? "Remove from all segments" : "Use in all segments";
            sharedButton.onclick = () => { sharedOn ? removeAssetAssignment(editor, asset, "shared") : assignAsset(editor, asset, "shared"); render(); };
            const segmentButton = document.createElement("button");
            segmentButton.classList.toggle("active", segmentOn);
            segmentButton.textContent = segmentOn ? "Unassign selected segment" : "Assign to selected segment";
            segmentButton.onclick = () => { segmentOn ? removeAssetAssignment(editor, asset, "segment") : assignAsset(editor, asset, "segment"); render(); };
            const removeButton = document.createElement("button"); removeButton.textContent = "Remove asset";
            removeButton.onclick = () => {
                removeAssetAssignment(editor, asset, "shared");
                for (let index = 0; index < (editor.timeline?.segments?.length || 0); index++) {
                    const previous = editor.selectedIndex; editor.selectedIndex = index;
                    removeAssetAssignment(editor, asset, "segment"); editor.selectedIndex = previous;
                }
                const current = parseJson(widget(editor.node, "ryn_state")?.value, documentState);
                current.assets = (current.assets || []).filter((item) => item.id !== asset.id);
                widget(editor.node, "ryn_state").value = JSON.stringify(current);
                render();
            };
            actions.append(sharedButton, segmentButton, removeButton);
            card.append(preview, info, actions);
            assetBox.append(card);
        }

        const loraBox = panel.querySelector("[data-ryn-loras]");
        loraBox.replaceChildren();
        const stack = scene.settings.loraStack;
        if (!stack.length) {
            const empty = document.createElement("div"); empty.className = "ryn-empty";
            empty.textContent = "No MODEL LoRAs. LoRAs are applied in the displayed order.";
            loraBox.append(empty);
        }
        stack.forEach((entry, index) => {
            const row = document.createElement("div"); row.className = "ryn-lora";
            const file = document.createElement("input"); file.type = "text"; file.placeholder = "LoRA filename"; file.value = entry.filename || "";
            const strength = document.createElement("input"); strength.type = "number"; strength.step = "0.05"; strength.value = String(entry.strength ?? 1);
            const enabled = document.createElement("label");
            const check = document.createElement("input"); check.type = "checkbox"; check.checked = entry.enabled !== false;
            enabled.append(check, document.createTextNode(" Enabled"));
            const actions = document.createElement("div"); actions.className = "ryn-lora-actions";
            for (const [label, delta] of [["Move up", -1], ["Move down", 1]]) {
                const button = document.createElement("button"); button.textContent = label;
                button.disabled = index + delta < 0 || index + delta >= stack.length;
                button.onclick = () => { const next = index + delta; [stack[index], stack[next]] = [stack[next], stack[index]]; saveStack(documentState, scene, stack); render(); };
                actions.append(button);
            }
            const remove = document.createElement("button"); remove.textContent = "Remove";
            remove.onclick = () => { stack.splice(index, 1); saveStack(documentState, scene, stack); render(); };
            actions.append(remove);
            const save = () => { entry.filename = file.value; entry.strength = Number(strength.value || 0); entry.enabled = check.checked; saveStack(documentState, scene, stack); };
            file.onchange = save; strength.onchange = save; check.onchange = save;
            row.append(file, strength, enabled, actions);
            loraBox.append(row);
        });
        syncRynStateWidgets(editor, editor.timeline);
    };

    const addAsset = async (kind) => {
        const picker = kind === "image" ? editor.chooseImageInput : kind === "video" ? editor.chooseVideoInput : editor.chooseAudioInput;
        const picked = await picker?.call(editor, { title: `Add ${kind} to shared assets` });
        const key = mediaPickerKey(picked, kind);
        if (!key) return;
        const current = timelineToRynState(editor, editor.timeline);
        if (!(current.assets || []).some((asset) => asset.kind === kind && asset.storage?.key === key)) {
            current.assets.push({ id: uid("asset"), kind, name: picked.fileName || key.split("/").at(-1), storage: { scheme: "comfy-input", key }, contentHash: null, metadata: {} });
            widget(editor.node, "ryn_state").value = JSON.stringify(current);
        }
        render();
    };
    panel.querySelector("[data-add-image]").onclick = () => addAsset("image");
    panel.querySelector("[data-add-video]").onclick = () => addAsset("video");
    panel.querySelector("[data-add-audio]").onclick = () => addAsset("audio");
    panel.querySelector("[data-add-lora]").onclick = () => {
        const current = timelineToRynState(editor, editor.timeline);
        const scene = currentScene(current);
        scene.settings.loraStack.push({ id: uid("lora"), filename: "", strength: 1, enabled: true, order: scene.settings.loraStack.length });
        widget(editor.node, "ryn_state").value = JSON.stringify(current);
        render();
    };
    const updateSelectionUI = editor.updateSelectionUI?.bind(editor);
    if (updateSelectionUI) {
        editor.updateSelectionUI = (...args) => {
            const result = updateSelectionUI(...args);
            render();
            return result;
        };
    }
    render();
}
