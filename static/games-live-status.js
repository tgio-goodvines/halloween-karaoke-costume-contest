(() => {
  const updateCountdowns = () => {
    document.querySelectorAll('[data-game-deadline]').forEach((node) => {
      const deadline = new Date(node.dataset.gameDeadline || '').getTime();
      if (!Number.isFinite(deadline)) return;
      const remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
      const minutes = Math.floor(remaining / 60);
      const seconds = remaining % 60;
      node.textContent = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    });
  };
  updateCountdowns();
  window.setInterval(updateCountdowns, 1000);

  const widgets = Array.from(document.querySelectorAll('[data-games-live-widget]'));
  if (!widgets.length) return;

  const intervalMs = 5000;
  let requestSequence = 0;
  let appliedSequence = 0;

  const element = (tag, className = '', text = '') => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== '') node.textContent = String(text);
    return node;
  };

  const renderScoreboard = (scores) => {
    const list = element('ol', 'compact-scoreboard');
    (Array.isArray(scores) ? scores : []).slice(0, 5).forEach((score, index) => {
      const item = element('li');
      item.append(
        element('span', '', `#${score.rank || index + 1} ${score.name || 'Player'}`),
        element('strong', '', `${score.points || 0} pts`),
      );
      list.appendChild(item);
    });
    return list;
  };

  const renderGameCard = (game) => {
    const card = element('article', 'live-game-card');
    card.dataset.gameCard = game.key || '';
    const image = element('img', 'live-game-card__image');
    image.src = game.phase === 'ended' && game.winners?.length ? game.winner_image_url : game.image_url;
    image.alt = '';
    image.addEventListener('error', () => image.remove(), { once: true });
    const body = element('div', 'live-game-card__body');
    const phase = element('span', `game-phase game-phase--${game.phase || 'signup'}`);
    const phaseLight = element('span');
    phaseLight.setAttribute('aria-hidden', 'true');
    phase.append(phaseLight, document.createTextNode(game.status_label || ''));
    body.append(
      phase,
      element('h4', '', game.title || 'Party game'),
    );
    if (game.winners?.length) body.appendChild(element('p', 'live-game-card__winner', `Winner${game.winners.length === 1 ? '' : 's'}: ${game.winners.join(', ')}`));
    else body.appendChild(element('p', '', game.description || ''));
    const metrics = element('dl', 'live-game-card__metrics');
    (game.metrics || []).forEach((metric) => {
      const item = element('div');
      item.append(element('dt', '', metric.label || ''), element('dd', '', metric.value ?? ''));
      metrics.appendChild(item);
    });
    body.appendChild(metrics);
    if (game.phase === 'ended' && game.scores?.length) body.appendChild(renderScoreboard(game.scores));
    if (game.enabled && document.body.dataset.partyDay === 'true') {
      const link = element('a', 'button', game.phase === 'ended' ? 'See Full Results' : 'Open Game');
      link.href = `/party/games?game=${encodeURIComponent(game.slug || '')}`;
      body.appendChild(link);
    }
    card.append(image, body);
    return card;
  };

  const renderAchievements = (container, achievementState) => {
    if (!container) return;
    container.replaceChildren();
    const achievements = achievementState?.achievements || [];
    if (!achievements.length) {
      container.appendChild(element('p', 'empty-state', 'Your first achievement will appear after the hosts credit attendance or an official win.'));
      return;
    }
    achievements.forEach((achievement) => {
      const card = element('article', 'achievement-card');
      const image = element('img');
      image.src = `/static/${String(achievement.image || '').replace(/^\/+/, '')}`;
      image.alt = '';
      const copy = element('div');
      copy.append(element('h4', '', achievement.title || ''), element('p', '', achievement.description || ''));
      card.append(image, copy);
      container.appendChild(card);
    });
  };

  const renderHistory = (container, archives) => {
    if (!container) return;
    container.replaceChildren();
    if (!archives?.length) {
      container.appendChild(element('p', 'empty-state', 'Official results will appear after the hosts publish a completed game or contest.'));
      return;
    }
    archives.forEach((archive) => {
      const card = element('article', 'history-card');
      const imageUrl = archive.winner_image_url || archive.image_url;
      if (imageUrl) {
        const image = element('img', 'history-card__image');
        image.src = imageUrl;
        image.alt = '';
        image.addEventListener('error', () => image.remove(), { once: true });
        card.appendChild(image);
      }
      const copy = element('div');
      copy.append(element('span', '', `${archive.year || ''} · ${archive.kind === 'costume' ? 'Costume' : 'Game'}`), element('h4', '', archive.title || 'Official result'));
      const winners = archive.summary?.winners || [];
      copy.appendChild(element('p', '', winners.length ? `Winner${winners.length === 1 ? '' : 's'}: ${winners.join(', ')}` : 'No positive-score winner was recorded.'));
      if (archive.summary?.scores?.length) copy.appendChild(renderScoreboard(archive.summary.scores));
      card.appendChild(copy);
      container.appendChild(card);
    });
  };

  const updateStatusIndicator = (status, game) => {
    if (!status || !game) return;
    status.classList.remove('game-status-indicator--signup', 'game-status-indicator--active', 'game-status-indicator--ended');
    status.classList.add(`game-status-indicator--${game.phase || 'signup'}`);
    const light = element('span');
    light.setAttribute('aria-hidden', 'true');
    status.replaceChildren(light, document.createTextNode(`${game.status_label} · ${game.participant_count} player${game.participant_count === 1 ? '' : 's'}`));
  };

  const applyPayload = (payload) => {
    widgets.forEach((widget) => {
      const liveGrid = widget.querySelector('[data-live-game-grid]');
      if (liveGrid) {
        liveGrid.replaceChildren();
        (payload.games || []).forEach((game) => liveGrid.appendChild(renderGameCard(game)));
        if (!payload.games?.length) liveGrid.appendChild(element('p', 'empty-state', 'No games are running yet.'));
      }
      renderAchievements(widget.querySelector('[data-achievement-grid]'), payload.achievements);
      renderHistory(widget.querySelector('[data-history-grid]'), payload.archives || []);
      const selected = (payload.games || []).find((game) => game.key === widget.dataset.selectedGame);
      updateStatusIndicator(widget.querySelector('[data-selected-game-live-status]'), selected);
      const summary = widget.querySelector('[data-dashboard-game-summary]');
      if (summary) {
        const active = (payload.games || []).filter((game) => game.phase === 'active').length;
        const ended = (payload.games || []).filter((game) => game.phase === 'ended').length;
        summary.textContent = active ? `${active} game${active === 1 ? '' : 's'} open now.` : (ended ? `${ended} final result${ended === 1 ? '' : 's'} ready.` : 'No games are open yet.');
      }
      const refresh = widget.querySelector('[data-games-refresh-status]');
      if (refresh) refresh.textContent = 'Updated now';
    });
  };

  const formSnapshot = (form) => ({
    key: form.dataset.liveFormKey,
    dirty: form.dataset.dirty === 'true',
    controls: Array.from(form.elements).map((control) => ({
      name: control.name,
      occurrence: Array.from(form.elements).filter((candidate) => candidate.name === control.name).indexOf(control),
      type: control.type,
      value: control.value,
      checked: control.checked,
    })),
  });

  const restoreForm = (root, snapshot) => {
    if (!snapshot.dirty || !snapshot.key) return;
    const form = Array.from(root.querySelectorAll('form[data-live-form-key]')).find((candidate) => candidate.dataset.liveFormKey === snapshot.key);
    if (!form) return;
    snapshot.controls.forEach((saved) => {
      const matches = Array.from(form.elements).filter((candidate) => candidate.name === saved.name);
      const control = saved.type === 'radio'
        ? matches.find((candidate) => candidate.value === saved.value)
        : matches[saved.occurrence];
      if (!control || control.name === 'csrf_token') return;
      if (saved.type === 'checkbox' || saved.type === 'radio') control.checked = saved.checked;
      else control.value = saved.value;
    });
    form.dataset.dirty = 'true';
  };

  const activateMmfRound = (root, roundId, { updateUrl = false, focus = false } = {}) => {
    const buttons = Array.from(root.querySelectorAll('[data-mmf-round-target]'));
    const panels = Array.from(root.querySelectorAll('[data-mmf-round-panel]'));
    if (!buttons.length || !panels.length) return;
    const selectedId = panels.some((panel) => panel.dataset.mmfRoundPanel === roundId) ? roundId : panels[0].dataset.mmfRoundPanel;
    buttons.forEach((button) => {
      const selected = button.dataset.mmfRoundTarget === selectedId;
      button.classList.toggle('is-selected', selected);
      button.setAttribute('aria-selected', selected ? 'true' : 'false');
      button.tabIndex = selected ? 0 : -1;
      if (selected && focus) button.focus({ preventScroll: true });
    });
    panels.forEach((panel) => panel.classList.toggle('is-selected', panel.dataset.mmfRoundPanel === selectedId));
    const workspace = root.querySelector('[data-mmf-round-workspace]');
    if (workspace) workspace.dataset.mmfEnhanced = 'true';
    if (updateUrl) {
      const url = new URL(window.location.href);
      url.searchParams.set('round', selectedId);
      url.searchParams.delete('success');
      url.searchParams.delete('error');
      history.replaceState(history.state, '', `${url.pathname}${url.search}${url.hash}`);
    }
  };

  const initializeMmfRounds = (root) => {
    const selected = root.querySelector('[data-mmf-round-target].is-selected') || root.querySelector('[data-mmf-round-target]');
    if (!selected) return;
    activateMmfRound(root, selected.dataset.mmfRoundTarget);
    root.querySelectorAll('[data-mmf-round-target]').forEach((button) => {
      button.addEventListener('click', () => activateMmfRound(root, button.dataset.mmfRoundTarget, { updateUrl: true }));
      button.addEventListener('keydown', (event) => {
        if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
        event.preventDefault();
        const buttons = Array.from(root.querySelectorAll('[data-mmf-round-target]'));
        const index = buttons.indexOf(button);
        const delta = ['ArrowLeft', 'ArrowUp'].includes(event.key) ? -1 : 1;
        const next = buttons[(index + delta + buttons.length) % buttons.length];
        activateMmfRound(root, next.dataset.mmfRoundTarget, { updateUrl: true, focus: true });
      });
    });
  };

  const reconcileGameContent = (widget, data) => {
    const current = widget.querySelector('[data-game-live-content]');
    if (!current || !data?.html || current.dataset.gameContentRevision === data.revision) return;
    const parsed = new DOMParser().parseFromString(data.html, 'text/html');
    const next = parsed.querySelector('[data-game-live-content]');
    if (!next) return;

    const active = document.activeElement;
    const anchor = active?.closest?.('[data-view-key]') || current.querySelector('.mmf-round.is-selected') || current;
    const anchorKey = anchor.dataset?.viewKey || anchor.id || '';
    const anchorTop = anchor.getBoundingClientRect().top;
    const forms = Array.from(current.querySelectorAll('form[data-live-form-key]')).map(formSnapshot);
    const openDetails = new Set(Array.from(current.querySelectorAll('details[open][data-view-key]')).map((details) => details.dataset.viewKey));
    const focusState = active?.form?.dataset?.liveFormKey ? {
      formKey: active.form.dataset.liveFormKey,
      name: active.name,
      occurrence: Array.from(active.form.elements).filter((control) => control.name === active.name).indexOf(active),
    } : null;

    forms.forEach((snapshot) => restoreForm(next, snapshot));
    next.querySelectorAll('details[data-view-key]').forEach((details) => { details.open = openDetails.has(details.dataset.viewKey); });
    current.replaceWith(next);
    initializeMmfRounds(next);

    requestAnimationFrame(() => requestAnimationFrame(() => {
      const replacementAnchor = anchorKey
        ? Array.from(next.querySelectorAll('[data-view-key], [id]')).find((candidate) => candidate.dataset.viewKey === anchorKey || candidate.id === anchorKey)
        : next;
      if (replacementAnchor) window.scrollBy(0, replacementAnchor.getBoundingClientRect().top - anchorTop);
      if (focusState) {
        const form = Array.from(next.querySelectorAll('form[data-live-form-key]')).find((candidate) => candidate.dataset.liveFormKey === focusState.formKey);
        const control = form ? Array.from(form.elements).filter((candidate) => candidate.name === focusState.name)[focusState.occurrence] : null;
        if (control) control.focus({ preventScroll: true });
      }
    }));
  };

  document.addEventListener('input', (event) => {
    const form = event.target.closest?.('form[data-live-form-key]');
    if (form) form.dataset.dirty = 'true';
  });
  document.addEventListener('change', (event) => {
    const form = event.target.closest?.('form[data-live-form-key]');
    if (form) form.dataset.dirty = 'true';
  });
  widgets.forEach(initializeMmfRounds);

  const refresh = async () => {
    const widget = widgets[0];
    const viewUrl = widget.dataset.gameViewUrl;
    const stateUrl = widget.dataset.gamesStateUrl;
    if (!viewUrl && !stateUrl) return;
    const sequence = ++requestSequence;
    try {
      const url = new URL(viewUrl || stateUrl, window.location.origin);
      if (viewUrl) {
        const current = new URL(window.location.href);
        ['participate', 'round'].forEach((key) => {
          if (current.searchParams.has(key)) url.searchParams.set(key, current.searchParams.get(key));
        });
      }
      const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (sequence < appliedSequence) return;
      appliedSequence = sequence;
      if (data.redirect_url) {
        window.location.assign(data.redirect_url);
        return;
      }
      const payload = viewUrl ? data.payload : data;
      applyPayload(payload);
      if (viewUrl) reconcileGameContent(widget, data);
    } catch (_error) {
      widgets.forEach((item) => {
        const status = item.querySelector('[data-games-refresh-status]');
        if (status) status.textContent = 'Reconnecting';
      });
    }
  };

  window.setInterval(refresh, intervalMs);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
})();
