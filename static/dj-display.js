(() => {
  const body = document.body;
  const initialData = document.getElementById('dj-data');
  if (!body || !initialData) return;

  const dataEndpoint = body.dataset.displayApi;
  const updatesEndpoint = body.dataset.displayUpdates;
  const receiverEndpoint = body.dataset.djReceiverApi;
  const tokenEndpoint = body.dataset.djTokenApi;
  const csrfToken = body.dataset.csrfToken || '';
  const enableButton = document.querySelector('[data-dj-enable]');
  const artworkWrap = document.querySelector('[data-dj-artwork-wrap]');
  const artwork = document.querySelector('[data-dj-artwork]');
  const statusElement = document.querySelector('[data-dj-status]');
  const titleElement = document.querySelector('[data-dj-title]');
  const artistElement = document.querySelector('[data-dj-artist]');
  const detailElement = document.querySelector('[data-dj-detail]');
  const receiverId = window.sessionStorage.getItem('halloween-dj-receiver-id') || crypto.randomUUID();
  window.sessionStorage.setItem('halloween-dj-receiver-id', receiverId);

  let dj = {};
  let music = null;
  let audioEnabled = false;
  let processingCommandId = '';

  try {
    dj = JSON.parse(initialData.textContent || '{}');
  } catch (error) {
    console.error('Unable to read DJ display data', error);
  }

  const receiver = () => (dj && typeof dj.receiver === 'object' ? dj.receiver : {});
  const songs = () => (Array.isArray(dj.playlist) ? dj.playlist : []);
  const songById = (songId) => songs().find((song) => song && String(song.id) === String(songId));

  const setDetail = (text) => {
    if (detailElement) detailElement.textContent = text || '';
  };

  const render = () => {
    const confirmedSong = dj.current_song || songById(receiver().current_song_id);
    const requestedSong = dj.desired_song || songById(dj?.desired?.song_id);
    const song = confirmedSong || requestedSong;
    const playbackStatus = receiver().effective_status === 'offline'
      ? 'Display offline'
      : (receiver().playback_status || 'stopped');

    if (statusElement) statusElement.textContent = `DJ ${String(playbackStatus).replaceAll('_', ' ')}`;
    if (titleElement) titleElement.textContent = song?.title || 'No confirmed song';
    if (artistElement) {
      artistElement.textContent = song
        ? [song.artist, song.album].filter(Boolean).join(' · ')
        : 'Open DJ controls from the admin console.';
    }
    if (artwork && artworkWrap) {
      if (song?.artwork_url) {
        artwork.src = song.artwork_url;
        artwork.alt = `${song.title} artwork`;
        artworkWrap.removeAttribute('hidden');
      } else {
        artwork.removeAttribute('src');
        artwork.alt = '';
        artworkWrap.setAttribute('hidden', '');
      }
    }

    if (enableButton) {
      if (audioEnabled) enableButton.setAttribute('hidden', '');
      else enableButton.removeAttribute('hidden');
    }
  };

  const statusPayload = (extra = {}) => ({
    receiver_id: receiverId,
    status: audioEnabled ? 'ready' : (extra.status || 'needs_audio_enable'),
    authorization_status: audioEnabled ? 'authorized' : (extra.authorization_status || 'not_authorized'),
    audio_enabled: audioEnabled,
    playback_status: extra.playback_status || receiver().playback_status || 'stopped',
    current_song_id: extra.current_song_id || receiver().current_song_id || '',
    playback_position_seconds: extra.playback_position_seconds || 0,
    acknowledged_command_id: extra.acknowledged_command_id || '',
    command_succeeded: Boolean(extra.command_succeeded),
    error: extra.error || '',
  });

  const report = async (extra = {}) => {
    if (!receiverEndpoint) return;
    try {
      const response = await fetch(receiverEndpoint, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
        body: JSON.stringify(statusPayload(extra)),
      });
      if (!response.ok) throw new Error(`Receiver report failed (${response.status})`);
      const payload = await response.json();
      if (payload.dj && typeof payload.dj === 'object') {
        dj = payload.dj;
        render();
      }
    } catch (error) {
      console.error('Unable to report DJ receiver state', error);
    }
  };

  const ensureMusicKit = async () => {
    if (music) return music;
    if (!window.MusicKit) throw new Error('Apple Music player is still loading. Please try again.');
    const response = await fetch(tokenEndpoint, { credentials: 'same-origin', cache: 'no-store' });
    const payload = await response.json();
    if (!response.ok || !payload.developer_token) throw new Error(payload.error || 'Apple Music is not configured.');
    await window.MusicKit.configure({
      developerToken: payload.developer_token,
      app: { name: payload.app_name || 'Halloween Party DJ', build: '1.0.0' },
    });
    music = window.MusicKit.getInstance();
    return music;
  };

  const queueSongs = async (queueOrder) => {
    const identifiers = (Array.isArray(queueOrder) ? queueOrder : [])
      .map(songById)
      .filter(Boolean)
      .map((song) => song.apple_music_id);
    if (!identifiers.length) throw new Error('The selected playlist has no enabled Apple Music songs.');
    await music.setQueue({ songs: identifiers });
    return identifiers;
  };

  const executeCommand = async () => {
    const command = dj?.current_command;
    if (!command || !command.id || command.id === processingCommandId) return;
    processingCommandId = command.id;

    if (!audioEnabled || !music) {
      setDetail('Enable DJ Audio on this display before remote controls can play music.');
      await report({
        status: 'needs_audio_enable',
        authorization_status: 'not_authorized',
        acknowledged_command_id: command.id,
        command_succeeded: false,
        error: 'DJ audio has not been enabled on the live display yet.',
      });
      return;
    }

    try {
      const action = command.action;
      let currentSongId = command.song_id || receiver().current_song_id || '';
      if (action === 'play_song' || action === 'play_playlist' || action === 'shuffle_playlist') {
        await queueSongs(command.queue_order);
        await music.play();
      } else if (action === 'pause') {
        await music.pause();
      } else if (action === 'stop') {
        await music.stop();
      } else if (action === 'next') {
        await music.skipToNextItem();
        const queueOrder = Array.isArray(dj?.desired?.queue_order) ? dj.desired.queue_order : [];
        const currentIndex = queueOrder.indexOf(currentSongId);
        if (currentIndex >= 0 && queueOrder.length) currentSongId = queueOrder[(currentIndex + 1) % queueOrder.length];
      } else if (action === 'previous') {
        await music.skipToPreviousItem();
        const queueOrder = Array.isArray(dj?.desired?.queue_order) ? dj.desired.queue_order : [];
        const currentIndex = queueOrder.indexOf(currentSongId);
        if (currentIndex >= 0 && queueOrder.length) currentSongId = queueOrder[(currentIndex - 1 + queueOrder.length) % queueOrder.length];
      }

      const playbackStatus = action === 'pause' ? 'paused' : (action === 'stop' ? 'stopped' : 'playing');
      await report({
        acknowledged_command_id: command.id,
        command_succeeded: true,
        playback_status: playbackStatus,
        current_song_id: currentSongId,
      });
      setDetail('Live display confirmed the DJ command.');
    } catch (error) {
      const message = error?.message || 'Apple Music could not complete the DJ command.';
      setDetail(message);
      await report({
        status: 'error',
        acknowledged_command_id: command.id,
        command_succeeded: false,
        error: message,
      });
    }
  };

  const sync = async () => {
    if (!dataEndpoint) return;
    try {
      const response = await fetch(dataEndpoint, { credentials: 'same-origin', cache: 'no-store' });
      if (!response.ok) throw new Error(`DJ sync failed (${response.status})`);
      const payload = await response.json();
      if (payload.dj && typeof payload.dj === 'object') {
        dj = payload.dj;
        render();
        await executeCommand();
      }
    } catch (error) {
      console.error('Unable to refresh DJ state', error);
    }
  };

  enableButton?.addEventListener('click', async () => {
    enableButton.disabled = true;
    setDetail('Connecting Apple Music…');
    try {
      const instance = await ensureMusicKit();
      await instance.authorize();
      audioEnabled = true;
      setDetail('Apple Music is connected. Remote DJ controls are ready.');
      render();
      await report({ status: 'ready', authorization_status: 'authorized' });
      await sync();
    } catch (error) {
      const message = error?.message || 'Apple Music authorization did not complete.';
      setDetail(message);
      await report({ status: 'error', authorization_status: 'error', error: message });
    } finally {
      enableButton.disabled = false;
    }
  });

  render();
  report({ status: 'needs_audio_enable', authorization_status: 'not_authorized' });
  sync();
  window.setInterval(() => report(), 5000);
  window.setInterval(sync, 5000);

  if (updatesEndpoint && typeof window.EventSource === 'function') {
    const eventSource = new EventSource(updatesEndpoint);
    eventSource.onmessage = sync;
    window.addEventListener('beforeunload', () => eventSource.close());
  }
})();
