const test = require('node:test');
const assert = require('node:assert/strict');

const queueState = require('../static/dj-queue-state.js');

const playlist = [
  { id: 'song-a', apple_music_id: 'catalog-a' },
  { id: 'song-b', apple_music_id: 'catalog-b' },
  { id: 'song-c', apple_music_id: 'catalog-c' },
];

test('resolves catalog songs from direct MusicKit identifiers', () => {
  assert.equal(queueState.localSongIdForMediaItem({ id: 'catalog-b' }, playlist), 'song-b');
  assert.equal(
    queueState.localSongIdForMediaItem({ attributes: { playParams: { id: 'catalog-c' } } }, playlist),
    'song-c',
  );
});

test('resolves library songs through their catalog and reporting identifiers', () => {
  assert.equal(
    queueState.localSongIdForMediaItem({
      id: 'i.library-a',
      playParams: { id: 'i.library-a', catalogId: 'catalog-a' },
    }, playlist),
    'song-a',
  );
  assert.equal(
    queueState.localSongIdForMediaItem({
      attributes: { playParams: { id: 'i.library-c', reportingId: 'catalog-c' } },
    }, playlist),
    'song-c',
  );
});

test('preserves MusicKit resolved queue order including unknown placeholders', () => {
  const queue = {
    items: [
      { playParams: { catalogId: 'catalog-b' } },
      { id: 'unavailable-item' },
      { attributes: { playParams: { catalogId: 'catalog-a' } } },
    ],
  };
  assert.deepEqual(queueState.localQueueOrder(queue, playlist), ['song-b', '', 'song-a']);
});

test('requires an actual song or queue-position change before confirming next', () => {
  assert.equal(queueState.selectionChanged({ songId: 'song-b', queueIndex: 0 }, 'song-b', 0), false);
  assert.equal(queueState.selectionChanged({ songId: 'song-a', queueIndex: 1 }, 'song-b', 0), true);
  assert.equal(queueState.selectionChanged({ songId: 'song-b', queueIndex: 1 }, 'song-b', 0), true);
  assert.equal(queueState.selectionChanged({ songId: 'song-b', queueIndex: 0 }, 'song-b', 0, true), true);
});

test('builds the non-interrupting remainder after the confirmed current song', () => {
  assert.deepEqual(
    queueState.commandRemainder(['song-b', 'song-a', 'song-c'], 'song-b'),
    ['song-a', 'song-c'],
  );
  assert.deepEqual(queueState.commandRemainder(['song-a'], 'song-a'), []);
  assert.deepEqual(
    queueState.priorityCatalogIdentifiers(['song-b', 'song-a', 'song-c'], 'song-b', playlist),
    ['catalog-a', 'catalog-c'],
  );
  assert.equal(
    queueState.priorityCatalogIdentifiers(['song-b', 'missing'], 'song-b', playlist),
    null,
  );
});

test('confirms priority synchronization only from the exact resolved remainder', () => {
  const expected = ['song-b', 'song-a', 'song-c'];
  assert.equal(queueState.queueSyncConfirmed({
    songId: 'song-b',
    queueIndex: 1,
    queueOrder: ['already-played', 'song-b', 'song-a', 'song-c'],
  }, 'song-b', expected), true);
  assert.equal(queueState.queueSyncConfirmed({
    songId: 'song-b',
    queueIndex: 1,
    queueOrder: ['already-played', 'song-b', '', 'song-c'],
  }, 'song-b', expected), false);
  assert.equal(queueState.queueSyncConfirmed({
    songId: 'song-a',
    queueIndex: 2,
    queueOrder: ['already-played', 'song-b', 'song-a', 'song-c'],
  }, 'song-b', expected), false);
});
