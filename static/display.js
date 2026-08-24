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
    gameMetrics: document.querySelector('[data-game-metrics]'),
    gameSteps: document.querySelector('[data-game-steps]'),
    gameAction: document.querySelector('[data-game-action]'),
    gamePosition: document.querySelector('[data-game-position]'),
    gameProgress: document.querySelector('[data-game-progress]'),
    centerStage: document.querySelector('[data-center-stage]'),
    centerCard: document.querySelector('[data-center-card]'),
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
    barFeature: document.querySelector('[data-bar-feature]'),
    barFeatureName: document.querySelector('[data-bar-feature-name]'),
    barFeatureDescription: document.querySelector('[data-bar-feature-description]'),
    barAction: document.querySelector('[data-bar-action]'),
    barPickup: document.querySelector('[data-bar-pickup]'),
    readyNotice: document.querySelector('[data-ready-notice]'),
    readyImageWrap: document.querySelector('[data-ready-image-wrap]'),
    readyImage: document.querySelector('[data-ready-image]'),
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
  let centerTransitionTimer = null;
  let gameIndex = 0;
  let gameEntryId = '';
  let gameTimer = null;
  let gameTimerEntryId = '';
  let noticeTimer = null;
  let karaokeTimer = null;

  const safeArray = (value) => (Array.isArray(value) ? value : []);
  const asObject = (value) => (value && typeof value === 'object' ? value : {});
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
  const boundedSeconds = (value, fallback = 8) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? Math.min(30, Math.max(4, parsed)) : fallback;
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
    if (panel.scrollHeight > panel.clientHeight + 2 || contentOverflows()) panel.classList.add('is-dense');
    if (panel.scrollHeight > panel.clientHeight + 2 || contentOverflows()) panel.classList.add('is-ultra-dense');
  };
  const fitAll = () => requestAnimationFrame(() => {
    fitPanel(elements.gameStage);
    fitPanel(elements.centerStage);
    fitPanel(elements.barStage);
    fitPanel(elements.music);
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
    const rows = safeArray(asObject(scoreboard).entries).slice(0, 6);
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
    const lineup = safeArray(karaoke.lineup).slice(0, 4);
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
    karaoke: override.karaoke,
    duration_seconds: 8,
    override_type: override.type || '',
  });

  const renderCenterEntry = (entry, { spotlight = false } = {}) => {
    const safeEntry = asObject(entry);
    clearCenterExtras();
    elements.centerStage?.classList.toggle('is-spotlight', spotlight);
    elements.centerStage?.classList.toggle('is-scoreboard', Boolean(asObject(safeEntry.scoreboard).entries));
    elements.centerStage?.classList.toggle('has-media', Boolean(safeEntry.image_url));
    ['access', 'action', 'profile', 'status', 'result', 'scoreboard', 'announcement'].forEach((kind) => {
      elements.centerStage?.classList.toggle(`is-${kind}`, safeEntry.kind === kind);
    });
    elements.centerStage?.classList.remove('is-transitioning');
    if (elements.centerCategory) elements.centerCategory.textContent = safeEntry.category || 'Live display';
    if (elements.centerPrimary) elements.centerPrimary.textContent = safeEntry.primary || 'Display standby';
    if (elements.centerSecondary) elements.centerSecondary.textContent = safeEntry.secondary || '';
    setOptionalText(elements.centerTertiary, safeEntry.tertiary || '');
    if (elements.centerImage && elements.centerImageWrap) {
      if (safeEntry.image_url) {
        elements.centerImage.src = safeEntry.image_url;
        elements.centerImage.alt = safeEntry.primary ? `${safeEntry.primary} image` : 'Display image';
        setHidden(elements.centerImageWrap, false);
      } else {
        elements.centerImage.removeAttribute('src');
        elements.centerImage.alt = '';
        setHidden(elements.centerImageWrap, true);
      }
    }
    if (safeEntry.cta) renderCta(safeEntry);
    renderFacts(elements.centerFacts, safeEntry.facts);
    renderSteps(elements.centerSteps, safeEntry.steps);
    renderScoreboard(safeEntry.scoreboard);
    if (safeEntry.link) {
      elements.centerLink.textContent = safeEntry.link_label ? `${safeEntry.link_label}: ${safeEntry.link}` : safeEntry.link;
      setHidden(elements.centerLink, false);
    }
    if (safeEntry.karaoke) renderKaraokeExtra(safeEntry);
    renderAction(elements.centerAction, safeEntry.action);
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
      elements.centerStage?.classList.add('is-transitioning');
      centerTransitionTimer = window.setTimeout(() => {
        centerTransitionTimer = null;
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
      }, 280);
    }, seconds * 1000);
  };

  const renderCenter = () => {
    const center = asObject(layout.center);
    const entries = safeArray(center.entries);
    const override = asObject(center.override);
    const revisionChanged = Number(center.revision) !== centerRevision;
    if (centerTransitionTimer && !Object.keys(override).length && !center.paused && !center.pinned_card_id && !revisionChanged) return;
    if (centerTransitionTimer) {
      window.clearTimeout(centerTransitionTimer);
      centerTransitionTimer = null;
      elements.centerStage?.classList.remove('is-transitioning');
    }
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
    if (elements.gameImage && elements.gameImageWrap) {
      if (game.image_url) {
        elements.gameImage.src = game.image_url;
        elements.gameImage.alt = `${game.title || 'Party game'} illustration`;
        elements.gameImage.onerror = () => setHidden(elements.gameImageWrap, true);
        setHidden(elements.gameImageWrap, false);
      } else {
        elements.gameImage.removeAttribute('src');
        elements.gameImage.alt = '';
        setHidden(elements.gameImageWrap, true);
      }
    }
    if (elements.gameStatus) elements.gameStatus.textContent = game.status_label || game.phase || '';
    if (elements.gameTitle) elements.gameTitle.textContent = game.title || 'Party Games';
    if (elements.gamePrimary) elements.gamePrimary.textContent = game.primary || '';
    if (elements.gameSecondary) elements.gameSecondary.textContent = game.secondary || '';
    if (elements.gameMetrics) {
      elements.gameMetrics.innerHTML = '';
      safeArray(game.metrics).slice(0, 3).forEach((metric) => {
        const item = document.createElement('div');
        const value = document.createElement('strong');
        const label = document.createElement('span');
        value.textContent = metric.value == null ? '' : String(metric.value);
        label.textContent = metric.label || '';
        item.append(value, label);
        elements.gameMetrics.appendChild(item);
      });
    }
    setHidden(elements.gameSteps, true);
    if (elements.gameSteps) elements.gameSteps.innerHTML = '';
    renderSteps(elements.gameSteps, game.steps);
    setOptionalText(elements.gameAction, game.action_label || '');
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
    const preserved = entries.findIndex((entry) => String(entry.id || '') === gameEntryId);
    if (preserved >= 0) gameIndex = preserved;
    gameIndex %= entries.length;
    renderGameEntry(entries[gameIndex], entries.length);
    if (entries.length > 1 && !games.pinned_game_key) {
      const entryId = String(entries[gameIndex]?.id || '');
      if (gameTimer && gameTimerEntryId === entryId) return;
      clearGameRotationTimer();
      const seconds = boundedSeconds(games.interval_seconds, 10);
      gameTimerEntryId = entryId;
      gameTimer = window.setTimeout(() => {
        gameTimer = null;
        gameTimerEntryId = '';
        const latestEntries = safeArray(asObject(layout.games).entries);
        if (!latestEntries.length) {
          renderGames();
          return;
        }
        const currentIndex = latestEntries.findIndex((entry) => String(entry.id || '') === gameEntryId);
        gameIndex = ((currentIndex >= 0 ? currentIndex : gameIndex) + 1) % latestEntries.length;
        gameEntryId = String(latestEntries[gameIndex]?.id || '');
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

  const renderBar = () => {
    const bar = asObject(layout.bar);
    const notice = asObject(bar.notice);
    const visible = Boolean(bar.visible);
    setHidden(elements.barStage, !visible);
    shell.classList.toggle('has-bar', visible);
    if (!visible) return;
    const hasNotice = Object.keys(notice).length > 0;
    setHidden(elements.readyNotice, !hasNotice);
    setHidden(elements.barQueue, hasNotice);
    if (hasNotice) {
      if (elements.readyName) elements.readyName.textContent = notice.highlight || 'Guest';
      if (elements.readyMessage) elements.readyMessage.textContent = notice.message || 'Your drink is ready at the bar.';
      if (elements.readyQueue) {
        const remaining = Number(bar.active_count) || 0;
        const queued = Number(bar.queued_notice_count) || 0;
        elements.readyQueue.textContent = `${remaining} active order${remaining === 1 ? '' : 's'}${queued ? ` · ${queued} more ready` : ''}`;
      }
      setOptionalText(elements.readyPickup, bar.pickup_note || 'Pick up at the bar.');
      if (elements.readyDetails) {
        elements.readyDetails.innerHTML = '';
        safeArray(notice.details).slice(0, 2).forEach((detail) => {
          const item = document.createElement('li');
          item.textContent = String(detail);
          elements.readyDetails.appendChild(item);
        });
        setHidden(elements.readyDetails, !elements.readyDetails.children.length);
      }
      if (elements.readyImage && elements.readyImageWrap) {
        if (notice.image_url) {
          elements.readyImage.src = notice.image_url;
          elements.readyImage.alt = `${notice.highlight || 'Guest'} drink`;
          setHidden(elements.readyImageWrap, false);
        } else {
          elements.readyImage.removeAttribute('src');
          setHidden(elements.readyImageWrap, true);
        }
      }
      scheduleNoticeRefresh(notice);
    } else {
      if (elements.barHeading) elements.barHeading.textContent = `Bar queue · ${Number(bar.active_count) || 0}`;
      if (elements.barOrders) {
        elements.barOrders.innerHTML = '';
        safeArray(bar.orders).forEach((order) => {
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
      }
      const overflow = Number(bar.overflow_count) || 0;
      setOptionalText(elements.barOverflow, overflow ? `+${overflow} more active order${overflow === 1 ? '' : 's'}` : '');
      const summary = asObject(bar.summary);
      renderFacts(elements.barSummary, [
        { label: 'Mixing', value: Number(summary.mixing_count) || 0 },
        { label: 'Waiting', value: Number(summary.waiting_count) || 0 },
        { label: 'Avg prep', value: summary.average_prep_label || 'About 8 min' },
        { label: 'Drinks', value: Number(summary.available_drink_count) || 0 },
      ]);
      const feature = asObject(bar.featured_item);
      if (elements.barImage && elements.barImageWrap) {
        const imageUrl = feature.image_url || bar.image_url || '';
        if (imageUrl) {
          elements.barImage.src = imageUrl;
          elements.barImage.alt = feature.name ? `${feature.name} image` : 'Bar illustration';
          elements.barImage.onerror = () => setHidden(elements.barImageWrap, true);
          setHidden(elements.barImageWrap, false);
        } else {
          elements.barImage.removeAttribute('src');
          setHidden(elements.barImageWrap, true);
        }
      }
      const hasFeature = Boolean(feature.name);
      setHidden(elements.barFeature, !hasFeature);
      if (elements.barFeatureName) elements.barFeatureName.textContent = feature.name || '';
      if (elements.barFeatureDescription) elements.barFeatureDescription.textContent = feature.description || 'Available to order from your phone.';
      renderAction(elements.barAction, bar.action);
      setOptionalText(elements.barPickup, bar.pickup_note || '');
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
    if (elements.costumeCount) elements.costumeCount.textContent = Number(header.costume_count) || 0;
    if (elements.karaokeCount) elements.karaokeCount.textContent = Number(header.karaoke_count) || 0;
    if (elements.gameCount) elements.gameCount.textContent = Number(header.game_count) || 0;
    body.classList.remove('display-density--compact', 'display-density--standard', 'display-density--large');
    body.classList.add(`display-density--${['compact', 'standard', 'large'].includes(layout.density) ? layout.density : 'standard'}`);
    renderGames();
    renderBar();
    renderMusic();
    renderCenter();
    fitAll();
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
  fetchLatest();
  window.setInterval(fetchLatest, 30000);
  startEventStream();
});
