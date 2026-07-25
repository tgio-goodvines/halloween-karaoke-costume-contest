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
  let appleMusicKitLoadPromise = null;
  let appleMusic = null;

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

  const loadAppleMusicKit = () => {
    if (window.MusicKit && typeof window.MusicKit.configure === 'function') {
      return Promise.resolve(window.MusicKit);
    }
    if (appleMusicKitLoadPromise) {
      return appleMusicKitLoadPromise;
    }

    appleMusicKitLoadPromise = new Promise((resolve, reject) => {
      const existingScript = document.querySelector('script[src*="js-cdn.music.apple.com/musickit"]');
      let settled = false;

      const complete = () => {
        if (settled) {
          return;
        }
        if (window.MusicKit && typeof window.MusicKit.configure === 'function') {
          settled = true;
          resolve(window.MusicKit);
        }
      };

      const fail = () => {
        if (!settled) {
          settled = true;
          reject(new Error('Apple MusicKit did not load. Check browser content blocking, then try again.'));
        }
      };

      if (existingScript) {
        existingScript.addEventListener('load', complete, { once: true });
        existingScript.addEventListener('error', fail, { once: true });
      } else {
        const script = document.createElement('script');
        script.src = 'https://js-cdn.music.apple.com/musickit/v3/musickit.js';
        script.addEventListener('load', complete, { once: true });
        script.addEventListener('error', fail, { once: true });
        document.head.appendChild(script);
      }

      window.setTimeout(() => {
        complete();
        if (!settled) {
          fail();
        }
      }, 8000);
    });

    return appleMusicKitLoadPromise;
  };

  const setAppleMusicStatus = (message, isError) => {
    const status = document.querySelector('[data-apple-music-signin-status]');
    if (!status) {
      return;
    }
    status.textContent = message || '';
    status.classList.toggle('form-helper--error', Boolean(isError));
  };

  const authorizeAppleMusicFromAdmin = async () => {
    if (appleMusic && appleMusic.isAuthorized === true) {
      return appleMusic;
    }
    const response = await fetch('/api/apple-music-token', {
      headers: { Accept: 'application/json' },
      cache: 'no-store',
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || 'Apple Music is not configured.');
    }
    const MusicKit = await loadAppleMusicKit();
    appleMusic = appleMusic || await MusicKit.configure({
      developerToken: payload.developer_token,
      app: {
        name: 'Halloween Party Jukebox',
        build: '1.0.0',
      },
      storefrontId: payload.storefront || 'us',
    });
    if (appleMusic.isAuthorized !== true && typeof appleMusic.authorize === 'function') {
      await appleMusic.authorize();
    }
    if (appleMusic.isAuthorized !== true) {
      throw new Error('Apple Music sign-in did not complete. Enter the Apple verification code if prompted, then try again.');
    }
    return appleMusic;
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
      setAppleMusicStatus('Opening Apple Music sign-in from admin...', false);
      try {
        await authorizeAppleMusicFromAdmin();
        setAppleMusicStatus('Apple Music is signed in. Syncing the live display playback tab...', false);
        await sendAppleMusicConnectCommand(button.dataset.csrfToken || '');
      } catch (error) {
        setAppleMusicStatus(error.message || 'Apple Music sign-in failed.', true);
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
