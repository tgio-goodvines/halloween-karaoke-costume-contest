document.addEventListener('DOMContentLoaded', () => {
  const root = document.querySelector('[data-youtube-search]');
  if (!root) {
    return;
  }

  const searchUrl = root.dataset.searchUrl || '/api/youtube-search';
  const queryInput = document.getElementById('youtube_search_query');
  const searchButton = root.querySelector('[data-youtube-search-button]');
  const statusElement = root.querySelector('[data-youtube-search-status]');
  const resultsElement = root.querySelector('[data-youtube-search-results]');
  const songTitleInput = document.getElementById('song_title');
  const artistInput = document.getElementById('artist');
  const linkInput = document.getElementById('youtube_link');
  const videoIdInput = document.getElementById('youtube_video_id');
  const embedStatusInput = document.getElementById('youtube_embed_status');
  const youtubeTitleInput = document.getElementById('youtube_title');
  const youtubeChannelInput = document.getElementById('youtube_channel');
  const thumbnailInput = document.getElementById('youtube_thumbnail_url');
  const durationInput = document.getElementById('youtube_duration');

  const setStatus = (message, tone = '') => {
    if (!statusElement) {
      return;
    }
    statusElement.textContent = message;
    statusElement.dataset.tone = tone;
  };

  const clearResults = () => {
    if (!resultsElement) {
      return;
    }
    resultsElement.innerHTML = '';
    resultsElement.setAttribute('hidden', '');
  };

  const fillSelectedSong = (result) => {
    if (songTitleInput && result.suggested_song_title) {
      songTitleInput.value = result.suggested_song_title;
    }
    if (artistInput && result.suggested_artist) {
      artistInput.value = result.suggested_artist;
    }
    if (linkInput) {
      linkInput.value = result.watch_url || '';
    }
    if (videoIdInput) {
      videoIdInput.value = result.video_id || '';
    }
    if (embedStatusInput) {
      embedStatusInput.value = result.embed_status || 'unverified';
    }
    if (youtubeTitleInput) {
      youtubeTitleInput.value = result.title || '';
    }
    if (youtubeChannelInput) {
      youtubeChannelInput.value = result.channel || '';
    }
    if (thumbnailInput) {
      thumbnailInput.value = result.thumbnail_url || '';
    }
    if (durationInput) {
      durationInput.value = result.duration || '';
    }
    setStatus(`Selected: ${result.title || 'YouTube video'}`, 'success');
    clearResults();
  };

  const renderResults = (results) => {
    if (!resultsElement) {
      return;
    }
    resultsElement.innerHTML = '';
    if (!Array.isArray(results) || !results.length) {
      setStatus('No embeddable YouTube results found. Try a different song or artist.', 'warning');
      resultsElement.setAttribute('hidden', '');
      return;
    }

    results.forEach((result) => {
      const card = document.createElement('article');
      card.className = 'youtube-result';

      const media = document.createElement('div');
      media.className = 'youtube-result__media';

      const image = document.createElement('img');
      image.className = 'youtube-result__thumb';
      image.src = result.thumbnail_url || '';
      image.alt = result.title ? `Thumbnail for ${result.title}` : 'YouTube video thumbnail';
      image.loading = 'lazy';

      media.appendChild(image);

      if (result.duration) {
        const duration = document.createElement('span');
        duration.className = 'youtube-result__duration';
        duration.textContent = result.duration;
        media.appendChild(duration);
      }

      const body = document.createElement('div');
      body.className = 'youtube-result__body';

      const title = document.createElement('strong');
      title.className = 'youtube-result__title';
      title.textContent = result.title || 'Untitled YouTube video';

      const meta = document.createElement('span');
      meta.className = 'youtube-result__meta';
      meta.textContent = result.channel || 'YouTube';

      const badge = document.createElement('span');
      badge.className = 'youtube-result__badge';
      badge.textContent = result.embed_status_label || 'Playable on live display';

      const actions = document.createElement('span');
      actions.className = 'youtube-result__actions';

      const previewButton = document.createElement('button');
      previewButton.type = 'button';
      previewButton.className = 'button button--outline youtube-result__button youtube-result__preview-toggle';
      previewButton.textContent = 'Preview';

      const useButton = document.createElement('button');
      useButton.type = 'button';
      useButton.className = 'button button--primary youtube-result__button';
      useButton.textContent = 'Use this song';

      const preview = document.createElement('div');
      preview.className = 'youtube-result__preview';
      preview.setAttribute('hidden', '');

      const frame = document.createElement('iframe');
      frame.className = 'youtube-result__preview-frame';
      frame.title = result.title ? `Preview ${result.title}` : 'YouTube video preview';
      frame.loading = 'lazy';
      frame.allow = 'encrypted-media; fullscreen; picture-in-picture';
      frame.setAttribute('allowfullscreen', '');

      preview.appendChild(frame);

      previewButton.addEventListener('click', () => {
        const isOpening = preview.hasAttribute('hidden');
        resultsElement.querySelectorAll('.youtube-result__preview').forEach((openPreview) => {
          openPreview.setAttribute('hidden', '');
          const openFrame = openPreview.querySelector('iframe');
          if (openFrame) {
            openFrame.removeAttribute('src');
          }
        });
        resultsElement.querySelectorAll('.youtube-result__preview-toggle').forEach((toggle) => {
          toggle.textContent = 'Preview';
        });

        if (isOpening && result.video_id) {
          const embedUrl = new URL(`https://www.youtube.com/embed/${result.video_id}`);
          embedUrl.searchParams.set('rel', '0');
          embedUrl.searchParams.set('playsinline', '1');
          frame.src = embedUrl.toString();
          preview.removeAttribute('hidden');
          previewButton.textContent = 'Hide preview';
        } else {
          frame.removeAttribute('src');
          preview.setAttribute('hidden', '');
          previewButton.textContent = 'Preview';
        }
      });

      useButton.addEventListener('click', () => fillSelectedSong(result));

      actions.appendChild(previewButton);
      actions.appendChild(useButton);

      body.appendChild(title);
      body.appendChild(meta);
      body.appendChild(badge);
      body.appendChild(actions);

      card.appendChild(media);
      card.appendChild(body);
      card.appendChild(preview);
      resultsElement.appendChild(card);
    });

    resultsElement.removeAttribute('hidden');
    setStatus('Choose the result you want to sing.', 'success');
  };

  const search = async () => {
    const query = queryInput ? queryInput.value.trim() : '';
    if (!query) {
      setStatus('Enter a song or artist to search.', 'warning');
      clearResults();
      return;
    }

    if (searchButton) {
      searchButton.disabled = true;
    }
    setStatus('Searching YouTube...');
    clearResults();

    try {
      const url = new URL(searchUrl, window.location.href);
      url.searchParams.set('q', query);
      const response = await fetch(url.toString(), {
        headers: {
          Accept: 'application/json',
        },
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || 'YouTube search failed.');
      }
      renderResults(payload.results || []);
    } catch (error) {
      setStatus(error.message || 'YouTube search is unavailable right now.', 'warning');
      clearResults();
    } finally {
      if (searchButton) {
        searchButton.disabled = false;
      }
    }
  };

  if (searchButton) {
    searchButton.addEventListener('click', search);
  }
  if (queryInput) {
    queryInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        search();
      }
    });
  }
});
