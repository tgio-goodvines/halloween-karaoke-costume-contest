const test = require('node:test');
const assert = require('node:assert/strict');

const media = require('../static/display-media.js');

test('background artwork is suppressed for cast-safe solid cards', () => {
  assert.equal(media.treatmentFor({ image_url: '/static/images/features/karaoke.jpg' }), 'none');
  assert.equal(media.treatmentFor({ image_url: 'https://example.test/custom.jpg', media_treatment: '' }), 'none');
  assert.equal(media.treatmentFor({ image_url: '/static/game.jpg', media_treatment: 'background' }), 'none');
});

test('center cards select one supporting focus group', () => {
  assert.equal(media.centerFocusMode({ cta: true, secondary: 'Extra copy' }), 'cta');
  assert.equal(media.centerFocusMode({ kind: 'action', action: { label: 'Join' }, secondary: 'Extra copy' }), 'action');
  assert.equal(media.centerFocusMode({ secondary: 'One readable message', facts: [{ label: 'Players', value: 4 }] }), 'message');
  assert.equal(media.centerFocusMode({ scoreboard: { entries: [{ name: 'Sam' }] }, secondary: 'Final' }), 'scoreboard');
});

test('game cards select one focal presentation', () => {
  assert.equal(media.gameFocusMode({ focus_items: ['One', 'Two', 'Three'], primary: 'Choose' }), 'choices');
  assert.equal(media.gameFocusMode({ spotlight_rows: [{ label: 'Murder', value: 'A vampire' }], primary: 'Results' }), 'spotlight');
  assert.equal(media.gameFocusMode({ focus_mode: 'spotlight', primary: 'Explicit mode' }), 'spotlight');
  assert.equal(media.gameFocusMode({ feature_text: 'Anonymous answer', primary: 'Prompt' }), 'feature');
  assert.equal(media.gameFocusMode({ primary: 'Current instruction', metrics: [{ value: 4 }] }), 'message');
});

test('foreground media remains an explicit opt-in and empty cards have no media', () => {
  assert.equal(media.treatmentFor({ image_url: '/static/album.jpg', media_treatment: 'foreground' }), 'foreground');
  assert.equal(media.treatmentFor({ image_url: '' }), 'none');
  assert.equal(media.treatmentFor(null), 'none');
});

test('media tones are bounded to supported contrast profiles', () => {
  assert.equal(media.toneFor({ media_tone: 'video' }), 'video');
  assert.equal(media.toneFor({ media_tone: 'custom' }), 'custom');
  assert.equal(media.toneFor({ media_tone: 'game' }), 'game');
  assert.equal(media.toneFor({ media_tone: 'unknown' }), 'feature');
  assert.equal(media.toneFor({}), 'feature');
});

test('region signatures are stable across object key order', () => {
  assert.equal(
    media.signatureFor({ visible: true, entries: [{ id: 'one', value: 2 }] }),
    media.signatureFor({ entries: [{ value: 2, id: 'one' }], visible: true }),
  );
  assert.notEqual(
    media.signatureFor({ entries: [{ id: 'one', value: 2 }] }),
    media.signatureFor({ entries: [{ id: 'one', value: 3 }] }),
  );
});

test('media replacement is skipped for an unchanged source', () => {
  assert.equal(media.shouldReplaceSource('/static/game.jpg', '/static/game.jpg'), false);
  assert.equal(media.shouldReplaceSource('/static/game.jpg', '/static/winner.jpg'), true);
  assert.equal(media.shouldReplaceSource('', ''), false);
});
