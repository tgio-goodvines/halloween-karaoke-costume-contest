document.addEventListener('DOMContentLoaded', () => {
  const dataElement = document.getElementById('entries-data');
  const overrideElement = document.getElementById('override-data');
  const noticeOverrideElement = document.getElementById('notice-override-data');
  const layoutElement = document.getElementById('layout-data');
  const activityElement = document.getElementById('activity-data');
  const card = document.querySelector('[data-display-card]');
  const emptyState = document.querySelector('[data-empty-state]');
  const leftRail = document.querySelector('[data-left-rail]');
  const activityRail = document.querySelector('[data-activity-rail]');
  const activityPanels = activityRail
    ? Array.from(activityRail.querySelectorAll('[data-activity-panel]'))
    : [];
  const activityDrinkElement = activityRail ? activityRail.querySelector('[data-activity-drinks]') : null;
  const activityReadyElement = activityRail ? activityRail.querySelector('[data-activity-ready]') : null;
  const activityCostumeElement = activityRail ? activityRail.querySelector('[data-activity-costumes]') : null;
  const activityKaraokeElement = activityRail ? activityRail.querySelector('[data-activity-karaoke]') : null;
  const overrideContainer = document.querySelector('[data-override-state]');
  const overrideCardElement = overrideContainer
    ? overrideContainer.querySelector('.display-override__card')
    : null;
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
  const overrideImageElement = overrideContainer ? overrideContainer.querySelector('[data-override-image]') : null;
  const noticeContainer = document.querySelector('[data-notice-state]');
  const noticeTitleElement = noticeContainer ? noticeContainer.querySelector('[data-notice-title]') : null;
  const noticeHighlightElement = noticeContainer ? noticeContainer.querySelector('[data-notice-highlight]') : null;
  const noticeMessageElement = noticeContainer ? noticeContainer.querySelector('[data-notice-message]') : null;
  const noticeDetailsElement = noticeContainer ? noticeContainer.querySelector('[data-notice-details]') : null;
  const noticeImageElement = noticeContainer ? noticeContainer.querySelector('[data-notice-image]') : null;
  const karaokeTitleElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-title]')
    : null;
  const karaokeSubtitleElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-subtitle]')
    : null;
  const karaokeMessageElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-message]')
    : null;
  const karaokeCountdownElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-countdown]')
    : null;
  const karaokeCountdownNoteElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-countdown-note]')
    : null;
  const karaokeLineupElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-lineup]')
    : null;
  const karaokeEmptyElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-empty]')
    : null;
  const karaokeRotatorElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-rotator]')
    : null;
  const karaokeStageElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-stage]')
    : null;
  const karaokeStageIntroElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-stage-intro]')
    : null;
  const karaokeStageSingerElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-stage-singer]')
    : null;
  const karaokeStageSongElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-stage-song]')
    : null;
  const karaokeStageYoutubeElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-stage-youtube]')
    : null;
  const karaokeStageNextElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-stage-next]')
    : null;
  const karaokeVideoElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-video]')
    : null;
  const karaokeVideoFrameElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-video-frame]')
    : null;
  const karaokeVideoFallbackElement = karaokeOverrideElement
    ? karaokeOverrideElement.querySelector('[data-karaoke-video-fallback]')
    : null;
  const costumeCountElement = document.querySelector('[data-costume-count]');
  const karaokeCountElement = document.querySelector('[data-karaoke-count]');
  let hasRefreshedDisplayStylesheet = false;
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

  const parseJsonElement = (element, fallback) => {
    if (!element) {
      return fallback;
    }

    try {
      return JSON.parse(element.textContent || 'null') ?? fallback;
    } catch (error) {
      console.error('Unable to parse display JSON', error);
      return fallback;
    }
  };

  let initialOverrideState = null;
  const parsedOverrideState = parseJsonElement(overrideElement, null);
  if (parsedOverrideState && typeof parsedOverrideState === 'object') {
    initialOverrideState = parsedOverrideState;
  }

  let initialNoticeOverrideState = null;
  const parsedNoticeOverrideState = parseJsonElement(noticeOverrideElement, null);
  if (parsedNoticeOverrideState && typeof parsedNoticeOverrideState === 'object') {
    initialNoticeOverrideState = parsedNoticeOverrideState;
  }

  let overrideState = null;
  let overrideSignature = 'null';
  let noticeOverrideState = null;
  let noticeOverrideSignature = 'null';
  let layoutState = parseJsonElement(layoutElement, { mode: 'idle' });
  let layoutSignature = 'null';
  let activityState = parseJsonElement(activityElement, {});
  let activitySignature = 'null';

  const defaultContent = card.querySelector('[data-entry-default]');
  const ctaLayout = card.querySelector('[data-cta-layout]');
  const ctaLedeElement = card.querySelector('[data-cta-lede]');
  const ctaWifiNetworkElement = card.querySelector('[data-cta-wifi-network]');
  const ctaWifiNetworkItemElement = card.querySelector('[data-cta-wifi-network-item]');
  const ctaWifiPasswordElement = card.querySelector('[data-cta-wifi-password]');
  const ctaWifiPasswordItemElement = card.querySelector('[data-cta-wifi-password-item]');
  const ctaSiteUrlElement = card.querySelector('[data-cta-site-url]');
  const ctaSiteUrlItemElement = card.querySelector('[data-cta-site-url-item]');
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

  const formatAverageScore = (value) => {
    const numeric = Number(value);
    if (Number.isFinite(numeric)) {
      return numeric.toFixed(2);
    }
    return '0.00';
  };

  const getEntryTextLength = (entry) => {
    if (!entry || typeof entry !== 'object') {
      return 0;
    }

    return ['category', 'primary', 'secondary', 'tertiary']
      .map((key) => (entry[key] ? String(entry[key]) : ''))
      .join(' ')
      .length;
  };

  const safeText = (value, fallback = '') => {
    const text = value == null ? '' : String(value).trim();
    return text || fallback;
  };

  const applyLayoutState = () => {
    const mode = layoutState && layoutState.mode === 'dashboard' ? 'dashboard' : 'idle';
    const leftRailEnabled = Boolean(layoutState && layoutState.left_rail_enabled);
    const rightRailEnabled = Boolean(layoutState && layoutState.right_rail_enabled);

    document.body.classList.toggle('display-mode--idle', mode === 'idle');
    document.body.classList.toggle('display-mode--dashboard', mode === 'dashboard');
    document.body.classList.toggle('display-mode--jukebox', leftRailEnabled);
    document.body.classList.toggle('display-mode--activity', rightRailEnabled);

    if (leftRail) {
      if (leftRailEnabled) {
        leftRail.removeAttribute('hidden');
      } else {
        leftRail.setAttribute('hidden', '');
      }
    }

    if (activityRail) {
      if (rightRailEnabled) {
        activityRail.removeAttribute('hidden');
      } else {
        activityRail.setAttribute('hidden', '');
      }
    }
  };

  const sectionHasItems = (items) => Array.isArray(items) && items.length > 0;

  const clearElement = (element) => {
    if (element) {
      element.innerHTML = '';
    }
  };

  const appendTextElement = (parent, tagName, className, text) => {
    const element = document.createElement(tagName);
    if (className) {
      element.className = className;
    }
    element.textContent = text;
    parent.appendChild(element);
    return element;
  };

  const renderActivityItems = (container, items, emptyText, renderItem) => {
    if (!container) {
      return;
    }

    clearElement(container);

    if (!sectionHasItems(items)) {
      const empty = document.createElement('p');
      empty.className = 'activity-rail__empty';
      empty.textContent = emptyText;
      container.appendChild(empty);
      return;
    }

    items.slice(0, 5).forEach((item, index) => {
      const article = document.createElement('article');
      article.className = 'activity-item';
      renderItem(article, item, index);
      container.appendChild(article);
    });
  };

  const setActivityPanelVisibility = () => {
    const activityMap = {
      drinks: activityState.drink_orders,
      ready: activityState.ready_drinks,
      costumes: activityState.costumes,
      karaoke: activityState.karaoke,
    };

    activityPanels.forEach((panel) => {
      const key = panel.getAttribute('data-activity-panel');
      if (sectionHasItems(activityMap[key])) {
        panel.removeAttribute('hidden');
      } else {
        panel.setAttribute('hidden', '');
        panel.classList.remove('is-active');
      }
    });
  };

  let karaokeCountdownTimerId = null;
  let karaokeCountdownTarget = null;
  let karaokeRotatorPanels = [];
  let karaokeRotatorIndex = 0;
  let karaokeRotatorTimerId = null;
  let karaokeRotatorResizeHandler = null;
  const KARAOKE_ROTATOR_INTERVAL = 8000;
  let activityPanelIndex = 0;
  let activityRotatorTimerId = null;
  const ACTIVITY_ROTATOR_INTERVAL = 10000;

  const visibleActivityPanels = () =>
    activityPanels.filter((panel) => !panel.hasAttribute('hidden'));

  const applyActivityPanelIndex = () => {
    const panels = visibleActivityPanels();
    if (!panels.length) {
      return;
    }

    if (activityPanelIndex >= panels.length) {
      activityPanelIndex = 0;
    }

    activityPanels.forEach((panel) => {
      panel.classList.remove('is-active');
    });
    panels[activityPanelIndex].classList.add('is-active');
  };

  const stopActivityRotator = () => {
    if (activityRotatorTimerId) {
      window.clearInterval(activityRotatorTimerId);
      activityRotatorTimerId = null;
    }
  };

  const startActivityRotator = ({ resetIndex = false } = {}) => {
    stopActivityRotator();
    setActivityPanelVisibility();

    const panels = visibleActivityPanels();
    if (resetIndex || activityPanelIndex >= panels.length) {
      activityPanelIndex = 0;
    }
    applyActivityPanelIndex();

    if (panels.length <= 1) {
      return;
    }

    activityRotatorTimerId = window.setInterval(() => {
      const currentPanels = visibleActivityPanels();
      if (!currentPanels.length) {
        stopActivityRotator();
        return;
      }
      activityPanelIndex = (activityPanelIndex + 1) % currentPanels.length;
      applyActivityPanelIndex();
    }, ACTIVITY_ROTATOR_INTERVAL);
  };

  const renderActivityRail = ({ resetIndex = false } = {}) => {
    renderActivityItems(
      activityDrinkElement,
      activityState.drink_orders,
      'No active bar orders.',
      (article, order) => {
        appendTextElement(article, 'span', 'activity-item__label', safeText(order.status_label, 'Order received'));
        appendTextElement(article, 'strong', '', safeText(order.drink, 'Drink'));
        appendTextElement(article, 'span', '', safeText(order.guest, 'Guest'));
      }
    );

    renderActivityItems(
      activityReadyElement,
      activityState.ready_drinks,
      'No drinks ready right now.',
      (article, order) => {
        article.classList.add('activity-item--ready');
        const imageUrl = safeText(order.image_url);
        if (imageUrl) {
          const image = document.createElement('img');
          image.className = 'activity-item__image';
          image.src = imageUrl;
          image.alt = '';
          article.appendChild(image);
        }
        appendTextElement(article, 'span', 'activity-item__label', 'Ready now');
        appendTextElement(article, 'strong', '', safeText(order.drink, 'Drink'));
        appendTextElement(article, 'span', '', safeText(order.guest, 'Guest'));
      }
    );

    renderActivityItems(
      activityCostumeElement,
      activityState.costumes,
      'Costume lineup is open.',
      (article, entry) => {
        appendTextElement(article, 'span', 'activity-item__label', 'Contestant');
        appendTextElement(article, 'strong', '', safeText(entry.name, 'Guest'));
        appendTextElement(article, 'span', '', safeText(entry.costume, 'Costume coming soon'));
      }
    );

    renderActivityItems(
      activityKaraokeElement,
      activityState.karaoke,
      'Karaoke lineup is open.',
      (article, entry, index) => {
        appendTextElement(article, 'span', 'activity-item__label', `Singer #${index + 1}`);
        appendTextElement(article, 'strong', '', safeText(entry.name, 'Singer'));
        const artist = safeText(entry.artist);
        const song = safeText(entry.song_title, 'Song coming soon');
        appendTextElement(article, 'span', '', artist ? `${song} · ${artist}` : song);
      }
    );

    if (layoutState && layoutState.right_rail_enabled) {
      startActivityRotator({ resetIndex });
    } else {
      stopActivityRotator();
    }
  };

  const refreshDisplayStylesheet = () => {
    if (hasRefreshedDisplayStylesheet) {
      return;
    }

    let displayStylesheetLink = null;

    document.querySelectorAll('link[rel~="stylesheet"]').forEach((link) => {
      if (displayStylesheetLink) {
        return;
      }

      const href = link.getAttribute('href') || '';
      if (href.includes('display.css')) {
        displayStylesheetLink = link;
      }
    });

    if (!displayStylesheetLink) {
      return;
    }

    try {
      const cacheBustingUrl = new URL(displayStylesheetLink.href, window.location.href);
      cacheBustingUrl.searchParams.set('_', Date.now().toString());
      displayStylesheetLink.href = cacheBustingUrl.toString();
      hasRefreshedDisplayStylesheet = true;
    } catch (error) {
      console.error('Unable to refresh display stylesheet', error);
    }
  };

  const stopKaraokeRotator = () => {
    if (karaokeRotatorTimerId) {
      window.clearInterval(karaokeRotatorTimerId);
      karaokeRotatorTimerId = null;
    }

    if (karaokeRotatorResizeHandler) {
      window.removeEventListener('resize', karaokeRotatorResizeHandler);
      karaokeRotatorResizeHandler = null;
    }
  };

  const collectKaraokeRotatorPanels = () => {
    if (!karaokeRotatorElement) {
      karaokeRotatorPanels = [];
      return;
    }

    karaokeRotatorPanels = Array.from(
      karaokeRotatorElement.querySelectorAll('[data-karaoke-panel]')
    ).filter((panel) => panel instanceof HTMLElement);
  };

  const applyKaraokeRotatorIndex = () => {
    if (!karaokeRotatorPanels.length) {
      return;
    }

    karaokeRotatorPanels.forEach((panel, panelIndex) => {
      if (panelIndex === karaokeRotatorIndex) {
        panel.classList.add('is-active');
        panel.setAttribute('aria-hidden', 'false');
      } else {
        panel.classList.remove('is-active');
        panel.setAttribute('aria-hidden', 'true');
      }
    });
  };

  const measureKaraokeRotatorHeight = () => {
    if (!karaokeRotatorElement || !karaokeRotatorPanels.length) {
      if (karaokeRotatorElement) {
        karaokeRotatorElement.style.height = '';
      }
      return;
    }

    let maxHeight = 0;

    karaokeRotatorPanels.forEach((panel) => {
      panel.classList.add('is-measuring');
      const panelHeight = panel.offsetHeight;
      if (panelHeight > maxHeight) {
        maxHeight = panelHeight;
      }
      panel.classList.remove('is-measuring');
    });

    if (maxHeight > 0) {
      karaokeRotatorElement.style.height = `${Math.ceil(maxHeight)}px`;
    } else {
      karaokeRotatorElement.style.height = '';
    }
  };

  const refreshKaraokeRotator = ({ resetIndex = false } = {}) => {
    if (!karaokeRotatorElement) {
      stopKaraokeRotator();
      return;
    }

    collectKaraokeRotatorPanels();

    if (!karaokeRotatorPanels.length) {
      karaokeRotatorElement.style.height = '';
      stopKaraokeRotator();
      return;
    }

    if (resetIndex || karaokeRotatorIndex >= karaokeRotatorPanels.length) {
      karaokeRotatorIndex = 0;
    }

    measureKaraokeRotatorHeight();
    applyKaraokeRotatorIndex();
  };

  const queueKaraokeRotatorRefresh = ({ resetIndex = false } = {}) => {
    if (!karaokeRotatorElement) {
      return;
    }

    if (karaokeOverrideElement && karaokeOverrideElement.hasAttribute('hidden')) {
      return;
    }

    window.requestAnimationFrame(() => {
      refreshKaraokeRotator({ resetIndex });
    });
  };

  const startKaraokeRotator = () => {
    if (!karaokeRotatorElement) {
      return;
    }

    stopKaraokeRotator();
    refreshKaraokeRotator({ resetIndex: true });

    if (!karaokeRotatorPanels.length) {
      return;
    }

    if (!karaokeRotatorResizeHandler) {
      karaokeRotatorResizeHandler = () => {
        queueKaraokeRotatorRefresh({ resetIndex: false });
      };
      window.addEventListener('resize', karaokeRotatorResizeHandler);
    }

    if (karaokeRotatorPanels.length <= 1) {
      return;
    }

    karaokeRotatorTimerId = window.setInterval(() => {
      karaokeRotatorIndex = (karaokeRotatorIndex + 1) % karaokeRotatorPanels.length;
      applyKaraokeRotatorIndex();
    }, KARAOKE_ROTATOR_INTERVAL);
  };

  const stopKaraokeCountdown = () => {
    if (karaokeCountdownTimerId) {
      window.clearInterval(karaokeCountdownTimerId);
      karaokeCountdownTimerId = null;
    }
    karaokeCountdownTarget = null;
  };

  const formatPerformerSong = (entry) => {
    if (!entry || typeof entry !== 'object') {
      return '';
    }

    const songTitle = entry.song_title ? String(entry.song_title).trim() : '';
    const artist = entry.artist ? String(entry.artist).trim() : '';

    if (songTitle && artist) {
      return `“${songTitle}” by ${artist}`;
    }
    if (songTitle) {
      return `“${songTitle}”`;
    }
    if (artist) {
      return artist;
    }

    return '';
  };

  const resetKaraokeStage = () => {
    if (karaokeStageElement) {
      karaokeStageElement.setAttribute('hidden', '');
    }
    if (karaokeStageIntroElement) {
      karaokeStageIntroElement.removeAttribute('hidden');
    }
    if (karaokeStageSingerElement) {
      karaokeStageSingerElement.textContent = '';
    }
    if (karaokeStageSongElement) {
      karaokeStageSongElement.textContent = '';
    }
    if (karaokeStageYoutubeElement) {
      karaokeStageYoutubeElement.href = '#';
      karaokeStageYoutubeElement.setAttribute('hidden', '');
    }
    if (karaokeStageNextElement) {
      karaokeStageNextElement.textContent = '';
      karaokeStageNextElement.setAttribute('hidden', '');
    }
    if (karaokeVideoElement) {
      karaokeVideoElement.setAttribute('hidden', '');
    }
    if (karaokeVideoFrameElement) {
      karaokeVideoFrameElement.removeAttribute('src');
      karaokeVideoFrameElement.onerror = null;
    }
    if (karaokeVideoFallbackElement) {
      karaokeVideoFallbackElement.textContent = '';
      karaokeVideoFallbackElement.setAttribute('hidden', '');
    }
  };

  const applyKaraokeStage = () => {
    if (!karaokeStageElement) {
      return;
    }

    const youtubeData =
      overrideState && overrideState.youtube && typeof overrideState.youtube === 'object'
        ? overrideState.youtube
        : {};
    const singerName =
      overrideState && overrideState.singer_name ? String(overrideState.singer_name).trim() : 'Next Singer';
    const songTitle =
      overrideState && overrideState.song_title ? String(overrideState.song_title).trim() : '';
    const artist = overrideState && overrideState.artist ? String(overrideState.artist).trim() : '';
    const songLine = formatPerformerSong({ song_title: songTitle, artist });
    const watchUrl = youtubeData.watch_url ? String(youtubeData.watch_url) : '';
    const videoId = youtubeData.video_id ? String(youtubeData.video_id) : '';
    const shouldShowVideo = Boolean(
      overrideState &&
        overrideState.mode === 'video' &&
        overrideState.video_enabled &&
        overrideState.video_playable &&
        videoId
    );

    karaokeStageElement.removeAttribute('hidden');

    if (karaokeStageSingerElement) {
      karaokeStageSingerElement.textContent = singerName;
    }
    if (karaokeStageSongElement) {
      karaokeStageSongElement.textContent = songLine || 'Song details coming up';
    }
    if (karaokeStageYoutubeElement) {
      if (watchUrl) {
        karaokeStageYoutubeElement.href = watchUrl;
        karaokeStageYoutubeElement.removeAttribute('hidden');
      } else {
        karaokeStageYoutubeElement.href = '#';
        karaokeStageYoutubeElement.setAttribute('hidden', '');
      }
    }

    const nextSinger =
      overrideState && overrideState.next_singer && typeof overrideState.next_singer === 'object'
        ? overrideState.next_singer
        : null;
    if (karaokeStageNextElement) {
      if (nextSinger && nextSinger.name) {
        const nextSong = formatPerformerSong(nextSinger);
        karaokeStageNextElement.textContent = nextSong
          ? `Up next: ${nextSinger.name} • ${nextSong}`
          : `Up next: ${nextSinger.name}`;
        karaokeStageNextElement.removeAttribute('hidden');
      } else {
        karaokeStageNextElement.textContent = '';
        karaokeStageNextElement.setAttribute('hidden', '');
      }
    }

    if (karaokeStageIntroElement) {
      if (shouldShowVideo) {
        karaokeStageIntroElement.setAttribute('hidden', '');
      } else {
        karaokeStageIntroElement.removeAttribute('hidden');
      }
    }

    if (karaokeVideoElement && karaokeVideoFrameElement) {
      if (shouldShowVideo) {
        const embedUrl = new URL(`https://www.youtube.com/embed/${videoId}`);
        embedUrl.searchParams.set('autoplay', '1');
        embedUrl.searchParams.set('playsinline', '1');
        embedUrl.searchParams.set('rel', '0');
        embedUrl.searchParams.set('origin', window.location.origin);
        karaokeVideoFrameElement.src = embedUrl.toString();
        karaokeVideoFrameElement.onerror = () => {
          karaokeVideoElement.setAttribute('hidden', '');
          if (karaokeStageIntroElement) {
            karaokeStageIntroElement.removeAttribute('hidden');
          }
          if (karaokeVideoFallbackElement) {
            karaokeVideoFallbackElement.textContent = 'Video playback was blocked. Use the stage card controls.';
            karaokeVideoFallbackElement.removeAttribute('hidden');
          }
        };
        karaokeVideoElement.removeAttribute('hidden');
      } else {
        karaokeVideoElement.setAttribute('hidden', '');
        karaokeVideoFrameElement.removeAttribute('src');
      }
    }
  };

  const updateKaraokeLineup = (entries) => {
    if (!karaokeLineupElement) {
      return;
    }

    karaokeLineupElement.innerHTML = '';
    const lineup = Array.isArray(entries) ? entries.filter((entry) => entry && typeof entry === 'object') : [];

    if (!lineup.length) {
      karaokeLineupElement.setAttribute('hidden', '');
      if (karaokeEmptyElement) {
        karaokeEmptyElement.removeAttribute('hidden');
      }
      queueKaraokeRotatorRefresh({ resetIndex: false });
      return;
    }

    lineup.slice(0, 6).forEach((entry, index) => {
      const item = document.createElement('li');
      item.className = 'karaoke-card__list-item';

      const rankElement = document.createElement('span');
      rankElement.className = 'karaoke-card__list-rank';
      rankElement.textContent = `#${index + 1}`;

      const infoElement = document.createElement('div');
      infoElement.className = 'karaoke-card__list-info';

      const nameElement = document.createElement('span');
      nameElement.className = 'karaoke-card__list-name';
      nameElement.textContent = entry.name ? String(entry.name).trim() || 'TBA' : 'TBA';

      infoElement.appendChild(nameElement);

      const songLine = formatPerformerSong(entry);
      if (songLine) {
        const songElement = document.createElement('span');
        songElement.className = 'karaoke-card__list-song';
        songElement.textContent = songLine;
        infoElement.appendChild(songElement);
      }

      item.appendChild(rankElement);
      item.appendChild(infoElement);

      karaokeLineupElement.appendChild(item);
    });

    karaokeLineupElement.removeAttribute('hidden');
    if (karaokeEmptyElement) {
      karaokeEmptyElement.setAttribute('hidden', '');
    }

    queueKaraokeRotatorRefresh({ resetIndex: false });
  };

  const startKaraokeCountdown = (targetIso, labelText = '') => {
    if (!karaokeCountdownElement) {
      return;
    }

    stopKaraokeCountdown();

    if (karaokeCountdownNoteElement) {
      if (labelText) {
        karaokeCountdownNoteElement.textContent = `Until ${labelText}`;
        karaokeCountdownNoteElement.removeAttribute('hidden');
      } else {
        karaokeCountdownNoteElement.textContent = '';
        karaokeCountdownNoteElement.setAttribute('hidden', '');
      }
    }

    if (!targetIso) {
      karaokeCountdownElement.textContent = '—';
      queueKaraokeRotatorRefresh({ resetIndex: false });
      return;
    }

    const parsedTarget = new Date(targetIso);
    if (Number.isNaN(parsedTarget.getTime())) {
      karaokeCountdownElement.textContent = '—';
      queueKaraokeRotatorRefresh({ resetIndex: false });
      return;
    }

    karaokeCountdownTarget = parsedTarget;

    const updateDisplay = () => {
      if (!karaokeCountdownTarget) {
        return;
      }

      const diff = karaokeCountdownTarget.getTime() - Date.now();

      if (diff <= 0) {
        karaokeCountdownElement.textContent = '00:00:00';
        if (karaokeCountdownNoteElement) {
          karaokeCountdownNoteElement.textContent = labelText
            ? `${labelText} has arrived!`
            : 'It\'s showtime!';
          karaokeCountdownNoteElement.removeAttribute('hidden');
        }
        stopKaraokeCountdown();
        queueKaraokeRotatorRefresh({ resetIndex: false });
        return;
      }

      const totalSeconds = Math.floor(diff / 1000);
      const hours = Math.floor(totalSeconds / 3600);
      const minutes = Math.floor((totalSeconds % 3600) / 60);
      const seconds = totalSeconds % 60;

      const formattedHours = hours.toString().padStart(2, '0');
      const formattedMinutes = minutes.toString().padStart(2, '0');
      const formattedSeconds = seconds.toString().padStart(2, '0');

      karaokeCountdownElement.textContent = `${formattedHours}:${formattedMinutes}:${formattedSeconds}`;
    };

    updateDisplay();
    karaokeCountdownTimerId = window.setInterval(updateDisplay, 1000);
    queueKaraokeRotatorRefresh({ resetIndex: false });
  };

  const updateOverrideContent = () => {
    if (!overrideContainer) {
      return;
    }

    if (overrideCardElement) {
      overrideCardElement.classList.remove(
        'display-override__card--inferno',
        'display-override__card--karaoke',
        'display-override__card--contest',
        'display-override__card--winner',
        'display-override__card--drink'
      );
    }

    const titleText = overrideState && overrideState.title ? overrideState.title : '';
    const highlightText = overrideState && overrideState.highlight ? overrideState.highlight : '';
    const messageText = overrideState && overrideState.message ? overrideState.message : '';
    const details = overrideState && Array.isArray(overrideState.details) ? overrideState.details : [];
    const overrideType = overrideState && overrideState.type ? String(overrideState.type) : '';
    const isKaraokeOverride = Boolean(
      (overrideType === 'karaoke_start' || overrideType === 'karaoke_stage') && karaokeOverrideElement
    );
    const isKaraokeStageOverride = overrideType === 'karaoke_stage';
    const isContestStartOverride = overrideType === 'contest_start';
    const isContestWinnerOverride = overrideType === 'winner';
    const isDrinkReadyOverride = overrideType === 'drink_ready';

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

    if (overrideImageElement) {
      const imageUrl = overrideState && overrideState.image_url ? String(overrideState.image_url) : '';
      if (imageUrl) {
        overrideImageElement.src = imageUrl;
        overrideImageElement.alt = highlightText || titleText || 'Drink image';
        overrideImageElement.removeAttribute('hidden');
      } else {
        overrideImageElement.removeAttribute('src');
        overrideImageElement.alt = '';
        overrideImageElement.setAttribute('hidden', '');
      }
    }

    if (isKaraokeOverride) {
      if (generalOverrideElement) {
        generalOverrideElement.setAttribute('hidden', '');
      }
      karaokeOverrideElement.removeAttribute('hidden');

      if (overrideCardElement) {
        overrideCardElement.classList.add(
          'display-override__card--inferno',
          'display-override__card--karaoke'
        );
      }

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

      if (isKaraokeStageOverride) {
        if (karaokeRotatorElement) {
          karaokeRotatorElement.setAttribute('hidden', '');
          karaokeRotatorElement.style.height = '';
        }
        stopKaraokeRotator();
        stopKaraokeCountdown();
        updateKaraokeLineup([]);
        applyKaraokeStage();
      } else {
        resetKaraokeStage();
        if (karaokeRotatorElement) {
          karaokeRotatorElement.removeAttribute('hidden');
        }
        const karaokeData =
          overrideState && overrideState.karaoke && typeof overrideState.karaoke === 'object'
            ? overrideState.karaoke
            : {};

        const lineup = Array.isArray(karaokeData.lineup) ? karaokeData.lineup : [];
        const countdownTarget =
          karaokeData.countdown_target && typeof karaokeData.countdown_target === 'string'
            ? karaokeData.countdown_target
            : '';
        const countdownLabel =
          karaokeData.countdown_label && typeof karaokeData.countdown_label === 'string'
            ? karaokeData.countdown_label
            : '';

        updateKaraokeLineup(lineup);
        startKaraokeCountdown(countdownTarget, countdownLabel);
        startKaraokeRotator();
      }
    } else {
      if (generalOverrideElement) {
        generalOverrideElement.removeAttribute('hidden');
      }

      if (karaokeOverrideElement) {
        karaokeOverrideElement.setAttribute('hidden', '');
      }

      stopKaraokeRotator();
      if (karaokeRotatorElement) {
        karaokeRotatorElement.style.height = '';
      }
      resetKaraokeStage();

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

      stopKaraokeCountdown();
      if (karaokeCountdownElement) {
        karaokeCountdownElement.textContent = '--:--:--';
      }
      if (karaokeCountdownNoteElement) {
        karaokeCountdownNoteElement.textContent = '';
        karaokeCountdownNoteElement.setAttribute('hidden', '');
      }
      updateKaraokeLineup([]);

      if (overrideCardElement && (isContestStartOverride || isContestWinnerOverride || isDrinkReadyOverride)) {
        overrideCardElement.classList.add('display-override__card--inferno');
        if (isContestStartOverride) {
          overrideCardElement.classList.add('display-override__card--contest');
        }
        if (isContestWinnerOverride) {
          overrideCardElement.classList.add('display-override__card--winner');
        }
        if (isDrinkReadyOverride) {
          overrideCardElement.classList.add('display-override__card--drink');
        }
      }
    }
  };

  const updateOverrideDisplay = () => {
    if (!overrideContainer) {
      return;
    }

    if (overrideState) {
      refreshDisplayStylesheet();
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

  const updateNoticeOverrideContent = () => {
    if (!noticeContainer) {
      return;
    }

    const titleText = noticeOverrideState && noticeOverrideState.title ? noticeOverrideState.title : '';
    const highlightText =
      noticeOverrideState && noticeOverrideState.highlight ? noticeOverrideState.highlight : '';
    const messageText = noticeOverrideState && noticeOverrideState.message ? noticeOverrideState.message : '';
    const details =
      noticeOverrideState && Array.isArray(noticeOverrideState.details)
        ? noticeOverrideState.details
        : [];

    if (noticeTitleElement) {
      noticeTitleElement.textContent = titleText;
    }

    if (noticeHighlightElement) {
      if (highlightText) {
        noticeHighlightElement.textContent = highlightText;
        noticeHighlightElement.removeAttribute('hidden');
      } else {
        noticeHighlightElement.textContent = '';
        noticeHighlightElement.setAttribute('hidden', '');
      }
    }

    if (noticeMessageElement) {
      noticeMessageElement.textContent = messageText;
    }

    if (noticeDetailsElement) {
      noticeDetailsElement.innerHTML = '';
      if (details.length) {
        details.forEach((detail) => {
          const item = document.createElement('li');
          item.textContent = detail;
          noticeDetailsElement.appendChild(item);
        });
        noticeDetailsElement.removeAttribute('hidden');
      } else {
        noticeDetailsElement.setAttribute('hidden', '');
      }
    }

    if (noticeImageElement) {
      const imageUrl =
        noticeOverrideState && noticeOverrideState.image_url
          ? String(noticeOverrideState.image_url)
          : '';
      if (imageUrl) {
        noticeImageElement.src = imageUrl;
        noticeImageElement.alt = highlightText || titleText || 'Drink image';
        noticeImageElement.removeAttribute('hidden');
      } else {
        noticeImageElement.removeAttribute('src');
        noticeImageElement.alt = '';
        noticeImageElement.setAttribute('hidden', '');
      }
    }
  };

  const updateNoticeOverrideDisplay = () => {
    if (!noticeContainer) {
      return;
    }

    if (noticeOverrideState) {
      refreshDisplayStylesheet();
      noticeContainer.removeAttribute('hidden');
    } else {
      noticeContainer.setAttribute('hidden', '');
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

    card.classList.remove(
      'display-card--inferno',
      'display-card--costume',
      'display-card--winner',
      'display-card--long',
      'display-card--dense',
      'display-card--spotlight',
      'display-card--mega'
    );

    const entryTextLength = getEntryTextLength(entry);
    const isIdleLayout = layoutState && layoutState.mode !== 'dashboard';
    if (isIdleLayout && entry.cta && entryTextLength < 230) {
      card.classList.add('display-card--mega');
    } else if (isIdleLayout && !hasScoreboard && entryTextLength < 150) {
      card.classList.add('display-card--spotlight');
    } else if (entryTextLength > 150) {
      card.classList.add('display-card--dense');
    } else if (entryTextLength > 95) {
      card.classList.add('display-card--long');
    } else if (entry.cta && entryTextLength < 180) {
      card.classList.add('display-card--mega');
    } else if (!hasScoreboard && entryTextLength < 82) {
      card.classList.add('display-card--spotlight');
    }

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
      if (ctaWifiNetworkItemElement) {
        if (ctaDetails.wifi_network) {
          ctaWifiNetworkItemElement.removeAttribute('hidden');
        } else {
          ctaWifiNetworkItemElement.setAttribute('hidden', '');
        }
      }

      if (ctaWifiPasswordElement) {
        ctaWifiPasswordElement.textContent = ctaDetails.wifi_password || '';
      }
      if (ctaWifiPasswordItemElement) {
        if (ctaDetails.wifi_password) {
          ctaWifiPasswordItemElement.removeAttribute('hidden');
        } else {
          ctaWifiPasswordItemElement.setAttribute('hidden', '');
        }
      }

      if (ctaSiteUrlElement) {
        ctaSiteUrlElement.textContent = ctaDetails.site_url || '';
      }
      if (ctaSiteUrlItemElement) {
        if (ctaDetails.site_url) {
          ctaSiteUrlItemElement.removeAttribute('hidden');
        } else {
          ctaSiteUrlItemElement.setAttribute('hidden', '');
        }
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
      if (ctaWifiNetworkItemElement) {
        ctaWifiNetworkItemElement.setAttribute('hidden', '');
      }
      if (ctaWifiPasswordElement) {
        ctaWifiPasswordElement.textContent = '';
      }
      if (ctaWifiPasswordItemElement) {
        ctaWifiPasswordItemElement.setAttribute('hidden', '');
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

    const categoryText = (entry.category || '').toLowerCase();
    const isWinnerCard = categoryText.includes('champion');
    const isCostumeCard = categoryText.includes('costume contest') && !hasScoreboard;

    if (isCostumeCard || isWinnerCard) {
      card.classList.add('display-card--inferno');
      if (isCostumeCard) {
        card.classList.add('display-card--costume');
      }
      if (isWinnerCard) {
        card.classList.add('display-card--winner');
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

  const setNoticeOverrideState = (state, { force = false } = {}) => {
    let signature = 'null';
    try {
      signature = JSON.stringify(state ?? null);
    } catch (error) {
      signature = 'null';
    }

    if (!force && signature === noticeOverrideSignature) {
      return;
    }

    noticeOverrideSignature = signature;
    noticeOverrideState = state && typeof state === 'object' ? state : null;
    updateNoticeOverrideContent();
    updateNoticeOverrideDisplay();
  };

  const setLayoutState = (state, { force = false } = {}) => {
    let signature = 'null';
    try {
      signature = JSON.stringify(state ?? null);
    } catch (error) {
      signature = 'null';
    }

    if (!force && signature === layoutSignature) {
      return;
    }

    layoutSignature = signature;
    layoutState = state && typeof state === 'object' ? state : { mode: 'idle' };
    applyLayoutState();
    renderActivityRail({ resetIndex: true });
    renderEntries({ resetIndex: false });
  };

  const setActivityState = (state, { force = false } = {}) => {
    let signature = 'null';
    try {
      signature = JSON.stringify(state ?? null);
    } catch (error) {
      signature = 'null';
    }

    if (!force && signature === activitySignature) {
      return;
    }

    activitySignature = signature;
    activityState = state && typeof state === 'object' ? state : {};
    renderActivityRail({ resetIndex: true });
  };

  setLayoutState(layoutState, { force: true });
  setActivityState(activityState, { force: true });
  setOverrideState(initialOverrideState ?? null, { force: true });
  setNoticeOverrideState(initialNoticeOverrideState ?? null, { force: true });

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
        event_override: newEventOverride,
        notice_override: newNoticeOverride,
        layout: newLayout,
        activity: newActivity,
      } = payload;

      updateCounts(costumeCount, karaokeCount);
      setLayoutState(newLayout || { mode: 'idle' });
      setActivityState(newActivity || {});
      setOverrideState(newEventOverride || newOverride || null);
      setNoticeOverrideState(newNoticeOverride || null);

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
