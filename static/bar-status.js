document.addEventListener('DOMContentLoaded', () => {
  const statusElement = document.querySelector('[data-bar-status]');

  if (!statusElement) {
    return;
  }

  const statusUrl = statusElement.dataset.barStatusUrl || '/api/party/bar-queue';
  let queueVersion = statusElement.dataset.barStatusVersion || '';
  let requestSequence = 0;
  let appliedSequence = 0;
  let refreshTimerId = null;
  const refreshIntervalMs = 5000;

  const setText = (selector, value) => {
    const element = document.querySelector(selector);
    if (element) {
      element.textContent = String(value ?? '');
    }
  };

  const renderPersonalOrders = (orders) => {
    const container = statusElement.querySelector('[data-bar-personal-orders]');
    if (!container) {
      return;
    }

    container.replaceChildren();
    if (!Array.isArray(orders) || orders.length === 0) {
      const empty = document.createElement('p');
      empty.className = 'bar-status__empty';
      empty.textContent = 'You have no active or recently completed drink orders.';
      container.append(empty);
      return;
    }

    orders.forEach((order) => {
      const card = document.createElement('article');
      card.className = `bar-status-order${order.ready ? ' bar-status-order--ready' : ''}`;

      const summary = document.createElement('div');
      const status = document.createElement('span');
      status.textContent = order.status_label || 'Order received';
      const name = document.createElement('strong');
      name.textContent = order.item_name || 'Drink';
      summary.append(status, name);

      const detail = document.createElement('small');
      const ordersAhead = Number.parseInt(order.orders_ahead, 10) || 0;
      if (order.ready) {
        detail.textContent = 'Ready now';
      } else if (ordersAhead === 0) {
        detail.textContent = `At the front of the queue · ${order.estimated_ready_label || 'Soon'}`;
      } else {
        detail.textContent = `${ordersAhead} order${ordersAhead === 1 ? '' : 's'} ahead · ${order.estimated_ready_label || 'Soon'}`;
      }

      card.append(summary, detail);
      container.append(card);
    });
  };

  const applyPayload = (payload) => {
    setText('[data-bar-active-count]', payload.active_count || 0);
    setText('[data-bar-mixing-count]', payload.mixing_count || 0);
    setText('[data-bar-waiting-count]', payload.waiting_count || 0);
    setText('[data-bar-personal-active-count]', payload.personal_active_count || 0);
    setText('[data-bar-personal-ready-count]', payload.personal_ready_count || 0);
    setText('[data-bar-average-prep]', payload.average_prep_label || 'About 8 minutes');
    renderPersonalOrders(payload.personal_orders);
  };

  const scheduleRefresh = () => {
    if (refreshTimerId) {
      window.clearTimeout(refreshTimerId);
    }
    refreshTimerId = window.setTimeout(refreshStatus, refreshIntervalMs);
  };

  const refreshStatus = async () => {
    if (document.hidden) {
      scheduleRefresh();
      return;
    }

    const sequence = ++requestSequence;
    try {
      const response = await window.fetch(statusUrl, {
        headers: { Accept: 'application/json' },
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
      if (sequence < appliedSequence) {
        return;
      }
      appliedSequence = sequence;

      const nextVersion = String(payload.queue_version || '');
      if (!nextVersion || nextVersion === queueVersion) {
        return;
      }

      queueVersion = nextVersion;
      statusElement.dataset.barStatusVersion = nextVersion;
      applyPayload(payload);
    } catch (error) {
      console.error('Unable to refresh bar status', error);
    } finally {
      scheduleRefresh();
    }
  };

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
      refreshStatus();
    }
  });

  scheduleRefresh();
});
