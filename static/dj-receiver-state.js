(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.HalloweenDjReceiverState = api;
})(typeof window !== 'undefined' ? window : globalThis, () => {
  const authorizationAfterConfiguration = (configured, isAuthorized) => {
    if (!configured) {
      return {
        status: 'needs_authorization',
        authorizationStatus: 'not_configured',
        audioEnabled: false,
      };
    }
    return {
      status: isAuthorized ? 'needs_audio_enable' : 'needs_authorization',
      authorizationStatus: isAuthorized ? 'authorized' : 'not_authorized',
      audioEnabled: false,
    };
  };

  const statusFor = ({ authorizationStatus, audioEnabled, hasError }) => {
    if (hasError) return 'error';
    if (authorizationStatus !== 'authorized') return 'needs_authorization';
    return audioEnabled ? 'ready' : 'needs_audio_enable';
  };

  const buttonLabelFor = (authorizationStatus) => {
    return authorizationStatus === 'authorized' ? 'Resume DJ Audio' : 'Enable DJ Audio';
  };

  const detailFor = ({ configured, initializing, authorizationStatus, audioEnabled, error }) => {
    if (error) return error;
    if (!configured) return 'Apple Music is not configured yet.';
    if (initializing) return 'Checking this display’s Apple Music authorization…';
    if (authorizationStatus !== 'authorized') return 'Authorize Apple Music on this display once.';
    if (!audioEnabled) return 'Apple Music is authorized. Resume DJ Audio on this display.';
    return 'Apple Music is connected. Remote DJ controls are ready.';
  };

  const commandTargetsReceiver = (command, receiverId) => {
    if (!command || !command.id || !receiverId) return false;
    const targets = Array.isArray(command.target_receiver_ids)
      ? command.target_receiver_ids.map(String)
      : [];
    if (targets.length && !targets.includes(String(receiverId))) return false;
    return !Boolean(command.acknowledgements?.[receiverId]);
  };

  const projectedPlaybackPosition = (leader, nowMs = Date.now()) => {
    const base = Math.max(0, Number(leader?.playback_position_seconds) || 0);
    if (String(leader?.playback_status || '') !== 'playing') return base;
    const reportedAt = Date.parse(String(leader?.last_seen_at || ''));
    if (!Number.isFinite(reportedAt)) return base;
    return base + Math.max(0, (Number(nowMs) - reportedAt) / 1000);
  };

  return {
    authorizationAfterConfiguration,
    buttonLabelFor,
    commandTargetsReceiver,
    detailFor,
    projectedPlaybackPosition,
    statusFor,
  };
});
