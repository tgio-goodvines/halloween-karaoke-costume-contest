const test = require('node:test');
const assert = require('node:assert/strict');

const receiverState = require('../static/dj-receiver-state.js');

test('rehydrates retained Apple authorization without claiming audio is enabled', () => {
  assert.deepEqual(
    receiverState.authorizationAfterConfiguration(true, true),
    {
      status: 'needs_audio_enable',
      authorizationStatus: 'authorized',
      audioEnabled: false,
    },
  );
  assert.equal(receiverState.buttonLabelFor('authorized'), 'Resume DJ Audio');
});

test('requires authorization only when MusicKit did not restore it', () => {
  assert.deepEqual(
    receiverState.authorizationAfterConfiguration(true, false),
    {
      status: 'needs_authorization',
      authorizationStatus: 'not_authorized',
      audioEnabled: false,
    },
  );
  assert.equal(receiverState.buttonLabelFor('not_authorized'), 'Enable DJ Audio');
});

test('keeps authorization and audio readiness as separate state axes', () => {
  assert.equal(receiverState.statusFor({
    authorizationStatus: 'authorized', audioEnabled: false, hasError: false,
  }), 'needs_audio_enable');
  assert.equal(receiverState.statusFor({
    authorizationStatus: 'authorized', audioEnabled: true, hasError: false,
  }), 'ready');
  assert.equal(receiverState.detailFor({
    configured: true,
    initializing: false,
    authorizationStatus: 'authorized',
    audioEnabled: false,
    error: '',
  }), 'Apple Music is authorized. Resume DJ Audio on this display.');
});

test('uses an initializing state before MusicKit authorization is known', () => {
  assert.equal(receiverState.detailFor({
    configured: true,
    initializing: true,
    authorizationStatus: 'checking',
    audioEnabled: false,
    error: '',
  }), 'Checking this display’s Apple Music authorization…');
});
