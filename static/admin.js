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

  const setJukeboxCommandStatus = (command, status, errorMessage) => {
    const statusElement = document.querySelector('[data-jukebox-command-status]');
    if (statusElement) {
      statusElement.textContent = `Last command: ${command || 'none'} · ${status || 'pending'}`;
      statusElement.classList.toggle('contest-status--inactive', status === 'error');
      statusElement.classList.toggle('contest-status--warning', status === 'pending');
      statusElement.classList.toggle('contest-status--active', Boolean(status) && status !== 'error' && status !== 'pending');
    }
    const errorElement = document.querySelector('[data-jukebox-command-error]');
    if (errorElement) {
      errorElement.textContent = errorMessage || '';
      errorElement.hidden = !errorMessage;
    }
  };

  const updateJukeboxStatusFromPayload = (payload) => {
    const jukebox = payload && payload.jukebox ? payload.jukebox : payload;
    const control = jukebox && jukebox.playback_control ? jukebox.playback_control : null;
    if (control) {
      setJukeboxCommandStatus(control.command, control.status, control.error);
    }
    const nowPlaying = jukebox && jukebox.now_playing ? jukebox.now_playing : null;
    const nowPlayingElement = document.querySelector('[data-jukebox-now-playing]');
    if (nowPlayingElement) {
      if (nowPlaying && nowPlaying.title) {
        nowPlayingElement.textContent = `Now playing: ${nowPlaying.title}${nowPlaying.artist ? ` by ${nowPlaying.artist}` : ''}`;
      } else {
        nowPlayingElement.textContent = 'No song is marked as playing yet.';
      }
    }
    const activePlaylistName = document.querySelector('[data-jukebox-active-playlist-name]');
    if (activePlaylistName && jukebox && jukebox.active_playlist_name) {
      activePlaylistName.textContent = jukebox.active_playlist_name;
    }
    const activePlaylistCount = document.querySelector('[data-jukebox-active-playlist-count]');
    if (activePlaylistCount && jukebox && Array.isArray(jukebox.queue)) {
      activePlaylistCount.textContent = String(jukebox.queue.length);
    }
    const activePlaylistDuration = document.querySelector('[data-jukebox-active-playlist-duration]');
    if (activePlaylistDuration && jukebox && jukebox.active_playlist_duration_label) {
      activePlaylistDuration.textContent = jukebox.active_playlist_duration_label;
    }
  };

  const reinitializeDynamicControls = () => {
    initTabs();
    if (window.HalloweenJukeboxSearch && typeof window.HalloweenJukeboxSearch.init === 'function') {
      window.HalloweenJukeboxSearch.init();
    }
    initJukeboxDjForms();
    initAjaxForms();
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
      if (form.dataset.adminNativeForm !== undefined) {
        return;
      }
      if (form.dataset.jukeboxDjForm !== undefined) {
        return;
      }
      if (form.dataset.adminAjaxBound === 'yes') {
        return;
      }
      form.dataset.adminAjaxBound = 'yes';
      form.querySelectorAll('button[type="submit"], input[type="submit"]').forEach((button) => {
        button.addEventListener('click', () => {
          form._lastSubmitter = button;
        });
      });
      form.addEventListener('submit', async (event) => {
        if (event.defaultPrevented) {
          return;
        }
        event.preventDefault();
        const submitter = event.submitter || form._lastSubmitter || null;
        const savedScrollY = window.scrollY;
        const activeTab = window.localStorage.getItem(tabStorageKey) || defaultTab;
        const openSummaries = openDetailsSnapshot();
        let formData;
        try {
          formData = submitter ? new FormData(form, submitter) : new FormData(form);
        } catch (error) {
          formData = new FormData(form);
        }
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

  const initJukeboxDjForms = () => {
    const panel = getPanel();
    if (!panel) {
      return;
    }
    panel.querySelectorAll('form[data-jukebox-dj-form]').forEach((form) => {
      if (form.dataset.jukeboxDjBound === 'yes') {
        return;
      }
      form.dataset.jukeboxDjBound = 'yes';
      form.querySelectorAll('button[type="submit"], input[type="submit"]').forEach((button) => {
        button.addEventListener('click', () => {
          form._lastSubmitter = button;
        });
      });
      form.addEventListener('submit', async (event) => {
        if (event.defaultPrevented) {
          return;
        }
        event.preventDefault();
        const submitter = event.submitter || form._lastSubmitter || null;
        const endpoint = form.dataset.jukeboxDjEndpoint || '/api/jukebox/dj-command';
        let formData;
        try {
          formData = submitter ? new FormData(form, submitter) : new FormData(form);
        } catch (error) {
          formData = new FormData(form);
        }
        formData.delete('action');
        if (submitter && submitter.name) {
          formData.set(submitter.name, submitter.value);
        }
        const command = String(formData.get('jukebox_command') || '');
        setJukeboxCommandStatus(command, 'pending', '');
        if (submitter) {
          submitter.disabled = true;
        }
        try {
          const response = await fetch(endpoint, {
            method: 'POST',
            body: formData,
            headers: { Accept: 'application/json', 'X-Requested-With': 'fetch' },
            cache: 'no-store',
          });
          const responseType = response.headers.get('content-type') || '';
          const payload = responseType.includes('application/json')
            ? await response.json()
            : { error: await response.text() };
          if (!response.ok) {
            throw new Error(payload.error || 'Unable to send DJ command.');
          }
          updateJukeboxStatusFromPayload(payload);
          refreshAdminPanel();
        } catch (error) {
          setJukeboxCommandStatus(command, 'error', error.message || 'Unable to send DJ command.');
        } finally {
          if (submitter) {
            submitter.disabled = false;
          }
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
