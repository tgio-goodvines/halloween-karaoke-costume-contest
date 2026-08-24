(() => {
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
    body.append(
      element('span', `game-phase game-phase--${game.phase || 'signup'}`, game.status_label || ''),
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
      const selectedKey = widget.dataset.selectedGame;
      const selected = (payload.games || []).find((game) => game.key === selectedKey);
      const status = widget.querySelector('[data-selected-game-live-status]');
      if (selected && status) {
        status.textContent = `${selected.status_label} · ${selected.participant_count} player${selected.participant_count === 1 ? '' : 's'}`;
      }
      const summary = widget.querySelector('[data-dashboard-game-summary]');
      if (summary) {
        const active = (payload.games || []).filter((game) => game.phase === 'active').length;
        const ended = (payload.games || []).filter((game) => game.phase === 'ended').length;
        summary.textContent = active ? `${active} game${active === 1 ? '' : 's'} live now.` : (ended ? `${ended} final result${ended === 1 ? '' : 's'} ready.` : 'Enrollment is open.');
      }
      const refresh = widget.querySelector('[data-games-refresh-status]');
      if (refresh) refresh.textContent = 'Updated now';
    });
  };

  const refresh = async () => {
    const url = widgets[0].dataset.gamesStateUrl;
    if (!url) return;
    const sequence = ++requestSequence;
    try {
      const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      if (sequence < appliedSequence) return;
      appliedSequence = sequence;
      applyPayload(payload);
    } catch (error) {
      widgets.forEach((widget) => {
        const status = widget.querySelector('[data-games-refresh-status]');
        if (status) status.textContent = 'Reconnecting';
      });
    }
  };

  window.setInterval(refresh, intervalMs);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
})();
