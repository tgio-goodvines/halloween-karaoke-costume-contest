const assert = require('node:assert/strict');
const test = require('node:test');

const karaoke = require('../static/karaoke-live-status.js');

class FakeNode {
  constructor(tagName = '') {
    this.tagName = tagName;
    this.children = [];
    this.dataset = {};
    this.className = '';
    this.textContent = '';
  }

  append(...children) {
    this.children.push(...children);
  }
}

const fakeDocument = {
  createElement: (tagName) => new FakeNode(tagName),
  createTextNode: (text) => ({ textContent: text }),
};

test('normalizes the attendee karaoke payload without exposing extra state', () => {
  const view = karaoke.buildView({
    display_update_version: 18,
    stage_mode: 'called',
    primary: {
      id: 'song-1',
      status: { key: 'called', label: 'You’ve been called to the stage' },
    },
    personal_entries: [{ id: 'song-1' }],
    lineup: [{ id: 'song-1', status_key: 'called' }],
  });

  assert.equal(view.updateVersion, 18);
  assert.equal(view.stageMode, 'called');
  assert.equal(view.primary.status.key, 'called');
  assert.equal(view.personalEntries.length, 1);
  assert.equal(view.lineup.length, 1);
});

test('renders public lineup text and status without HTML interpolation', () => {
  const item = karaoke.createLineupItem(fakeDocument, {
    id: 'song-1',
    singer_label: '<Jamie & Morgan>',
    song_title: '<Thriller>',
    artist: 'Michael Jackson',
    status_key: 'up_next',
    status_label: 'Up next',
  });

  assert.equal(item.dataset.karaokeLineupEntry, 'song-1');
  assert.equal(item.children[0].textContent, '<Jamie & Morgan>');
  assert.match(item.children[1].textContent, /<Thriller>/);
  assert.equal(item.children[2].textContent, 'Up next');
  assert.match(item.children[2].className, /karaoke-lineup-status--up_next/);
});

test('rejects stale or out-of-order attendee refresh responses', () => {
  assert.equal(karaoke.shouldApplyResponse({
    requestNumber: 2,
    latestRequestNumber: 2,
    updateVersion: 10,
    latestUpdateVersion: 9,
  }), true);
  assert.equal(karaoke.shouldApplyResponse({
    requestNumber: 1,
    latestRequestNumber: 2,
    updateVersion: 11,
    latestUpdateVersion: 9,
  }), false);
  assert.equal(karaoke.shouldApplyResponse({
    requestNumber: 2,
    latestRequestNumber: 2,
    updateVersion: 8,
    latestUpdateVersion: 9,
  }), false);
});
