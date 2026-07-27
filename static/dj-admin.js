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
  const pagination = searchRoot.querySelector('[data-dj-catalog-pagination]');
  const previousButton = searchRoot.querySelector('[data-dj-catalog-previous]');
  const nextButton = searchRoot.querySelector('[data-dj-catalog-next]');
  const pageLabel = searchRoot.querySelector('[data-dj-catalog-page]');
  const searchUrl = searchRoot.dataset.searchUrl;
  let activeQuery = '';
  let activeOffset = 0;
  let nextOffset = null;

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

  const updatePagination = () => {
    if (!pagination) return;
    const hasResults = Boolean(results?.children.length);
    pagination.hidden = !hasResults;
    if (previousButton) previousButton.disabled = activeOffset === 0;
    if (nextButton) nextButton.disabled = nextOffset === null;
    if (pageLabel) pageLabel.textContent = hasResults ? `Page ${Math.floor(activeOffset / 8) + 1}` : '';
  };

  const search = async (offset = 0) => {
    const query = (queryInput?.value || '').trim();
    if (query.length < 2) {
      setMessage('Enter at least two characters to search Apple Music.', true);
      return;
    }
    if (!searchUrl) return;
    if (query !== activeQuery) offset = 0;

    searchButton.disabled = true;
    if (previousButton) previousButton.disabled = true;
    if (nextButton) nextButton.disabled = true;
    setMessage('Searching Apple Music…');
    if (results) results.innerHTML = '';
    try {
      const url = new URL(searchUrl, window.location.origin);
      url.searchParams.set('q', query);
      url.searchParams.set('offset', String(offset));
      const response = await fetch(url, { cache: 'no-store' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Search failed.');
      const songs = Array.isArray(payload.results) ? payload.results : [];
      activeQuery = query;
      activeOffset = Number.isInteger(payload.offset) ? payload.offset : offset;
      nextOffset = Number.isInteger(payload.next_offset) ? payload.next_offset : null;
      if (!songs.length) {
        updatePagination();
        setMessage(activeOffset ? 'No more Apple Music songs matched that search.' : 'No Apple Music songs matched that search. You can still add a catalog ID manually.');
        return;
      }
      renderResults(songs);
      updatePagination();
      setMessage(`${songs.length} matching song${songs.length === 1 ? '' : 's'} found on page ${Math.floor(activeOffset / 8) + 1}.`);
    } catch (error) {
      nextOffset = null;
      updatePagination();
      setMessage(error.message || 'Apple Music catalog search is unavailable.', true);
    } finally {
      searchButton.disabled = false;
    }
  };

  searchButton?.addEventListener('click', search);
  previousButton?.addEventListener('click', () => search(Math.max(0, activeOffset - 8)));
  nextButton?.addEventListener('click', () => {
    if (nextOffset !== null) search(nextOffset);
  });
  queryInput?.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      search();
    }
  });
})();
