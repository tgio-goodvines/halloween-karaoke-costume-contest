const test = require('node:test');
const assert = require('node:assert/strict');

const widgets = require('../static/dj-live-widgets.js');

class FakeElement {
  constructor(dataset = {}) {
    this.dataset = { ...dataset };
    this.attributes = new Map();
    this.textContent = '';
    this.alt = '';
    this.hidden = false;
  }

  getAttribute(name) { return this.attributes.get(name) ?? null; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  removeAttribute(name) { this.attributes.delete(name); }
}

const widgetFixture = () => {
  const elements = new Map([
    ['[data-live-dj-title]', new FakeElement({ playingPrefix: 'Now Playing: ', emptyText: 'The DJ Is Ready' })],
    ['[data-live-dj-artist]', new FakeElement({ emptyText: 'Browse the playlist.' })],
    ['[data-live-dj-status]', new FakeElement()],
    ['[data-live-dj-request-link]', new FakeElement({ baseLabel: 'Open Jukebox' })],
    ['[data-live-dj-receiver-status]', new FakeElement()],
    ['[data-live-dj-admin-summary]', new FakeElement()],
    ['[data-live-dj-music-visible]', new FakeElement()],
    ['[data-live-dj-artwork-wrap]', new FakeElement()],
    ['[data-live-dj-artwork]', new FakeElement()],
  ]);
  return {
    elements,
    root: {
      dataset: {},
      querySelector: (selector) => elements.get(selector) || null,
    },
  };
};

test('normalizes attendee and admin DJ payloads into one widget contract', () => {
  const attendee = widgets.buildWidgetView({
    now_playing: { id: 'song-a', title: 'Song A', artist: 'Artist A' },
    playback_status: 'playing',
    pending_requests: [{ id: 'request-1' }],
    playlist: [{ id: 'song-a' }, { id: 'song-b' }],
    update_version: 7,
  });
  assert.equal(attendee.song.id, 'song-a');
  assert.equal(attendee.requestCount, 1);
  assert.equal(attendee.updateVersion, 7);

  const admin = widgets.buildWidgetView({
    display_update_version: 8,
    dj: {
      current_song: { id: 'song-b', title: 'Song B' },
      request_count: 2,
      playlist: [{ id: 'song-a' }, { id: 'song-b' }],
      receiver: { playback_status: 'paused', effective_status: 'ready' },
    },
    layout: { music: { visible: true } },
  }, 'display');
  assert.equal(admin.song.id, 'song-b');
  assert.equal(admin.receiverStatus, 'ready');
  assert.equal(admin.musicVisible, true);
  assert.equal(admin.updateVersion, 8);
});

test('updates artwork atomically across song, missing-artwork, and empty transitions', () => {
  const { root, elements } = widgetFixture();
  const artwork = elements.get('[data-live-dj-artwork]');
  const artworkWrap = elements.get('[data-live-dj-artwork-wrap]');
  const title = elements.get('[data-live-dj-title]');

  widgets.renderWidget(root, {
    song: { id: 'song-a', title: 'Song A', artist: 'Artist A', artwork_url: 'https://example.test/a.jpg' },
    playbackStatus: 'playing', requestCount: 1, playlistCount: 2, receiverStatus: '', musicVisible: true,
  });
  assert.equal(artwork.getAttribute('src'), 'https://example.test/a.jpg');
  assert.equal(artwork.alt, 'Song A artwork');
  assert.equal(artworkWrap.hidden, false);
  assert.equal(title.textContent, 'Now Playing: Song A');

  widgets.renderWidget(root, {
    song: { id: 'song-b', title: 'Song B', artist: 'Artist B', artwork_url: 'https://example.test/b.jpg' },
    playbackStatus: 'playing', requestCount: 0, playlistCount: 2, receiverStatus: '', musicVisible: true,
  });
  assert.equal(artwork.getAttribute('src'), 'https://example.test/b.jpg');
  assert.equal(artwork.alt, 'Song B artwork');
  assert.equal(root.dataset.liveDjSongId, 'song-b');

  widgets.renderWidget(root, {
    song: { id: 'song-c', title: 'Song C', artist: 'Artist C', artwork_url: '' },
    playbackStatus: 'playing', requestCount: 0, playlistCount: 3, receiverStatus: '', musicVisible: true,
  });
  assert.equal(artwork.getAttribute('src'), null);
  assert.equal(artwork.alt, '');
  assert.equal(artworkWrap.hidden, true);

  widgets.renderWidget(root, {
    song: null, playbackStatus: 'stopped', requestCount: 0, playlistCount: 3, receiverStatus: '', musicVisible: false,
  });
  assert.equal(title.textContent, 'The DJ Is Ready');
  assert.equal(root.dataset.liveDjSongId, '');
});

test('rejects older or out-of-order refresh responses', () => {
  assert.equal(widgets.shouldApplyResponse({
    requestNumber: 2, latestRequestNumber: 2, updateVersion: 10, latestUpdateVersion: 9,
  }), true);
  assert.equal(widgets.shouldApplyResponse({
    requestNumber: 1, latestRequestNumber: 2, updateVersion: 11, latestUpdateVersion: 9,
  }), false);
  assert.equal(widgets.shouldApplyResponse({
    requestNumber: 2, latestRequestNumber: 2, updateVersion: 8, latestUpdateVersion: 9,
  }), false);
});
