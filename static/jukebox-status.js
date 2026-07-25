(function () {
  const root = document.querySelector('[data-jukebox-live-status]');
  if (!root) {
    return;
  }

  const text = (value) => (value === null || value === undefined ? '' : String(value));

  const setText = (selector, value) => {
    const element = document.querySelector(selector);
    if (element) {
      element.textContent = value;
    }
  };

  const updateStatus = async () => {
    try {
      const response = await fetch('/api/jukebox-state', {
        headers: { Accept: 'application/json' },
        cache: 'no-store',
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || 'Unable to refresh jukebox status.');
      }

      const nowPlaying = payload.now_playing || {};
      setText('[data-jukebox-now-title]', nowPlaying.title || 'Waiting for the next song');
      setText('[data-jukebox-now-artist]', nowPlaying.artist || '');

      const settings = payload.settings || {};
      setText('[data-jukebox-requests-state]', settings.requests_enabled ? 'Open' : 'Paused');
      const pendingCount = Number(payload.pending_request_count || 0);
      setText('[data-jukebox-pending-count]', `${pendingCount} pending`);

      const requests = Array.isArray(payload.requests) ? payload.requests : [];
      requests.forEach((requestItem) => {
        const requestId = text(requestItem.id);
        const status = text(requestItem.status);
        document.querySelectorAll(`[data-jukebox-request-status="${CSS.escape(requestId)}"]`).forEach((element) => {
          element.textContent = status;
        });
      });
    } catch (error) {
      window.clearInterval(intervalId);
    }
  };

  const intervalId = window.setInterval(updateStatus, 3000);
  updateStatus();
})();
