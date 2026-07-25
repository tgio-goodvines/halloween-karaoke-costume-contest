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
  let currentQueueItem = null;
  let lastEndedItemId = '';
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

  const visibleQueue = () => {
    const queue = Array.isArray(state.queue) ? state.queue : [];
    return queue.filter((item) => item && item.status !== 'played' && item.status !== 'skipped');
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

  const postPlaybackEvent = async (event, item) => {
    const formData = new FormData();
    formData.append('csrf_token', csrfToken);
    formData.append('event', event);
    formData.append('queue_item_id', item && item.id ? item.id : '');
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
        render();
      }
    } catch (error) {
      setStatus('Jukebox state refresh failed.');
    }
  };

  const configureMusic = async () => {
    if (music) {
      return music;
    }
    const response = await fetch('/api/apple-music-token', { headers: { Accept: 'application/json' } });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || 'Apple Music is not configured.');
    }
    if (!window.MusicKit || typeof window.MusicKit.configure !== 'function') {
      throw new Error('MusicKit did not load yet.');
    }
    music = await window.MusicKit.configure({
      developerToken: payload.developer_token,
      app: {
        name: 'Halloween Party Jukebox',
        build: '1.0.0',
      },
      storefrontId: payload.storefront || 'us',
    });
    if (music && typeof music.authorize === 'function') {
      await music.authorize();
    }
    setStatus('Host Apple Music connected. Guests can keep using party requests.');
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
        await activeMusic.setQueue({ songs: ids.length ? ids : [queueItem.apple_music_id] });
      } catch (error) {
        await activeMusic.setQueue({ song: queueItem.apple_music_id });
      }
    }
  };

  const startPlayback = async () => {
    await refreshState();
    const nextItem = visibleQueue()[0];
    if (!nextItem) {
      setStatus('Queue is empty. Add songs or configure an autoplay seed.');
      return;
    }
    await setMusicQueue(nextItem);
    if (music && music.player && typeof music.player.play === 'function') {
      await music.player.play();
    } else if (music && typeof music.play === 'function') {
      await music.play();
    }
    currentQueueItem = nextItem;
    lastEndedItemId = '';
    await postPlaybackEvent('started', currentQueueItem);
    setStatus('Jukebox playing from the host Apple Music account. Cast this Chrome tab for TV audio.');
  };

  const skipPlayback = async () => {
    if (music && music.player && typeof music.player.skipToNextItem === 'function') {
      try {
        await music.player.skipToNextItem();
      } catch (error) {
        setStatus('Apple Music skip was blocked; syncing app queue.');
      }
    }
    if (currentQueueItem) {
      await postPlaybackEvent('skipped', currentQueueItem);
    }
    currentQueueItem = visibleQueue()[0] || null;
    if (currentQueueItem) {
      await startPlayback();
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

  render();
  watchForEnded();
  window.setInterval(refreshState, 15000);
})();
