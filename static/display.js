document.addEventListener('DOMContentLoaded', () => {
  const dataElement = document.getElementById('entries-data');
  const overrideElement = document.getElementById('override-data');
  const card = document.querySelector('[data-display-card]');
  const emptyState = document.querySelector('[data-empty-state]');
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

  let karaokeCountdownTimerId = null;
  let karaokeCountdownTarget = null;
  let karaokeRotatorPanels = [];
  let karaokeRotatorIndex = 0;
  let karaokeRotatorTimerId = null;
  let karaokeRotatorResizeHandler = null;
  const KARAOKE_ROTATOR_INTERVAL = 8000;

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
        'display-override__card--winner'
      );
    }

    const titleText = overrideState && overrideState.title ? overrideState.title : '';
    const highlightText = overrideState && overrideState.highlight ? overrideState.highlight : '';
    const messageText = overrideState && overrideState.message ? overrideState.message : '';
    const details = overrideState && Array.isArray(overrideState.details) ? overrideState.details : [];
    const overrideType = overrideState && overrideState.type ? String(overrideState.type) : '';
    const isKaraokeOverride = Boolean(overrideType === 'karaoke_start' && karaokeOverrideElement);
    const isContestStartOverride = overrideType === 'contest_start';
    const isContestWinnerOverride = overrideType === 'winner';

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

      if (overrideCardElement && (isContestStartOverride || isContestWinnerOverride)) {
        overrideCardElement.classList.add('display-override__card--inferno');
        if (isContestStartOverride) {
          overrideCardElement.classList.add('display-override__card--contest');
        }
        if (isContestWinnerOverride) {
          overrideCardElement.classList.add('display-override__card--winner');
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

    card.classList.remove('display-card--inferno', 'display-card--costume', 'display-card--winner');

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
