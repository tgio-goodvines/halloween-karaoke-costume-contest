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

test('targets only listed receivers that have not acknowledged the command', () => {
  const command = {
    id: 'command-1',
    target_receiver_ids: ['leader', 'follower'],
    acknowledgements: { leader: { succeeded: true } },
  };

  assert.equal(receiverState.commandTargetsReceiver(command, 'leader'), false);
  assert.equal(receiverState.commandTargetsReceiver(command, 'follower'), true);
  assert.equal(receiverState.commandTargetsReceiver(command, 'other'), false);
  assert.equal(receiverState.commandTargetsReceiver({ id: 'legacy-command' }, 'follower'), true);
});

test('projects a playing leader position while keeping paused position fixed', () => {
  const now = Date.parse('2026-10-16T22:00:05Z');
  const leader = {
    playback_status: 'playing',
    playback_position_seconds: 40,
    last_seen_at: '2026-10-16T22:00:02Z',
  };

  assert.equal(receiverState.projectedPlaybackPosition(leader, now), 43);
  assert.equal(receiverState.projectedPlaybackPosition({ ...leader, playback_status: 'paused' }, now), 40);
});
