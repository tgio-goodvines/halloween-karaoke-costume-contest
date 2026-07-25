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
  const connectButton = root.querySelector('[data-jukebox-connect]');
  const startButton = root.querySelector('[data-jukebox-start]');
  const skipButton = root.querySelector('[data-jukebox-skip]');
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

  const showAuthPrompt = (control, message) => {
    pendingAuthCommand = control || null;
    if (!authPrompt) {
      return;
    }
    setText(authTitle, control && control.command === 'play' ? 'Sign In To Start Jukebox' : 'Connect Apple Music');
    setText(
      authMessage,
      message ||
        'Sign in with the host Apple Music subscriber account in this browser. Attendees can keep sending requests from their phones.'
    );
    if (authActionButton) {
      authActionButton.textContent = control && control.command === 'play' ? 'Sign In And Play' : 'Sign In With Apple Music';
      authActionButton.disabled = false;
    }
    authPrompt.hidden = false;
    configureMusic({ authorize: false }).catch((error) => {
      setAuthPromptError(error.message || 'Apple Music is not ready in this browser yet.');
    });
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
      authActionButton.disabled = false;
    }
  };

  const visibleQueue = () => {
    const queue = Array.isArray(state.queue) ? state.queue : [];
    return queue.filter((item) => item && item.status !== 'played' && item.status !== 'skipped');
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
    const enabled = Boolean(state && state.enabled);
    root.hidden = !enabled;
    if (body) {
      body.classList.toggle('display-mode--jukebox', enabled);
    }
    if (!enabled) {
      return;
    }

    const nowPlaying = state.now_playing && state.now_playing.title ? state.now_playing : visibleQueue()[0];
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

    setText(stateLabel, music ? 'Connected' : 'Ready');
    if (queueList) {
      queueList.innerHTML = '';
      visibleQueue()
        .slice(0, 6)
        .forEach((item) => {
          const li = document.createElement('li');
          const strong = document.createElement('strong');
          const span = document.createElement('span');
          strong.textContent = item.title || 'Queued song';
          span.textContent = [item.artist, item.requester_name ? `for ${item.requester_name}` : '']
            .filter(Boolean)
            .join(' · ');
          li.appendChild(strong);
          li.appendChild(span);
          queueList.appendChild(li);
        });
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

  const refreshState = async () => {
    try {
      const response = await fetch('/api/jukebox-state', { headers: { Accept: 'application/json' } });
      const payload = await response.json();
      if (response.ok) {
        state = payload;
        syncCurrentQueueItem();
        render();
        await handleDjCommand();
      }
    } catch (error) {
      setStatus('Jukebox state refresh failed.');
    }
  };

  const withTimeout = (operation, message, timeoutMs = 10000) =>
    Promise.race([
      Promise.resolve().then(operation),
      new Promise((resolve, reject) => {
        window.setTimeout(() => reject(new Error(message)), timeoutMs);
      }),
    ]);

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
      if (shouldAuthorize && !musicAuthorized && typeof music.authorize === 'function') {
        await withTimeout(
          () => music.authorize(),
          'Apple Music authorization did not finish. Use the sign-in prompt on this display, allow Apple Music, then press Play again.'
        );
        musicAuthorized = true;
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
    if (shouldAuthorize && music && typeof music.authorize === 'function') {
      await withTimeout(
        () => music.authorize(),
        'Apple Music authorization did not finish. Click the live display once, allow Apple Music sign-in, then press Play again.'
      );
      musicAuthorized = true;
    }
    if (shouldAuthorize) {
      setStatus('Host Apple Music connected. Guests can keep using party requests.');
      hideAuthPrompt();
    }
    render();
    return music;
  };

  const setMusicQueue = async (queueItem) => {
    const activeMusic = await configureMusic();
    const upcoming = visibleQueue();
    const ids = upcoming.map((item) => item.apple_music_id).filter(Boolean);
    if (!queueItem || !queueItem.apple_music_id) {
      throw new Error('No queued Apple Music song is ready.');
    }
    if (typeof activeMusic.setQueue === 'function') {
      try {
        await withTimeout(
          () => activeMusic.setQueue({ songs: ids.length ? ids : [queueItem.apple_music_id] }),
          'Apple Music did not accept the jukebox queue.'
        );
      } catch (error) {
        await withTimeout(
          () => activeMusic.setQueue({ song: queueItem.apple_music_id }),
          'Apple Music did not accept the queued song.'
        );
      }
    }
  };

  const startPlayback = async (commandId) => {
    await refreshState();
    const nextItem = visibleQueue()[0];
    if (!nextItem) {
      setStatus('Queue is empty. Add songs or configure an autoplay seed.');
      return;
    }
    await setMusicQueue(nextItem);
    if (music && typeof music.play === 'function') {
      await withTimeout(
        () => music.play(),
        'Apple Music playback did not start. Click the live display once, confirm Apple Music is signed in, then press Play again.'
      );
    } else if (music && music.player && typeof music.player.play === 'function') {
      await withTimeout(
        () => music.player.play(),
        'Apple Music playback did not start. Click the live display once, confirm Apple Music is signed in, then press Play again.'
      );
    }
    currentQueueItem = nextItem;
    lastEndedItemId = '';
    await postPlaybackEvent('started', currentQueueItem, commandId);
    setStatus('Jukebox playing from the host Apple Music account. Cast this Chrome tab for TV audio.');
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
    if (music && music.player && typeof music.player.skipToNextItem === 'function') {
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
        if (!music) {
          showAuthPrompt(control, 'Admin requested Apple Music sign-in. Use the host Apple Music subscriber account on this display.');
          return;
        }
        await configureMusic();
        await postPlaybackEvent('sync', currentQueueItem, control.id);
      } else if (control.command === 'play') {
        if (!music) {
          showAuthPrompt(control, 'Admin pressed Play. Sign in with Apple Music on this display to start the jukebox audio.');
          return;
        }
        await startPlayback(control.id);
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
    if (authActionButton) {
      authActionButton.disabled = true;
    }
    try {
      if (!control) {
        await configureMusic();
        return;
      }
      if (control.command === 'connect') {
        await configureMusic();
        await postPlaybackEvent('sync', currentQueueItem, control.id);
      } else if (control.command === 'play') {
        await configureMusic();
        await startPlayback(control.id);
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
      if (!music || !music.player || !currentQueueItem || lastEndedItemId === currentQueueItem.id) {
        return;
      }
      const duration = Number(music.player.currentPlaybackDuration || 0);
      const remaining = Number(music.player.currentPlaybackTimeRemaining || 0);
      const playing = Boolean(music.player.isPlaying);
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

  if (connectButton) {
    connectButton.addEventListener('click', async () => {
      try {
        await configureMusic();
      } catch (error) {
        setStatus(error.message || 'Apple Music connection failed.');
      }
    });
  }
  if (startButton) {
    startButton.addEventListener('click', async () => {
      try {
        await startPlayback();
      } catch (error) {
        setStatus(error.message || 'Apple Music playback failed.');
      }
    });
  }
  if (skipButton) {
    skipButton.addEventListener('click', async () => {
      try {
        await skipPlayback();
      } catch (error) {
        setStatus(error.message || 'Unable to skip song.');
      }
    });
  }
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
  window.setInterval(refreshState, 3000);
})();
