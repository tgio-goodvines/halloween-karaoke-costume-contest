document.addEventListener('DOMContentLoaded', () => {
  const dataElement = document.getElementById('entries-data');
  const overrideElement = document.getElementById('override-data');
  const card = document.querySelector('[data-display-card]');
  const emptyState = document.querySelector('[data-empty-state]');
  const overrideContainer = document.querySelector('[data-override-state]');
  const generalOverrideElement = overrideContainer
    ? overrideContainer.querySelector('[data-override-general]')
    : null;
  const karaokeOverrideElement = overrideContainer
    ? overrideContainer.querySelector('[data-override-karaoke]')
    : null;
  const overrideTitleElement = overrideContainer ? overrideContainer.querySelector('[data-override-title]') : null;
  const overrideHighlightElement = overrideContainer ? overrideContainer.querySelector('[data-override-highlight]') : null;
  const overrideMessageElement = overrideContainer ? overrideContainer.querySelector('[data-override-message]') : null;
  const overrideDetailsElement = overrideContainer ? overrideContainer.querySelector('[data-override-details]') : null;
  const karaokeTitleElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-title]')
    : null;
  const karaokeSubtitleElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-subtitle]')
    : null;
  const karaokeMessageElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-message]')
    : null;
  const karaokeSingerElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-singer]')
    : null;
  const karaokeSongElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-song]')
    : null;
  const karaokePreviewElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-preview]')
    : null;
  const karaokeIframeElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-iframe]')
    : null;
  const karaokeThumbnailLinkElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-thumbnail]')
    : null;
  const karaokeThumbnailImageElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-thumbnail-image]')
    : null;
  const karaokeThumbnailLabelElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-thumbnail-label]')
    : null;
  const karaokeOpenLinkElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-open-link]')
    : null;
  const karaokeNoteElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-note]')
    : null;
  const costumeCountElement = document.querySelector('[data-costume-count]');
  const karaokeCountElement = document.querySelector('[data-karaoke-count]');
  const bodyDataset = (document.body && document.body.dataset) || {};
  const dataEndpoint = bodyDataset.displayApi || '/api/display-data';
  const updatesEndpoint = bodyDataset.displayUpdates || null;

  if (!dataElement || !card || !emptyState) {
    return;
  }

  let entries = [];
  try {
    entries = JSON.parse(dataElement.textContent || '[]');
    if (!Array.isArray(entries)) {
      entries = [];
    }
  } catch (error) {
    console.error('Unable to parse display entries', error);
    entries = [];
  }

  let entriesSignature;
  try {
    entriesSignature = JSON.stringify(entries);
  } catch (error) {
    entriesSignature = '[]';
  }

  let initialOverrideState = null;
  if (overrideElement) {
    try {
      const parsed = JSON.parse(overrideElement.textContent || 'null');
      if (parsed && typeof parsed === 'object') {
        initialOverrideState = parsed;
      }
    } catch (error) {
      console.error('Unable to parse override state', error);
    }
  }

  let overrideState = null;
  let overrideSignature = 'null';

  const defaultContent = card.querySelector('[data-entry-default]');
  const ctaLayout = card.querySelector('[data-cta-layout]');
  const ctaLedeElement = card.querySelector('[data-cta-lede]');
  const ctaWifiNetworkElement = card.querySelector('[data-cta-wifi-network]');
  const ctaWifiPasswordElement = card.querySelector('[data-cta-wifi-password]');
  const ctaPortalLinkElement = card.querySelector('[data-cta-portal-link]');
  const ctaPortalNoteElement = card.querySelector('[data-cta-portal-note]');
  const ctaReminderElement = card.querySelector('[data-cta-reminder]');
  const scoreboardLayout = card.querySelector('[data-scoreboard-layout]');
  const scoreboardTitleElement = scoreboardLayout
    ? scoreboardLayout.querySelector('[data-scoreboard-title]')
    : null;
  const scoreboardSubtitleElement = scoreboardLayout
    ? scoreboardLayout.querySelector('[data-scoreboard-subtitle]')
    : null;
  const scoreboardListElement = scoreboardLayout
    ? scoreboardLayout.querySelector('[data-scoreboard-list]')
    : null;
  const scoreboardNoteElement = scoreboardLayout
    ? scoreboardLayout.querySelector('[data-scoreboard-note]')
    : null;
  const typeElement = card.querySelector('[data-entry-type]');
  const primaryElement = card.querySelector('[data-entry-primary]');
  const secondaryElement = card.querySelector('[data-entry-secondary]');
  const tertiaryElement = card.querySelector('[data-entry-tertiary]');
  const linkElement = card.querySelector('[data-entry-link]');

  const formatAverageScore = (value) => {
    const numeric = Number(value);
    if (Number.isFinite(numeric)) {
      return numeric.toFixed(2);
    }
    return '0.00';
  };

  const extractYoutubeVideoId = (rawUrl) => {
    if (!rawUrl || typeof rawUrl !== 'string') {
      return '';
    }

    let parsed;
    try {
      parsed = new URL(rawUrl);
    } catch (error) {
      return '';
    }

    const { hostname, pathname, searchParams } = parsed;
    const cleanPathname = pathname || '';
    let videoId = '';

    if (hostname.includes('youtu.be')) {
      const [, potentialId] = cleanPathname.split('/');
      videoId = potentialId || '';
    } else if (cleanPathname.startsWith('/embed/')) {
      videoId = cleanPathname.replace('/embed/', '').split(/[/?&#]/)[0];
    } else if (cleanPathname.startsWith('/shorts/')) {
      videoId = cleanPathname.replace('/shorts/', '').split(/[/?&#]/)[0];
    } else {
      videoId = searchParams.get('v') || '';
    }

    if (!videoId && cleanPathname) {
      const segments = cleanPathname.split('/').filter(Boolean);
      if (segments.length) {
        videoId = segments[segments.length - 1].split(/[?&#]/)[0];
      }
    }

    return videoId;
  };

  const updateOverrideContent = () => {
    if (!overrideContainer) {
      return;
    }

    const titleText = overrideState && overrideState.title ? overrideState.title : '';
    const highlightText = overrideState && overrideState.highlight ? overrideState.highlight : '';
    const messageText = overrideState && overrideState.message ? overrideState.message : '';
    const details = overrideState && Array.isArray(overrideState.details) ? overrideState.details : [];
    const isKaraokeOverride = Boolean(
      overrideState && overrideState.type === 'karaoke_start' && karaokeOverrideElement
    );

    if (overrideTitleElement) {
      overrideTitleElement.textContent = titleText;
    }

    if (overrideHighlightElement) {
      if (highlightText) {
        overrideHighlightElement.textContent = highlightText;
        overrideHighlightElement.removeAttribute('hidden');
      } else {
        overrideHighlightElement.textContent = '';
        overrideHighlightElement.setAttribute('hidden', '');
      }
    }

    if (overrideMessageElement) {
      overrideMessageElement.textContent = messageText;
    }

    if (overrideDetailsElement) {
      overrideDetailsElement.innerHTML = '';
      if (details.length) {
        details.forEach((detail) => {
          const item = document.createElement('li');
          item.textContent = detail;
          overrideDetailsElement.appendChild(item);
        });
        overrideDetailsElement.removeAttribute('hidden');
      } else {
        overrideDetailsElement.setAttribute('hidden', '');
      }
    }

    if (isKaraokeOverride) {
      if (generalOverrideElement) {
        generalOverrideElement.setAttribute('hidden', '');
      }
      karaokeOverrideElement.removeAttribute('hidden');

      if (karaokeTitleElement) {
        karaokeTitleElement.textContent = titleText || 'Halloween Karaoke Party';
      }

      if (karaokeSubtitleElement) {
        if (highlightText) {
          karaokeSubtitleElement.textContent = highlightText;
          karaokeSubtitleElement.removeAttribute('hidden');
        } else {
          karaokeSubtitleElement.textContent = '';
          karaokeSubtitleElement.setAttribute('hidden', '');
        }
      }

      if (karaokeMessageElement) {
        if (messageText) {
          karaokeMessageElement.textContent = messageText;
          karaokeMessageElement.removeAttribute('hidden');
        } else {
          karaokeMessageElement.textContent = '';
          karaokeMessageElement.setAttribute('hidden', '');
        }
      }

      const karaokeData =
        overrideState && overrideState.karaoke && typeof overrideState.karaoke === 'object'
          ? overrideState.karaoke
          : {};

      if (karaokeSingerElement) {
        karaokeSingerElement.textContent = karaokeData.singer_name || 'TBA';
      }

      if (karaokeSongElement) {
        let songLine = '';
        const songTitle = karaokeData.song_title || '';
        const artist = karaokeData.artist || '';

        if (songTitle && artist) {
          songLine = `"${songTitle}" by ${artist}`;
        } else if (songTitle) {
          songLine = `"${songTitle}"`;
        } else if (artist) {
          songLine = artist;
        }

        karaokeSongElement.textContent = songLine;
      }

      const embedUrl = karaokeData.youtube_embed_url || '';

      if (embedUrl && karaokePreviewElement && karaokeIframeElement) {
        karaokePreviewElement.removeAttribute('hidden');
        const embedSrc = embedUrl.includes('?') ? `${embedUrl}&rel=0` : `${embedUrl}?rel=0`;
        karaokeIframeElement.setAttribute('src', embedSrc);
        karaokeIframeElement.removeAttribute('hidden');
        if (karaokeThumbnailLinkElement) {
          karaokeThumbnailLinkElement.setAttribute('hidden', '');
          karaokeThumbnailLinkElement.setAttribute('href', '#');
        }
        if (karaokeOpenLinkElement) {
          karaokeOpenLinkElement.setAttribute('hidden', '');
          karaokeOpenLinkElement.setAttribute('href', '#');
        }
        if (karaokeThumbnailImageElement) {
          karaokeThumbnailImageElement.setAttribute('src', '');
          karaokeThumbnailImageElement.setAttribute('alt', '');
        }
        if (karaokeNoteElement) {
          karaokeNoteElement.textContent = '';
          karaokeNoteElement.setAttribute('hidden', '');
        }
      } else {
        const youtubeLink = karaokeData.youtube_link || '';
        const videoId =
          extractYoutubeVideoId(karaokeData.youtube_embed_url || '') ||
          extractYoutubeVideoId(youtubeLink);
        const hasYoutubeLink = Boolean(youtubeLink);

        if (karaokePreviewElement) {
          if (videoId && hasYoutubeLink) {
            karaokePreviewElement.removeAttribute('hidden');
          } else {
            karaokePreviewElement.setAttribute('hidden', '');
          }
        }

        if (karaokeIframeElement) {
          karaokeIframeElement.setAttribute('src', '');
          karaokeIframeElement.setAttribute('hidden', '');
        }

        if (videoId && hasYoutubeLink && karaokeThumbnailLinkElement) {
          const thumbnailUrl = `https://img.youtube.com/vi/${videoId}/hqdefault.jpg`;
          karaokeThumbnailLinkElement.setAttribute('href', youtubeLink);
          karaokeThumbnailLinkElement.removeAttribute('hidden');
          if (karaokeThumbnailImageElement) {
            karaokeThumbnailImageElement.setAttribute('src', thumbnailUrl);
            const descriptionParts = [];
            if (karaokeData.song_title) {
              descriptionParts.push(`“${karaokeData.song_title}”`);
            }
            if (karaokeData.artist) {
              descriptionParts.push(`by ${karaokeData.artist}`);
            }
            const description = descriptionParts.length
              ? `YouTube thumbnail for ${descriptionParts.join(' ')}`
              : 'YouTube thumbnail preview';
            karaokeThumbnailImageElement.setAttribute('alt', description);
          }
          if (karaokeThumbnailLabelElement) {
            karaokeThumbnailLabelElement.textContent = 'Open on YouTube';
          }
          if (karaokeOpenLinkElement) {
            karaokeOpenLinkElement.setAttribute('hidden', '');
            karaokeOpenLinkElement.setAttribute('href', '#');
          }
          if (karaokeNoteElement) {
            karaokeNoteElement.textContent = 'Embeds are disabled—open the video on YouTube to play it.';
            karaokeNoteElement.removeAttribute('hidden');
          }
        } else if (hasYoutubeLink) {
          if (karaokeThumbnailLinkElement) {
            karaokeThumbnailLinkElement.setAttribute('hidden', '');
            karaokeThumbnailLinkElement.setAttribute('href', '#');
          }
          if (karaokeThumbnailImageElement) {
            karaokeThumbnailImageElement.setAttribute('src', '');
            karaokeThumbnailImageElement.setAttribute('alt', '');
          }
          if (karaokeOpenLinkElement) {
            karaokeOpenLinkElement.setAttribute('href', youtubeLink);
            karaokeOpenLinkElement.removeAttribute('hidden');
          }
          if (karaokeNoteElement) {
            karaokeNoteElement.textContent = 'Preview unavailable—open the video on YouTube to play it.';
            karaokeNoteElement.removeAttribute('hidden');
          }
        } else {
          if (karaokeThumbnailLinkElement) {
            karaokeThumbnailLinkElement.setAttribute('hidden', '');
            karaokeThumbnailLinkElement.setAttribute('href', '#');
          }
          if (karaokeThumbnailImageElement) {
            karaokeThumbnailImageElement.setAttribute('src', '');
            karaokeThumbnailImageElement.setAttribute('alt', '');
          }
          if (karaokeOpenLinkElement) {
            karaokeOpenLinkElement.setAttribute('hidden', '');
            karaokeOpenLinkElement.setAttribute('href', '#');
          }
          if (karaokeNoteElement) {
            karaokeNoteElement.textContent =
              'Please give Tony the YouTube link so he can cast it to the TV.';
            karaokeNoteElement.removeAttribute('hidden');
          }
        }
      }
    } else {
      if (generalOverrideElement) {
        generalOverrideElement.removeAttribute('hidden');
      }

      if (karaokeOverrideElement) {
        karaokeOverrideElement.setAttribute('hidden', '');
      }

      if (karaokeTitleElement) {
        karaokeTitleElement.textContent = '';
      }

      if (karaokeSubtitleElement) {
        karaokeSubtitleElement.textContent = '';
        karaokeSubtitleElement.setAttribute('hidden', '');
      }

      if (karaokeMessageElement) {
        karaokeMessageElement.textContent = '';
        karaokeMessageElement.setAttribute('hidden', '');
      }

      if (karaokeSingerElement) {
        karaokeSingerElement.textContent = '';
      }

      if (karaokeSongElement) {
        karaokeSongElement.textContent = '';
      }

      if (karaokePreviewElement) {
        karaokePreviewElement.setAttribute('hidden', '');
      }

      if (karaokeIframeElement) {
        karaokeIframeElement.setAttribute('src', '');
        karaokeIframeElement.setAttribute('hidden', '');
      }

      if (karaokeThumbnailLinkElement) {
        karaokeThumbnailLinkElement.setAttribute('hidden', '');
        karaokeThumbnailLinkElement.setAttribute('href', '#');
      }

      if (karaokeOpenLinkElement) {
        karaokeOpenLinkElement.setAttribute('hidden', '');
        karaokeOpenLinkElement.setAttribute('href', '#');
      }

      if (karaokeThumbnailImageElement) {
        karaokeThumbnailImageElement.setAttribute('src', '');
        karaokeThumbnailImageElement.setAttribute('alt', '');
      }

      if (karaokeThumbnailLabelElement) {
        karaokeThumbnailLabelElement.textContent = 'Open on YouTube';
      }

      if (karaokeNoteElement) {
        karaokeNoteElement.textContent = '';
        karaokeNoteElement.setAttribute('hidden', '');
      }
    }
  };

  const updateOverrideDisplay = () => {
    if (!overrideContainer) {
      return;
    }

    if (overrideState) {
      overrideContainer.removeAttribute('hidden');
      if (card) {
        card.classList.remove('active');
        card.setAttribute('hidden', '');
      }
      if (emptyState) {
        emptyState.classList.remove('is-visible');
        emptyState.setAttribute('hidden', '');
      }
    } else {
      overrideContainer.setAttribute('hidden', '');
      if (emptyState) {
        emptyState.removeAttribute('hidden');
      }
      if (card) {
        card.removeAttribute('hidden');
      }
    }
  };

  const applyEntry = (entry) => {
    typeElement.textContent = entry.category || '';
    primaryElement.textContent = entry.primary || '';
    secondaryElement.textContent = entry.secondary || '';

    if (entry.tertiary) {
      tertiaryElement.textContent = entry.tertiary;
      tertiaryElement.removeAttribute('hidden');
    } else {
      tertiaryElement.textContent = '';
      tertiaryElement.setAttribute('hidden', '');
    }

    const ctaDetails = entry.cta_details || {};
    const hasScoreboard = Boolean(
      scoreboardLayout && entry.scoreboard && Array.isArray(entry.scoreboard.entries) && entry.scoreboard.entries.length
    );
    const shouldShowCtaLayout = Boolean(entry.cta && ctaLayout && defaultContent && !hasScoreboard);

    if (hasScoreboard) {
      if (defaultContent) {
        defaultContent.setAttribute('hidden', '');
      }
      if (ctaLayout) {
        ctaLayout.setAttribute('hidden', '');
      }
      scoreboardLayout.removeAttribute('hidden');
      card.classList.add('scoreboard');
      card.classList.remove('cta');

      if (scoreboardTitleElement) {
        scoreboardTitleElement.textContent = entry.primary || 'Top Costume Scores';
      }

      if (scoreboardSubtitleElement) {
        const subtitle = entry.secondary || '';
        if (subtitle) {
          scoreboardSubtitleElement.textContent = subtitle;
          scoreboardSubtitleElement.removeAttribute('hidden');
        } else {
          scoreboardSubtitleElement.textContent = '';
          scoreboardSubtitleElement.setAttribute('hidden', '');
        }
      }

      if (scoreboardNoteElement) {
        const note = entry.tertiary || '';
        if (note) {
          scoreboardNoteElement.textContent = note;
          scoreboardNoteElement.removeAttribute('hidden');
        } else {
          scoreboardNoteElement.textContent = '';
          scoreboardNoteElement.setAttribute('hidden', '');
        }
      }

      if (scoreboardListElement) {
        scoreboardListElement.innerHTML = '';
        const rows = entry.scoreboard.entries || [];
        rows.forEach((row, index) => {
          const item = document.createElement('li');
          item.className = 'display-scoreboard__item';

          const rankElement = document.createElement('span');
          rankElement.className = 'display-scoreboard__rank';
          const rankValue = Number(row.rank);
          const safeRank = Number.isFinite(rankValue) ? rankValue : index + 1;
          rankElement.textContent = `#${safeRank}`;

          const infoElement = document.createElement('div');
          infoElement.className = 'display-scoreboard__info';

          const nameElement = document.createElement('span');
          nameElement.className = 'display-scoreboard__name';
          nameElement.textContent = row.name || '';

          const costumeElement = document.createElement('span');
          costumeElement.className = 'display-scoreboard__costume';
          costumeElement.textContent = row.costume ? `as ${row.costume}` : '';

          infoElement.appendChild(nameElement);
          infoElement.appendChild(costumeElement);

          const metricsElement = document.createElement('div');
          metricsElement.className = 'display-scoreboard__metrics';

          const averageElement = document.createElement('span');
          averageElement.className = 'display-scoreboard__average';
          averageElement.textContent = formatAverageScore(row.average);

          const votesElement = document.createElement('span');
          votesElement.className = 'display-scoreboard__votes';
          const voteCount = Number(row.count);
          const safeCount = Number.isFinite(voteCount) ? voteCount : 0;
          votesElement.textContent = `${safeCount} ${safeCount === 1 ? 'vote' : 'votes'}`;

          metricsElement.appendChild(averageElement);
          metricsElement.appendChild(votesElement);

          item.appendChild(rankElement);
          item.appendChild(infoElement);
          item.appendChild(metricsElement);

          scoreboardListElement.appendChild(item);
        });
      }
    } else if (shouldShowCtaLayout) {
      defaultContent.setAttribute('hidden', '');
      ctaLayout.removeAttribute('hidden');

      if (ctaLedeElement) {
        ctaLedeElement.textContent = ctaDetails.lede || entry.secondary || entry.primary || '';
      }

      if (ctaWifiNetworkElement) {
        ctaWifiNetworkElement.textContent = ctaDetails.wifi_network || '';
      }

      if (ctaWifiPasswordElement) {
        ctaWifiPasswordElement.textContent = ctaDetails.wifi_password || '';
      }

      if (ctaPortalLinkElement) {
        const portalUrl = ctaDetails.portal_url || entry.link || '';
        const portalLabel = ctaDetails.portal_label || portalUrl;

        if (portalUrl) {
          ctaPortalLinkElement.textContent = portalLabel || portalUrl;
          ctaPortalLinkElement.setAttribute('href', portalUrl);
        } else {
          ctaPortalLinkElement.textContent = '';
          ctaPortalLinkElement.removeAttribute('href');
        }
      }

      if (ctaPortalNoteElement) {
        ctaPortalNoteElement.textContent = ctaDetails.portal_note || '';
      }

      if (ctaReminderElement) {
        ctaReminderElement.textContent = ctaDetails.reminder || entry.tertiary || '';
      }

      if (scoreboardLayout) {
        scoreboardLayout.setAttribute('hidden', '');
        if (scoreboardListElement) {
          scoreboardListElement.innerHTML = '';
        }
      }

      card.classList.remove('scoreboard');
    } else {
      if (defaultContent) {
        defaultContent.removeAttribute('hidden');
      }
      if (ctaLayout) {
        ctaLayout.setAttribute('hidden', '');
      }
      if (ctaLedeElement) {
        ctaLedeElement.textContent = '';
      }
      if (ctaWifiNetworkElement) {
        ctaWifiNetworkElement.textContent = '';
      }
      if (ctaWifiPasswordElement) {
        ctaWifiPasswordElement.textContent = '';
      }
      if (ctaPortalLinkElement) {
        ctaPortalLinkElement.textContent = '';
        ctaPortalLinkElement.removeAttribute('href');
      }
      if (ctaPortalNoteElement) {
        ctaPortalNoteElement.textContent = '';
      }
      if (ctaReminderElement) {
        ctaReminderElement.textContent = '';
      }
      if (scoreboardLayout) {
        scoreboardLayout.setAttribute('hidden', '');
        if (scoreboardListElement) {
          scoreboardListElement.innerHTML = '';
        }
      }

      card.classList.remove('scoreboard');
    }

    if (!hasScoreboard && entry.cta) {
      card.classList.add('cta');
    } else if (!entry.cta || hasScoreboard) {
      card.classList.remove('cta');
    }

    if (linkElement) {
      if (entry.link && !entry.cta && !hasScoreboard) {
        linkElement.textContent = entry.link_label || entry.link;
        linkElement.setAttribute('href', entry.link);
        linkElement.removeAttribute('hidden');
      } else {
        linkElement.textContent = '';
        linkElement.removeAttribute('href');
        linkElement.setAttribute('hidden', '');
      }
    }
  };

  const cycleDelay = 8000;
  const transitionDelay = 450;
  let currentIndex = 0;
  let rotationTimerId = null;

  const stopRotation = () => {
    if (rotationTimerId) {
      window.clearInterval(rotationTimerId);
      rotationTimerId = null;
    }
  };

  const swapEntry = (useTransition) => {
    if (!entries.length) {
      return;
    }

    const show = () => {
      applyEntry(entries[currentIndex]);
      card.classList.add('active');
    };

    if (useTransition) {
      card.classList.remove('active');
      window.setTimeout(show, transitionDelay);
    } else {
      show();
    }
  };

  const renderEntries = ({ resetIndex = false, animate = false } = {}) => {
    updateOverrideDisplay();

    if (overrideState) {
      stopRotation();
      return;
    }

    if (entries.length === 0) {
      stopRotation();
      emptyState.classList.add('is-visible');
      card.classList.remove('active');
      card.setAttribute('hidden', '');
      return;
    }

    if (resetIndex) {
      currentIndex = 0;
    } else {
      currentIndex = currentIndex % entries.length;
    }

    emptyState.classList.remove('is-visible');
    card.removeAttribute('hidden');

    stopRotation();
    swapEntry(animate);

    if (entries.length > 1) {
      rotationTimerId = window.setInterval(() => {
        currentIndex = (currentIndex + 1) % entries.length;
        swapEntry(true);
      }, cycleDelay);
    }
  };

  const setOverrideState = (state, { force = false } = {}) => {
    let signature = 'null';
    try {
      signature = JSON.stringify(state ?? null);
    } catch (error) {
      signature = 'null';
    }

    if (!force && signature === overrideSignature) {
      return;
    }

    overrideSignature = signature;
    overrideState = state && typeof state === 'object' ? state : null;
    updateOverrideContent();
    renderEntries({ resetIndex: true });
  };

  setOverrideState(initialOverrideState ?? null, { force: true });

  const updateCounts = (costumeCount, karaokeCount) => {
    if (costumeCountElement && Number.isFinite(costumeCount)) {
      costumeCountElement.textContent = costumeCount;
    }

    if (karaokeCountElement && Number.isFinite(karaokeCount)) {
      karaokeCountElement.textContent = karaokeCount;
    }
  };

  const refreshInterval = 30000;

  const fetchLatestEntries = async () => {
    try {
      const response = await fetch(dataEndpoint, { cache: 'no-store' });

      if (!response.ok) {
        throw new Error(`Request failed with status ${response.status}`);
      }

      const payload = await response.json();
      const {
        entries: newEntries,
        costume_count: costumeCount,
        karaoke_count: karaokeCount,
        override: newOverride,
      } = payload;

      updateCounts(costumeCount, karaokeCount);
      setOverrideState(newOverride || null);

      if (Array.isArray(newEntries)) {
        const newSignature = JSON.stringify(newEntries);
        if (newSignature !== entriesSignature) {
          entries = newEntries;
          entriesSignature = newSignature;
          renderEntries({ resetIndex: true, animate: true });
        }
      }
    } catch (error) {
      console.error('Unable to refresh display data', error);
    }
  };

  fetchLatestEntries();
  window.setInterval(fetchLatestEntries, refreshInterval);

  const startEventStream = () => {
    if (!updatesEndpoint || typeof window.EventSource !== 'function') {
      return;
    }

    let reconnectTimer = null;
    let retryDelay = 2000;
    let eventSource;

    const cleanup = () => {
      if (reconnectTimer) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      if (eventSource) {
        try {
          eventSource.close();
        } catch (error) {
          // Ignore close errors.
        }
        eventSource = null;
      }
    };

    const connect = () => {
      cleanup();
      eventSource = new EventSource(updatesEndpoint, { withCredentials: false });

      eventSource.onmessage = () => {
        fetchLatestEntries();
      };

      eventSource.onopen = () => {
        retryDelay = 2000;
      };

      eventSource.onerror = () => {
        cleanup();
        const delay = retryDelay;
        reconnectTimer = window.setTimeout(() => {
          retryDelay = Math.min(Math.max(delay * 1.5, 4000), 30000);
          connect();
        }, delay);
      };
    };

    connect();

    window.addEventListener('beforeunload', cleanup);
  };

  startEventStream();
});
