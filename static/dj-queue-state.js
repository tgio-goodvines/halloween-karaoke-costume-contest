((root, factory) => {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.HalloweenDjQueueState = api;
})(typeof window !== 'undefined' ? window : globalThis, () => {
  const mediaItemIdentifiers = (item) => [
    item?.id,
    item?.playParams?.id,
    item?.playParams?.catalogId,
    item?.playParams?.reportingId,
    item?.attributes?.playParams?.id,
    item?.attributes?.playParams?.catalogId,
    item?.attributes?.playParams?.reportingId,
  ].filter(Boolean).map(String);

  const localSongIdForMediaItem = (item, songs) => {
    const playlist = Array.isArray(songs) ? songs : [];
    const identifiers = new Set(mediaItemIdentifiers(item));
    const song = playlist.find((entry) => (
      entry && identifiers.has(String(entry.apple_music_id || ''))
    ));
    return song ? String(song.id || '') : '';
  };

  const queueItems = (queueCandidate) => {
    const items = queueCandidate?.items;
    if (Array.isArray(items)) return items;
    if (!items || typeof items[Symbol.iterator] !== 'function') return [];
    return [...items];
  };

  const localQueueOrder = (queueCandidate, songs) => (
    queueItems(queueCandidate).map((item) => localSongIdForMediaItem(item, songs))
  );

  const selectionChanged = (snapshot, previousSongId, previousQueueIndex, allowSame = false) => Boolean(
    snapshot?.songId
    && (
      allowSame
      || snapshot.songId !== previousSongId
      || snapshot.queueIndex !== previousQueueIndex
    )
  );

  return {
    localQueueOrder,
    localSongIdForMediaItem,
    mediaItemIdentifiers,
    queueItems,
    selectionChanged,
  };
});
