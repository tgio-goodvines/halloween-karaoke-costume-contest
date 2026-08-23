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

  const renderDismissError = (widgetRoot, message = '') => {
    const error = widgetRoot.querySelector('[data-karaoke-dismiss-error]');
    if (!error) return;
    error.textContent = String(message || '');
    error.hidden = !message;
  };

  const responsePayload = async (response) => {
    const contentType = String(response.headers?.get?.('content-type') || '');
    if (contentType.includes('application/json')) return response.json();
    const message = String(await response.text()).trim();
    return message ? { error: message } : {};
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
    const dismissButton = alert.querySelector('[data-karaoke-dismiss-completion]');
    if (dismissButton) {
      dismissButton.hidden = !status.dismissible;
      dismissButton.disabled = false;
      dismissButton.dataset.endpoint = status.dismissible ? String(primary.dismiss_url || '') : '';
      dismissButton.dataset.karaokeEntryId = String(primary.id || '');
      dismissButton.dataset.completionId = status.dismissible ? String(primary.completion_id || '') : '';
    }
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

  const createPersonalEntry = (documentRoot, entry) => {
    const article = documentRoot.createElement('article');
    article.className = 'karaoke-request karaoke-request--attendee';
    article.dataset.karaokePersonalEntry = String(entry.id || '');

    const song = documentRoot.createElement('p');
    const singer = documentRoot.createElement('strong');
    singer.textContent = String(entry.singer_label || 'Singer');
    song.append(
      singer,
      documentRoot.createTextNode(` — “${entry.song_title || 'Song'}”${entry.artist ? ` by ${entry.artist}` : ''}`),
    );
    article.append(song);

    if (entry.relationship === 'singer') {
      const relationship = documentRoot.createElement('p');
      relationship.className = 'karaoke-participation-label';
      relationship.textContent = 'You’re listed as a singer on this request.';
      article.append(relationship);
    }

    const status = documentRoot.createElement('p');
    status.className = 'contest-status';
    status.dataset.karaokeEntryStatus = '';
    const label = documentRoot.createElement('strong');
    label.dataset.karaokeEntryStatusLabel = '';
    const detail = documentRoot.createElement('span');
    detail.dataset.karaokeEntryStatusDetail = '';
    status.append(label, detail);
    article.append(status);

    const dismiss = documentRoot.createElement('button');
    dismiss.type = 'button';
    dismiss.className = 'button button--small';
    dismiss.dataset.karaokeDismissCompletion = '';
    dismiss.dataset.karaokeEntryId = String(entry.id || '');
    dismiss.textContent = 'Dismiss completed performance';
    article.append(dismiss);
    return article;
  };

  const renderPersonalEntries = (documentRoot, entries) => {
    const entryMap = new Map(safeArray(entries).map((entry) => [String(entry.id || ''), entry]));
    const personalList = documentRoot.querySelector('[data-karaoke-personal-list]');
    if (personalList) {
      const existingIds = new Set(
        Array.from(personalList.querySelectorAll('[data-karaoke-personal-entry]'))
          .map((element) => String(element.dataset.karaokePersonalEntry || '')),
      );
      entryMap.forEach((entry, entryId) => {
        if (!existingIds.has(entryId)) personalList.append(createPersonalEntry(documentRoot, entry));
      });
    }
    documentRoot.querySelectorAll('[data-karaoke-personal-entry]').forEach((entryElement) => {
      const entry = entryMap.get(entryElement.dataset.karaokePersonalEntry || '');
      if (!entry) {
        entryElement.remove();
        return;
      }
      const status = safeObject(entry.status);
      const statusElement = entryElement.querySelector('[data-karaoke-entry-status]');
      if (statusElement) statusElement.dataset.karaokeStatusTone = String(status.tone || 'neutral');
      setText(entryElement.querySelector('[data-karaoke-entry-status-label]'), status.label);
      setText(entryElement.querySelector('[data-karaoke-entry-status-detail]'), status.detail);
      const manageActions = entryElement.querySelector('[data-karaoke-manage-actions]');
      if (manageActions) manageActions.hidden = !entry.can_manage;
      const dismissButton = entryElement.querySelector('[data-karaoke-dismiss-completion]');
      if (dismissButton) {
        dismissButton.hidden = !status.dismissible;
        dismissButton.disabled = false;
        dismissButton.dataset.endpoint = status.dismissible ? String(entry.dismiss_url || '') : '';
        dismissButton.dataset.karaokeEntryId = String(entry.id || '');
        dismissButton.dataset.completionId = status.dismissible ? String(entry.completion_id || '') : '';
      }
      renderWorkflow(entryElement, entry.steps);
    });
    documentRoot.querySelectorAll('[data-karaoke-personal-empty]').forEach((empty) => {
      empty.hidden = entryMap.size > 0;
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

    const applyPayload = (payload) => {
      const view = buildView(payload);
      latestUpdateVersion = Math.max(latestUpdateVersion, view.updateVersion);
      renderWidget(widgetRoot, view);
      widgetRoot.dispatchEvent(new CustomEvent('karaoke:state-updated', { detail: { payload, view } }));
      return view;
    };

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
        applyPayload(payload);
      } catch (error) {
        console.error('Unable to refresh live karaoke status', error);
      }
    };

    const onClick = async (event) => {
      const button = event.target.closest?.('[data-karaoke-dismiss-completion]');
      if (!button || !widgetRoot.contains(button) || button.hidden || button.disabled) return;
      const endpoint = String(button.dataset.endpoint || '');
      if (!endpoint) return;
      const entryId = String(button.dataset.karaokeEntryId || '');
      const completionId = String(button.dataset.completionId || '');
      if (!completionId) return;
      const matchingButtons = Array.from(
        widgetRoot.querySelectorAll('[data-karaoke-dismiss-completion]'),
      ).filter((candidate) => String(candidate.dataset.karaokeEntryId || '') === entryId);
      matchingButtons.forEach((candidate) => { candidate.disabled = true; });
      renderDismissError(widgetRoot);
      latestRequestNumber += 1;
      try {
        const response = await fetch(endpoint, {
          method: 'POST',
          credentials: 'same-origin',
          cache: 'no-store',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
            'X-CSRF-Token': String(widgetRoot.dataset.karaokeCsrfToken || ''),
          },
          body: JSON.stringify({ completion_id: completionId }),
        });
        const payload = await responsePayload(response);
        if (!response.ok) throw new Error(payload.error || `Unable to dismiss karaoke status (${response.status})`);
        applyPayload(payload);
      } catch (error) {
        matchingButtons.forEach((candidate) => { candidate.disabled = false; });
        renderDismissError(
          widgetRoot,
          error?.message || 'Unable to dismiss this completed performance. Refresh and try again.',
        );
        console.error('Unable to dismiss completed karaoke status', error);
      }
    };

    const intervalId = window.setInterval(refresh, 5000);
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') refresh();
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    widgetRoot.addEventListener('click', onClick);
    const controller = {
      refresh,
      close: () => {
        if (closed) return;
        closed = true;
        window.clearInterval(intervalId);
        document.removeEventListener('visibilitychange', onVisibilityChange);
        widgetRoot.removeEventListener('click', onClick);
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
    createPersonalEntry,
    createLineupItem,
    renderAlert,
    renderLineups,
    renderPersonalEntries,
    renderDismissError,
    renderWidget,
    shouldApplyResponse,
    startAll,
  };
});
