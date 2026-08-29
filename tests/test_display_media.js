const test = require('node:test');
const assert = require('node:assert/strict');

const media = require('../static/display-media.js');

test('image-bearing display cards use background media by default', () => {
  assert.equal(media.treatmentFor({ image_url: '/static/images/features/karaoke.jpg' }), 'background');
  assert.equal(media.treatmentFor({ image_url: 'https://example.test/custom.jpg', media_treatment: '' }), 'background');
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
