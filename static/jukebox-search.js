(function () {
  const text = (value) => (value === null || value === undefined ? '' : String(value));

  const setStatus = (form, message, isError) => {
    const status = form.querySelector('[data-jukebox-search-status]');
    if (!status) {
      return;
    }
    status.textContent = message;
    status.classList.toggle('is-error', Boolean(isError));
  };

  const setField = (form, name, value) => {
    const field = form.querySelector(`[data-jukebox-field="${name}"]`);
    if (field) {
      field.value = text(value);
    }
  };

  const selectTrack = (form, track) => {
    setField(form, 'apple_music_id', track.apple_music_id);
    setField(form, 'title', track.title);
    setField(form, 'artist', track.artist);
    setField(form, 'album', track.album);
    setField(form, 'artwork_url', track.artwork_url);
    setField(form, 'duration_ms', track.duration_ms || 0);
    setField(form, 'explicit', track.explicit ? 'yes' : 'no');

    const selected = form.querySelector('[data-jukebox-selected]');
    if (selected) {
      const artist = track.artist ? ` by ${track.artist}` : '';
      selected.textContent = `Selected: ${track.title}${artist}`;
    }
  };

  const renderResults = (form, results, options = {}) => {
    const append = Boolean(options.append);
    const container = form.querySelector('[data-jukebox-search-results]');
    if (!container) {
      return;
    }
    if (!append) {
      container.innerHTML = '';
    } else {
      const existingMore = container.querySelector('[data-jukebox-search-more]');
      if (existingMore) {
        existingMore.remove();
      }
    }
    if (!results.length && !append) {
      setStatus(form, 'No Apple Music songs found.', true);
      return;
    }
    const totalShown = container.querySelectorAll('.song-search-result').length + results.length;
    setStatus(form, `${totalShown} song${totalShown === 1 ? '' : 's'} shown.`, false);
    results.forEach((track) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'song-search-result';
      const image = track.artwork_url
        ? `<img src="${track.artwork_url}" alt="" loading="lazy" decoding="async">`
        : '<span class="song-search-result__art"></span>';
      const explicit = track.explicit ? '<span class="status-pill">Explicit</span>' : '';
      button.innerHTML = `
        ${image}
        <span class="song-search-result__body">
          <strong></strong>
          <span></span>
          ${explicit}
        </span>
      `;
      button.querySelector('strong').textContent = text(track.title);
      button.querySelector('.song-search-result__body > span').textContent = [track.artist, track.album]
        .filter(Boolean)
        .join(' · ');
      button.addEventListener('click', () => selectTrack(form, track));
      container.appendChild(button);
    });
    if (options.hasMore) {
      const moreButton = document.createElement('button');
      moreButton.type = 'button';
      moreButton.className = 'button button--outline song-search-more';
      moreButton.dataset.jukeboxSearchMore = 'yes';
      moreButton.textContent = 'More Results';
      moreButton.addEventListener('click', () => search(form, { append: true }));
      container.appendChild(moreButton);
    }
  };

  const search = async (form, options = {}) => {
    const input = form.querySelector('[data-jukebox-search-input]');
    const query = input ? input.value.trim() : '';
    if (query.length < 2) {
      setStatus(form, 'Enter at least two characters.', true);
      return;
    }

    const append = Boolean(options.append);
    const previousQuery = form.dataset.jukeboxSearchQuery || '';
    const offset = append && previousQuery === query ? Number(form.dataset.jukeboxSearchNextOffset || 0) : 0;
    setStatus(form, append ? 'Loading more Apple Music songs...' : 'Searching Apple Music...', false);
    try {
      const params = new URLSearchParams({
        q: query,
        offset: String(Number.isFinite(offset) ? offset : 0),
        limit: '8',
      });
      const response = await fetch(`/api/jukebox-search?${params.toString()}`, {
        headers: { Accept: 'application/json' },
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || 'Apple Music search failed.');
      }
      form.dataset.jukeboxSearchQuery = query;
      form.dataset.jukeboxSearchNextOffset = String(payload.next_offset || 0);
      renderResults(form, Array.isArray(payload.results) ? payload.results : [], {
        append,
        hasMore: Boolean(payload.has_more),
      });
    } catch (error) {
      setStatus(form, error.message || 'Apple Music search failed.', true);
    }
  };

  const init = () => {
    const forms = Array.from(document.querySelectorAll('[data-jukebox-search-form]'));
    forms.forEach((form) => {
      if (form.dataset.jukeboxSearchBound === 'yes') {
        return;
      }
      form.dataset.jukeboxSearchBound = 'yes';
      const button = form.querySelector('[data-jukebox-search-button]');
      const input = form.querySelector('[data-jukebox-search-input]');
      if (button) {
        button.addEventListener('click', () => search(form));
      }
      if (input) {
        input.addEventListener('keydown', (event) => {
          if (event.key === 'Enter') {
            event.preventDefault();
            search(form);
          }
        });
      }
    });
  };

  window.HalloweenJukeboxSearch = { init };
  document.addEventListener('DOMContentLoaded', init);
})();
