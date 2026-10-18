(function displayMediaModule(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.HalloweenDisplayMedia = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, () => {
  const MEDIA_TONES = new Set(['feature', 'video', 'custom', 'game']);

  const treatmentFor = (entry) => {
    const safeEntry = entry && typeof entry === 'object' ? entry : {};
    if (!safeEntry.image_url) return 'none';
    return safeEntry.media_treatment === 'foreground' ? 'foreground' : 'none';
  };

  const centerFocusMode = (entry) => {
    const safeEntry = entry && typeof entry === 'object' ? entry : {};
    if (safeEntry.karaoke) return 'karaoke';
    if (Array.isArray(safeEntry.scoreboard?.entries) && safeEntry.scoreboard.entries.length) return 'scoreboard';
    if (safeEntry.cta) return 'cta';
    if (safeEntry.kind === 'action' && (safeEntry.action?.label || safeEntry.action?.url)) return 'action';
    if (safeEntry.secondary) return 'message';
    if (safeEntry.action?.label || safeEntry.action?.url) return 'action';
    if (Array.isArray(safeEntry.facts) && safeEntry.facts.length) return 'facts';
    if (Array.isArray(safeEntry.steps) && safeEntry.steps.length) return 'steps';
    if (safeEntry.link) return 'link';
    if (safeEntry.tertiary) return 'message';
    return 'title';
  };

  const gameFocusMode = (entry) => {
    const safeEntry = entry && typeof entry === 'object' ? entry : {};
    const requestedMode = String(safeEntry.focus_mode || '');
    if (['message', 'choices', 'spotlight', 'feature', 'metrics', 'action'].includes(requestedMode)) {
      return requestedMode;
    }
    if (Array.isArray(safeEntry.focus_items) && safeEntry.focus_items.length) return 'choices';
    if (Array.isArray(safeEntry.spotlight_rows) && safeEntry.spotlight_rows.length) return 'spotlight';
    if (safeEntry.feature_text) return 'feature';
    if (safeEntry.primary) return 'message';
    if (Array.isArray(safeEntry.metrics) && safeEntry.metrics.length) return 'metrics';
    if (safeEntry.action_label) return 'action';
    return 'message';
  };

  const toneFor = (entry) => {
    const safeEntry = entry && typeof entry === 'object' ? entry : {};
    const tone = String(safeEntry.media_tone || '').toLowerCase();
    return MEDIA_TONES.has(tone) ? tone : 'feature';
  };

  const signatureFor = (value) => {
    const normalize = (candidate) => {
      if (Array.isArray(candidate)) return candidate.map(normalize);
      if (!candidate || typeof candidate !== 'object') return candidate;
      return Object.keys(candidate).sort().reduce((result, key) => {
        const normalized = normalize(candidate[key]);
        if (typeof normalized !== 'undefined') result[key] = normalized;
        return result;
      }, {});
    };
    return JSON.stringify(normalize(value));
  };

  const shouldReplaceSource = (currentSource, requestedSource) => (
    String(currentSource || '') !== String(requestedSource || '')
  );

  return { treatmentFor, centerFocusMode, gameFocusMode, toneFor, signatureFor, shouldReplaceSource };
});
