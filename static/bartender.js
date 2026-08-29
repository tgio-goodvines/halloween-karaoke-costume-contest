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

  const findByAttribute = (selector, attribute, value) => Array.from(
    queueElement.querySelectorAll(selector),
  ).find((element) => element.getAttribute(attribute) === value) || null;

  const captureQueueView = () => {
    const activeElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const visibleOrder = Array.from(queueElement.querySelectorAll("[data-queue-order-id]"))
      .find((element) => element.getBoundingClientRect().bottom > 0);
    const anchor = activeElement?.closest("[data-queue-order-id]") || visibleOrder;
    return {
      openPrepIds: Array.from(queueElement.querySelectorAll("details[open][data-prep-order-id]"))
        .map((details) => details.dataset.prepOrderId),
      anchorOrderId: anchor?.dataset.queueOrderId || "",
      anchorTop: anchor?.getBoundingClientRect().top || 0,
      actionKey: activeElement?.dataset.bartenderAction || "",
      prepFocusId: activeElement?.closest("details[data-prep-order-id]")?.dataset.prepOrderId || "",
    };
  };

  const restoreQueueView = (saved) => {
    saved.openPrepIds.forEach((orderId) => {
      const details = findByAttribute("details[data-prep-order-id]", "data-prep-order-id", orderId);
      if (details instanceof HTMLDetailsElement) details.open = true;
    });

    const adjustScroll = () => {
      const anchor = findByAttribute("[data-queue-order-id]", "data-queue-order-id", saved.anchorOrderId);
      if (anchor) window.scrollBy(0, anchor.getBoundingClientRect().top - saved.anchorTop);
    };
    requestAnimationFrame(() => requestAnimationFrame(adjustScroll));

    const action = findByAttribute("[data-bartender-action]", "data-bartender-action", saved.actionKey);
    const prep = findByAttribute("details[data-prep-order-id]", "data-prep-order-id", saved.prepFocusId);
    const focusTarget = action || prep?.querySelector("summary");
    if (focusTarget instanceof HTMLElement) focusTarget.focus({ preventScroll: true });
  };

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
        const savedView = captureQueueView();
        queueElement.innerHTML = payload.html;
        queueVersion = nextVersion;
        queueElement.dataset.bartenderQueueVersion = nextVersion;
        restoreQueueView(savedView);
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
