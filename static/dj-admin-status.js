(() => {
  const root = document.querySelector('[data-dj-status-root]');
  if (!root) return;

  const displayApi = root.dataset.djDisplayApi;
  const updatesApi = root.dataset.djDisplayUpdates;
  const titleize = (value) => String(value || '').replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
  const songLabel = (song, fallback) => song ? [song.title, song.artist].filter(Boolean).join(' — ') : fallback;
  const stateClass = (value) => String(value || 'idle').replaceAll('_', '-');
  const flowSteps = [...root.querySelectorAll('[data-dj-flow-step]')];
  const commandState = root.querySelector('[data-dj-command-state]');
  const receiverError = root.querySelector('[data-dj-receiver-error]');

  const setText = (selector, value) => {
    const element = root.querySelector(selector);
    if (element) element.textContent = value;
  };

  const renderCommand = (dj) => {
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
    if (!dj || typeof dj !== 'object') return;
    const receiver = dj.receiver || {};
    const desired = dj.desired || {};
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
    setText('[data-dj-confirmed-status]', titleize(receiver.playback_status || 'stopped'));
    setText('[data-dj-confirmed-song]', songLabel(dj.current_song, 'No confirmed song'));
    setText('[data-dj-heartbeat-status]', receiver.online ? 'Connected' : 'Offline');
    setText('[data-dj-heartbeat-detail]', receiver.last_seen_at ? `Last seen ${new Date(receiver.last_seen_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}` : 'Open the live display on the TV');
    setText('[data-dj-audio-status]', receiver.audio_enabled ? 'Enabled' : 'Needs display click');
    setText('[data-dj-audio-detail]', titleize(receiver.authorization_status || 'not configured'));
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
  const refresh = async () => {
    if (refreshing || !displayApi) return;
    refreshing = true;
    try {
      const response = await fetch(displayApi, { credentials: 'same-origin', cache: 'no-store' });
      const payload = await response.json();
      if (response.ok) render(payload.dj);
    } catch (error) {
      console.error('Unable to refresh DJ admin status', error);
    } finally {
      refreshing = false;
    }
  };

  window.setInterval(refresh, 5000);
  if (updatesApi && typeof window.EventSource === 'function') {
    const stream = new EventSource(updatesApi);
    stream.onmessage = refresh;
    window.addEventListener('beforeunload', () => stream.close());
  }
})();
