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

  const commandRemainder = (queueOrder, currentSongId) => {
    const order = Array.isArray(queueOrder) ? queueOrder.map((songId) => String(songId || '')) : [];
    const currentIndex = order.indexOf(String(currentSongId || ''));
    return currentIndex >= 0 ? order.slice(currentIndex + 1) : [];
  };

  const queueSyncConfirmed = (snapshot, currentSongId, expectedQueueOrder) => {
    if (!snapshot?.songId || snapshot.songId !== String(currentSongId || '')) return false;
    if (!Array.isArray(snapshot.queueOrder) || snapshot.queueIndex < 0) return false;
    if (snapshot.queueOrder[snapshot.queueIndex] !== snapshot.songId) return false;
    const expectedRemainder = commandRemainder(expectedQueueOrder, currentSongId);
    const actualRemainder = snapshot.queueOrder.slice(snapshot.queueIndex + 1);
    return expectedRemainder.length === actualRemainder.length
      && expectedRemainder.every((songId, index) => songId && actualRemainder[index] === songId);
  };

  const priorityCatalogIdentifiers = (queueOrder, currentSongId, songs) => {
    const playlist = Array.isArray(songs) ? songs : [];
    const remainder = commandRemainder(queueOrder, currentSongId);
    const identifiers = remainder.map((songId) => (
      playlist.find((song) => String(song?.id || '') === songId)?.apple_music_id || ''
    ));
    return identifiers.every(Boolean) ? identifiers.map(String) : null;
  };

  return {
    commandRemainder,
    localQueueOrder,
    localSongIdForMediaItem,
    mediaItemIdentifiers,
    priorityCatalogIdentifiers,
    queueItems,
    queueSyncConfirmed,
    selectionChanged,
  };
});
