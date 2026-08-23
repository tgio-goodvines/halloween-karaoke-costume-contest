((root, factory) => {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.HalloweenKaraokeLiveStatus = api;
  if (root?.document) {
    const start = () => api.startAll(root.document);
    if (root.document.readyState === 'loading') {
      root.document.addEventListener('DOMContentLoaded', start, { once: true });
    } else {
      start();
    }
  }
})(typeof window !== 'undefined' ? window : globalThis, () => {
  const connections = new WeakMap();
  const statusStates = ['complete', 'current', 'waiting', 'attention'];
  const alertTones = ['neutral', 'muted', 'pending', 'attention', 'success', 'live', 'urgent'];

  const safeArray = (value) => (Array.isArray(value) ? value : []);
  const safeObject = (value) => (value && typeof value === 'object' ? value : {});

  const buildView = (payload) => {
    const source = safeObject(payload);
    return {
      updateVersion: Math.max(0, Number(source.display_update_version) || 0),
      primary: source.primary && typeof source.primary === 'object' ? source.primary : null,
      personalEntries: safeArray(source.personal_entries),
      lineup: safeArray(source.lineup),
      stageMode: String(source.stage_mode || 'standby'),
    };
  };

  const shouldApplyResponse = ({ requestNumber, latestRequestNumber, updateVersion, latestUpdateVersion }) => (
    requestNumber === latestRequestNumber
    && (updateVersion === 0 || updateVersion >= latestUpdateVersion)
  );

  const findWithin = (rootElement, selector) => (
    rootElement.matches?.(selector) ? rootElement : rootElement.querySelector(selector)
  );

  const setText = (element, value) => {
    if (element) element.textContent = String(value || '');
  };

  const renderAlert = (widgetRoot, primary) => {
    const alert = findWithin(widgetRoot, '[data-karaoke-alert]');
    if (!alert) return;
    if (!primary) {
      alert.hidden = true;
      return;
    }
    const status = safeObject(primary.status);
    alert.hidden = false;
    alertTones.forEach((tone) => alert.classList.remove(`karaoke-attendee-alert--${tone}`));
    alert.classList.add(`karaoke-attendee-alert--${status.tone || 'neutral'}`);
    setText(alert.querySelector('[data-karaoke-alert-label]'), status.label);
    setText(alert.querySelector('[data-karaoke-alert-detail]'), status.detail);
    setText(
      alert.querySelector('[data-karaoke-alert-song]'),
      `${primary.singer_label || 'Singer'} · “${primary.song_title || 'Song'}”${primary.artist ? ` by ${primary.artist}` : ''}`,
    );
  };

  const renderWorkflow = (entryElement, steps) => {
    const stepMap = new Map(safeArray(steps).map((step) => [String(step.key || ''), step]));
    entryElement.querySelectorAll('[data-karaoke-workflow-step]').forEach((stepElement) => {
      const step = stepMap.get(stepElement.dataset.karaokeWorkflowStep || '');
      if (!step) return;
      statusStates.forEach((state) => stepElement.classList.remove(`karaoke-workflow__step--${state}`));
      const state = statusStates.includes(step.state) ? step.state : 'waiting';
      stepElement.classList.add(`karaoke-workflow__step--${state}`);
      stepElement.setAttribute('aria-current', state === 'current' ? 'step' : 'false');
      setText(
        stepElement.querySelector('[data-karaoke-workflow-marker]'),
        state === 'complete' ? '✓' : (state === 'attention' ? '!' : (state === 'current' ? '●' : '○')),
      );
      setText(stepElement.querySelector('[data-karaoke-workflow-label]'), step.label);
    });
  };

  const renderPersonalEntries = (documentRoot, entries) => {
    const entryMap = new Map(safeArray(entries).map((entry) => [String(entry.id || ''), entry]));
    documentRoot.querySelectorAll('[data-karaoke-personal-entry]').forEach((entryElement) => {
      const entry = entryMap.get(entryElement.dataset.karaokePersonalEntry || '');
      if (!entry) return;
      const status = safeObject(entry.status);
      const statusElement = entryElement.querySelector('[data-karaoke-entry-status]');
      if (statusElement) statusElement.dataset.karaokeStatusTone = String(status.tone || 'neutral');
      setText(entryElement.querySelector('[data-karaoke-entry-status-label]'), status.label);
      setText(entryElement.querySelector('[data-karaoke-entry-status-detail]'), status.detail);
      const manageActions = entryElement.querySelector('[data-karaoke-manage-actions]');
      if (manageActions) manageActions.hidden = !entry.can_manage;
      renderWorkflow(entryElement, entry.steps);
    });
  };

  const createLineupItem = (documentRoot, entry) => {
    const item = documentRoot.createElement('li');
    item.dataset.karaokeLineupEntry = String(entry.id || '');
    const singer = documentRoot.createElement('strong');
    singer.textContent = String(entry.singer_label || 'Singer');
    const song = documentRoot.createTextNode(
      ` will sing “${entry.song_title || 'Song'}”${entry.artist ? ` by ${entry.artist}` : ''} `,
    );
    const status = documentRoot.createElement('span');
    status.className = `karaoke-lineup-status karaoke-lineup-status--${entry.status_key || 'ready'}`;
    status.textContent = String(entry.status_label || 'Ready');
    item.append(singer, song, status);
    return item;
  };

  const renderLineups = (documentRoot, lineup) => {
    const entries = safeArray(lineup);
    documentRoot.querySelectorAll('[data-karaoke-public-lineup]').forEach((list) => {
      const limit = Math.max(0, Number(list.dataset.karaokeLineupLimit) || 0);
      const visibleEntries = limit ? entries.slice(0, limit) : entries;
      list.replaceChildren(...visibleEntries.map((entry) => createLineupItem(documentRoot, entry)));
      list.hidden = visibleEntries.length === 0;
    });
    documentRoot.querySelectorAll('[data-karaoke-lineup-empty]').forEach((empty) => {
      empty.hidden = entries.length > 0;
    });
    documentRoot.querySelectorAll('[data-karaoke-lineup-count]').forEach((count) => {
      count.hidden = entries.length === 0;
      count.textContent = `${entries.length} song${entries.length === 1 ? '' : 's'} in the active lineup.`;
    });
  };

  const updateDocumentTitle = (documentRoot, primary) => {
    if (!documentRoot?.title) return;
    if (!documentRoot.documentElement.dataset.karaokeBaseTitle) {
      documentRoot.documentElement.dataset.karaokeBaseTitle = documentRoot.title;
    }
    const baseTitle = documentRoot.documentElement.dataset.karaokeBaseTitle;
    const key = String(primary?.status?.key || '');
    if (key === 'called') documentRoot.title = `KARAOKE CALL · ${baseTitle}`;
    else if (key === 'up_next') documentRoot.title = `UP NEXT · ${baseTitle}`;
    else documentRoot.title = baseTitle;
  };

  const renderWidget = (widgetRoot, view) => {
    const documentRoot = widgetRoot.ownerDocument || document;
    renderAlert(widgetRoot, view.primary);
    renderPersonalEntries(documentRoot, view.personalEntries);
    renderLineups(documentRoot, view.lineup);
    updateDocumentTitle(documentRoot, view.primary);
    widgetRoot.dataset.karaokeStageMode = view.stageMode;
  };

  const connect = (widgetRoot) => {
    if (!widgetRoot || connections.has(widgetRoot)) return connections.get(widgetRoot);
    const stateUrl = widgetRoot.dataset.karaokeStateUrl || '';
    if (!stateUrl) return null;
    let latestRequestNumber = 0;
    let latestUpdateVersion = 0;
    let closed = false;

    const refresh = async () => {
      const requestNumber = ++latestRequestNumber;
      try {
        const response = await fetch(stateUrl, {
          credentials: 'same-origin',
          cache: 'no-store',
          headers: { Accept: 'application/json' },
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || `Karaoke status refresh failed (${response.status})`);
        const view = buildView(payload);
        if (closed || !shouldApplyResponse({
          requestNumber,
          latestRequestNumber,
          updateVersion: view.updateVersion,
          latestUpdateVersion,
        })) return;
        latestUpdateVersion = Math.max(latestUpdateVersion, view.updateVersion);
        renderWidget(widgetRoot, view);
        widgetRoot.dispatchEvent(new CustomEvent('karaoke:state-updated', { detail: { payload, view } }));
      } catch (error) {
        console.error('Unable to refresh live karaoke status', error);
      }
    };

    const intervalId = window.setInterval(refresh, 5000);
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') refresh();
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    const controller = {
      refresh,
      close: () => {
        if (closed) return;
        closed = true;
        window.clearInterval(intervalId);
        document.removeEventListener('visibilitychange', onVisibilityChange);
        connections.delete(widgetRoot);
      },
    };
    connections.set(widgetRoot, controller);
    refresh();
    return controller;
  };

  const startAll = (documentRoot) => {
    documentRoot.querySelectorAll('[data-karaoke-live-widget]').forEach(connect);
  };

  return {
    buildView,
    connect,
    createLineupItem,
    renderAlert,
    renderLineups,
    renderPersonalEntries,
    renderWidget,
    shouldApplyResponse,
    startAll,
  };
});
