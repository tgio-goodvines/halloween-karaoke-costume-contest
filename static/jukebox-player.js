(function () {
  const root = document.querySelector('[data-jukebox-display]');
  const initialDataElement = document.getElementById('jukebox-data');
  if (!root || !initialDataElement) {
    return;
  }

  const parseJson = (element, fallback) => {
    try {
      return JSON.parse(element.textContent || '');
    } catch (error) {
      return fallback;
    }
  };

  let state = parseJson(initialDataElement, {});
  let music = null;
  let musicAuthorized = false;
  let currentQueueItem = null;
  let lastEndedItemId = '';
  let lastDjCommandId = '';
  let musicKitLoadPromise = null;
  let pendingAuthCommand = null;
  let playbackPollId = null;
  let refreshStatePromise = null;

  const body = document.body;
  const csrfToken = body ? body.dataset.csrfToken || '' : '';
  const art = root.querySelector('[data-jukebox-art]');
  const artPlaceholder = root.querySelector('[data-jukebox-art-placeholder]');
  const player = root.querySelector('.jukebox-display__player');
  const title = root.querySelector('[data-jukebox-title]');
  const artist = root.querySelector('[data-jukebox-artist]');
  const requester = root.querySelector('[data-jukebox-requester]');
  const status = root.querySelector('[data-jukebox-status]');
  const stateLabel = root.querySelector('[data-jukebox-state-label]');
  const queueList = root.querySelector('[data-jukebox-queue]');
  const authPrompt = document.querySelector('[data-jukebox-auth]');
  const authTitle = document.querySelector('[data-jukebox-auth-title]');
  const authMessage = document.querySelector('[data-jukebox-auth-message]');
  const authActionButton = document.querySelector('[data-jukebox-auth-action]');
  const authDismissButton = document.querySelector('[data-jukebox-auth-dismiss]');
  const fitClasses = [
    'jukebox-display--compact',
    'jukebox-display--micro',
    'jukebox-display--ultra',
    'jukebox-display--minimal',
    'jukebox-display--no-art',
    'jukebox-display--queue-3',
    'jukebox-display--queue-2',
    'jukebox-display--queue-1',
    'jukebox-display--queue-0',
  ];

  const setStatus = (message) => {
    if (status) {
      status.textContent = message;
    }
  };

  const setText = (element, value) => {
    if (element) {
      element.textContent = value || '';
    }
  };

  const isPlaybackStartCommand = (control) =>
    control && (control.command === 'play' || control.command === 'restart_playlist');

  const syncAuthorizationState = () => {
    if (music && music.isAuthorized === true) {
      musicAuthorized = true;
    }
    return musicAuthorized;
  };

  const setAuthPromptBusy = (message, buttonText) => {
    if (message) {
      setText(authMessage, message);
    }
    if (authActionButton) {
      authActionButton.textContent = buttonText || 'Working...';
      authActionButton.disabled = true;
    }
  };

  const showAuthPrompt = (control, message) => {
    pendingAuthCommand = control || null;
    if (!authPrompt) {
      return;
    }
    setText(authTitle, isPlaybackStartCommand(control) ? 'Sign In To Start Jukebox' : 'Authorize Apple Music Display');
    setText(
      authMessage,
      message ||
        'Use this live-display browser to sign in with the host Apple Music subscriber account. If your phone shows an Apple verification code, enter it in the Apple sign-in window on this display.'
    );
    if (authActionButton) {
      authActionButton.textContent = isPlaybackStartCommand(control) ? 'Sign In And Play' : 'Authorize Apple Music';
      authActionButton.disabled = false;
    }
    authPrompt.hidden = false;
  };

  const hideAuthPrompt = () => {
    pendingAuthCommand = null;
    if (authPrompt) {
      authPrompt.hidden = true;
    }
  };

  const setAuthPromptError = (message) => {
    setText(authMessage, message || 'Apple Music sign-in did not finish. Try again from this display.');
    if (authActionButton) {
      authActionButton.textContent = isPlaybackStartCommand(pendingAuthCommand) ? 'Try Sign In And Play Again' : 'Try Apple Music Authorization Again';
      authActionButton.disabled = false;
    }
  };

  const setAuthPromptReady = (message) => {
    setText(
      authMessage,
      message ||
        'Apple Music is ready for authorization on this display. Press the button here, complete Apple sign-in, then return to admin controls.'
    );
    if (authActionButton) {
      authActionButton.textContent = isPlaybackStartCommand(pendingAuthCommand) ? 'Sign In And Play' : 'Authorize Apple Music';
      authActionButton.disabled = false;
    }
  };

  const visibleQueue = () => {
    const queue = Array.isArray(state.queue) ? state.queue : [];
    return queue.filter((item) => item && item.status !== 'played' && item.status !== 'skipped');
  };

  const findQueueItem = (queueItemId) => {
    const targetId = String(queueItemId || '');
    if (!targetId) {
      return null;
    }
    return visibleQueue().find((item) => String(item.id || '') === targetId) || null;
  };

  const syncCurrentQueueItem = () => {
    if (state && state.now_playing && state.now_playing.id) {
      currentQueueItem = state.now_playing;
      return;
    }
    if (!currentQueueItem) {
      currentQueueItem = visibleQueue()[0] || null;
    }
  };

  const setFitClasses = (classes) => {
    root.classList.remove(...fitClasses);
    classes.forEach((className) => root.classList.add(className));
  };

  const playerOverflows = () => {
    if (!player) {
      return false;
    }
    return player.scrollHeight > player.clientHeight + 1 || player.scrollWidth > player.clientWidth + 1;
  };

  const fitJukeboxCard = () => {
    if (!player || root.hidden) {
      return;
    }

    window.requestAnimationFrame(() => {
      const modes = [
        [],
        ['jukebox-display--queue-3'],
        ['jukebox-display--compact', 'jukebox-display--queue-3'],
        ['jukebox-display--compact', 'jukebox-display--queue-2'],
        ['jukebox-display--micro', 'jukebox-display--queue-2'],
        ['jukebox-display--micro', 'jukebox-display--no-art', 'jukebox-display--queue-2'],
        ['jukebox-display--micro', 'jukebox-display--no-art', 'jukebox-display--queue-1'],
        ['jukebox-display--ultra', 'jukebox-display--no-art', 'jukebox-display--queue-1'],
        ['jukebox-display--ultra', 'jukebox-display--no-art', 'jukebox-display--queue-0'],
        ['jukebox-display--minimal', 'jukebox-display--no-art', 'jukebox-display--queue-0'],
      ];

      for (const mode of modes) {
        setFitClasses(mode);
        if (!playerOverflows()) {
          return;
        }
      }

      setFitClasses(modes[modes.length - 1]);
    });
  };

  const render = () => {
    const enabled = Boolean(state && state.display_active);
    root.hidden = !enabled;
    if (body) {
      body.classList.toggle('display-mode--jukebox', enabled);
    }
    if (!enabled) {
      return;
    }

    const nowPlaying = state.now_playing && state.now_playing.title ? state.now_playing : null;
    if (nowPlaying) {
      setText(title, nowPlaying.title || 'Queued song');
      setText(artist, nowPlaying.artist || '');
      setText(
        requester,
        nowPlaying.requester_name ? `Requested by ${nowPlaying.requester_name}` : 'Curated by the hosts'
      );
      if (nowPlaying.artwork_url && art) {
        art.src = nowPlaying.artwork_url;
        art.alt = `${nowPlaying.title || 'Album'} artwork`;
        art.hidden = false;
        if (artPlaceholder) {
          artPlaceholder.hidden = true;
        }
      } else {
        if (art) {
          art.removeAttribute('src');
          art.alt = '';
          art.hidden = true;
        }
        if (artPlaceholder) {
          artPlaceholder.hidden = false;
        }
      }
    } else {
      setText(title, 'Start the jukebox');
      setText(artist, 'Connect the host Apple Music account on this display');
      setText(requester, '');
    }

    syncAuthorizationState();
    setText(stateLabel, musicAuthorized ? 'Connected' : music ? 'Sign In Needed' : 'Ready');
    if (queueList) {
      queueList.innerHTML = '';
      queueList.hidden = true;
    }
    fitJukeboxCard();
  };

  const postPlaybackEvent = async (event, item, commandId, errorMessage) => {
    const formData = new FormData();
    formData.append('csrf_token', csrfToken);
    formData.append('event', event);
    formData.append('queue_item_id', item && item.id ? item.id : '');
    formData.append('command_id', commandId || '');
    formData.append('error', errorMessage || '');
    const response = await fetch('/api/jukebox/playback-event', {
      method: 'POST',
      body: formData,
      headers: { Accept: 'application/json' },
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || 'Unable to sync jukebox playback.');
    }
    state = payload;
    render();
  };

  const fetchState = async () => {
    const response = await fetch('/api/jukebox-state', {
      headers: { Accept: 'application/json' },
      cache: 'no-store',
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || 'Unable to refresh jukebox state.');
    }
    state = payload;
    syncCurrentQueueItem();
    render();
  };

  const refreshState = async (options = {}) => {
    const shouldHandleCommand = options.handleCommand !== false;
    if (refreshStatePromise) {
      return refreshStatePromise;
    }
    refreshStatePromise = (async () => {
      await fetchState();
      if (shouldHandleCommand) {
        await handleDjCommand();
      }
    })();
    try {
      await refreshStatePromise;
    } catch (error) {
      setStatus('Jukebox state refresh failed.');
    } finally {
      refreshStatePromise = null;
    }
  };

  const withTimeout = (operation, message, timeoutMs = 10000) =>
    Promise.race([
      Promise.resolve().then(operation),
      new Promise((resolve, reject) => {
        window.setTimeout(() => reject(new Error(message)), timeoutMs);
      }),
    ]);

  const isMusicPlaying = () =>
    Boolean(
      music &&
        (music.isPlaying === true || (music.player && music.player.isPlaying === true))
    );

  const waitForPlaybackStart = (timeoutMs = 45000) =>
    new Promise((resolve, reject) => {
      const startedAt = Date.now();
      const check = () => {
        if (isMusicPlaying()) {
          resolve();
          return;
        }
        if (Date.now() - startedAt >= timeoutMs) {
          reject(new Error('Apple Music did not report active playback. Click the live display once, confirm the Apple Music account has an active subscription, then press Play again.'));
          return;
        }
        window.setTimeout(check, 200);
      };
      check();
    });

  const triggerMusicPlay = async () => {
    if (music && typeof music.play === 'function') {
      await music.play();
    } else if (music && music.player && typeof music.player.play === 'function') {
      await music.player.play();
    } else {
      throw new Error('Apple Music playback is not available in this display browser.');
    }
  };

  const confirmPlaybackStarted = (commandId, queueItem, playPromise) => {
    const expectedItemId = queueItem && queueItem.id ? queueItem.id : '';
    setStatus(`Apple Music accepted ${queueItem && queueItem.title ? queueItem.title : 'the selected song'} and is starting playback...`);
    Promise.race([
      waitForPlaybackStart(),
      Promise.resolve(playPromise).then(() => waitForPlaybackStart()),
    ])
      .then(async () => {
        if (expectedItemId && (!currentQueueItem || currentQueueItem.id !== expectedItemId)) {
          return;
        }
        await postPlaybackEvent('started', queueItem, commandId);
        setStatus('Jukebox playing from the host Apple Music account. Cast this Chrome tab for TV audio.');
      })
      .catch(async (error) => {
        try {
          await fetchState();
          const control = state && state.playback_control ? state.playback_control : null;
          if (control && control.id === commandId && control.status === 'pending') {
            await postPlaybackEvent('command_error', queueItem, commandId, error.message || 'Apple Music playback did not start.');
          }
        } catch (ackError) {
          setStatus(ackError.message || error.message || 'Apple Music playback did not start.');
        }
      });
  };

  const waitForMusicKit = () => {
    if (window.MusicKit && typeof window.MusicKit.configure === 'function') {
      return Promise.resolve(window.MusicKit);
    }
    if (musicKitLoadPromise) {
      return musicKitLoadPromise;
    }

    musicKitLoadPromise = new Promise((resolve, reject) => {
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
          reject(new Error('Apple MusicKit did not load in this browser. Check network/content blocking, then reload the live display.'));
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

    return musicKitLoadPromise;
  };

  const configureMusic = async (options = {}) => {
    const shouldAuthorize = options.authorize !== false;
    if (music) {
      syncAuthorizationState();
      if (shouldAuthorize && !musicAuthorized && typeof music.authorize === 'function') {
        setAuthPromptBusy('Opening Apple Music sign-in on this display...', 'Waiting For Apple...');
        await withTimeout(
          () => music.authorize(),
          'Apple Music authorization did not finish. Allow pop-ups for this site, complete Apple sign-in on this display, then try again.',
          20000
        );
        syncAuthorizationState();
        if (music.isAuthorized !== true) {
          throw new Error('Apple Music sign-in did not complete. Enter the Apple verification code in the sign-in window on this display, then try again.');
        }
        musicAuthorized = true;
      } else if (shouldAuthorize && !musicAuthorized) {
        throw new Error('Apple Music authorization is not available in this display browser.');
      }
      return music;
    }
    const response = await fetch('/api/apple-music-token', { headers: { Accept: 'application/json' } });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || 'Apple Music is not configured.');
    }
    const MusicKit = await waitForMusicKit();
    music = await MusicKit.configure({
      developerToken: payload.developer_token,
      app: {
        name: 'Halloween Party Jukebox',
        build: '1.0.0',
      },
      storefrontId: payload.storefront || 'us',
    });
    syncAuthorizationState();
    if (shouldAuthorize && music && typeof music.authorize === 'function') {
      setAuthPromptBusy('Opening Apple Music sign-in on this display...', 'Waiting For Apple...');
      await withTimeout(
        () => music.authorize(),
        'Apple Music authorization did not finish. Allow pop-ups for this site, complete Apple sign-in on this display, then try again.',
        20000
      );
      syncAuthorizationState();
      if (music.isAuthorized !== true) {
        throw new Error('Apple Music sign-in did not complete. Enter the Apple verification code in the sign-in window on this display, then try again.');
      }
      musicAuthorized = true;
    } else if (shouldAuthorize && !musicAuthorized) {
      throw new Error('Apple Music authorization is not available in this display browser.');
    }
    if (shouldAuthorize) {
      setStatus('Host Apple Music connected. Guests can keep using party requests.');
      hideAuthPrompt();
    }
    render();
    return music;
  };

  const requestDisplayAuthorization = async (control, message) => {
    showAuthPrompt(control, message);
    setAuthPromptBusy('Checking Apple Music authorization on this display...', 'Checking...');
    try {
      await configureMusic({ authorize: false });
      if (syncAuthorizationState()) {
        if (control && control.command === 'connect') {
          setAuthPromptReady('Apple Music looks authorized on this display. Press Confirm Connection here to keep this display as the playback surface.');
          if (authActionButton) {
            authActionButton.textContent = 'Confirm Connection';
          }
          return;
        }
        setAuthPromptBusy('Apple Music is already authorized on this display. Syncing admin controls...', 'Connected');
        if (isPlaybackStartCommand(control)) {
          await startPlayback(control.id, control.queue_item_id);
        } else if (control && control.id) {
          await postPlaybackEvent('sync', currentQueueItem, control.id);
        }
        hideAuthPrompt();
        return;
      }
      setAuthPromptReady(message);
    } catch (error) {
      const authMessageText = error.message || 'Apple Music is not ready in this display browser yet.';
      setStatus(authMessageText);
      setAuthPromptError(authMessageText);
    }
  };

  const setMusicQueue = async (queueItem) => {
    const activeMusic = await configureMusic();
    if (!queueItem || !queueItem.apple_music_id) {
      throw new Error('No queued Apple Music song is ready.');
    }
    if (typeof activeMusic.setQueue === 'function') {
      try {
        await withTimeout(
          () => activeMusic.setQueue({ song: queueItem.apple_music_id }),
          'Apple Music did not accept the queued song.'
        );
      } catch (error) {
        await withTimeout(
          () => activeMusic.setQueue({ songs: [queueItem.apple_music_id] }),
          'Apple Music did not accept the queued song.'
        );
      }
    }
  };

  const startPlayback = async (commandId, queueItemId) => {
    await fetchState();
    const nextItem = findQueueItem(queueItemId) || visibleQueue()[0];
    if (!nextItem) {
      setStatus('Queue is empty. Add songs or configure an autoplay seed.');
      return;
    }
    await setMusicQueue(nextItem);
    currentQueueItem = nextItem;
    lastEndedItemId = '';
    setStatus(`Starting ${nextItem.title || 'the selected song'} through Apple Music...`);
    const playPromise = triggerMusicPlay();
    confirmPlaybackStarted(commandId, currentQueueItem, playPromise);
  };

  const pausePlayback = async (commandId, eventName) => {
    if (music && typeof music.pause === 'function') {
      await withTimeout(() => music.pause(), 'Apple Music did not pause.');
    } else if (music && music.player && typeof music.player.pause === 'function') {
      await withTimeout(() => music.player.pause(), 'Apple Music did not pause.');
    } else {
      throw new Error('Apple Music is not connected on this display yet.');
    }
    await postPlaybackEvent(eventName || 'paused', currentQueueItem, commandId);
    setStatus(eventName === 'stopped' ? 'Jukebox stopped from admin.' : 'Jukebox paused from admin.');
  };

  const skipPlayback = async (commandId) => {
    if (music && typeof music.skipToNextItem === 'function') {
      try {
        await music.skipToNextItem();
      } catch (error) {
        setStatus('Apple Music skip was blocked; syncing app queue.');
      }
    } else if (music && music.player && typeof music.player.skipToNextItem === 'function') {
      try {
        await music.player.skipToNextItem();
      } catch (error) {
        setStatus('Apple Music skip was blocked; syncing app queue.');
      }
    }
    if (currentQueueItem) {
      await postPlaybackEvent('skipped', currentQueueItem, commandId);
    }
    currentQueueItem = visibleQueue()[0] || null;
    if (currentQueueItem) {
      await startPlayback();
    }
  };

  const handleDjCommand = async () => {
    const control = state && state.playback_control ? state.playback_control : null;
    if (!control || control.status !== 'pending' || !control.id || control.id === lastDjCommandId) {
      return;
    }
    lastDjCommandId = control.id;
    try {
      if (control.command === 'connect') {
        if (!musicAuthorized) {
          await requestDisplayAuthorization(
            control,
            'Admin requested Apple Music authorization. Use this live-display browser to sign in with the host Apple Music subscriber account.'
          );
          return;
        }
        await configureMusic();
        await postPlaybackEvent('sync', currentQueueItem, control.id);
      } else if (control.command === 'play') {
        if (!musicAuthorized) {
          await requestDisplayAuthorization(
            control,
            'Admin pressed Play. Authorize Apple Music on this display to start jukebox audio.'
          );
          return;
        }
        await startPlayback(control.id, control.queue_item_id);
      } else if (control.command === 'restart_playlist') {
        if (!musicAuthorized) {
          await requestDisplayAuthorization(
            control,
            'Admin restarted the active playlist. Authorize Apple Music on this display to play from the beginning.'
          );
          return;
        }
        await startPlayback(control.id, control.queue_item_id);
      } else if (control.command === 'pause') {
        await pausePlayback(control.id, 'paused');
      } else if (control.command === 'stop') {
        await pausePlayback(control.id, 'stopped');
      } else if (control.command === 'skip') {
        await skipPlayback(control.id);
      }
    } catch (error) {
      const message = error.message || 'Unable to complete DJ command on the live display.';
      setStatus(message);
      try {
        await postPlaybackEvent('command_error', currentQueueItem, control.id, message);
      } catch (ackError) {
        setStatus(ackError.message || message);
      }
    }
  };

  const completeAuthPrompt = async () => {
    const control = pendingAuthCommand;
    setAuthPromptBusy('Opening Apple Music sign-in on this display...', 'Waiting For Apple...');
    try {
      if (!control) {
        await configureMusic();
        hideAuthPrompt();
        return;
      }
      if (control.command === 'connect') {
        await configureMusic();
        await postPlaybackEvent('sync', currentQueueItem, control.id);
      } else if (isPlaybackStartCommand(control)) {
        await configureMusic();
        await startPlayback(control.id, control.queue_item_id);
      }
      hideAuthPrompt();
    } catch (error) {
      const message = error.message || 'Apple Music sign-in failed.';
      setStatus(message);
      setAuthPromptError(message);
      if (control && control.id) {
        try {
          await postPlaybackEvent('command_error', currentQueueItem, control.id, message);
        } catch (ackError) {
          setAuthPromptError(ackError.message || message);
        }
      }
    }
  };

  const watchForEnded = () => {
    if (playbackPollId) {
      window.clearInterval(playbackPollId);
    }
    playbackPollId = window.setInterval(async () => {
      if (!music || !currentQueueItem || lastEndedItemId === currentQueueItem.id) {
        return;
      }
      const duration = Number(music.currentPlaybackDuration || (music.player && music.player.currentPlaybackDuration) || 0);
      const remaining = Number(music.currentPlaybackTimeRemaining || (music.player && music.player.currentPlaybackTimeRemaining) || 0);
      const playing = isMusicPlaying();
      if (duration > 0 && remaining <= 1 && !playing) {
        lastEndedItemId = currentQueueItem.id;
        try {
          await postPlaybackEvent('ended', currentQueueItem);
          currentQueueItem = visibleQueue()[0] || null;
          if (currentQueueItem) {
            await startPlayback();
          }
        } catch (error) {
          setStatus(error.message || 'Unable to advance jukebox queue.');
        }
      }
    }, 2000);
  };

  if (authActionButton) {
    authActionButton.addEventListener('click', completeAuthPrompt);
  }
  if (authDismissButton) {
    authDismissButton.addEventListener('click', async () => {
      const control = pendingAuthCommand;
      hideAuthPrompt();
      if (control && control.id) {
        try {
          await postPlaybackEvent('command_error', currentQueueItem, control.id, 'Apple Music sign-in was dismissed on the live display.');
        } catch (error) {
          setStatus(error.message || 'Unable to dismiss Apple Music sign-in.');
        }
      }
    });
  }

  render();
  watchForEnded();
  refreshState();
  window.addEventListener('halloween:display-update', () => {
    refreshState();
  });
  window.setInterval(refreshState, 3000);
})();
