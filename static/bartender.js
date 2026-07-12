document.addEventListener('DOMContentLoaded', () => {
  const queueElement = document.querySelector('[data-bartender-queue]');

  if (!queueElement) {
    return;
  }

  const queueUrl = queueElement.dataset.bartenderQueueUrl || '/api/bartender-queue';
  let queueVersion = queueElement.dataset.bartenderQueueVersion || '';
  let isRefreshing = false;
  let refreshTimerId = null;
  const refreshIntervalMs = 3000;

  const scheduleRefresh = () => {
    if (refreshTimerId) {
      window.clearTimeout(refreshTimerId);
    }

    refreshTimerId = window.setTimeout(refreshQueue, refreshIntervalMs);
  };

  const refreshQueue = async () => {
    if (document.hidden || isRefreshing) {
      scheduleRefresh();
      return;
    }

    isRefreshing = true;

    try {
      const response = await window.fetch(queueUrl, {
        headers: {
          Accept: 'application/json',
        },
        credentials: 'same-origin',
      });

      if (response.redirected || response.status === 401 || response.status === 403) {
        window.location.reload();
        return;
      }

      if (!response.ok) {
        return;
      }

      const payload = await response.json();
      const nextVersion = payload.queue_version || '';

      if (nextVersion && nextVersion !== queueVersion && typeof payload.html === 'string') {
        queueElement.innerHTML = payload.html;
        queueVersion = nextVersion;
        queueElement.dataset.bartenderQueueVersion = nextVersion;
      }
    } catch (error) {
      console.error('Unable to refresh bartender queue', error);
    } finally {
      isRefreshing = false;
      scheduleRefresh();
    }
  };

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
      refreshQueue();
    }
  });

  scheduleRefresh();
});
