(() => {
  const body = document.body;
  const initialData = document.getElementById('dj-data');
  if (!body || !initialData) return;

  const dataEndpoint = body.dataset.displayApi;
  const updatesEndpoint = body.dataset.displayUpdates;
  const receiverEndpoint = body.dataset.djReceiverApi;
  const tokenEndpoint = body.dataset.djTokenApi;
  const appleMusicConfigured = body.dataset.djAppleMusicConfigured === 'true';
  const queueState = window.HalloweenDjQueueState;
  if (!queueState) {
    console.error('DJ queue state helpers did not load. Refresh this display and try again.');
    return;
  }
  const csrfToken = body.dataset.csrfToken || '';
  const enableButton = document.querySelector('[data-dj-enable]');
  const artworkWrap = document.querySelector('[data-dj-artwork-wrap]');
  const artwork = document.querySelector('[data-dj-artwork]');
  const statusElement = document.querySelector('[data-dj-status]');
  const titleElement = document.querySelector('[data-dj-title]');
  const artistElement = document.querySelector('[data-dj-artist]');
  const detailElement = document.querySelector('[data-dj-detail]');
  const receiverId = window.sessionStorage.getItem('halloween-dj-receiver-id')
    || (window.crypto?.randomUUID?.() || `receiver-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  window.sessionStorage.setItem('halloween-dj-receiver-id', receiverId);

  let dj = {};
  let music = null;
  let audioEnabled = false;
  let authorizationStatus = 'not_authorized';
  let verifiedMusicUserToken = '';
  let receiverError = '';
  let pairingInProgress = false;
  let processingCommandId = '';
  let playbackSongId = '';
  let actualQueueOrder = [];
  let currentQueueIndex = -1;
  let queueRevision = 0;
  let priorityRevision = 0;
  let pendingTrackSelection = null;
  let eventMusic = null;
  let reportChain = Promise.resolve();

  try {
    dj = JSON.parse(initialData.textContent || '{}');
  } catch (error) {
    console.error('Unable to read DJ display data', error);
  }

  const receiver = () => (dj && typeof dj.receiver === 'object' ? dj.receiver : {});
  const songs = () => (Array.isArray(dj.playlist) ? dj.playlist : []);
  const songById = (songId) => songs().find((song) => song && String(song.id) === String(songId));

  playbackSongId = receiver().current_song_id || '';
  actualQueueOrder = Array.isArray(receiver().queue_order) ? [...receiver().queue_order] : [];
  currentQueueIndex = Number.isInteger(Number(receiver().current_queue_index))
    ? Number(receiver().current_queue_index)
    : -1;
  queueRevision = Math.max(0, Number(receiver().queue_revision) || 0);
  priorityRevision = Math.max(0, Number(receiver().priority_revision) || 0);

  const localSongIdForMediaItem = (item) => queueState.localSongIdForMediaItem(item, songs());

  const queueItems = (queueCandidate = music?.queue) => queueState.queueItems(queueCandidate);

  const playbackSnapshot = (item = music?.nowPlayingItem, queueCandidate = music?.queue) => {
    const songId = localSongIdForMediaItem(item);
    const items = queueItems(queueCandidate);
    if (queueCandidate?.items != null) {
      actualQueueOrder = items.map(localSongIdForMediaItem);
    }
    const reportedIndex = Number(music?.nowPlayingItemIndex);
    if (Number.isInteger(reportedIndex) && reportedIndex >= 0) {
      currentQueueIndex = reportedIndex;
    } else if (songId) {
      const resolvedIndex = actualQueueOrder.indexOf(songId);
      if (resolvedIndex >= 0) currentQueueIndex = resolvedIndex;
    }
    return {
      songId,
      queueOrder: [...actualQueueOrder],
      queueIndex: currentQueueIndex,
    };
  };

  const applyPlaybackSnapshot = (snapshot) => {
    if (!snapshot?.songId) return;
    playbackSongId = snapshot.songId;
    actualQueueOrder = [...snapshot.queueOrder];
    currentQueueIndex = snapshot.queueIndex;
    receiver().current_song_id = snapshot.songId;
    receiver().queue_order = [...snapshot.queueOrder];
    receiver().current_queue_index = snapshot.queueIndex;
    dj.current_song = songById(snapshot.songId) || null;
    render();
  };

  const setDetail = (text) => {
    if (detailElement) detailElement.textContent = text || '';
  };

  const errorMessage = (error, fallback) => {
    const candidates = [
      error?.message,
      error?.error?.message,
      error?.detail,
      typeof error === 'string' ? error : '',
    ];
    const message = candidates.find((candidate) => (
      typeof candidate === 'string' && candidate.trim() && candidate.trim().toLowerCase() !== 'undefined'
    ));
    return message ? message.trim() : fallback;
  };

  const render = () => {
    const confirmedSong = songById(playbackSongId) || dj.current_song || songById(receiver().current_song_id);
    const song = confirmedSong;
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
      if (audioEnabled || pairingInProgress || !appleMusicConfigured) enableButton.setAttribute('hidden', '');
      else enableButton.removeAttribute('hidden');
    }
  };

  const statusPayload = (extra = {}) => {
    const hasError = Object.prototype.hasOwnProperty.call(extra, 'error');
    const hasCurrentSong = Object.prototype.hasOwnProperty.call(extra, 'current_song_id');
    const hasPlaybackPosition = Object.prototype.hasOwnProperty.call(extra, 'playback_position_seconds');
    return {
      receiver_id: receiverId,
      status: extra.status || (audioEnabled ? 'ready' : (receiverError ? 'error' : 'needs_audio_enable')),
      authorization_status: extra.authorization_status || (audioEnabled ? 'authorized' : authorizationStatus),
      audio_enabled: audioEnabled,
      playback_status: extra.playback_status || receiver().playback_status || 'stopped',
      current_song_id: hasCurrentSong
        ? String(extra.current_song_id || '')
        : (playbackSongId || receiver().current_song_id || ''),
      playback_position_seconds: hasPlaybackPosition
        ? (extra.playback_position_seconds || 0)
        : Math.max(0, Number(music?.currentPlaybackTime) || 0),
      queue_order: Array.isArray(extra.queue_order) ? extra.queue_order : [...actualQueueOrder],
      current_queue_index: Object.prototype.hasOwnProperty.call(extra, 'current_queue_index')
        ? Number(extra.current_queue_index)
        : currentQueueIndex,
      queue_revision: Object.prototype.hasOwnProperty.call(extra, 'queue_revision')
        ? Math.max(0, Number(extra.queue_revision) || 0)
        : queueRevision,
      priority_revision: Object.prototype.hasOwnProperty.call(extra, 'priority_revision')
        ? Math.max(0, Number(extra.priority_revision) || 0)
        : priorityRevision,
      acknowledged_command_id: extra.acknowledged_command_id || '',
      command_succeeded: Boolean(extra.command_succeeded),
      clear_error: Boolean(extra.clear_error),
      error: hasError ? extra.error : receiverError,
    };
  };

  const sendReport = async (extra = {}) => {
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

  // Keep receiver reports ordered. A heartbeat that starts while MusicKit is
  // changing tracks must not arrive after the track-change report and put the
  // old song back into Redis.
  const report = (extra = {}) => {
    reportChain = reportChain.then(() => sendReport(extra));
    return reportChain;
  };

  const clearPendingTrackSelection = (error) => {
    if (!pendingTrackSelection) return;
    window.clearTimeout(pendingTrackSelection.timeoutId);
    const pending = pendingTrackSelection;
    pendingTrackSelection = null;
    if (error) pending.reject(error);
  };

  const resolvePendingTrackSelection = (snapshot) => {
    if (!pendingTrackSelection || !snapshot?.songId) return false;
    if (
      snapshot.queueOrder.length
      && snapshot.queueIndex >= 0
      && snapshot.queueOrder[snapshot.queueIndex] !== snapshot.songId
    ) return false;
    if (!queueState.selectionChanged(
      snapshot,
      pendingTrackSelection.previousSongId,
      pendingTrackSelection.previousQueueIndex,
      pendingTrackSelection.allowSame,
    )) return false;
    window.clearTimeout(pendingTrackSelection.timeoutId);
    const pending = pendingTrackSelection;
    pendingTrackSelection = null;
    pending.resolve(snapshot);
    return true;
  };

  const waitForConfirmedTrack = async (performAction, { allowSame = false } = {}) => {
    clearPendingTrackSelection(new Error('A newer DJ track change replaced the previous one.'));
    const previousSongId = playbackSongId || receiver().current_song_id || '';
    const previousQueueIndex = currentQueueIndex;
    const confirmation = new Promise((resolve, reject) => {
      const timeoutId = window.setTimeout(() => {
        if (!pendingTrackSelection) return;
        pendingTrackSelection = null;
        reject(new Error('Apple Music changed the queue but did not confirm the resulting song. Try the command again.'));
      }, 7000);
      pendingTrackSelection = {
        allowSame,
        previousSongId,
        previousQueueIndex,
        resolve,
        reject,
        timeoutId,
      };
    });

    try {
      await performAction();
      const immediate = playbackSnapshot();
      if (immediate.songId) resolvePendingTrackSelection(immediate);
      return await confirmation;
    } catch (error) {
      if (pendingTrackSelection) {
        window.clearTimeout(pendingTrackSelection.timeoutId);
        pendingTrackSelection = null;
      }
      throw error;
    }
  };

  const waitForConfirmedQueue = async (performAction, currentSongId, expectedQueueOrder) => {
    const returnedQueue = await performAction();
    for (let attempt = 0; attempt < 30; attempt += 1) {
      const candidate = attempt === 0 && returnedQueue ? returnedQueue : music?.queue;
      const snapshot = playbackSnapshot(music?.nowPlayingItem, candidate);
      if (queueState.queueSyncConfirmed(snapshot, currentSongId, expectedQueueOrder)) return snapshot;
      await new Promise((resolve) => window.setTimeout(resolve, 100));
    }
    throw new Error('MusicKit did not confirm the requested priority queue order. The current song was left unchanged.');
  };

  const onNowPlayingItemDidChange = async (event) => {
    if (!audioEnabled) return;
    const snapshot = playbackSnapshot(event?.item || music?.nowPlayingItem);
    if (!snapshot.songId) {
      setDetail('Apple Music changed songs, but the new catalog item is not in the saved DJ playlist.');
      return;
    }
    applyPlaybackSnapshot(snapshot);
    if (resolvePendingTrackSelection(snapshot)) return;
    await report({
      current_song_id: snapshot.songId,
      queue_order: snapshot.queueOrder,
      current_queue_index: snapshot.queueIndex,
      playback_status: music?.isPlaying ? 'playing' : (receiver().playback_status || 'stopped'),
    });
  };

  const bindMusicEvents = (instance) => {
    if (!instance || eventMusic === instance || typeof instance.addEventListener !== 'function') return;
    if (eventMusic && typeof eventMusic.removeEventListener === 'function') {
      eventMusic.removeEventListener('nowPlayingItemDidChange', onNowPlayingItemDidChange);
    }
    eventMusic = instance;
    eventMusic.addEventListener('nowPlayingItemDidChange', onNowPlayingItemDidChange);
  };

  const waitForMusicKit = async () => {
    if (window.MusicKit) return window.MusicKit;
    return new Promise((resolve, reject) => {
      const timeout = window.setTimeout(() => reject(new Error('Apple Music player did not load. Refresh this display and try again.')), 12000);
      const finish = () => {
        if (!window.MusicKit) return;
        window.clearTimeout(timeout);
        window.removeEventListener('musickitloaded', finish);
        resolve(window.MusicKit);
      };
      window.addEventListener('musickitloaded', finish, { once: true });
      window.setTimeout(finish, 0);
    });
  };

  const ensureMusicKit = async () => {
    if (music) return music;
    const musicKit = await waitForMusicKit();
    const response = await fetch(tokenEndpoint, { credentials: 'same-origin', cache: 'no-store' });
    const payload = await response.json();
    if (!response.ok || !payload.developer_token) throw new Error(payload.error || 'Apple Music is not configured.');
    await musicKit.configure({
      developerToken: payload.developer_token,
      app: { name: payload.app_name || 'Halloween Party DJ', build: '1.0.0' },
      storefrontId: payload.storefront || 'us',
    });
    music = musicKit.getInstance();
    if (!music || typeof music.authorize !== 'function') throw new Error('Apple Music did not initialize correctly. Refresh this display and try again.');
    bindMusicEvents(music);
    return music;
  };

  const resetLocalReceiver = async () => {
    let stopError = null;
    try {
      if (music && typeof music.stop === 'function') await music.stop();
    } catch (error) {
      stopError = error;
    }
    music = null;
    audioEnabled = false;
    authorizationStatus = 'not_authorized';
    receiverError = '';
    processingCommandId = '';
    playbackSongId = '';
    actualQueueOrder = [];
    currentQueueIndex = -1;
    queueRevision = 0;
    priorityRevision = 0;
    clearPendingTrackSelection(new Error('The DJ workflow was reset.'));
    if (stopError) throw stopError;
  };

  const queueSongs = async (queueOrder, revision) => {
    const identifiers = (Array.isArray(queueOrder) ? queueOrder : [])
      .map(songById)
      .filter(Boolean)
      .map((song) => song.apple_music_id);
    if (!identifiers.length) throw new Error('The selected playlist has no enabled Apple Music songs.');
    const resolvedQueue = await music.setQueue({ songs: identifiers });
    const resolvedItems = queueItems(resolvedQueue || music?.queue);
    actualQueueOrder = resolvedItems.map(localSongIdForMediaItem);
    currentQueueIndex = -1;
    queueRevision = Math.max(0, Number(revision) || queueRevision + 1);
    return actualQueueOrder;
  };

  const syncPriorityQueue = async (command) => {
    const currentSongId = String(command.song_id || playbackSongId || receiver().current_song_id || '');
    const currentSnapshot = playbackSnapshot();
    if (!currentSongId || currentSnapshot.songId !== currentSongId) {
      throw new Error('MusicKit current-song state changed before the priority queue update could be applied.');
    }
    if (typeof music.playNext !== 'function') {
      throw new Error('This MusicKit receiver does not support non-interrupting Play Next queue updates.');
    }
    const expectedQueueOrder = Array.isArray(command.queue_order) ? command.queue_order.map(String) : [];
    const identifiers = queueState.priorityCatalogIdentifiers(expectedQueueOrder, currentSongId, songs());
    if (!identifiers) {
      throw new Error('A priority queue song is missing valid Apple Music metadata.');
    }
    const snapshot = await waitForConfirmedQueue(
      () => music.playNext({ songs: identifiers }, true),
      currentSongId,
      expectedQueueOrder,
    );
    queueRevision = Math.max(0, Number(command.revision) || queueRevision + 1);
    priorityRevision = Math.max(0, Number(command.priority_revision) || priorityRevision);
    return snapshot;
  };

  const executeCommand = async () => {
    const command = dj?.current_command;
    if (!command || !command.id || command.id === processingCommandId) return;
    processingCommandId = command.id;

    if (command.action === 'reset') {
      try {
        await resetLocalReceiver();
        setDetail('DJ workflow reset. Enable DJ Audio before playing music again.');
        await report({
          status: 'needs_audio_enable',
          authorization_status: 'not_authorized',
          acknowledged_command_id: command.id,
          command_succeeded: true,
          playback_status: 'stopped',
          current_song_id: '',
          error: '',
          clear_error: true,
        });
      } catch (error) {
        const message = errorMessage(error, 'The live display could not stop Apple Music during the reset.');
        receiverError = message;
        authorizationStatus = 'error';
        setDetail(message);
        await report({
          status: 'error',
          authorization_status: 'error',
          acknowledged_command_id: command.id,
          command_succeeded: false,
          error: message,
        });
      }
      processingCommandId = '';
      return;
    }

    if (!audioEnabled || !music) {
      receiverError = 'DJ audio has not been enabled on the live display yet.';
      authorizationStatus = 'not_authorized';
      setDetail(receiverError);
      await report({
        status: 'needs_audio_enable',
        authorization_status: 'not_authorized',
        acknowledged_command_id: command.id,
        command_succeeded: false,
        error: receiverError,
      });
      return;
    }

    try {
      const action = command.action;
      let currentSongId = playbackSongId || receiver().current_song_id || '';
      let snapshot = playbackSnapshot();
      if (action === 'play_song' || action === 'play_playlist' || action === 'shuffle_playlist') {
        await queueSongs(command.queue_order, command.revision);
        snapshot = await waitForConfirmedTrack(() => music.play(), { allowSame: true });
        currentSongId = snapshot.songId;
        priorityRevision = Math.max(0, Number(command.priority_revision) || priorityRevision);
      } else if (action === 'sync_priority_queue') {
        snapshot = await syncPriorityQueue(command);
        currentSongId = snapshot.songId;
      } else if (action === 'pause') {
        await music.pause();
        snapshot = playbackSnapshot();
      } else if (action === 'stop') {
        await music.stop();
        snapshot = playbackSnapshot();
      } else if (action === 'next') {
        snapshot = await waitForConfirmedTrack(() => music.skipToNextItem());
        currentSongId = snapshot.songId;
      } else if (action === 'previous') {
        snapshot = await waitForConfirmedTrack(() => music.skipToPreviousItem());
        currentSongId = snapshot.songId;
      }

      const playbackStatus = action === 'pause'
        ? 'paused'
        : (action === 'stop' ? 'stopped' : (action === 'sync_priority_queue' ? (receiver().playback_status || 'playing') : 'playing'));
      playbackSongId = currentSongId;
      if (currentSongId) applyPlaybackSnapshot(snapshot);
      await report({
        acknowledged_command_id: command.id,
        command_succeeded: true,
        playback_status: playbackStatus,
        current_song_id: currentSongId,
        queue_order: snapshot.queueOrder,
        current_queue_index: snapshot.queueIndex,
        queue_revision: queueRevision,
        priority_revision: priorityRevision,
        error: '',
        clear_error: true,
      });
      receiverError = '';
      setDetail('Live display confirmed the DJ command.');
    } catch (error) {
      const message = errorMessage(error, 'Apple Music could not complete the DJ command.');
      receiverError = message;
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
    pairingInProgress = true;
    enableButton.disabled = true;
    setDetail('Connecting Apple Music…');
    try {
      const instance = await ensureMusicKit();
      // MusicKit can retain an unusable/stale browser authorization from an
      // earlier page. The first explicit enable click must establish a real
      // Music User Token so the operator sees Apple's consent/account flow.
      if (!verifiedMusicUserToken && instance.isAuthorized && typeof instance.unauthorize === 'function') {
        await instance.unauthorize();
      }
      const userToken = await instance.authorize();
      if (!instance.isAuthorized || !userToken) {
        throw new Error('Apple Music sign-in did not complete. Click Enable DJ Audio again and finish the Apple prompt on this display.');
      }
      verifiedMusicUserToken = userToken;
      audioEnabled = true;
      authorizationStatus = 'authorized';
      receiverError = '';
      setDetail('Apple Music is connected. Remote DJ controls are ready.');
      await report({ status: 'ready', authorization_status: 'authorized', error: '', clear_error: true });
      await sync();
    } catch (error) {
      const message = errorMessage(error, 'Apple Music authorization did not complete.');
      receiverError = message;
      authorizationStatus = 'error';
      setDetail(message);
      await report({ status: 'error', authorization_status: 'error', error: message });
    } finally {
      pairingInProgress = false;
      enableButton.disabled = false;
      render();
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
