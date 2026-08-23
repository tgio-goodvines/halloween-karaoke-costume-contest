(() => {
  const root = document.querySelector('[data-karaoke-signup]');
  if (!root) return;

  const searchUrl = root.dataset.searchUrl;
  const form = root.querySelector('[data-karaoke-selection-form]');
  const singerEditor = form?.querySelector('[data-karaoke-singers]');
  const songTitleInput = form?.elements.song_title;
  const artistInput = form?.elements.artist;
  const searchButton = root.querySelector('[data-karaoke-search]');
  const searchMessage = root.querySelector('[data-karaoke-search-message]');
  const resultsPanel = root.querySelector('[data-karaoke-results-panel]');
  const results = root.querySelector('[data-karaoke-results]');
  const pagination = root.querySelector('[data-karaoke-pagination]');
  const previousButton = root.querySelector('[data-karaoke-previous]');
  const nextButton = root.querySelector('[data-karaoke-next]');
  const pageLabel = root.querySelector('[data-karaoke-page]');
  const selection = root.querySelector('[data-karaoke-selection]');
  const review = root.querySelector('[data-karaoke-review]');
  const reviewSong = root.querySelector('[data-karaoke-review-song]');
  const reviewSingers = root.querySelector('[data-karaoke-review-singers]');
  const submit = root.querySelector('[data-karaoke-submit]');
  const directLink = root.querySelector('[data-karaoke-link-fallback]');
  const detailsSection = root.querySelector('[data-karaoke-details]');
  let activeSignature = '';
  let selectedSignature = '';
  let nextPageToken = '';
  let previousPageToken = '';
  let pageNumber = 1;
  let requestSequence = 0;

  const detailSignature = () => JSON.stringify([
    (songTitleInput?.value || '').trim().toLocaleLowerCase(),
    (artistInput?.value || '').trim().toLocaleLowerCase(),
  ]);

  const setMessage = (message, isError = false) => {
    if (!searchMessage) return;
    searchMessage.textContent = message;
    searchMessage.classList.toggle('is-error', isError);
  };

  const setStepState = (name, state) => {
    const step = root.querySelector(`[data-karaoke-builder-step="${name}"]`);
    if (!step) return;
    step.classList.remove('is-current', 'is-complete', 'is-pending');
    step.classList.add(state);
  };

  const updateSteps = (stage) => {
    setStepState('details', stage === 'details' ? 'is-current' : 'is-complete');
    setStepState(
      'video',
      stage === 'details' ? 'is-pending' : (stage === 'video' ? 'is-current' : 'is-complete'),
    );
    setStepState('review', stage === 'review' ? 'is-current' : 'is-pending');
  };

  const updateReviewSong = () => {
    if (!reviewSong) return;
    if (reviewSingers) {
      reviewSingers.textContent = singerEditor?.dataset.singerLabel || 'Your singers';
    }
    const song = (songTitleInput?.value || '').trim() || 'your song';
    const artist = (artistInput?.value || '').trim() || 'the original artist';
    const singer = reviewSingers || document.createElement('strong');
    if (!reviewSingers) singer.textContent = singerEditor?.dataset.singerLabel || 'Your singers';
    reviewSong.replaceChildren(singer, ` will sing “${song}” by ${artist}.`);
  };

  const updateFindButton = () => {
    if (!searchButton) return;
    searchButton.disabled = !(
      (songTitleInput?.value || '').trim()
      && (artistInput?.value || '').trim()
    );
  };

  const validateSongDetails = () => {
    const singerInputs = Array.from(
      form?.querySelectorAll('[data-karaoke-singer-select], [data-karaoke-custom-name]:required') || [],
    );
    for (const input of [...singerInputs, songTitleInput, artistInput]) {
      if (input && !input.checkValidity()) {
        input.reportValidity();
        input.focus();
        updateSteps('details');
        return false;
      }
    }
    return true;
  };

  const updatePagination = () => {
    if (!pagination) return;
    pagination.hidden = !results?.children.length;
    if (previousButton) previousButton.disabled = !previousPageToken;
    if (nextButton) nextButton.disabled = !nextPageToken;
    if (pageLabel) pageLabel.textContent = `Page ${pageNumber}`;
  };

  const clearResults = () => {
    results?.replaceChildren();
    if (resultsPanel) resultsPanel.hidden = true;
    nextPageToken = '';
    previousPageToken = '';
    pageNumber = 1;
    updatePagination();
  };

  const clearSelection = () => {
    if (!form || !selection) return;
    form.elements.youtube_video_id.value = '';
    form.elements.youtube_link.value = '';
    selectedSignature = '';
    selection.replaceChildren();
    const prompt = document.createElement('p');
    prompt.textContent = 'Choose a search result or paste a direct YouTube link above.';
    selection.appendChild(prompt);
    selection.classList.remove('is-selected');
    if (review) review.hidden = true;
    if (submit) submit.disabled = true;
  };

  const renderSelection = (video) => {
    if (!form || !selection) return;
    form.elements.youtube_video_id.value = video.video_id || '';
    form.elements.youtube_link.value = (
      video.watch_url
      || `https://www.youtube.com/watch?v=${video.video_id || ''}`
    );
    selection.replaceChildren();
    if (video.thumbnail_url) {
      const image = document.createElement('img');
      image.src = video.thumbnail_url;
      image.alt = '';
      image.loading = 'lazy';
      selection.appendChild(image);
    }
    const copy = document.createElement('div');
    const title = document.createElement('strong');
    title.textContent = video.title || 'Selected YouTube video';
    const channel = document.createElement('span');
    channel.textContent = video.channel_title || 'The host will verify this link';
    copy.append(title, channel);
    const preview = document.createElement('a');
    preview.className = 'button';
    preview.href = form.elements.youtube_link.value;
    preview.target = '_blank';
    preview.rel = 'noopener';
    preview.textContent = 'Preview on YouTube';
    selection.append(copy, preview);
    selection.classList.add('is-selected');
    selectedSignature = detailSignature();
    updateReviewSong();
    if (review) review.hidden = false;
    if (submit) submit.disabled = false;
    if (resultsPanel) resultsPanel.hidden = true;
    updateSteps('review');
    review?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const renderResults = (videos) => {
    if (!results) return;
    results.replaceChildren();
    videos.forEach((video) => {
      const card = document.createElement('article');
      card.className = 'karaoke-video-result';
      if (video.thumbnail_url) {
        const image = document.createElement('img');
        image.src = video.thumbnail_url;
        image.alt = '';
        image.loading = 'lazy';
        card.appendChild(image);
      }
      const copy = document.createElement('div');
      const title = document.createElement('strong');
      title.textContent = video.title || 'Untitled video';
      const detail = document.createElement('span');
      const duration = Number(video.duration_seconds || 0);
      const durationLabel = duration
        ? `${Math.floor(duration / 60)}:${String(duration % 60).padStart(2, '0')}`
        : '';
      detail.textContent = [
        video.channel_title,
        durationLabel,
        video.age_restricted ? 'Age restricted' : '',
      ].filter(Boolean).join(' · ');
      copy.append(title, detail);
      const actions = document.createElement('div');
      actions.className = 'karaoke-video-result__actions';
      const preview = document.createElement('a');
      preview.className = 'button';
      preview.href = (
        video.watch_url
        || `https://www.youtube.com/watch?v=${video.video_id || ''}`
      );
      preview.target = '_blank';
      preview.rel = 'noopener';
      preview.textContent = 'Preview';
      const choose = document.createElement('button');
      choose.type = 'button';
      choose.className = 'button button--primary';
      choose.textContent = 'Choose This Version';
      choose.disabled = !video.available || video.age_restricted;
      choose.addEventListener('click', () => renderSelection(video));
      actions.append(preview, choose);
      card.append(copy, actions);
      results.appendChild(card);
    });
  };

  const search = async (pageToken = '', direction = 0) => {
    if (!validateSongDetails()) return;
    if (!searchUrl) {
      setMessage('YouTube search is not configured. Paste a direct link instead.', true);
      return;
    }
    const signature = detailSignature();
    if (signature !== activeSignature) {
      pageToken = '';
      direction = 0;
      pageNumber = 1;
    }
    const title = (songTitleInput?.value || '').trim();
    const artist = (artistInput?.value || '').trim();
    const sequence = ++requestSequence;
    if (searchButton) {
      searchButton.disabled = true;
      searchButton.textContent = 'Searching…';
    }
    if (resultsPanel) resultsPanel.hidden = false;
    updateSteps('video');
    setMessage(`Searching YouTube for “${title}” by ${artist} karaoke…`);
    try {
      const url = new URL(searchUrl, window.location.origin);
      url.searchParams.set('song_title', title);
      url.searchParams.set('artist', artist);
      if (pageToken) url.searchParams.set('page_token', pageToken);
      const response = await fetch(url, {
        credentials: 'same-origin',
        cache: 'no-store',
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || 'YouTube search failed.');
      }
      if (sequence !== requestSequence) return;
      const videos = Array.isArray(payload.items) ? payload.items : [];
      activeSignature = signature;
      nextPageToken = payload.next_page_token || '';
      previousPageToken = payload.previous_page_token || '';
      pageNumber = Math.max(1, pageNumber + direction);
      renderResults(videos);
      updatePagination();
      setMessage(
        videos.length
          ? `${videos.length} karaoke version${videos.length === 1 ? '' : 's'} found for “${title}” by ${artist}.`
          : 'No matching karaoke versions were found. Edit the song details or paste a direct link.',
      );
      resultsPanel?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (error) {
      if (sequence !== requestSequence) return;
      clearResults();
      if (resultsPanel) resultsPanel.hidden = false;
      setMessage(error.message || 'YouTube search is unavailable.', true);
    } finally {
      if (sequence === requestSequence && searchButton) {
        updateFindButton();
        searchButton.textContent = activeSignature
          ? 'Search Again'
          : 'Find Karaoke Versions';
      }
    }
  };

  searchButton?.addEventListener('click', () => search());
  previousButton?.addEventListener('click', () => {
    if (previousPageToken) search(previousPageToken, -1);
  });
  nextButton?.addEventListener('click', () => {
    if (nextPageToken) search(nextPageToken, 1);
  });

  [songTitleInput, artistInput].forEach((input) => {
    input?.addEventListener('input', () => {
      updateFindButton();
      const signature = detailSignature();
      if (selectedSignature && signature !== selectedSignature) {
        clearSelection();
      }
      if (activeSignature && signature !== activeSignature) {
        requestSequence += 1;
        activeSignature = '';
        clearResults();
        if (searchButton) searchButton.textContent = 'Find Karaoke Versions';
        setMessage('Song details changed. Press Find Karaoke Versions to refresh the results.');
      }
      updateReviewSong();
    });
    input?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        search();
      }
    });
  });
  form?.addEventListener('karaoke:singers-change', updateReviewSong);

  root.querySelector('[data-karaoke-use-link]')?.addEventListener('click', () => {
    if (!validateSongDetails()) return;
    const value = (directLink?.value || '').trim();
    if (!value) {
      setMessage('Paste a YouTube video link first.', true);
      directLink?.focus();
      return;
    }
    if (directLink && !directLink.checkValidity()) {
      directLink.reportValidity();
      directLink.focus();
      setMessage('Paste a complete YouTube video link.', true);
      return;
    }
    renderSelection({
      video_id: '',
      watch_url: value,
      title: 'Direct YouTube video',
      channel_title: 'The host will verify this link',
    });
  });

  root.querySelector('[data-karaoke-change-video]')?.addEventListener('click', () => {
    if (resultsPanel && results?.children.length) {
      resultsPanel.hidden = false;
      updateSteps('video');
      resultsPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } else {
      search();
    }
  });

  root.querySelector('[data-karaoke-edit-details]')?.addEventListener('click', () => {
    clearSelection();
    updateSteps('details');
    detailsSection?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    songTitleInput?.focus();
  });

  form?.addEventListener('submit', (event) => {
    if (
      !selection?.classList.contains('is-selected')
      || !form.elements.youtube_link.value
    ) {
      event.preventDefault();
      setMessage('Choose a YouTube karaoke version before submitting.', true);
      updateSteps('video');
      return;
    }
    if (selectedSignature && selectedSignature !== detailSignature()) {
      event.preventDefault();
      clearSelection();
      setMessage('Song details changed. Search again and choose a matching version.', true);
      updateSteps('details');
      return;
    }
    if (submit) {
      submit.disabled = true;
      submit.textContent = 'Sending for Approval…';
    }
  });

  updateFindButton();
  updateReviewSong();
  window.addEventListener('pageshow', updateFindButton);
  if (selection?.classList.contains('is-selected')) {
    selectedSignature = detailSignature();
    updateSteps('review');
  } else {
    updateSteps('details');
  }
})();
