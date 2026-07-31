(() => {
  const root = document.querySelector('[data-karaoke-admin]');
  if (!root) return;

  const messageContainer = root.querySelector('[data-karaoke-admin-message]');
  const clearProgress = root.querySelector('[data-karaoke-clear-progress]');
  const csrfToken = document.querySelector('input[name="csrf_token"]')?.value || '';
  let actionInFlight = false;

  const setClearStep = (name, state) => {
    const step = clearProgress?.querySelector(`[data-clear-step="${name}"]`);
    if (!step) return;
    step.classList.remove('is-complete', 'is-current', 'has-error', 'is-pending');
    step.classList.add(state);
  };

  const updateClearProgress = (clear = {}) => {
    if (!clearProgress || !clear.status || clear.status === 'idle') return;
    clearProgress.hidden = false;
    setClearStep('backup', 'is-complete');
    setClearStep('stage', 'is-complete');
    const finished = ['completed', 'local_only_completed'].includes(clear.status);
    setClearStep(
      'youtube',
      clear.status === 'failed' ? 'has-error' : (finished ? 'is-complete' : 'is-current'),
    );
    setClearStep('local', finished ? 'is-complete' : 'is-pending');
    setClearStep('complete', finished ? 'is-complete' : 'is-pending');
    const label = clearProgress.querySelector('[data-clear-youtube-label]');
    if (label) {
      label.textContent = clear.status === 'failed'
        ? 'YouTube needs attention'
        : (clear.status === 'local_only_completed'
          ? 'YouTube intentionally unchanged'
          : (clear.status === 'completed' ? 'YouTube items removed' : 'Removing YouTube items'));
    }
    const count = clearProgress.querySelector('[data-clear-count]');
    if (count) {
      count.textContent = `${clear.deleted_count || 0} of ${clear.target_count || 0} removed`;
    }
  };

  const showMessage = (message, isError = false) => {
    if (!messageContainer) return;
    messageContainer.replaceChildren();
    const notice = document.createElement('div');
    notice.className = `flash ${isError ? 'flash--error' : 'flash--success'}`;
    const paragraph = document.createElement('p');
    paragraph.textContent = message;
    notice.appendChild(paragraph);
    messageContainer.appendChild(notice);
    notice.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  };

  const runAction = async (endpoint, formData = null, trigger = null) => {
    if (!endpoint || actionInFlight) return;
    if (trigger?.dataset.confirm && !window.confirm(trigger.dataset.confirm)) return;
    actionInFlight = true;
    if (trigger) {
      trigger.disabled = true;
      trigger.dataset.originalLabel = trigger.textContent;
      trigger.textContent = 'Processing…';
    }
    if (endpoint.endsWith('/api/admin/karaoke/reset')) {
      updateClearProgress({ status: 'preparing', deleted_count: 0, target_count: 0 });
    }
    const body = formData || new FormData();
    if (!body.has('csrf_token')) body.append('csrf_token', csrfToken);
    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
        body,
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.message || 'The karaoke action failed.');
      showMessage(payload.message || 'Karaoke workflow updated.');
      window.setTimeout(() => window.location.reload(), 450);
    } catch (error) {
      showMessage(error.message || 'The karaoke action failed.', true);
      if (trigger) {
        trigger.disabled = false;
        trigger.textContent = trigger.dataset.originalLabel || 'Try Again';
        if (trigger.dataset.reloadOnError !== undefined) {
          window.setTimeout(() => window.location.reload(), 900);
        }
      }
    } finally {
      actionInFlight = false;
    }
  };

  root.querySelectorAll('[data-karaoke-api]').forEach((button) => {
    button.addEventListener('click', () => runAction(button.dataset.karaokeApi, null, button));
  });

  root.querySelectorAll('[data-karaoke-api-form]').forEach((form) => {
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      runAction(form.action, new FormData(form), form.querySelector('button[type="submit"]'));
    });
  });

  const searchForm = root.querySelector('[data-karaoke-admin-search]');
  const searchResults = root.querySelector('[data-karaoke-admin-search-results]');
  const searchMessage = root.querySelector('[data-karaoke-admin-search-message]');
  let replacementInput = null;

  root.querySelectorAll('[data-karaoke-find-for]').forEach((button) => {
    button.addEventListener('click', () => {
      replacementInput = button.closest('form')?.querySelector('input[name="youtube_link"]') || null;
      const searchSection = searchForm?.closest('details');
      const queryInput = searchForm?.querySelector('input[name="q"]');
      if (!searchForm || !searchSection || !queryInput) {
        showMessage('YouTube search is unavailable. Paste a direct YouTube link instead.', true);
        return;
      }
      searchSection.open = true;
      queryInput.value = button.dataset.karaokeQuery || '';
      queryInput.focus();
      searchSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
      searchForm.requestSubmit();
    });
  });

  const renderSearchResults = (items) => {
    if (!searchResults) return;
    searchResults.replaceChildren();
    items.forEach((video) => {
      const card = document.createElement('article');
      card.className = 'karaoke-video-result';
      if (video.thumbnail_url) {
        const image = document.createElement('img');
        image.src = video.thumbnail_url;
        image.alt = '';
        image.loading = 'lazy';
        card.appendChild(image);
      }
      const body = document.createElement('div');
      const title = document.createElement('strong');
      title.textContent = video.title || 'Untitled YouTube video';
      const meta = document.createElement('span');
      meta.textContent = video.channel_title || 'Unknown channel';
      const actions = document.createElement('div');
      const preview = document.createElement('a');
      preview.className = 'button';
      preview.href = video.watch_url || '#';
      preview.target = '_blank';
      preview.rel = 'noopener';
      preview.textContent = 'Preview';
      const choose = document.createElement('button');
      choose.type = 'button';
      choose.className = 'button button--primary';
      choose.textContent = 'Use for Replacement';
      choose.addEventListener('click', () => {
        if (!replacementInput) {
          showMessage('Press “Find on YouTube” on a request card first.', true);
          return;
        }
        replacementInput.value = video.watch_url || '';
        replacementInput.focus();
        replacementInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
        showMessage('Replacement video selected. Review the card and press Replace Video.');
      });
      actions.append(preview, choose);
      body.append(title, meta, actions);
      card.appendChild(body);
      searchResults.appendChild(card);
    });
  };

  searchForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const query = new FormData(searchForm).get('q')?.toString().trim() || '';
    if (!query || !root.dataset.searchUrl) return;
    const submit = searchForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    if (searchMessage) searchMessage.textContent = 'Searching YouTube…';
    try {
      const url = new URL(root.dataset.searchUrl, window.location.origin);
      url.searchParams.set('q', query);
      const response = await fetch(url, {
        credentials: 'same-origin',
        cache: 'no-store',
        headers: { Accept: 'application/json' },
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'YouTube search failed.');
      renderSearchResults(payload.items || []);
      if (searchMessage) {
        searchMessage.textContent = payload.items?.length
          ? `Found ${payload.items.length} videos.`
          : 'No matching YouTube videos were found.';
      }
    } catch (error) {
      if (searchMessage) searchMessage.textContent = error.message || 'YouTube search failed.';
    } finally {
      submit.disabled = false;
    }
  });

  const playlistForm = root.querySelector('[data-karaoke-playlist-select]');
  const playlistSelect = playlistForm?.querySelector('select[name="playlist_id"]');
  const loadPlaylists = async () => {
    if (!playlistForm || !playlistSelect || !root.dataset.playlistsUrl) return;
    try {
      const response = await fetch(root.dataset.playlistsUrl, {
        credentials: 'same-origin',
        cache: 'no-store',
        headers: { Accept: 'application/json' },
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Unable to list playlists.');
      playlistSelect.replaceChildren();
      const empty = document.createElement('option');
      empty.value = '';
      empty.textContent = 'Choose a YouTube playlist';
      playlistSelect.appendChild(empty);
      (payload.items || []).forEach((playlist) => {
        const option = document.createElement('option');
        option.value = playlist.playlist_id || '';
        option.textContent = `${playlist.title || 'Untitled'} · ${playlist.privacy || 'unknown'}`;
        playlistSelect.appendChild(option);
      });
    } catch (error) {
      showMessage(error.message || 'Unable to list YouTube playlists.', true);
    }
  };
  playlistForm?.addEventListener('submit', (event) => {
    event.preventDefault();
    const endpoint = playlistForm.querySelector('[data-endpoint]')?.dataset.endpoint;
    runAction(endpoint, new FormData(playlistForm), playlistForm.querySelector('[data-endpoint]'));
  });
  loadPlaylists();

  let lastVersion = null;
  const stateUrl = root.dataset.stateUrl;
  const refreshStateVersion = async () => {
    if (!stateUrl) return;
    try {
      const response = await fetch(stateUrl, { credentials: 'same-origin', cache: 'no-store' });
      if (!response.ok) return;
      const state = await response.json();
      updateClearProgress(state.clear_operation);
      const signature = JSON.stringify({
        metrics: state.metrics,
        current: state.current?.id || '',
        next: state.next?.id || '',
        connection: state.youtube?.connection_status || '',
        reconciled: state.youtube?.last_reconciled_at || '',
        clearStatus: state.clear_operation?.status || '',
        clearDeleted: state.clear_operation?.deleted_count || 0,
        clearFailed: state.clear_operation?.failed_count || 0,
      });
      if (lastVersion === null) {
        lastVersion = signature;
      } else if (
        signature !== lastVersion
        && !actionInFlight
        && !root.querySelector('input:focus, select:focus, textarea:focus')
      ) {
        window.location.reload();
      }
    } catch (error) {
      console.error('Unable to refresh karaoke admin state', error);
    }
  };
  window.setInterval(refreshStateVersion, 2000);
  refreshStateVersion();
})();
