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

  const renderResults = (form, results) => {
    const container = form.querySelector('[data-jukebox-search-results]');
    if (!container) {
      return;
    }
    container.innerHTML = '';
    if (!results.length) {
      setStatus(form, 'No Apple Music songs found.', true);
      return;
    }
    setStatus(form, `${results.length} song${results.length === 1 ? '' : 's'} found.`, false);
    results.forEach((track) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'song-search-result';
      const image = track.artwork_url
        ? `<img src="${track.artwork_url}" alt="">`
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
  };

  const search = async (form) => {
    const input = form.querySelector('[data-jukebox-search-input]');
    const query = input ? input.value.trim() : '';
    if (query.length < 2) {
      setStatus(form, 'Enter at least two characters.', true);
      return;
    }

    setStatus(form, 'Searching Apple Music...', false);
    try {
      const response = await fetch(`/api/jukebox-search?q=${encodeURIComponent(query)}`, {
        headers: { Accept: 'application/json' },
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || 'Apple Music search failed.');
      }
      renderResults(form, Array.isArray(payload.results) ? payload.results : []);
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
