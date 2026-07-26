(() => {
  const searchRoot = document.querySelector('[data-dj-catalog-search]');
  const songForm = document.querySelector('[data-dj-song-form]');
  if (!searchRoot || !songForm) {
    return;
  }

  const queryInput = searchRoot.querySelector('#dj_catalog_query');
  const searchButton = searchRoot.querySelector('[data-dj-catalog-search-button]');
  const message = searchRoot.querySelector('[data-dj-catalog-search-message]');
  const results = searchRoot.querySelector('[data-dj-catalog-search-results]');
  const searchUrl = searchRoot.dataset.searchUrl;

  const setMessage = (text, isError = false) => {
    if (!message) return;
    message.textContent = text;
    message.classList.toggle('is-error', isError);
  };

  const fillSongForm = (song) => {
    const setField = (name, value) => {
      const field = songForm.querySelector(`[data-dj-field="${name}"]`);
      if (!field) return;
      if (field.type === 'checkbox') {
        field.checked = Boolean(value);
      } else {
        field.value = value || '';
      }
    };

    setField('title', song.title);
    setField('artist', song.artist);
    setField('apple_music_id', song.apple_music_id);
    setField('album', song.album);
    setField('artwork_url', song.artwork_url);
    setField('duration_ms', song.duration_ms);
    setField('explicit', song.explicit);
    songForm.open = true;
    songForm.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    setMessage(`Selected ${song.title} by ${song.artist}. Review and add it to the playlist.`);
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
      const subtitle = document.createElement('span');
      subtitle.textContent = [song.artist, song.album].filter(Boolean).join(' · ');
      copy.append(title, subtitle);
      result.appendChild(copy);

      const choose = document.createElement('button');
      choose.type = 'button';
      choose.className = 'button';
      choose.textContent = 'Use Song';
      choose.addEventListener('click', () => fillSongForm(song));
      result.appendChild(choose);
      results.appendChild(result);
    });
  };

  const search = async () => {
    const query = (queryInput?.value || '').trim();
    if (query.length < 2) {
      setMessage('Enter at least two characters to search Apple Music.', true);
      return;
    }
    if (!searchUrl) return;

    searchButton.disabled = true;
    setMessage('Searching Apple Music…');
    if (results) results.innerHTML = '';
    try {
      const url = new URL(searchUrl, window.location.origin);
      url.searchParams.set('q', query);
      const response = await fetch(url, { cache: 'no-store' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Search failed.');
      const songs = Array.isArray(payload.results) ? payload.results : [];
      if (!songs.length) {
        setMessage('No Apple Music songs matched that search. You can still add a catalog ID manually.');
        return;
      }
      renderResults(songs);
      setMessage(`${songs.length} matching song${songs.length === 1 ? '' : 's'} found.`);
    } catch (error) {
      setMessage(error.message || 'Apple Music catalog search is unavailable.', true);
    } finally {
      searchButton.disabled = false;
    }
  };

  searchButton?.addEventListener('click', search);
  queryInput?.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      search();
    }
  });
})();
