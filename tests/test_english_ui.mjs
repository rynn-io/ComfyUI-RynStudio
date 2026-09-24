import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import * as i18n from "../web/js/minimax_i18n.js";

const timelineSource = await readFile(
    new URL("../web/js/minimax_timeline.js", import.meta.url),
    "utf8",
);

test("Director UI translations are English-only", () => {
    assert.equal(i18n.t("toolbar.addRefGroup"), "Add asset group");
    assert.equal(i18n.t("run.detailOverall", { pct: 42 }), "Overall 42%");
    assert.equal("toggleLocale" in i18n, false);
    assert.equal("setLocale" in i18n, false);
    assert.equal("onLocaleChange" in i18n, false);
});

test("Director toolbar does not expose a language toggle", () => {
    assert.doesNotMatch(timelineSource, /data-a=["']lang-toggle["']/);
    assert.doesNotMatch(timelineSource, /toggleLocale/);
});
