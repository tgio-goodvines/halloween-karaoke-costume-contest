(() => {
  const root = document.querySelector('[data-karaoke-signup]');
  if (!root) return;

  const searchUrl = root.dataset.searchUrl;
  const query = root.querySelector('#youtube_query');
  const searchButton = root.querySelector('[data-karaoke-search]');
  const searchMessage = root.querySelector('[data-karaoke-search-message]');
  const results = root.querySelector('[data-karaoke-results]');
  const pagination = root.querySelector('[data-karaoke-pagination]');
  const previousButton = root.querySelector('[data-karaoke-previous]');
  const nextButton = root.querySelector('[data-karaoke-next]');
  const pageLabel = root.querySelector('[data-karaoke-page]');
  const form = root.querySelector('[data-karaoke-selection-form]');
  const selection = root.querySelector('[data-karaoke-selection]');
  const submit = root.querySelector('[data-karaoke-submit]');
  const directLink = root.querySelector('[data-karaoke-link-fallback]');
  let activeQuery = '';
  let nextPageToken = '';
  let previousPageToken = '';
  let pageNumber = 1;

  const setMessage = (message, isError = false) => {
    if (!searchMessage) return;
    searchMessage.textContent = message;
    searchMessage.classList.toggle('is-error', isError);
  };

  const chooseVideo = (video) => {
    if (!form || !selection) return;
    form.elements.youtube_video_id.value = video.video_id || '';
    form.elements.youtube_link.value = video.watch_url || `https://www.youtube.com/watch?v=${video.video_id || ''}`;
    if (!form.elements.song_title.value) form.elements.song_title.value = video.title || '';
    if (!form.elements.artist.value) form.elements.artist.value = video.channel_title || '';
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
    channel.textContent = video.channel_title || 'YouTube';
    copy.append(title, channel);
    selection.appendChild(copy);
    selection.classList.add('is-selected');
    if (submit) submit.disabled = false;
    form.scrollIntoView({ behavior: 'smooth', block: 'start' });
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
      const durationLabel = duration ? `${Math.floor(duration / 60)}:${String(duration % 60).padStart(2, '0')}` : '';
      detail.textContent = [video.channel_title, durationLabel, video.age_restricted ? 'Age restricted' : ''].filter(Boolean).join(' · ');
      copy.append(title, detail);
      const actions = document.createElement('div');
      actions.className = 'karaoke-video-result__actions';
      const preview = document.createElement('a');
      preview.className = 'button';
      preview.href = video.watch_url || `https://www.youtube.com/watch?v=${video.video_id || ''}`;
      preview.target = '_blank';
      preview.rel = 'noopener';
      preview.textContent = 'Preview';
      const choose = document.createElement('button');
      choose.type = 'button';
      choose.className = 'button button--primary';
      choose.textContent = 'Choose This Version';
      choose.disabled = !video.available || video.age_restricted;
      choose.addEventListener('click', () => chooseVideo(video));
      actions.append(preview, choose);
      card.append(copy, actions);
      results.appendChild(card);
    });
  };

  const updatePagination = () => {
    if (!pagination) return;
    pagination.hidden = !results?.children.length;
    if (previousButton) previousButton.disabled = !previousPageToken;
    if (nextButton) nextButton.disabled = !nextPageToken;
    if (pageLabel) pageLabel.textContent = `Page ${pageNumber}`;
  };

  const search = async (pageToken = '', direction = 0) => {
    const term = (query?.value || '').trim();
    if (term.length < 2) return setMessage('Enter at least two characters to search YouTube.', true);
    if (!searchUrl) return setMessage('YouTube search is not configured.', true);
    if (term !== activeQuery) {
      pageToken = '';
      direction = 0;
      pageNumber = 1;
    }
    if (searchButton) searchButton.disabled = true;
    setMessage('Searching YouTube…');
    try {
      const url = new URL(searchUrl, window.location.origin);
      url.searchParams.set('q', term);
      if (pageToken) url.searchParams.set('page_token', pageToken);
      const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'YouTube search failed.');
      const videos = Array.isArray(payload.items) ? payload.items : [];
      activeQuery = term;
      nextPageToken = payload.next_page_token || '';
      previousPageToken = payload.previous_page_token || '';
      pageNumber = Math.max(1, pageNumber + direction);
      renderResults(videos);
      updatePagination();
      setMessage(videos.length ? `${videos.length} YouTube result${videos.length === 1 ? '' : 's'} found.` : 'No matching videos found. Try another search.');
    } catch (error) {
      renderResults([]);
      nextPageToken = '';
      previousPageToken = '';
      updatePagination();
      setMessage(error.message || 'YouTube search is unavailable.', true);
    } finally {
      if (searchButton) searchButton.disabled = false;
    }
  };

  searchButton?.addEventListener('click', () => search());
  query?.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      search();
    }
  });
  previousButton?.addEventListener('click', () => {
    if (previousPageToken) search(previousPageToken, -1);
  });
  nextButton?.addEventListener('click', () => {
    if (nextPageToken) search(nextPageToken, 1);
  });
  root.querySelector('[data-karaoke-use-link]')?.addEventListener('click', () => {
    const value = (directLink?.value || '').trim();
    if (!value) return setMessage('Paste a YouTube video link first.', true);
    chooseVideo({
      video_id: '',
      watch_url: value,
      title: 'Direct YouTube video',
      channel_title: 'The host will verify this link',
    });
  });
})();
