/** External graph groups are outside the Ryn H3 Director MVP boundary. */
export function attachExternalGroupsWitness(timeline) {
    if (timeline && typeof timeline === "object") delete timeline.externalGroupsWitness;
    return timeline;
}

export function injectExternalGroupsWitness(timeline) {
    if (timeline && typeof timeline === "object") delete timeline.externalGroupsWitness;
    return timeline;
}

export function setExternalGroupSpecsProvider() {
    // Intentionally disabled: Ryn v1 has one canonical execution authority.
}
