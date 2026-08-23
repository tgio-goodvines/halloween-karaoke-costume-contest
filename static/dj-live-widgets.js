((root, factory) => {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.HalloweenDjLiveWidgets = api;
  if (root?.document) {
    const start = () => api.startAll(root.document);
    if (root.document.readyState === 'loading') root.document.addEventListener('DOMContentLoaded', start, { once: true });
    else start();
  }
})(typeof window !== 'undefined' ? window : globalThis, () => {
  const connections = new WeakMap();

  const titleize = (value) => String(value || '')
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

  const safeSong = (candidate) => (
    candidate && typeof candidate === 'object' && candidate.title
      ? candidate
      : null
  );

  const buildWidgetView = (payload, shape = 'jukebox') => {
    const source = payload && typeof payload === 'object' ? payload : {};
    if (shape === 'display') {
      const dj = source.dj && typeof source.dj === 'object' ? source.dj : {};
      const receiver = dj.receiver && typeof dj.receiver === 'object' ? dj.receiver : {};
      const layout = source.layout && typeof source.layout === 'object' ? source.layout : {};
      const music = layout.music && typeof layout.music === 'object' ? layout.music : {};
      return {
        song: safeSong(dj.current_song),
        playbackStatus: String(receiver.playback_status || 'stopped'),
        receiverStatus: String(receiver.effective_status || receiver.status || 'offline'),
        requestCount: Math.max(0, Number(dj.request_count) || 0),
        playlistCount: Array.isArray(dj.playlist) ? dj.playlist.length : 0,
        musicVisible: Boolean(music.visible),
        updateVersion: Math.max(0, Number(source.display_update_version) || 0),
        sourceState: dj,
      };
    }

    return {
      song: safeSong(source.now_playing),
      playbackStatus: String(source.playback_status || 'stopped'),
      receiverStatus: '',
      requestCount: Array.isArray(source.pending_requests) ? source.pending_requests.length : 0,
      playlistCount: Array.isArray(source.playlist) ? source.playlist.length : 0,
      musicVisible: Boolean(source.now_playing),
      updateVersion: Math.max(0, Number(source.update_version) || 0),
      sourceState: source,
    };
  };

  const shouldApplyResponse = ({ requestNumber, latestRequestNumber, updateVersion, latestUpdateVersion }) => (
    requestNumber === latestRequestNumber
    && (updateVersion === 0 || updateVersion >= latestUpdateVersion)
  );

  const setText = (element, value) => {
    if (element) element.textContent = value;
  };

  const renderArtwork = (widgetRoot, song) => {
    const wrap = widgetRoot.querySelector('[data-live-dj-artwork-wrap]');
    const image = widgetRoot.querySelector('[data-live-dj-artwork]');
    if (!wrap || !image) return;
    const artworkUrl = String(song?.artwork_url || '');
    if (song && artworkUrl) {
      if (image.getAttribute('src') !== artworkUrl) image.setAttribute('src', artworkUrl);
      image.alt = `${song.title} artwork`;
      wrap.hidden = false;
    } else {
      image.removeAttribute('src');
      image.alt = '';
      wrap.hidden = true;
    }
  };

  const renderWidget = (widgetRoot, view) => {
    const song = view.song;
    const title = widgetRoot.querySelector('[data-live-dj-title]');
    const artist = widgetRoot.querySelector('[data-live-dj-artist]');
    const status = widgetRoot.querySelector('[data-live-dj-status]');
    const requestLink = widgetRoot.querySelector('[data-live-dj-request-link]');
    const receiverStatus = widgetRoot.querySelector('[data-live-dj-receiver-status]');
    const adminSummary = widgetRoot.querySelector('[data-live-dj-admin-summary]');
    const musicVisible = widgetRoot.querySelector('[data-live-dj-music-visible]');

    if (title) {
      const prefix = title.dataset.playingPrefix || '';
      setText(title, song ? `${prefix}${song.title}` : (title.dataset.emptyText || 'Nothing is playing yet'));
    }
    if (artist) {
      setText(
        artist,
        song
          ? [song.artist, song.album].filter(Boolean).join(' · ')
          : (artist.dataset.emptyText || 'The next DJ selection will appear here.'),
      );
    }
    setText(status, titleize(view.playbackStatus || 'stopped'));
    if (requestLink) {
      const baseLabel = requestLink.dataset.baseLabel || 'Open Jukebox';
      setText(requestLink, `${baseLabel}${view.requestCount ? ` · ${view.requestCount} pending` : ''}`);
    }
    setText(receiverStatus, titleize(view.receiverStatus || 'offline'));
    if (adminSummary) {
      const requestLabel = view.requestCount
        ? `${view.requestCount} request${view.requestCount === 1 ? '' : 's'} waiting · `
        : '';
      const songLabel = song
        ? song.title
        : `${view.playlistCount} song${view.playlistCount === 1 ? '' : 's'} in playlist`;
      setText(adminSummary, `${requestLabel}${songLabel}`);
    }
    setText(musicVisible, view.musicVisible ? 'Visible' : 'Collapsed');
    renderArtwork(widgetRoot, song);
    widgetRoot.dataset.liveDjSongId = String(song?.id || '');
  };

  const connect = (widgetRoot) => {
    if (!widgetRoot || connections.has(widgetRoot)) return connections.get(widgetRoot);
    const stateUrl = widgetRoot.dataset.djStateUrl || '';
    if (!stateUrl) return null;
    const updatesUrl = widgetRoot.dataset.djUpdatesUrl || '';
    const shape = widgetRoot.dataset.djPayloadShape || 'jukebox';
    let latestRequestNumber = 0;
    let latestUpdateVersion = 0;
    let closed = false;

    const refresh = async () => {
      const requestNumber = ++latestRequestNumber;
      try {
        const response = await fetch(stateUrl, { credentials: 'same-origin', cache: 'no-store' });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || `DJ state refresh failed (${response.status})`);
        const view = buildWidgetView(payload, shape);
        if (closed) return;
        if (!shouldApplyResponse({
          requestNumber,
          latestRequestNumber,
          updateVersion: view.updateVersion,
          latestUpdateVersion,
        })) return;
        latestUpdateVersion = Math.max(latestUpdateVersion, view.updateVersion);
        renderWidget(widgetRoot, view);
        widgetRoot.dispatchEvent(new CustomEvent('dj:state-updated', {
          detail: { payload, state: view.sourceState, view },
        }));
      } catch (error) {
        console.error('Unable to refresh live DJ widget', error);
      }
    };

    const intervalId = window.setInterval(refresh, 5000);
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') refresh();
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    const stream = updatesUrl && typeof window.EventSource === 'function'
      ? new EventSource(updatesUrl)
      : null;
    if (stream) stream.onmessage = refresh;

    const controller = {
      refresh,
      close: () => {
        if (closed) return;
        closed = true;
        window.clearInterval(intervalId);
        document.removeEventListener('visibilitychange', onVisibilityChange);
        stream?.close();
        connections.delete(widgetRoot);
      },
    };
    connections.set(widgetRoot, controller);
    refresh();
    return controller;
  };

  const startAll = (documentRoot) => {
    documentRoot.querySelectorAll('[data-dj-live-widget]').forEach(connect);
  };

  return {
    buildWidgetView,
    connect,
    renderArtwork,
    renderWidget,
    shouldApplyResponse,
    startAll,
    titleize,
  };
});
