(function displayMediaModule(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.HalloweenDisplayMedia = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, () => {
  const MEDIA_TONES = new Set(['feature', 'video', 'custom', 'game']);

  const treatmentFor = (entry) => {
    const safeEntry = entry && typeof entry === 'object' ? entry : {};
    if (!safeEntry.image_url) return 'none';
    return safeEntry.media_treatment === 'foreground' ? 'foreground' : 'background';
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

  return { treatmentFor, toneFor, signatureFor, shouldReplaceSource };
});
