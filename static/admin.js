(function () {
  const tabStorageKey = 'halloween-admin-active-tab';
  const defaultTab = 'setup';
  const updatesEndpoint = '/api/display-updates';
  let eventSource = null;
  let refreshInFlight = false;
  let pendingRefresh = false;
  let hasReceivedInitialUpdate = false;
  let lastScrollAt = 0;
  let deferredRefreshTimer = null;

  const getPanel = () => document.querySelector('[data-admin-panel]');

  const activeTabFromLocation = () => {
    const hash = window.location.hash.replace(/^#/, '');
    if (hash.startsWith('admin-')) {
      return hash.slice('admin-'.length);
    }
    return window.localStorage.getItem(tabStorageKey) || defaultTab;
  };

  const setActiveTab = (tabName, updateHash) => {
    const panel = getPanel();
    if (!panel) {
      return;
    }
    const panels = Array.from(panel.querySelectorAll('[data-admin-tab-panel]'));
    const buttons = Array.from(panel.querySelectorAll('[data-admin-tab]'));
    const hasTab = panels.some((candidate) => candidate.dataset.adminTabPanel === tabName);
    const nextTab = hasTab ? tabName : defaultTab;

    panels.forEach((candidate) => {
      candidate.hidden = candidate.dataset.adminTabPanel !== nextTab;
    });
    buttons.forEach((button) => {
      const isActive = button.dataset.adminTab === nextTab;
      button.classList.toggle('is-active', isActive);
      button.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });

    window.localStorage.setItem(tabStorageKey, nextTab);
    if (updateHash) {
      window.history.replaceState(null, '', `#admin-${nextTab}`);
    }
  };

  const initTabs = () => {
    const panel = getPanel();
    if (!panel) {
      return;
    }
    panel.querySelectorAll('[data-admin-tab]').forEach((button) => {
      button.addEventListener('click', () => {
        setActiveTab(button.dataset.adminTab || defaultTab, true);
        window.scrollTo({ top: 0, behavior: 'smooth' });
      });
    });
    setActiveTab(activeTabFromLocation(), false);
  };

  const restoreDetails = (openSummaries) => {
    if (!openSummaries.length) {
      return;
    }
    document.querySelectorAll('details.admin-entry').forEach((details) => {
      const summary = details.querySelector('summary');
      const text = summary ? summary.textContent.trim().replace(/\s+/g, ' ') : '';
      details.open = openSummaries.includes(text);
    });
  };

  const openDetailsSnapshot = () => (
    Array.from(document.querySelectorAll('details.admin-entry[open] summary'))
      .map((summary) => summary.textContent.trim().replace(/\s+/g, ' '))
      .filter(Boolean)
  );

  const reinitializeDynamicControls = () => {
    initTabs();
    if (window.HalloweenJukeboxSearch && typeof window.HalloweenJukeboxSearch.init === 'function') {
      window.HalloweenJukeboxSearch.init();
    }
    initAppleMusicSignIn();
    initAjaxForms();
  };

  const setAppleMusicStatus = (message, isError) => {
    const status = document.querySelector('[data-apple-music-signin-status]');
    if (!status) {
      return;
    }
    status.textContent = message || '';
    status.classList.toggle('form-helper--error', Boolean(isError));
  };

  const sendAppleMusicConnectCommand = async (csrfToken) => {
    const formData = new FormData();
    formData.append('csrf_token', csrfToken || '');
    formData.append('action', 'jukebox_dj_command');
    formData.append('jukebox_command', 'connect');
    const savedScrollY = window.scrollY;
    const activeTab = window.localStorage.getItem(tabStorageKey) || defaultTab;
    const openSummaries = openDetailsSnapshot();
    const response = await fetch('/admin', {
      method: 'POST',
      body: formData,
      headers: { Accept: 'text/html', 'X-Requested-With': 'fetch' },
      cache: 'no-store',
    });
    if (!response.ok) {
      throw new Error('Apple Music connected, but the live display command could not be sent.');
    }
    replaceAdminPanel(await response.text(), savedScrollY, activeTab, openSummaries);
  };

  const initAppleMusicSignIn = () => {
    const button = document.querySelector('[data-apple-music-signin]');
    if (!button || button.dataset.appleMusicBound === 'yes') {
      return;
    }
    button.dataset.appleMusicBound = 'yes';
    button.addEventListener('click', async () => {
      button.disabled = true;
      setAppleMusicStatus('Requesting Apple Music authorization on the live display...', false);
      try {
        await sendAppleMusicConnectCommand(button.dataset.csrfToken || '');
        setAppleMusicStatus('Authorization requested. Use the Apple Music prompt on the live display.', false);
      } catch (error) {
        setAppleMusicStatus(error.message || 'Unable to request Apple Music authorization on the live display.', true);
      } finally {
        button.disabled = false;
      }
    });
  };

  const replaceAdminPanel = (html, savedScrollY, activeTab, openSummaries) => {
    const parser = new DOMParser();
    const nextDocument = parser.parseFromString(html, 'text/html');
    const nextPanel = nextDocument.querySelector('[data-admin-panel]');
    const currentPanel = getPanel();
    if (!nextPanel || !currentPanel) {
      window.location.reload();
      return;
    }
    currentPanel.replaceWith(nextPanel);
    setActiveTab(activeTab, false);
    restoreDetails(openSummaries);
    reinitializeDynamicControls();
    const maxScroll = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
    window.scrollTo(0, Math.min(savedScrollY, maxScroll));
  };

  const refreshAdminPanel = async () => {
    if (refreshInFlight) {
      pendingRefresh = true;
      return;
    }
    const panel = getPanel();
    if (!panel) {
      return;
    }
    refreshInFlight = true;
    pendingRefresh = false;
    const savedScrollY = window.scrollY;
    const activeTab = window.localStorage.getItem(tabStorageKey) || defaultTab;
    const openSummaries = openDetailsSnapshot();
    panel.classList.add('is-refreshing');
    try {
      const response = await fetch('/admin', {
        headers: { Accept: 'text/html', 'X-Requested-With': 'fetch' },
        cache: 'no-store',
      });
      if (!response.ok) {
        throw new Error('Admin refresh failed.');
      }
      replaceAdminPanel(await response.text(), savedScrollY, activeTab, openSummaries);
    } catch (error) {
      panel.classList.remove('is-refreshing');
    } finally {
      refreshInFlight = false;
      if (pendingRefresh) {
        refreshAdminPanel();
      }
    }
  };

  const activeFieldHasFocus = () => {
    const activeElement = document.activeElement;
    return Boolean(activeElement && ['INPUT', 'TEXTAREA', 'SELECT'].includes(activeElement.tagName));
  };

  const requestBackgroundRefresh = () => {
    window.clearTimeout(deferredRefreshTimer);
    const timeSinceScroll = Date.now() - lastScrollAt;
    if (activeFieldHasFocus()) {
      return;
    }
    if (timeSinceScroll < 700) {
      deferredRefreshTimer = window.setTimeout(requestBackgroundRefresh, 800 - timeSinceScroll);
      return;
    }
    refreshAdminPanel();
  };

  const initAjaxForms = () => {
    const panel = getPanel();
    if (!panel) {
      return;
    }
    panel.querySelectorAll('form[method="post"]').forEach((form) => {
      if (form.dataset.adminAjaxBound === 'yes') {
        return;
      }
      form.dataset.adminAjaxBound = 'yes';
      form.addEventListener('submit', async (event) => {
        if (event.defaultPrevented) {
          return;
        }
        event.preventDefault();
        const submitter = event.submitter;
        const savedScrollY = window.scrollY;
        const activeTab = window.localStorage.getItem(tabStorageKey) || defaultTab;
        const openSummaries = openDetailsSnapshot();
        const formData = new FormData(form);
        if (submitter && submitter.name && !formData.has(submitter.name)) {
          formData.append(submitter.name, submitter.value);
        }
        panel.classList.add('is-refreshing');
        if (submitter) {
          submitter.disabled = true;
        }
        try {
          const response = await fetch(form.action || window.location.href, {
            method: 'POST',
            body: formData,
            headers: { Accept: 'text/html', 'X-Requested-With': 'fetch' },
            cache: 'no-store',
          });
          if (!response.ok) {
            throw new Error('Admin action failed.');
          }
          replaceAdminPanel(await response.text(), savedScrollY, activeTab, openSummaries);
        } catch (error) {
          window.location.reload();
        }
      });
    });
  };

  const connectUpdates = () => {
    if (eventSource || typeof window.EventSource !== 'function') {
      return;
    }
    try {
      eventSource = new EventSource(updatesEndpoint);
      eventSource.onmessage = () => {
        if (!hasReceivedInitialUpdate) {
          hasReceivedInitialUpdate = true;
          return;
        }
        requestBackgroundRefresh();
      };
      eventSource.onerror = () => {
        if (eventSource) {
          eventSource.close();
          eventSource = null;
        }
        window.setTimeout(connectUpdates, 5000);
      };
    } catch (error) {
      eventSource = null;
    }
  };

  window.addEventListener('scroll', () => {
    lastScrollAt = Date.now();
  }, { passive: true });
  window.addEventListener('hashchange', () => setActiveTab(activeTabFromLocation(), false));
  document.addEventListener('DOMContentLoaded', () => {
    reinitializeDynamicControls();
    connectUpdates();
  });
})();
