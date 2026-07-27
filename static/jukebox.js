(() => {
  const root = document.querySelector('[data-party-jukebox]');
  if (!root) return;

  const searchUrl = root.dataset.searchUrl;
  const stateUrl = root.dataset.stateUrl;
  const query = root.querySelector('[data-jukebox-query]');
  const searchButton = root.querySelector('[data-jukebox-search]');
  const searchMessage = root.querySelector('[data-jukebox-search-message]');
  const results = root.querySelector('[data-jukebox-results]');
  const requestForm = document.querySelector('[data-jukebox-request-form]');

  const setMessage = (message, isError = false) => {
    if (!searchMessage) return;
    searchMessage.textContent = message;
    searchMessage.classList.toggle('is-error', isError);
  };

  const renderSongList = (container, entries, ordered, emptyMessage) => {
    if (!container) return;
    container.replaceChildren();
    if (!entries.length) {
      const empty = document.createElement('p');
      empty.textContent = emptyMessage;
      container.appendChild(empty);
      return;
    }
    const list = document.createElement(ordered ? 'ol' : 'ul');
    list.className = 'jukebox-song-list';
    entries.forEach((entry) => {
      const song = entry.song || entry;
      const item = document.createElement('li');
      const title = document.createElement('strong');
      title.textContent = song.title || 'Untitled song';
      const detail = document.createElement('span');
      detail.textContent = [song.artist, song.album].filter(Boolean).join(' · ');
      item.append(title, detail);
      list.appendChild(item);
    });
    container.appendChild(list);
  };

  const submitRequest = (song) => {
    if (!requestForm) return;
    ['title', 'artist', 'apple_music_id', 'album', 'artwork_url', 'duration_ms'].forEach((key) => {
      const input = requestForm.elements.namedItem(key);
      if (input) input.value = song[key] || '';
    });
    const explicit = requestForm.elements.namedItem('explicit');
    if (explicit) explicit.value = song.explicit ? 'yes' : '';
    requestForm.submit();
  };

  const renderResults = (songs) => {
    if (!results) return;
    results.innerHTML = '';
    songs.forEach((song) => {
      const result = document.createElement('article');
      result.className = 'dj-catalog-result';
      if (song.artwork_url) {
        const artwork = document.createElement('img');
        artwork.src = song.artwork_url;
        artwork.alt = '';
        artwork.loading = 'lazy';
        result.appendChild(artwork);
      }
      const copy = document.createElement('div');
      const title = document.createElement('strong');
      title.textContent = song.title || 'Untitled song';
      const detail = document.createElement('span');
      detail.textContent = [song.artist, song.album, song.explicit ? 'Explicit' : ''].filter(Boolean).join(' · ');
      copy.append(title, detail);
      const choose = document.createElement('button');
      choose.type = 'button';
      choose.className = 'button button--primary';
      choose.textContent = 'Request Song';
      choose.addEventListener('click', () => submitRequest(song));
      result.append(copy, choose);
      results.appendChild(result);
    });
  };

  const search = async () => {
    const term = (query?.value || '').trim();
    if (term.length < 2) return setMessage('Enter at least two characters to search Apple Music.', true);
    searchButton.disabled = true;
    setMessage('Searching Apple Music…');
    if (results) results.innerHTML = '';
    try {
      const url = new URL(searchUrl, window.location.origin);
      url.searchParams.set('q', term);
      const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Search failed.');
      const songs = Array.isArray(payload.results) ? payload.results : [];
      if (!songs.length) return setMessage('No matching songs found. Try another search.');
      renderResults(songs);
      setMessage(`${songs.length} matching song${songs.length === 1 ? '' : 's'} found.`);
    } catch (error) {
      setMessage(error.message || 'Apple Music catalog search is unavailable.', true);
    } finally {
      searchButton.disabled = false;
    }
  };

  const refresh = async () => {
    if (!stateUrl) return;
    try {
      const response = await fetch(stateUrl, { credentials: 'same-origin', cache: 'no-store' });
      const state = await response.json();
      if (!response.ok) return;
      const nowPlaying = state.now_playing || null;
      const title = root.querySelector('[data-jukebox-title]');
      const artist = root.querySelector('[data-jukebox-artist]');
      const status = root.querySelector('[data-jukebox-status]');
      if (title) title.textContent = nowPlaying?.title || 'Nothing is playing yet';
      if (artist) artist.textContent = nowPlaying ? [nowPlaying.artist, nowPlaying.album].filter(Boolean).join(' · ') : 'The next DJ selection will appear here.';
      if (status) status.textContent = String(state.playback_status || 'stopped').replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
      const playlist = root.querySelector('[data-jukebox-playlist]');
      const pending = root.querySelector('[data-jukebox-pending]');
      renderSongList(playlist, Array.isArray(state.playlist) ? state.playlist : [], true, 'The DJ has not added songs to the playlist yet.');
      renderSongList(pending, Array.isArray(state.pending_requests) ? state.pending_requests : [], false, 'No requests waiting for DJ approval.');
    } catch (error) {
      console.error('Unable to refresh jukebox state', error);
    }
  };

  searchButton?.addEventListener('click', search);
  query?.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      search();
    }
  });
  window.setInterval(refresh, 5000);
})();
