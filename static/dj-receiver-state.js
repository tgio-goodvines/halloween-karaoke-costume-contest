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

  const buttonLabelFor = (authorizationStatus) => (
    authorizationStatus === 'authorized' ? 'Resume DJ Audio' : 'Enable DJ Audio'
  );

  const detailFor = ({ configured, initializing, authorizationStatus, audioEnabled, error }) => {
    if (error) return error;
    if (!configured) return 'Apple Music is not configured yet.';
    if (initializing) return 'Checking this display’s Apple Music authorization…';
    if (authorizationStatus !== 'authorized') return 'Authorize Apple Music on this display once.';
    if (!audioEnabled) return 'Apple Music is authorized. Resume DJ Audio on this display.';
    return 'Apple Music is connected. Remote DJ controls are ready.';
  };

  return {
    authorizationAfterConfiguration,
    buttonLabelFor,
    detailFor,
    statusFor,
  };
});
