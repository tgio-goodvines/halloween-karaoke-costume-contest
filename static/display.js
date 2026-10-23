document.addEventListener('DOMContentLoaded', () => {
  const body = document.body;
  const shell = document.querySelector('[data-display-shell]');
  const bootstrap = document.getElementById('display-layout-data');
  if (!body || !shell || !bootstrap) return;

  const apiUrl = body.dataset.displayApi || '/api/display-data';
  const updatesUrl = body.dataset.displayUpdates || '';
  const elements = {
    costumeCount: document.querySelector('[data-costume-count]'),
    karaokeCount: document.querySelector('[data-karaoke-count]'),
    gameCount: document.querySelector('[data-game-count]'),
    gameStage: document.querySelector('[data-game-stage]'),
    gameImageWrap: document.querySelector('[data-game-image-wrap]'),
    gameImage: document.querySelector('[data-game-image]'),
    gameStatus: document.querySelector('[data-game-status]'),
    gameTitle: document.querySelector('[data-game-title]'),
    gamePrimary: document.querySelector('[data-game-primary]'),
    gameSecondary: document.querySelector('[data-game-secondary]'),
    gameFocusLabel: document.querySelector('[data-game-focus-label]'),
    gameFocusItems: document.querySelector('[data-game-focus-items]'),
    gameSpotlight: document.querySelector('[data-game-spotlight]'),
    gameFeature: document.querySelector('[data-game-feature]'),
    gameMetrics: document.querySelector('[data-game-metrics]'),
    gameSteps: document.querySelector('[data-game-steps]'),
    gameAction: document.querySelector('[data-game-action]'),
    gamePosition: document.querySelector('[data-game-position]'),
    gameProgress: document.querySelector('[data-game-progress]'),
    centerStage: document.querySelector('[data-center-stage]'),
    centerCard: document.querySelector('[data-center-card]'),
    centerBody: document.querySelector('[data-center-card] [data-fit-content]'),
    centerMode: document.querySelector('[data-center-mode]'),
    centerPosition: document.querySelector('[data-center-position]'),
    centerCategory: document.querySelector('[data-center-category]'),
    centerPrimary: document.querySelector('[data-center-primary]'),
    centerSecondary: document.querySelector('[data-center-secondary]'),
    centerTertiary: document.querySelector('[data-center-tertiary]'),
    centerFacts: document.querySelector('[data-center-facts]'),
    centerSteps: document.querySelector('[data-center-steps]'),
    centerAction: document.querySelector('[data-center-action]'),
    centerImageWrap: document.querySelector('[data-center-image-wrap]'),
    centerImage: document.querySelector('[data-center-image]'),
    centerCta: document.querySelector('[data-center-cta]'),
    centerScoreboard: document.querySelector('[data-center-scoreboard]'),
    centerLink: document.querySelector('[data-center-link]'),
    centerProgress: document.querySelector('[data-center-progress]'),
    ctaNetworkItem: document.querySelector('[data-cta-wifi-network-item]'),
    ctaNetwork: document.querySelector('[data-cta-wifi-network]'),
    ctaPasswordItem: document.querySelector('[data-cta-wifi-password-item]'),
    ctaPassword: document.querySelector('[data-cta-wifi-password]'),
    ctaSiteItem: document.querySelector('[data-cta-site-url-item]'),
    ctaSite: document.querySelector('[data-cta-site-url]'),
    karaokeExtra: document.querySelector('[data-karaoke-extra]'),
    karaokeCountdown: document.querySelector('[data-karaoke-countdown]'),
    karaokeLineup: document.querySelector('[data-karaoke-lineup]'),
    barStage: document.querySelector('[data-bar-stage]'),
    barQueue: document.querySelector('[data-bar-queue]'),
    barHeading: document.querySelector('[data-bar-heading]'),
    barImageWrap: document.querySelector('[data-bar-image-wrap]'),
    barImage: document.querySelector('[data-bar-image]'),
    barOrders: document.querySelector('[data-bar-orders]'),
    barOverflow: document.querySelector('[data-bar-overflow]'),
    barSummary: document.querySelector('[data-bar-summary]'),
    barPromotionsTop: document.querySelector('[data-bar-promotions-top]'),
    barPromotionsBottom: document.querySelector('[data-bar-promotions-bottom]'),
    barHistory: document.querySelector('[data-bar-history]'),
    barHistoryOrders: document.querySelector('[data-bar-history-orders]'),
    barAction: document.querySelector('[data-bar-action]'),
    barPickup: document.querySelector('[data-bar-pickup]'),
    readyNotice: document.querySelector('[data-ready-notice]'),
    readyName: document.querySelector('[data-ready-name]'),
    readyMessage: document.querySelector('[data-ready-message]'),
    readyDetails: document.querySelector('[data-ready-details]'),
    readyQueue: document.querySelector('[data-ready-queue]'),
    readyPickup: document.querySelector('[data-ready-pickup]'),
    music: document.querySelector('[data-dj-now-playing]'),
    djProgressWrap: document.querySelector('[data-dj-progress-wrap]'),
    djProgress: document.querySelector('[data-dj-progress]'),
    djTime: document.querySelector('[data-dj-time]'),
    djNext: document.querySelector('[data-dj-next]'),
    djNextTitle: document.querySelector('[data-dj-next-title]'),
  };

  let layout = {};
  try { layout = JSON.parse(bootstrap.textContent || '{}'); } catch (error) { console.error('Unable to parse display layout', error); }
  let centerIndex = 0;
  let centerEntryId = '';
  let centerRevision = -1;
  let centerTimer = null;
  let centerTimerEntryId = '';
  let gameIndex = 0;
  let gameEntryId = '';
  let gameTimer = null;
  let gameTimerEntryId = '';
  let gameRotationQueue = [];
  const gameDetailBags = new Map();
  let barPromotionIndex = 0;
  let barPromotionItemId = '';
  let barHistoryIndex = 0;
  let barHistoryItemId = '';
  let barRotationTimer = null;
  let barRotationTimerKey = '';
  let noticeTimer = null;
  let karaokeTimer = null;
  const regionSignatures = new Map();
  const mediaRequests = new WeakMap();

  const safeArray = (value) => (Array.isArray(value) ? value : []);
  const asObject = (value) => (value && typeof value === 'object' ? value : {});
  const shuffled = (items) => {
    const result = [...items];
    for (let index = result.length - 1; index > 0; index -= 1) {
      const target = Math.floor(Math.random() * (index + 1));
      [result[index], result[target]] = [result[target], result[index]];
    }
    return result;
  };

  const detailSelectionsForGame = (gameKey, candidates, count = 2) => {
    const candidateIds = candidates.map((entry) => String(entry.id || '')).filter(Boolean);
    if (!candidateIds.length) return [];
    let bag = safeArray(gameDetailBags.get(gameKey)).filter((id) => candidateIds.includes(id));
    const selected = [];
    while (selected.length < Math.min(count, candidateIds.length)) {
      if (!bag.length) bag = shuffled(candidateIds.filter((id) => id !== gameEntryId && !selected.includes(id)));
      if (!bag.length) bag = shuffled(candidateIds.filter((id) => !selected.includes(id)));
      if (!bag.length) break;
      const id = bag.shift();
      if (id && !selected.includes(id)) selected.push(id);
    }
    gameDetailBags.set(gameKey, bag);
    return selected;
  };

  const buildGameRotationQueue = (entries) => {
    const statuses = entries.filter((entry) => entry.entry_kind === 'live_status');
    const detailsByGame = new Map();
    entries.filter((entry) => entry.entry_kind !== 'live_status').forEach((entry) => {
      const key = String(entry.game_key || 'games');
      if (!detailsByGame.has(key)) detailsByGame.set(key, []);
      detailsByGame.get(key).push(entry);
    });
    const selectedIds = statuses.map((entry) => String(entry.id || '')).filter(Boolean);
    detailsByGame.forEach((candidates, gameKey) => {
      selectedIds.push(...detailSelectionsForGame(gameKey, candidates));
    });
    const queue = shuffled(selectedIds.filter((id) => id && id !== gameEntryId));
    if (queue.length > 1 && queue[0] === gameTimerEntryId) queue.push(queue.shift());
    return queue;
  };
  const mediaHelpers = window.HalloweenDisplayMedia || {};
  const mediaTreatmentFor = mediaHelpers.treatmentFor || ((entry) => (
    entry?.image_url && entry.media_treatment === 'foreground' ? 'foreground' : 'none'
  ));
  const centerFocusMode = mediaHelpers.centerFocusMode || (() => 'message');
  const gameFocusMode = mediaHelpers.gameFocusMode || (() => 'message');
  const mediaToneFor = mediaHelpers.toneFor || (() => 'feature');
  const signatureFor = mediaHelpers.signatureFor || ((value) => JSON.stringify(value));
  const shouldReplaceSource = mediaHelpers.shouldReplaceSource || ((current, requested) => current !== requested);
  const setHidden = (element, hidden) => {
    if (!element) return;
    if (hidden) element.setAttribute('hidden', '');
    else element.removeAttribute('hidden');
  };
  const setOptionalText = (element, value) => {
    if (!element) return;
    const text = value == null ? '' : String(value);
    element.textContent = text;
    setHidden(element, !text);
  };
  const renderRegionIfChanged = (name, value, renderer) => {
    const signature = signatureFor(value);
    if (regionSignatures.get(name) === signature) return false;
    regionSignatures.set(name, signature);
    renderer();
    return true;
  };
  const swapMedia = (image, wrap, requestedSource, { alt = '', onReady, onError } = {}) => {
    if (!image || !wrap) return;
    const requested = String(requestedSource || '');
    const current = String(image.dataset.displaySource || image.getAttribute('src') || '');
    if (!requested) {
      mediaRequests.delete(image);
      image.removeAttribute('src');
      delete image.dataset.displaySource;
      image.alt = '';
      setHidden(wrap, true);
      return;
    }
    if (!shouldReplaceSource(current, requested)) {
      image.alt = alt;
      setHidden(wrap, false);
      return;
    }
    const pendingRequest = mediaRequests.get(image);
    if (pendingRequest?.source === requested) return;

    const requestToken = {};
    mediaRequests.set(image, { token: requestToken, source: requested });
    const loader = new Image();
    let committed = false;
    const commit = async () => {
      if (committed) return;
      committed = true;
      if (typeof loader.decode === 'function') {
        try { await loader.decode(); } catch (error) { /* Loaded pixels remain usable. */ }
      }
      if (mediaRequests.get(image)?.token !== requestToken) return;
      image.src = requested;
      image.dataset.displaySource = requested;
      image.alt = alt;
      setHidden(wrap, false);
      mediaRequests.delete(image);
      if (typeof onReady === 'function') onReady();
    };
    loader.onload = commit;
    loader.onerror = () => {
      if (mediaRequests.get(image)?.token !== requestToken) return;
      mediaRequests.delete(image);
      if (!current) {
        setHidden(wrap, true);
        if (typeof onError === 'function') onError();
      }
    };
    loader.src = requested;
    if (loader.complete && loader.naturalWidth) commit();
  };
  const gameSecondaryText = (game) => {
    let secondary = game.secondary || '';
    if (game.deadline_at && game.deadline_prefix) {
      const deadline = new Date(game.deadline_at).getTime();
      if (Number.isFinite(deadline)) {
        const remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
        secondary = `${game.deadline_prefix} ${String(Math.floor(remaining / 60)).padStart(2, '0')}:${String(remaining % 60).padStart(2, '0')}`;
      }
    }
    return secondary;
  };
  const boundedSeconds = (value, fallback = 15) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? Math.min(30, Math.max(10, parsed)) : fallback;
  };
  const formatDuration = (seconds) => {
    const value = Math.max(0, Math.floor(Number(seconds) || 0));
    return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`;
  };

  const fitPanel = (panel) => {
    if (!panel || panel.hasAttribute('hidden')) return;
    panel.classList.remove('is-sparse', 'is-dense', 'is-ultra-dense');
    const fitContent = panel.querySelector('[data-fit-content]');
    const availableHeight = Math.max(1, panel.clientHeight);
    const contentHeight = fitContent ? Math.max(fitContent.scrollHeight, fitContent.getBoundingClientRect().height) : panel.scrollHeight;
    const contentOverflows = () => Boolean(
      fitContent && fitContent.clientHeight > 0 && fitContent.scrollHeight > fitContent.clientHeight + 2
    );
    if (contentHeight / availableHeight < 0.56) panel.classList.add('is-sparse');
    if (panel.scrollHeight > panel.clientHeight + 2 || contentOverflows()) {
      panel.classList.add('is-dense');
      if (panel !== elements.gameStage) panel.classList.add('is-ultra-dense');
      else {
        panel.getBoundingClientRect();
        if (panel.scrollHeight > panel.clientHeight + 2 || contentOverflows()) panel.classList.add('is-ultra-dense');
      }
    }
  };

  const fitTextRows = (rows, selector, minimumSizeFor) => {
    Array.from(rows || []).forEach((row) => {
      const copy = Array.from(row.querySelectorAll(selector));
      copy.forEach((child) => { child.style.fontSize = ''; });
      if (!copy.length || row.clientHeight <= 0 || row.scrollHeight <= row.clientHeight + 1) return;

      const minimumSizes = copy.map((child) => minimumSizeFor(child));
      const baseSizes = copy.map((child, index) => Number.parseFloat(window.getComputedStyle(child).fontSize) || minimumSizes[index]);
      const applyScale = (scale) => copy.forEach((child, index) => {
        child.style.fontSize = `${Math.max(minimumSizes[index], baseSizes[index] * scale)}px`;
      });
      let lower = 0.62;
      let upper = 1;
      applyScale(lower);
      if (row.scrollHeight > row.clientHeight + 1) return;
      for (let attempt = 0; attempt < 7; attempt += 1) {
        const candidate = (lower + upper) / 2;
        applyScale(candidate);
        if (row.scrollHeight <= row.clientHeight + 1) lower = candidate;
        else upper = candidate;
      }
      applyScale(lower);
    });
  };

  const fitStructuredDisplayRows = () => {
    const wideDisplay = window.innerWidth >= 901;
    if (elements.gameSpotlight && !elements.gameSpotlight.hasAttribute('hidden')) {
      fitTextRows(
        elements.gameSpotlight.children,
        'span, strong, small',
        (child) => (child.tagName === 'STRONG' ? (wideDisplay ? 16 : 12) : (wideDisplay ? 13 : 10)),
      );
    }
    [elements.barOrders, elements.barHistoryOrders].forEach((list) => {
      if (!list || list.hasAttribute('hidden')) return;
      fitTextRows(
        list.children,
        'strong, small, em',
        (child) => (child.tagName === 'STRONG' ? (wideDisplay ? 17 : 11) : (wideDisplay ? 14 : 10)),
      );
    });
    if (elements.centerScoreboard && !elements.centerScoreboard.hasAttribute('hidden')) {
      fitTextRows(
        elements.centerScoreboard.children,
        'strong, small',
        (child) => (child.tagName === 'STRONG' ? (wideDisplay ? 18 : 12) : (wideDisplay ? 15 : 10)),
      );
    }
    if (elements.centerBody && !elements.centerStage?.hasAttribute('hidden')) {
      fitTextRows(
        [elements.centerBody],
        '.display-pill, h2, .display-center-card__secondary, .display-center-card__link, .display-center-card__action, dt, dd, .display-action-steps li, .display-scoreboard li > span, .display-scoreboard li > strong, .display-karaoke-extra__countdown, .display-karaoke-extra li',
        (child) => {
          if (child.tagName === 'H2') return wideDisplay ? 34 : 20;
          if (child.matches('dd, .display-center-card__secondary, .display-center-card__link, .display-center-card__action')) return wideDisplay ? 19 : 12;
          return wideDisplay ? 15 : 10;
        },
      );
    }
  };

  const fitAll = () => requestAnimationFrame(() => {
    fitPanel(elements.gameStage);
    fitPanel(elements.centerStage);
    fitPanel(elements.barStage);
    fitPanel(elements.music);
    fitStructuredDisplayRows();
  });

  const startProgress = (element, seconds) => {
    if (!element) return;
    element.style.animation = 'none';
    element.offsetWidth;
    element.style.animation = `display-progress ${seconds}s linear forwards`;
  };

  const clearCenterRotationTimer = () => {
    if (centerTimer) window.clearTimeout(centerTimer);
    centerTimer = null;
    centerTimerEntryId = '';
  };

  const clearGameRotationTimer = () => {
    if (gameTimer) window.clearTimeout(gameTimer);
    gameTimer = null;
    gameTimerEntryId = '';
  };

  const clearBarRotationTimer = () => {
    if (barRotationTimer) window.clearTimeout(barRotationTimer);
    barRotationTimer = null;
    barRotationTimerKey = '';
  };

  const clearCenterExtras = () => {
    setHidden(elements.centerCta, true);
    setHidden(elements.centerScoreboard, true);
    setHidden(elements.centerLink, true);
    setHidden(elements.karaokeExtra, true);
    setHidden(elements.centerFacts, true);
    setHidden(elements.centerSteps, true);
    setHidden(elements.centerAction, true);
    if (elements.centerScoreboard) elements.centerScoreboard.innerHTML = '';
    if (elements.karaokeLineup) elements.karaokeLineup.innerHTML = '';
    if (elements.centerFacts) elements.centerFacts.innerHTML = '';
    if (elements.centerSteps) elements.centerSteps.innerHTML = '';
    if (karaokeTimer) window.clearInterval(karaokeTimer);
    karaokeTimer = null;
  };

  const renderScoreboard = (scoreboard) => {
    const safeScoreboard = asObject(scoreboard);
    const entries = safeArray(safeScoreboard.entries);
    const rows = safeScoreboard.show_all_entries ? entries : entries.slice(0, 3);
    if (!elements.centerScoreboard || !rows.length) return false;
    elements.centerScoreboard.innerHTML = '';
    rows.forEach((row, index) => {
      const item = document.createElement('li');
      const rank = document.createElement('span');
      const copy = document.createElement('div');
      const value = document.createElement('strong');
      rank.textContent = `#${row.rank || index + 1}`;
      copy.innerHTML = `<strong></strong><small></small>`;
      copy.querySelector('strong').textContent = row.name || '';
      copy.querySelector('small').textContent = row.detail || row.meta_label || '';
      value.textContent = row.value_label || '';
      item.append(rank, copy, value);
      elements.centerScoreboard.appendChild(item);
    });
    setHidden(elements.centerScoreboard, false);
    return true;
  };

  const renderCta = (entry) => {
    const details = asObject(entry.cta_details);
    const rows = [
      [elements.ctaNetworkItem, elements.ctaNetwork, details.wifi_network],
      [elements.ctaPasswordItem, elements.ctaPassword, details.wifi_password],
      [elements.ctaSiteItem, elements.ctaSite, details.site_url],
    ];
    let visible = false;
    rows.forEach(([item, valueElement, value]) => {
      if (valueElement) valueElement.textContent = value || '';
      setHidden(item, !value);
      visible = visible || Boolean(value);
    });
    setHidden(elements.centerCta, !visible);
  };

  const renderFacts = (container, facts, limit = 4) => {
    const entries = safeArray(facts).slice(0, limit);
    if (!container || !entries.length) return false;
    container.innerHTML = '';
    entries.forEach((fact) => {
      const item = document.createElement('div');
      const label = document.createElement('dt');
      const value = document.createElement('dd');
      label.textContent = fact.label || '';
      value.textContent = fact.value == null ? '' : String(fact.value);
      item.append(label, value);
      container.appendChild(item);
    });
    setHidden(container, false);
    return true;
  };

  const renderSteps = (container, steps, limit = 3) => {
    const entries = safeArray(steps).filter(Boolean).slice(0, limit);
    if (!container || !entries.length) return false;
    container.innerHTML = '';
    entries.forEach((step) => {
      const item = document.createElement('li');
      item.textContent = String(step);
      container.appendChild(item);
    });
    setHidden(container, false);
    return true;
  };

  const renderAction = (element, action) => {
    const safeAction = asObject(action);
    const label = safeAction.label || '';
    const url = safeAction.url || '';
    setOptionalText(element, label && url ? `${label} · ${url}` : (label || url));
  };

  const renderKaraokeExtra = (entry) => {
    const karaoke = asObject(entry.karaoke);
    const target = karaoke.countdown_target ? new Date(karaoke.countdown_target) : null;
    const lineup = safeArray(karaoke.lineup).slice(0, 3);
    if ((!target || Number.isNaN(target.getTime())) && !lineup.length) return;
    setHidden(elements.karaokeExtra, false);
    if (elements.karaokeLineup) {
      elements.karaokeLineup.innerHTML = '';
      lineup.forEach((singer, index) => {
        const item = document.createElement('li');
        item.textContent = `${index + 1}. ${singer.singer_label || singer.name || 'TBA'} · ${singer.song_title || 'Song TBA'}`;
        elements.karaokeLineup.appendChild(item);
      });
    }
    if (target && !Number.isNaN(target.getTime()) && elements.karaokeCountdown) {
      const tick = () => {
        const remaining = Math.max(0, Math.floor((target.getTime() - Date.now()) / 1000));
        const hours = Math.floor(remaining / 3600);
        const minutes = Math.floor((remaining % 3600) / 60);
        const seconds = remaining % 60;
        elements.karaokeCountdown.textContent = `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
      };
      tick();
      karaokeTimer = window.setInterval(tick, 1000);
    }
  };

  const overrideAsEntry = (override) => ({
    category: override.title || String(override.type || 'Spotlight').replaceAll('_', ' '),
    primary: override.highlight || override.title || 'Live spotlight',
    secondary: override.message || '',
    tertiary: safeArray(override.details).join(' · '),
    image_url: override.image_url || '',
    media_treatment: override.media_treatment || '',
    media_tone: override.media_tone || '',
    karaoke: override.karaoke,
    scoreboard: override.scoreboard,
    duration_seconds: 8,
    override_type: override.type || '',
  });

  const renderCenterEntry = (entry, { spotlight = false } = {}) => {
    const safeEntry = asObject(entry);
    const mediaTreatment = mediaTreatmentFor(safeEntry);
    const hasImage = mediaTreatment !== 'none';
    const hasForegroundMedia = mediaTreatment === 'foreground';
    const focusMode = centerFocusMode(safeEntry);
    clearCenterExtras();
    if (elements.centerStage) elements.centerStage.dataset.focusMode = focusMode;
    elements.centerStage?.classList.toggle('is-spotlight', spotlight);
    elements.centerStage?.classList.toggle('is-scoreboard', Boolean(asObject(safeEntry.scoreboard).entries));
    elements.centerStage?.classList.toggle('has-media', hasImage);
    elements.centerStage?.classList.remove('has-background-media');
    elements.centerStage?.classList.toggle('has-foreground-media', hasForegroundMedia);
    if (elements.centerStage) elements.centerStage.dataset.mediaTone = hasImage ? mediaToneFor(safeEntry) : '';
    ['access', 'action', 'profile', 'status', 'result', 'scoreboard', 'announcement'].forEach((kind) => {
      elements.centerStage?.classList.toggle(`is-${kind}`, safeEntry.kind === kind);
    });
    elements.centerStage?.classList.remove('is-transitioning');
    if (elements.centerCategory) elements.centerCategory.textContent = safeEntry.category || 'Live display';
    if (elements.centerPrimary) elements.centerPrimary.textContent = safeEntry.primary || 'Display standby';
    setOptionalText(
      elements.centerSecondary,
      focusMode === 'message' ? (safeEntry.secondary || safeEntry.tertiary || '') : '',
    );
    setOptionalText(elements.centerTertiary, '');
    if (elements.centerImage && elements.centerImageWrap) {
      if (hasForegroundMedia && safeEntry.image_url) {
        elements.centerImageWrap.setAttribute('aria-hidden', 'false');
        swapMedia(elements.centerImage, elements.centerImageWrap, safeEntry.image_url, {
          alt: safeEntry.primary ? `${safeEntry.primary} image` : 'Display image',
          onReady: fitAll,
          onError: () => {
            elements.centerStage?.classList.remove('has-media', 'has-background-media', 'has-foreground-media');
            fitAll();
          },
        });
      } else {
        swapMedia(elements.centerImage, elements.centerImageWrap, '');
      }
    }
    if (focusMode === 'cta') renderCta(safeEntry);
    if (focusMode === 'facts') renderFacts(elements.centerFacts, safeEntry.facts, 2);
    if (focusMode === 'steps') renderSteps(elements.centerSteps, safeEntry.steps, 2);
    if (focusMode === 'scoreboard') renderScoreboard(safeEntry.scoreboard);
    if (focusMode === 'link' && safeEntry.link) {
      elements.centerLink.textContent = safeEntry.link_label ? `${safeEntry.link_label}: ${safeEntry.link}` : safeEntry.link;
      setHidden(elements.centerLink, false);
    }
    if (focusMode === 'karaoke') renderKaraokeExtra(safeEntry);
    if (focusMode === 'action') renderAction(elements.centerAction, safeEntry.action);
    fitAll();
  };

  const selectCenterIndex = (center) => {
    const entries = safeArray(center.entries);
    if (!entries.length) return 0;
    const pinnedId = center.pinned_card_id || '';
    if (pinnedId) {
      const pinnedIndex = entries.findIndex((entry) => String(entry.id || '') === String(pinnedId));
      if (pinnedIndex >= 0) return pinnedIndex;
    }
    if (Number(center.revision) !== centerRevision) {
      centerRevision = Number(center.revision) || 0;
      return Math.abs(Number(center.index) || 0) % entries.length;
    }
    const preserved = entries.findIndex((entry) => String(entry.id || '') === centerEntryId);
    return preserved >= 0 ? preserved : Math.min(centerIndex, entries.length - 1);
  };

  const scheduleCenterRotation = () => {
    const center = asObject(layout.center);
    const entries = safeArray(center.entries);
    if (center.override || center.paused || center.pinned_card_id || entries.length <= 1) {
      clearCenterRotationTimer();
      if (elements.centerProgress) elements.centerProgress.style.animation = 'none';
      return;
    }
    const entry = entries[centerIndex] || {};
    const entryId = String(entry.id || '');
    if (centerTimer && centerTimerEntryId === entryId) return;
    clearCenterRotationTimer();
    const seconds = boundedSeconds(entry.duration_seconds, boundedSeconds(center.interval_seconds));
    startProgress(elements.centerProgress, seconds);
    centerTimerEntryId = entryId;
    centerTimer = window.setTimeout(() => {
      centerTimer = null;
      centerTimerEntryId = '';
      const currentEntries = safeArray(asObject(layout.center).entries);
      if (currentEntries.length <= 1) {
        renderCenter();
        return;
      }
      const currentIndex = currentEntries.findIndex((item) => String(item.id || '') === centerEntryId);
      centerIndex = ((currentIndex >= 0 ? currentIndex : centerIndex) + 1) % currentEntries.length;
      const latestEntries = safeArray(asObject(layout.center).entries);
      if (!latestEntries.length) {
        renderCenter();
        return;
      }
      centerIndex %= latestEntries.length;
      centerEntryId = String(latestEntries[centerIndex]?.id || '');
      renderCenterEntry(latestEntries[centerIndex]);
      if (elements.centerPosition) elements.centerPosition.textContent = `${centerIndex + 1} of ${latestEntries.length}`;
      scheduleCenterRotation();
    }, seconds * 1000);
  };

  const renderCenter = () => {
    const center = asObject(layout.center);
    const entries = safeArray(center.entries);
    const override = asObject(center.override);
    if (Object.keys(override).length) {
      if (elements.centerMode) elements.centerMode.textContent = 'Host spotlight';
      if (elements.centerPosition) elements.centerPosition.textContent = '';
      renderCenterEntry(overrideAsEntry(override), { spotlight: true });
      clearCenterRotationTimer();
      return;
    }
    centerIndex = selectCenterIndex(center);
    const entry = entries[centerIndex] || { category: 'Standby', primary: 'The live display is ready.' };
    centerEntryId = String(entry.id || '');
    if (elements.centerMode) elements.centerMode.textContent = center.pinned_card_id ? 'Pinned card' : (center.paused ? 'Rotation paused' : 'Live rotation');
    if (elements.centerPosition) elements.centerPosition.textContent = entries.length ? `${centerIndex + 1} of ${entries.length}` : '';
    renderCenterEntry(entry);
    scheduleCenterRotation();
  };

  const renderGameEntry = (entry, count) => {
    const game = asObject(entry);
    const focusMode = gameFocusMode(game);
    const presentation = ['signup', 'recruitment', 'active', 'clue', 'tally', 'leaderboard', 'prompt', 'voting', 'response', 'reveal', 'result'].includes(game.presentation)
      ? game.presentation
      : (game.phase === 'ended' ? 'result' : (game.phase === 'active' ? 'active' : 'signup'));
    if (elements.gameStage) elements.gameStage.dataset.presentation = presentation;
    elements.gameStage?.classList.remove('has-background-media');
    if (elements.gameStatus) elements.gameStatus.textContent = game.status_label || game.phase || '';
    if (elements.gameTitle) elements.gameTitle.textContent = game.title || 'Party Games';
    setOptionalText(elements.gamePrimary, ['choices', 'spotlight'].includes(focusMode) ? '' : (game.primary || 'Follow the live game status here.'));
    setOptionalText(elements.gameSecondary, focusMode === 'message' && game.deadline_at ? gameSecondaryText(game) : '');
    setOptionalText(elements.gameFocusLabel, ['choices', 'spotlight', 'feature'].includes(focusMode) ? (game.focus_label || 'Live focus') : '');
    setOptionalText(elements.gameFeature, focusMode === 'feature' ? (game.feature_text || '') : '');
    if (elements.gameFocusItems) {
      elements.gameFocusItems.innerHTML = '';
      safeArray(game.focus_items).filter(Boolean).slice(0, focusMode === 'choices' ? 3 : 0).forEach((focusItem) => {
        const item = document.createElement('li');
        item.textContent = String(focusItem);
        elements.gameFocusItems.appendChild(item);
      });
      setHidden(elements.gameFocusItems, !elements.gameFocusItems.children.length);
    }
    if (elements.gameSpotlight) {
      elements.gameSpotlight.innerHTML = '';
      safeArray(game.spotlight_rows).slice(0, focusMode === 'spotlight' ? 3 : 0).forEach((spotlightRow) => {
        const row = asObject(spotlightRow);
        const item = document.createElement('div');
        const label = document.createElement('span');
        const value = document.createElement('strong');
        label.textContent = row.label || '';
        value.textContent = row.value || '';
        item.append(label, value);
        if (row.detail) {
          const detail = document.createElement('small');
          detail.textContent = row.detail;
          item.append(detail);
        }
        elements.gameSpotlight.appendChild(item);
      });
      setHidden(elements.gameSpotlight, !elements.gameSpotlight.children.length);
    }
    const metrics = safeArray(game.metrics).slice(0, 2);
    const footerMode = focusMode === 'metrics' ? 'metrics' : (focusMode === 'action' ? 'action' : 'none');
    if (elements.gameStage) elements.gameStage.dataset.footerMode = footerMode;
    if (elements.gameMetrics) {
      elements.gameMetrics.innerHTML = '';
      metrics.forEach((metric) => {
        const item = document.createElement('div');
        const value = document.createElement('strong');
        const label = document.createElement('span');
        value.textContent = metric.value == null ? '' : String(metric.value);
        label.textContent = metric.label || '';
        item.append(value, label);
        elements.gameMetrics.appendChild(item);
      });
      setHidden(elements.gameMetrics, footerMode !== 'metrics' || !elements.gameMetrics.children.length);
    }
    setHidden(elements.gameSteps, true);
    if (elements.gameSteps) elements.gameSteps.innerHTML = '';
    setOptionalText(elements.gameAction, footerMode === 'action' ? (game.action_label || '') : '');
    if (elements.gamePosition) elements.gamePosition.textContent = count > 1 ? `Game ${gameIndex + 1} of ${count}` : 'Game live';
    if (elements.gameProgress) elements.gameProgress.textContent = count > 1 ? 'Rotating' : 'Pinned';
    gameEntryId = String(game.id || '');
    fitAll();
  };

  const renderGames = () => {
    const games = asObject(layout.games);
    const entries = safeArray(games.entries);
    const visible = Boolean(games.visible && entries.length);
    setHidden(elements.gameStage, !visible);
    shell.classList.toggle('has-games', visible);
    if (!visible) {
      clearGameRotationTimer();
      return;
    }
    const validIds = new Set(entries.map((entry) => String(entry.id || '')).filter(Boolean));
    gameRotationQueue = gameRotationQueue.filter((id) => validIds.has(id) && id !== gameEntryId);
    let preserved = entries.findIndex((entry) => String(entry.id || '') === gameEntryId);
    if (preserved < 0) {
      gameRotationQueue = buildGameRotationQueue(entries);
      const latestStatus = entries.find((entry) => entry.entry_kind === 'live_status');
      gameEntryId = String(latestStatus?.id || gameRotationQueue.shift() || entries[0]?.id || '');
      gameRotationQueue = gameRotationQueue.filter((id) => id !== gameEntryId);
      preserved = entries.findIndex((entry) => String(entry.id || '') === gameEntryId);
    }
    gameIndex = Math.max(0, preserved);
    renderGameEntry(entries[gameIndex], entries.length);
    if (entries.length > 1 && !games.pinned_game_key) {
      const entryId = String(entries[gameIndex]?.id || '');
      if (gameTimer && gameTimerEntryId === entryId) return;
      clearGameRotationTimer();
      const seconds = boundedSeconds(games.interval_seconds, 20);
      gameTimerEntryId = entryId;
      gameTimer = window.setTimeout(() => {
        gameTimer = null;
        gameTimerEntryId = '';
        const latestEntries = safeArray(asObject(layout.games).entries);
        if (!latestEntries.length) {
          renderGames();
          return;
        }
        if (!gameRotationQueue.length) gameRotationQueue = buildGameRotationQueue(latestEntries);
        gameEntryId = gameRotationQueue.shift() || String(latestEntries[0]?.id || '');
        gameIndex = Math.max(0, latestEntries.findIndex((entry) => String(entry.id || '') === gameEntryId));
        renderGames();
      }, seconds * 1000);
    } else clearGameRotationTimer();
  };

  const scheduleNoticeRefresh = (notice) => {
    if (noticeTimer) window.clearTimeout(noticeTimer);
    noticeTimer = null;
    const expiresAt = notice?.expires_at ? new Date(notice.expires_at).getTime() : 0;
    if (expiresAt > Date.now()) noticeTimer = window.setTimeout(fetchLatest, Math.max(100, expiresAt - Date.now() + 100));
  };

  const rotationWindow = (items, startIndex, count) => {
    const entries = safeArray(items);
    if (!entries.length || count <= 0) return [];
    const length = Math.min(entries.length, count);
    return Array.from({ length }, (_, offset) => entries[(startIndex + offset) % entries.length]);
  };

  const preserveRotationIndex = (items, currentId, fallbackIndex) => {
    const entries = safeArray(items);
    if (!entries.length) return 0;
    const preserved = entries.findIndex((item) => String(item.id || '') === String(currentId || ''));
    return preserved >= 0 ? preserved : Math.min(fallbackIndex, entries.length - 1);
  };

  const renderPromotionCards = (container, promotions) => {
    if (!container) return;
    container.replaceChildren();
    safeArray(promotions).forEach((promotion) => {
      const card = document.createElement('article');
      card.className = 'display-bar-promotion';
      const label = document.createElement('span');
      label.textContent = `${promotion.category_label || 'Menu'} · ${promotion.availability_label || 'Available tonight'}`;
      const name = document.createElement('strong');
      name.textContent = promotion.name || 'Tonight\'s menu';
      const description = document.createElement('p');
      description.textContent = promotion.description || 'Browse the full menu from your phone.';
      card.append(label, name, description);
      container.append(card);
    });
    container.style.setProperty('--bar-promotion-count', String(Math.max(1, container.children.length)));
    setHidden(container, !container.children.length);
  };

  const renderCompletedHistory = (completedOrders, visible, capacity = 3) => {
    const orders = safeArray(completedOrders);
    setHidden(elements.barHistory, !visible || !orders.length);
    if (!visible || !orders.length || !elements.barHistoryOrders) return;
    elements.barHistoryOrders.replaceChildren();
    rotationWindow(orders, barHistoryIndex, capacity).forEach((order) => {
      const item = document.createElement('li');
      item.className = order.picked_up ? 'is-picked-up' : 'is-ready';
      const dot = document.createElement('span');
      const copy = document.createElement('div');
      const name = document.createElement('strong');
      const drink = document.createElement('small');
      const status = document.createElement('em');
      name.textContent = order.name || 'Guest';
      drink.textContent = order.drink || 'Drink';
      status.textContent = order.picked_up
        ? `Picked up${order.picked_up_label ? ` · ${order.picked_up_label}` : ''}`
        : `Ready · ${order.completed_label || 'Tonight'}`;
      copy.append(name, drink);
      item.append(dot, copy, status);
      elements.barHistoryOrders.append(item);
    });
  };

  const scheduleBarRotation = (bar, hasNotice, hasActiveQueue, promotionSlots, historySlots) => {
    const promotions = safeArray(bar.promotion_items);
    const completedOrders = safeArray(bar.completed_orders);
    const rotatesPromotions = promotionSlots > 0 && promotions.length > promotionSlots;
    const rotatesHistory = historySlots > 0 && completedOrders.length > historySlots;
    if (hasNotice || (!rotatesPromotions && !rotatesHistory)) {
      clearBarRotationTimer();
      return;
    }
    const key = [
      hasActiveQueue ? 'queue' : 'idle',
      barPromotionItemId,
      barHistoryItemId,
      promotions.map((item) => item.id).join(','),
      completedOrders.map((item) => item.id).join(','),
    ].join(':');
    if (barRotationTimer && barRotationTimerKey === key) return;
    clearBarRotationTimer();
    barRotationTimerKey = key;
    const seconds = boundedSeconds(bar.promotion_interval_seconds, 20);
    barRotationTimer = window.setTimeout(() => {
      barRotationTimer = null;
      barRotationTimerKey = '';
      const latestBar = asObject(layout.bar);
      const latestPromotions = safeArray(latestBar.promotion_items);
      const latestHistory = safeArray(latestBar.completed_orders);
      if (latestPromotions.length) barPromotionIndex = (barPromotionIndex + 1) % latestPromotions.length;
      if (latestHistory.length) barHistoryIndex = (barHistoryIndex + 1) % latestHistory.length;
      barPromotionItemId = String(latestPromotions[barPromotionIndex]?.id || '');
      barHistoryItemId = String(latestHistory[barHistoryIndex]?.id || '');
      renderBar();
    }, seconds * 1000);
  };

  const renderBarBackground = (imageUrl) => {
    elements.barStage?.classList.remove('has-background-media');
    if (elements.barImage && elements.barImageWrap) swapMedia(elements.barImage, elements.barImageWrap, '');
  };

  const renderBar = () => {
    const bar = asObject(layout.bar);
    const notice = asObject(bar.notice);
    const visible = Boolean(bar.visible);
    setHidden(elements.barStage, !visible);
    shell.classList.toggle('has-bar', visible);
    if (!visible) {
      elements.barStage?.classList.remove('is-ready', 'is-idle', 'has-history');
      clearBarRotationTimer();
      renderBarBackground('');
      return;
    }
    const hasNotice = Object.keys(notice).length > 0;
    const activeOrders = safeArray(bar.orders);
    const promotions = safeArray(bar.promotion_items);
    const completedOrders = safeArray(bar.completed_orders);
    const hasActiveQueue = activeOrders.length > 0;
    const hasHistory = completedOrders.length > 0;
    const promotionSlots = hasActiveQueue || hasHistory ? 0 : 1;
    const historySlots = hasActiveQueue ? 0 : 3;
    elements.barStage?.classList.toggle('is-idle', !hasNotice && !hasActiveQueue);
    elements.barStage?.classList.toggle('has-history', !hasNotice && !hasActiveQueue && hasHistory);
    if (elements.barStage) elements.barStage.dataset.presentation = hasNotice ? 'notice' : (hasActiveQueue ? 'queue' : 'idle');
    setHidden(elements.readyNotice, !hasNotice);
    setHidden(elements.barQueue, hasNotice);
    if (hasNotice) {
      clearBarRotationTimer();
      if (elements.readyName) elements.readyName.textContent = notice.highlight || 'Guest';
      if (elements.readyMessage) elements.readyMessage.textContent = notice.message || 'Your drink is ready at the bar.';
      if (elements.readyQueue) {
        elements.readyQueue.textContent = '';
        setHidden(elements.readyQueue, true);
      }
      setOptionalText(elements.readyPickup, '');
      if (elements.readyDetails) {
        elements.readyDetails.innerHTML = '';
        setHidden(elements.readyDetails, true);
      }
      elements.barStage?.classList.add('is-ready');
      renderBarBackground('');
      scheduleNoticeRefresh(notice);
    } else {
      elements.barStage?.classList.remove('is-ready');
      barPromotionIndex = preserveRotationIndex(promotions, barPromotionItemId, barPromotionIndex);
      barHistoryIndex = preserveRotationIndex(completedOrders, barHistoryItemId, barHistoryIndex);
      barPromotionItemId = String(promotions[barPromotionIndex]?.id || '');
      barHistoryItemId = String(completedOrders[barHistoryIndex]?.id || '');
      if (elements.barHeading) {
        elements.barHeading.textContent = hasActiveQueue
          ? `Bar queue · ${Number(bar.active_count) || 0}`
          : (hasHistory ? `Completed · ${completedOrders.length}` : (promotions.length ? 'Tonight\'s menu' : 'Bar standby'));
      }
      if (elements.barOrders) {
        elements.barOrders.replaceChildren();
        activeOrders.forEach((order) => {
          const item = document.createElement('li');
          item.className = order.status === 'in_progress' ? 'is-mixing' : '';
          const dot = document.createElement('span');
          const copy = document.createElement('div');
          const status = document.createElement('em');
          copy.innerHTML = '<strong></strong><small></small>';
          copy.querySelector('strong').textContent = `${order.position ? `#${order.position} · ` : ''}${order.name || 'Guest'}`;
          copy.querySelector('small').textContent = order.drink || 'Drink';
          status.textContent = order.estimated_ready_label ? `${order.status_label} · ${order.estimated_ready_label}` : order.status_label || '';
          item.append(dot, copy, status);
          elements.barOrders.appendChild(item);
        });
        setHidden(elements.barOrders, !hasActiveQueue);
      }
      const overflow = Number(bar.overflow_count) || 0;
      setOptionalText(elements.barOverflow, hasActiveQueue && overflow ? `+${overflow} more active order${overflow === 1 ? '' : 's'}` : '');
      const summary = asObject(bar.summary);
      renderFacts(elements.barSummary, [
        { label: 'Mixing', value: Number(summary.mixing_count) || 0 },
        { label: 'Waiting', value: Number(summary.waiting_count) || 0 },
        { label: 'Avg prep', value: summary.average_prep_label || 'About 8 min' },
        { label: 'Drinks', value: Number(summary.available_drink_count) || 0 },
      ]);
      setHidden(elements.barSummary, true);

      const promotionWindow = rotationWindow(promotions, barPromotionIndex, promotionSlots);
      const topPromotionCount = Math.min(1, promotionWindow.length);
      renderPromotionCards(elements.barPromotionsTop, promotionWindow.slice(0, topPromotionCount));
      renderPromotionCards(elements.barPromotionsBottom, promotionWindow.slice(topPromotionCount));
      renderCompletedHistory(completedOrders, !hasActiveQueue && hasHistory, historySlots);

      renderBarBackground('');
      if (!hasActiveQueue && !hasHistory && promotions.length) renderAction(elements.barAction, bar.action);
      else setOptionalText(elements.barAction, '');
      setOptionalText(elements.barPickup, '');
      scheduleBarRotation(bar, false, hasActiveQueue, promotionSlots, historySlots);
    }
    fitAll();
  };

  const renderMusic = () => {
    const music = asObject(layout.music);
    const visible = Boolean(music.visible);
    setHidden(elements.music, !visible);
    shell.classList.toggle('has-music', visible);
    if (!visible) return;
    const dj = asObject(music.state);
    const receiver = asObject(dj.receiver);
    const song = asObject(music.current_song);
    const durationSeconds = Math.max(0, Math.floor((Number(song.duration_ms) || 0) / 1000));
    const position = Math.max(0, Number(receiver.playback_position_seconds) || 0);
    if (durationSeconds && elements.djProgress && elements.djProgressWrap) {
      elements.djProgress.style.width = `${Math.min(100, (position / durationSeconds) * 100)}%`;
      elements.djTime.textContent = `${formatDuration(position)} / ${formatDuration(durationSeconds)}`;
      setHidden(elements.djProgressWrap, false);
    } else {
      setHidden(elements.djProgressWrap, true);
      if (elements.djTime) elements.djTime.textContent = '';
    }
    const nextSong = asObject(music.next_song);
    if (nextSong.title && elements.djNext && elements.djNextTitle) {
      elements.djNextTitle.textContent = `${nextSong.title}${nextSong.artist ? ` · ${nextSong.artist}` : ''}`;
      setHidden(elements.djNext, false);
    } else setHidden(elements.djNext, true);
    fitAll();
  };

  const renderLayout = () => {
    const header = asObject(layout.header);
    const density = ['compact', 'standard', 'large'].includes(layout.density) ? layout.density : 'standard';
    renderRegionIfChanged('density', density, () => {
      body.classList.remove('display-density--compact', 'display-density--standard', 'display-density--large');
      body.classList.add(`display-density--${density}`);
    });
    renderRegionIfChanged('header', header, () => {
      if (elements.costumeCount) elements.costumeCount.textContent = Number(header.costume_count) || 0;
      if (elements.karaokeCount) elements.karaokeCount.textContent = Number(header.karaoke_count) || 0;
      if (elements.gameCount) elements.gameCount.textContent = Number(header.game_count) || 0;
    });
    const gamesChanged = renderRegionIfChanged('games', asObject(layout.games), renderGames);
    const barChanged = renderRegionIfChanged('bar', asObject(layout.bar), renderBar);
    const musicChanged = renderRegionIfChanged('music', asObject(layout.music), renderMusic);
    const centerChanged = renderRegionIfChanged('center', asObject(layout.center), renderCenter);
    if (gamesChanged || barChanged || musicChanged || centerChanged) fitAll();
  };

  const fetchLatest = async () => {
    try {
      const response = await fetch(apiUrl, { cache: 'no-store', credentials: 'same-origin' });
      if (!response.ok) throw new Error(`Display refresh failed (${response.status})`);
      const payload = await response.json();
      if (payload.layout && typeof payload.layout === 'object') {
        layout = payload.layout;
        renderLayout();
      }
    } catch (error) { console.error('Unable to refresh live display', error); }
  };

  const startEventStream = () => {
    if (!updatesUrl || typeof EventSource !== 'function') return;
    let retryTimer = null;
    let retryDelay = 2000;
    let source = null;
    const connect = () => {
      if (source) source.close();
      source = new EventSource(updatesUrl);
      source.onopen = () => { retryDelay = 2000; };
      source.onmessage = fetchLatest;
      source.onerror = () => {
        source.close();
        retryTimer = window.setTimeout(connect, retryDelay);
        retryDelay = Math.min(30000, Math.max(4000, retryDelay * 1.5));
      };
    };
    connect();
    window.addEventListener('beforeunload', () => {
      if (retryTimer) window.clearTimeout(retryTimer);
      if (source) source.close();
    });
  };

  if (typeof ResizeObserver === 'function') new ResizeObserver(fitAll).observe(shell);
  renderLayout();
  if (document.fonts?.ready) document.fonts.ready.then(fitAll);
  fetchLatest();
  window.setInterval(fetchLatest, 30000);
  window.setInterval(() => {
    const entry = safeArray(asObject(layout.games).entries).find((item) => String(item.id || '') === gameEntryId);
    if (entry) {
      const focusMode = gameFocusMode(entry);
      setOptionalText(elements.gameSecondary, focusMode === 'message' && entry.deadline_at ? gameSecondaryText(entry) : '');
    }
  }, 1000);
  startEventStream();
});
