(() => {
  let root = document.querySelector('[data-dj-status-root]');
  if (!root) return;

  const displayApi = root.dataset.djDisplayApi;
  const updatesApi = root.dataset.djDisplayUpdates;
  const requestQueueApi = root.dataset.djRequestQueueUrl;
  const titleize = (value) => String(value || '').replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
  const songLabel = (song, fallback) => song ? [song.title, song.artist].filter(Boolean).join(' — ') : fallback;
  const stateClass = (value) => String(value || 'idle').replaceAll('_', '-');

  const setText = (selector, value) => {
    const element = root.querySelector(selector);
    if (element) element.textContent = value;
  };

  const setArtwork = (wrapSelector, imageSelector, song) => {
    const wrap = root.querySelector(wrapSelector);
    const image = root.querySelector(imageSelector);
    if (!wrap || !image) return;
    if (song?.artwork_url) {
      image.src = song.artwork_url;
      image.alt = `${song.title || 'Song'} artwork`;
      wrap.removeAttribute('hidden');
    } else {
      image.removeAttribute('src');
      image.alt = '';
      wrap.setAttribute('hidden', '');
    }
  };

  const renderCommand = (dj) => {
    const commandState = root?.querySelector('[data-dj-command-state]');
    if (!commandState) return;
    const command = dj.current_command || dj.last_command;
    if (!command) {
      commandState.setAttribute('hidden', '');
      return;
    }
    const status = dj.current_command ? 'pending' : (command.status || 'confirmed');
    commandState.className = `dj-command-state dj-command-state--${stateClass(status)}`;
    commandState.textContent = `${dj.current_command ? 'Waiting for confirmation' : 'Last command'}: ${titleize(command.action)} — ${titleize(status)}${command.error ? `: ${command.error}` : ''}`;
    commandState.removeAttribute('hidden');
  };

  const render = (dj) => {
    root = document.querySelector('[data-dj-status-root]');
    if (!root || !dj || typeof dj !== 'object') return;
    const flowSteps = [...root.querySelectorAll('[data-dj-flow-step]')];
    const receiverError = root.querySelector('[data-dj-receiver-error]');
    const receiver = dj.receiver || {};
    const desired = dj.desired || {};
    const currentSong = dj.current_song || null;
    const nextSong = dj.next_song || null;
    const queueSize = Math.max(0, Number(dj.actual_queue_size) || 0);
    const currentPosition = Math.max(0, Number(dj.current_queue_position) || 0);
    const nextPosition = Math.max(0, Number(dj.next_queue_position) || 0);
    const effectiveStatus = receiver.effective_status || receiver.status || 'offline';
    const pill = root.querySelector('[data-dj-receiver-status]');
    if (pill) {
      pill.className = `dj-status-pill dj-status-pill--${stateClass(effectiveStatus)}`;
      pill.textContent = titleize(effectiveStatus);
    }

    const flow = Array.isArray(dj.flow) ? dj.flow : [];
    flowSteps.forEach((element, index) => {
      const step = flow[index];
      if (!step) return;
      element.className = `dj-flow__step dj-flow__step--${stateClass(step.state)}`;
      const state = element.querySelector('[data-dj-flow-state]');
      const detail = element.querySelector('[data-dj-flow-detail]');
      if (state) state.textContent = titleize(step.state);
      if (detail) detail.textContent = step.detail || '';
    });

    setText('[data-dj-requested-status]', titleize(desired.playback_status || 'stopped'));
    setText('[data-dj-requested-song]', songLabel(dj.desired_song, 'No song selected'));
    setText('[data-dj-queue-status]', queueSize ? `${queueSize} Track${queueSize === 1 ? '' : 's'}` : 'Waiting');
    setText('[data-dj-queue-detail]', currentPosition
      ? `Confirmed position ${currentPosition} of ${queueSize}`
      : 'Start playback to confirm the resolved queue');
    setText('[data-dj-heartbeat-status]', receiver.online ? 'Connected' : 'Offline');
    setText('[data-dj-heartbeat-detail]', receiver.last_seen_at ? `Last seen ${new Date(receiver.last_seen_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}` : 'Open the live display on the TV');
    setText('[data-dj-audio-status]', receiver.audio_enabled ? 'Enabled' : 'Needs display click');
    setText('[data-dj-audio-detail]', titleize(receiver.authorization_status || 'not configured'));
    setText('[data-dj-current-title]', currentSong?.title || 'No confirmed song');
    setText('[data-dj-current-artist]', currentSong
      ? [currentSong.artist, currentSong.album].filter(Boolean).join(' · ')
      : 'Waiting for the live display receiver.');
    setText('[data-dj-current-meta]', `${titleize(receiver.playback_status || 'stopped')}${currentPosition ? ` · Queue ${currentPosition} of ${queueSize}` : ''}`);
    setText('[data-dj-next-title]', nextSong?.title || 'No confirmed next song');
    setText('[data-dj-next-artist]', dj.next_song_detail || (nextSong
      ? [nextSong.artist, nextSong.album].filter(Boolean).join(' · ')
      : 'MusicKit has not confirmed another queue item.'));
    setText('[data-dj-next-meta]', dj.next_song_meta || (nextPosition
      ? `Queue position ${nextPosition} of ${queueSize}`
      : 'No confirmed queue successor'));
    setArtwork('[data-dj-current-artwork-wrap]', '[data-dj-current-artwork]', currentSong);
    setArtwork('[data-dj-next-artwork-wrap]', '[data-dj-next-artwork]', nextSong);

    const priorityStatus = root.querySelector('[data-dj-priority-status]');
    if (priorityStatus) {
      const status = dj.priority_sync_status || 'idle';
      priorityStatus.className = `dj-priority-status dj-priority-status--${stateClass(status)}`;
      priorityStatus.toggleAttribute('hidden', status === 'idle');
      setText('[data-dj-priority-title]', dj.priority_song?.title
        ? `Priority request: ${dj.priority_song.title}`
        : 'Priority queue update');
      setText('[data-dj-priority-message]', dj.priority_sync_message || 'No priority requests are waiting.');
      const retry = priorityStatus.querySelector('[data-dj-priority-retry]');
      if (retry) retry.toggleAttribute('hidden', status !== 'failed');
    }

    const readiness = root.querySelector('[data-dj-controls-readiness]');
    if (readiness) {
      readiness.textContent = dj.controls_message || 'DJ receiver state is unavailable.';
      readiness.classList.toggle('dj-controls-readiness--ready', Boolean(dj.controls_ready));
    }
    const enabledPlaylist = Array.isArray(dj.playlist) && dj.playlist.some((song) => song?.enabled !== false);
    document.querySelectorAll('[data-dj-playback-control]').forEach((control) => {
      const requiresPlaylist = control.dataset.djRequiresPlaylist === 'true';
      const songEnabled = control.dataset.djSongEnabled !== 'false';
      control.disabled = !dj.controls_ready || !songEnabled || (requiresPlaylist && !enabledPlaylist);
    });
    renderCommand(dj);

    if (receiverError) {
      if (receiver.last_error) {
        receiverError.textContent = `Receiver message: ${receiver.last_error}`;
        receiverError.removeAttribute('hidden');
      } else {
        receiverError.setAttribute('hidden', '');
      }
    }
  };

  let refreshing = false;
  const refreshRequestQueue = async () => {
    const requestQueue = document.querySelector('[data-dj-song-request-queue]');
    if (!requestQueueApi || !requestQueue) return;
    try {
      const response = await fetch(requestQueueApi, { credentials: 'same-origin', cache: 'no-store' });
      const payload = await response.json();
      if (response.ok && typeof payload.html === 'string') requestQueue.innerHTML = payload.html;
    } catch (error) {
      console.error('Unable to refresh DJ song requests', error);
    }
  };

  const refresh = async () => {
    if (refreshing || !displayApi) return;
    refreshing = true;
    try {
      const response = await fetch(displayApi, { credentials: 'same-origin', cache: 'no-store' });
      const payload = await response.json();
      if (response.ok) {
        render(payload.dj);
        await refreshRequestQueue();
      }
    } catch (error) {
      console.error('Unable to refresh DJ admin status', error);
    } finally {
      refreshing = false;
    }
  };

  window.setInterval(refresh, 5000);
  document.addEventListener('admin:panel-updated', () => {
    root = document.querySelector('[data-dj-status-root]');
    refresh();
  });
  if (updatesApi && typeof window.EventSource === 'function') {
    const stream = new EventSource(updatesApi);
    stream.onmessage = refresh;
    window.addEventListener('beforeunload', () => stream.close());
  }
})();
