// Wohnsinnig vernetzt Dashboard Player & Blueprints Cards v2.8.0

class WohnsinnigVernetztCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {
      title: "Wohnsinnig vernetzt",
      show_list_default: true,
    };
    this._episodes = [];
    this._podcastTitle = "Wohnsinnig vernetzt";
    this._podcastImage = "/wohnsinnig_vernetzt/logo.png";
    this._currentIndex = 0;
    this._listOpen = true;
    this._searchQuery = "";
    this._loaded = false;
    this._fetching = false;
    this._lastFetchAttempt = 0;
    this._lastSensorState = null;
    this._loadedTrackUrl = "";
    this._isBuffering = false;
    this._statusText = "";
    this._statusIsError = false;
    this._lastCommandId = null;
    this._speeds = [1, 1.25, 1.5, 2];
    this._speedIdx = 0;

    this._audio = new Audio();
    this._audio.preload = "metadata";
    this._setupAudioEvents();
  }

  static getStubConfig() {
    return {
      title: "Wohnsinnig vernetzt",
      show_list_default: true,
    };
  }

  connectedCallback() {
    if (this.shadowRoot.innerHTML === "") {
      this._renderShell();
    }
    if (this._hass && !this._loaded && !this._fetching) {
      this._fetchEpisodes();
    }
  }

  setConfig(config) {
    this._config = {
      title: "Wohnsinnig vernetzt",
      show_list_default: true,
      ...(config || {}),
    };
    this._listOpen = Boolean(this._config.show_list_default);
    if (this.shadowRoot.innerHTML === "") {
      this._renderShell();
    }
    this._updateUI();
  }

  _findPlayerEntity(hass) {
    if (!hass || !hass.states) return null;
    if (hass.states["media_player.wohnsinnig_vernetzt_player"]) {
      return hass.states["media_player.wohnsinnig_vernetzt_player"];
    }
    return Object.values(hass.states).find(
      (s) =>
        s.entity_id.startsWith("media_player.wohnsinnig_vernetzt") &&
        s.attributes &&
        "play_command_id" in s.attributes
    );
  }

  set hass(hass) {
    this._hass = hass;
    if (this.shadowRoot.innerHTML === "") {
      this._renderShell();
    }

    const sensor =
      hass.states["sensor.wohnsinnig_vernetzt_neueste_folge"] ||
      Object.values(hass.states).find(
        (s) =>
          s.entity_id.startsWith("sensor.wohnsinnig_vernetzt") &&
          s.attributes &&
          "episode_count" in s.attributes
      );
    const sensorState = sensor ? sensor.state : null;

    const now = Date.now();
    const shouldRetryEmpty =
      !this._loaded && !this._fetching && now - this._lastFetchAttempt > 5000;
    const sensorChanged =
      Boolean(sensorState) && sensorState !== this._lastSensorState;

    if (shouldRetryEmpty || (sensorChanged && !this._fetching)) {
      this._lastSensorState = sensorState;
      this._fetchEpisodes();
    }

    // Optionaler Sync: Wenn am Gerät "Dashboard-Browser" als Ziel gewählt ist und
    // dort eine Folge gestartet/pausiert wird, reagiert der Dashboard-Player mit.
    const player = this._findPlayerEntity(hass);
    if (player && player.attributes) {
      const targetEntity = player.attributes.target_entity || "__browser__";
      const cmdId = player.attributes.play_command_id;
      const action = player.attributes.last_command_action;
      const selectedGuid = player.attributes.selected_guid;

      if (this._lastCommandId === null) {
        this._lastCommandId = cmdId;
      } else if (
        targetEntity === "__browser__" &&
        cmdId !== undefined &&
        cmdId !== this._lastCommandId
      ) {
        this._lastCommandId = cmdId;
        this._handleRemoteCommand(action, selectedGuid);
      }
    }
  }

  getCardSize() {
    return this._listOpen ? 7 : 3;
  }

  async _fetchEpisodes() {
    if (!this._hass || this._fetching) return;
    this._fetching = true;
    this._lastFetchAttempt = Date.now();
    try {
      const data = await this._hass.callApi("GET", "wohnsinnig_vernetzt/episodes");
      const currentGuid = this._episodes[this._currentIndex]?.guid;
      this._podcastTitle =
        (this._config && this._config.title) || data.title || "Wohnsinnig vernetzt";
      this._podcastImage = data.image || "/wohnsinnig_vernetzt/logo.png";
      this._episodes = Array.isArray(data.episodes) ? data.episodes : [];

      if (this._episodes.length > 0) {
        this._loaded = true;
      }

      if (currentGuid) {
        const idx = this._episodes.findIndex((e) => e.guid === currentGuid);
        this._currentIndex = idx >= 0 ? idx : 0;
      } else {
        this._currentIndex = 0;
      }

      this._setStatus("", false);
      this._updateUI();
    } catch (err) {
      this._setStatus("Folgen konnten nicht geladen werden.", true);
      this._updateUI();
    } finally {
      this._fetching = false;
    }
  }

  _setupAudioEvents() {
    this._audio.addEventListener("timeupdate", () => this._updateProgress());
    this._audio.addEventListener("loadedmetadata", () => this._updateProgress());
    this._audio.addEventListener("waiting", () => {
      this._isBuffering = true;
      this._setStatus("Lade Audio…", false);
      this._updatePlayIcon();
    });
    this._audio.addEventListener("canplay", () => {
      if (this._isBuffering) {
        this._isBuffering = false;
        this._setStatus("", false);
        this._updatePlayIcon();
      }
    });
    this._audio.addEventListener("playing", () => {
      this._isBuffering = false;
      this._setStatus("", false);
      this._updatePlayIcon();
    });
    this._audio.addEventListener("play", () => {
      this._updatePlayIcon();
      this._syncStateToHA("playing");
    });
    this._audio.addEventListener("pause", () => {
      this._isBuffering = false;
      this._updatePlayIcon();
      this._syncStateToHA("paused");
    });
    this._audio.addEventListener("ended", () => {
      this._isBuffering = false;
      this._updatePlayIcon();
      this._syncStateToHA("idle");
    });
    this._audio.addEventListener("error", () => {
      if (!this._loadedTrackUrl) return;
      this._isBuffering = false;
      this._setStatus("Audio-Stream konnte im Browser nicht geladen werden.", true);
      this._updatePlayIcon();
    });
  }

  _syncStateToHA(state) {
    const ep = this._episodes[this._currentIndex];
    if (!this._hass || !ep) return;
    this._hass
      .callApi("POST", "wohnsinnig_vernetzt/player_state", {
        state,
        guid: ep.guid,
      })
      .catch(() => {});
  }

  _setStatus(text, isError) {
    this._statusText = text || "";
    this._statusIsError = Boolean(isError);
    const el = this.shadowRoot && this.shadowRoot.getElementById("player-status");
    if (!el) return;
    el.textContent = this._statusText;
    el.className = `player-status ${this._statusIsError ? "error" : ""}`;
    el.style.display = this._statusText ? "block" : "none";
  }

  _formatTime(sec) {
    if (!Number.isFinite(sec) || sec < 0) return "0:00";
    const s = Math.floor(sec);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const r = s % 60;
    if (h > 0) {
      return `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
    }
    return `${m}:${String(r).padStart(2, "0")}`;
  }

  _selectEpisode(index) {
    if (index < 0 || index >= this._episodes.length) return;
    const isDifferent = this._currentIndex !== index;
    this._currentIndex = index;

    if (isDifferent) {
      if (!this._audio.paused) {
        this._audio.pause();
      }
      this._isBuffering = false;
      this._loadedTrackUrl = "";
      this._setStatus("", false);
    }

    this._updateUI();
  }

  _playCurrentEpisode() {
    if (!this._episodes.length) return;
    const ep = this._episodes[this._currentIndex];
    if (!ep || !ep.audio_url) {
      this._setStatus("Für diese Folge liegt keine Audio-URL vor.", true);
      return;
    }

    const trackChanged = this._loadedTrackUrl !== ep.audio_url;
    if (trackChanged) {
      this._loadedTrackUrl = ep.audio_url;
      this._audio.src = ep.audio_url;
      this._audio.load();
    }

    this._audio.playbackRate = this._speeds[this._speedIdx];
    this._isBuffering = true;
    this._setStatus("Starte Wiedergabe…", false);
    this._updatePlayIcon();

    const playPromise = this._audio.play();
    if (playPromise && typeof playPromise.then === "function") {
      playPromise
        .then(() => {
          this._isBuffering = false;
          this._setStatus("", false);
          this._updatePlayIcon();
        })
        .catch((err) => {
          this._isBuffering = false;
          if (err && err.name === "NotAllowedError") {
            this._setStatus("Autoplay blockiert – bitte einmal auf Play tippen.", false);
          } else if (err && err.name === "AbortError") {
            this._setStatus("", false);
          } else {
            this._setStatus(
              "Wiedergabe fehlgeschlagen. Bitte erneut auf Play tippen.",
              true
            );
          }
          this._updatePlayIcon();
        });
    }
  }

  _togglePlay() {
    if (!this._episodes.length) return;
    const ep = this._episodes[this._currentIndex];
    if (!ep || !ep.audio_url) return;

    const isSameLoaded = this._loadedTrackUrl === ep.audio_url;
    if (isSameLoaded && !this._audio.paused) {
      this._audio.pause();
    } else {
      this._playCurrentEpisode();
    }
  }

  _handleRemoteCommand(action, guid) {
    if (guid && this._episodes.length) {
      const idx = this._episodes.findIndex((e) => e.guid === guid);
      if (idx >= 0) {
        this._currentIndex = idx;
      }
    }

    if (action === "play") {
      this._updateUI();
      this._playCurrentEpisode();
    } else if (action === "pause") {
      this._audio.pause();
      this._updateUI();
    } else if (action === "stop") {
      this._audio.pause();
      if (this._loadedTrackUrl) {
        try {
          this._audio.currentTime = 0;
        } catch (_) {}
      }
      this._updateUI();
    }
  }

  _skip(seconds) {
    const ep = this._episodes[this._currentIndex];
    if (!ep || this._loadedTrackUrl !== ep.audio_url) return;
    if (!Number.isFinite(this._audio.duration)) return;
    this._audio.currentTime = Math.min(
      Math.max(0, this._audio.currentTime + seconds),
      this._audio.duration
    );
  }

  _cycleSpeed() {
    this._speedIdx = (this._speedIdx + 1) % this._speeds.length;
    this._audio.playbackRate = this._speeds[this._speedIdx];
    const btn = this.shadowRoot.getElementById("speed-btn");
    if (btn) btn.textContent = `${this._speeds[this._speedIdx]}x`;
  }

  _updatePlayIcon() {
    const btn = this.shadowRoot.getElementById("play-btn");
    if (!btn) return;
    const ep = this._episodes[this._currentIndex];
    const isPlayingCurrent =
      ep && this._loadedTrackUrl === ep.audio_url && !this._audio.paused;

    btn.innerHTML = isPlayingCurrent
      ? `<svg viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>`
      : `<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>`;
  }

  _updateProgress() {
    const bar = this.shadowRoot.getElementById("progress");
    const cur = this.shadowRoot.getElementById("time-current");
    const dur = this.shadowRoot.getElementById("time-total");
    if (!bar || !cur || !dur) return;

    const ep = this._episodes[this._currentIndex];
    const isLoaded = ep && this._loadedTrackUrl === ep.audio_url;
    const duration =
      isLoaded && Number.isFinite(this._audio.duration) ? this._audio.duration : 0;
    const current =
      isLoaded && Number.isFinite(this._audio.currentTime)
        ? this._audio.currentTime
        : 0;

    bar.max = duration || 100;
    bar.value = current;
    cur.textContent = this._formatTime(current);
    dur.textContent =
      duration > 0 ? this._formatTime(duration) : ep?.duration || "0:00";
  }

  _renderEpisodeList() {
    const listWrap = this.shadowRoot.getElementById("episode-list");
    if (!listWrap) return;

    const query = this._searchQuery.trim().toLowerCase();
    listWrap.innerHTML = "";

    const filtered = this._episodes
      .map((item, idx) => ({ item, idx }))
      .filter(({ item }) => !query || item.title.toLowerCase().includes(query));

    if (!filtered.length) {
      const empty = document.createElement("div");
      empty.className = "empty-hint";
      empty.textContent = this._episodes.length
        ? "Keine passende Folge gefunden."
        : "Noch keine Folgen geladen.";
      listWrap.appendChild(empty);
      return;
    }

    filtered.forEach(({ item, idx }) => {
      const row = document.createElement("button");
      row.className = `ep-row ${idx === this._currentIndex ? "active" : ""}`;
      row.type = "button";

      const info = document.createElement("div");
      info.className = "ep-row-info";

      const t = document.createElement("div");
      t.className = "ep-row-title";
      t.textContent = item.title;

      const m = document.createElement("div");
      m.className = "ep-row-meta";
      m.textContent = [item.pub_date, item.duration].filter(Boolean).join(" • ");

      info.appendChild(t);
      info.appendChild(m);
      row.appendChild(info);

      row.addEventListener("click", () => this._selectEpisode(idx));
      listWrap.appendChild(row);
    });
  }

  _updateUI() {
    if (!this.shadowRoot || this.shadowRoot.innerHTML === "") return;

    const ep = this._episodes[this._currentIndex];
    const cover = this.shadowRoot.getElementById("cover");
    const podcastLabel = this.shadowRoot.getElementById("podcast-label");
    const epTitle = this.shadowRoot.getElementById("ep-title");
    const epMeta = this.shadowRoot.getElementById("ep-meta");
    const listToggle = this.shadowRoot.getElementById("list-toggle");
    const listSection = this.shadowRoot.getElementById("list-section");

    if (podcastLabel) podcastLabel.textContent = this._podcastTitle;

    if (!ep) {
      if (epTitle) {
        epTitle.textContent = this._fetching
          ? "Lade Folgen…"
          : "Keine Folgen verfügbar";
      }
      if (epMeta) epMeta.textContent = "";
      this._renderEpisodeList();
      this._updatePlayIcon();
      this._updateProgress();
      return;
    }

    if (cover) {
      cover.src = ep.image || this._podcastImage || "";
      cover.style.display = cover.src ? "block" : "none";
    }
    if (epTitle) epTitle.textContent = ep.title;
    if (epMeta) {
      epMeta.textContent = [ep.pub_date, ep.duration].filter(Boolean).join(" • ");
    }

    if (listToggle) {
      listToggle.textContent = this._listOpen
        ? `Alle Folgen ausblenden (${this._episodes.length})`
        : `Alle Folgen anzeigen (${this._episodes.length})`;
    }

    if (listSection) {
      listSection.style.display = this._listOpen ? "block" : "none";
    }

    this._renderEpisodeList();
    this._updatePlayIcon();
    this._updateProgress();
  }

  _renderShell() {
    this.shadowRoot.innerHTML = `
      <style>
        ha-card {
          padding: 14px;
          color: var(--primary-text-color);
        }
        .header {
          display: flex;
          gap: 12px;
          align-items: center;
        }
        .cover {
          width: 60px;
          height: 60px;
          border-radius: 10px;
          object-fit: cover;
          flex-shrink: 0;
          background: var(--secondary-background-color);
        }
        .info {
          min-width: 0;
          flex: 1;
        }
        .podcast-label {
          font-size: 11px;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          color: var(--primary-color);
          font-weight: 600;
        }
        .ep-title {
          font-size: 15px;
          font-weight: 600;
          line-height: 1.25;
          margin: 2px 0;
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
          overflow: hidden;
        }
        .ep-meta {
          font-size: 12px;
          color: var(--secondary-text-color);
        }
        .player-status {
          display: none;
          margin-top: 8px;
          padding: 6px 10px;
          border-radius: 8px;
          font-size: 12px;
          background: rgba(var(--rgb-primary-color, 3, 169, 244), 0.14);
          color: var(--primary-color);
          text-align: center;
        }
        .player-status.error {
          background: rgba(219, 68, 55, 0.14);
          color: var(--error-color, #db4437);
        }
        .progress-wrap {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-top: 12px;
          font-size: 11px;
          color: var(--secondary-text-color);
          font-variant-numeric: tabular-nums;
        }
        input[type="range"] {
          flex: 1;
          accent-color: var(--primary-color);
          cursor: pointer;
          height: 4px;
        }
        .controls {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-top: 10px;
        }
        .controls-center {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        button {
          background: none;
          border: none;
          color: var(--primary-text-color);
          cursor: pointer;
          font-family: inherit;
        }
        .icon-btn {
          padding: 6px 8px;
          border-radius: 8px;
          font-size: 12px;
          font-weight: 600;
          color: var(--secondary-text-color);
        }
        .icon-btn:hover {
          background: var(--secondary-background-color);
          color: var(--primary-text-color);
        }
        .play-btn {
          width: 42px;
          height: 42px;
          border-radius: 50%;
          background: var(--primary-color);
          color: var(--text-primary-color, #fff);
          display: flex;
          align-items: center;
          justify-content: center;
        }
        .play-btn svg {
          width: 22px;
          height: 22px;
          fill: currentColor;
        }
        .list-toggle {
          width: 100%;
          margin-top: 10px;
          padding-top: 8px;
          border-top: 1px solid var(--divider-color);
          font-size: 12px;
          color: var(--secondary-text-color);
          text-align: center;
        }
        .list-toggle:hover {
          color: var(--primary-color);
        }
        .search-input {
          width: 100%;
          box-sizing: border-box;
          padding: 8px 10px;
          border-radius: 8px;
          border: 1px solid var(--divider-color);
          background: var(--secondary-background-color);
          color: var(--primary-text-color);
          font-family: inherit;
          font-size: 13px;
          margin-top: 8px;
        }
        .episode-list {
          margin-top: 6px;
          max-height: 250px;
          overflow-y: auto;
        }
        .empty-hint {
          font-size: 12px;
          color: var(--secondary-text-color);
          padding: 10px 4px;
          text-align: center;
        }
        .ep-row {
          width: 100%;
          text-align: left;
          padding: 8px;
          border-radius: 8px;
          display: flex;
          align-items: center;
          border-bottom: 1px solid var(--divider-color);
        }
        .ep-row:last-child {
          border-bottom: none;
        }
        .ep-row:hover {
          background: var(--secondary-background-color);
        }
        .ep-row.active {
          background: rgba(var(--rgb-primary-color, 3, 169, 244), 0.14);
        }
        .ep-row.active .ep-row-title {
          color: var(--primary-color);
        }
        .ep-row-info {
          min-width: 0;
          flex: 1;
        }
        .ep-row-title {
          font-size: 13px;
          font-weight: 500;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .ep-row-meta {
          font-size: 11px;
          color: var(--secondary-text-color);
          margin-top: 2px;
        }
      </style>
      <ha-card>
        <div class="header">
          <img id="cover" class="cover" alt="Podcast Cover" />
          <div class="info">
            <div id="podcast-label" class="podcast-label">Wohnsinnig vernetzt</div>
            <div id="ep-title" class="ep-title">Lade Folgen…</div>
            <div id="ep-meta" class="ep-meta"></div>
          </div>
        </div>

        <div id="player-status" class="player-status"></div>

        <div class="progress-wrap">
          <span id="time-current">0:00</span>
          <input id="progress" type="range" min="0" max="100" value="0" />
          <span id="time-total">0:00</span>
        </div>

        <div class="controls">
          <button id="speed-btn" class="icon-btn" type="button">1x</button>
          <div class="controls-center">
            <button id="back-btn" class="icon-btn" type="button">-15s</button>
            <button id="play-btn" class="play-btn" type="button" aria-label="Abspielen / Pause"></button>
            <button id="fwd-btn" class="icon-btn" type="button">+30s</button>
          </div>
          <div style="width: 34px;"></div>
        </div>

        <button id="list-toggle" class="list-toggle" type="button">Alle Folgen anzeigen</button>
        <div id="list-section">
          <input id="search-input" class="search-input" type="search" placeholder="Folgen durchsuchen…" />
          <div id="episode-list" class="episode-list"></div>
        </div>
      </ha-card>
    `;

    this.shadowRoot.getElementById("play-btn").addEventListener("click", () => this._togglePlay());
    this.shadowRoot.getElementById("back-btn").addEventListener("click", () => this._skip(-15));
    this.shadowRoot.getElementById("fwd-btn").addEventListener("click", () => this._skip(30));
    this.shadowRoot.getElementById("speed-btn").addEventListener("click", () => this._cycleSpeed());
    this.shadowRoot.getElementById("progress").addEventListener("input", (e) => {
      const ep = this._episodes[this._currentIndex];
      if (ep && this._loadedTrackUrl === ep.audio_url) {
        this._audio.currentTime = Number(e.target.value);
      }
    });
    this.shadowRoot.getElementById("list-toggle").addEventListener("click", () => {
      this._listOpen = !this._listOpen;
      this._updateUI();
    });
    this.shadowRoot.getElementById("search-input").addEventListener("input", (e) => {
      this._searchQuery = e.target.value || "";
      this._renderEpisodeList();
    });

    this._updatePlayIcon();
  }
}

class WohnsinnigVernetztBlueprintsCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = { title: "Wohnsinnig vernetzt Blueprints" };
    this._blueprints = [];
    this._searchQuery = "";
    this._statusMsg = "";
    this._statusType = "";
    this._busyIds = new Set();
    this._busyAll = false;
    this._loaded = false;
    this._lastBpKey = null;
  }

  static getStubConfig() {
    return { title: "Wohnsinnig vernetzt Blueprints" };
  }

  connectedCallback() {
    if (this.shadowRoot.innerHTML === "") {
      this._renderShell();
    }
  }

  setConfig(config) {
    this._config = {
      title: "Wohnsinnig vernetzt Blueprints",
      ...(config || {}),
    };
    if (this.shadowRoot.innerHTML === "") {
      this._renderShell();
    }
  }

  set hass(hass) {
    this._hass = hass;
    const bpSensor =
      hass.states["sensor.wohnsinnig_vernetzt_blueprints"] ||
      Object.values(hass.states).find(
        (s) =>
          s.entity_id.startsWith("sensor.wohnsinnig_vernetzt") &&
          s.attributes &&
          "installed_count" in s.attributes
      );
    const bpKey = bpSensor
      ? `${bpSensor.state}:${bpSensor.attributes.installed_count}`
      : "";

    if (!this._loaded || (bpKey && bpKey !== this._lastBpKey)) {
      this._lastBpKey = bpKey;
      this._loaded = true;
      this._fetchBlueprints();
    }
  }

  getCardSize() {
    return 6;
  }

  async _fetchBlueprints() {
    if (!this._hass) return;
    try {
      const data = await this._hass.callApi("GET", "wohnsinnig_vernetzt/episodes");
      this._blueprints = data.blueprints || [];
      this._renderList();
    } catch (_) {
      this._statusMsg = "Blueprints konnten nicht geladen werden.";
      this._statusType = "error";
      this._renderList();
    }
  }

  async _importOne(bp) {
    if (!this._hass || !bp) return;
    this._busyIds.add(bp.id);
    this._statusMsg = `Importiere „${bp.title}“…`;
    this._statusType = "";
    this._renderList();

    try {
      const resp = await this._hass.callApi(
        "POST",
        "wohnsinnig_vernetzt/import_blueprint",
        { url: bp.url, blueprint_id: bp.id }
      );
      if (Array.isArray(resp.blueprints)) this._blueprints = resp.blueprints;
      this._statusMsg = `„${bp.title}“ in Home Assistant importiert!`;
      this._statusType = "ok";
    } catch (err) {
      this._statusMsg = err?.body?.error || err?.message || "Import fehlgeschlagen.";
      this._statusType = "error";
    } finally {
      this._busyIds.delete(bp.id);
      this._renderList();
    }
  }

  async _importAll() {
    if (!this._hass || this._busyAll) return;
    this._busyAll = true;
    this._statusMsg = "Importiere alle Blueprints…";
    this._statusType = "";
    this._renderList();

    try {
      const resp = await this._hass.callApi(
        "POST",
        "wohnsinnig_vernetzt/import_blueprint",
        { import_all: true }
      );
      if (Array.isArray(resp.blueprints)) this._blueprints = resp.blueprints;
      const count = Array.isArray(resp.imported) ? resp.imported.length : 0;
      this._statusMsg = `${count} Blueprints importiert!`;
      this._statusType = "ok";
    } catch (err) {
      this._statusMsg = err?.body?.error || err?.message || "Import fehlgeschlagen.";
      this._statusType = "error";
    } finally {
      this._busyAll = false;
      this._renderList();
    }
  }

  _renderList() {
    const titleEl = this.shadowRoot.getElementById("card-title");
    const statusEl = this.shadowRoot.getElementById("bp-status");
    const importAllBtn = this.shadowRoot.getElementById("bp-import-all");
    const listEl = this.shadowRoot.getElementById("bp-list");

    if (titleEl) titleEl.textContent = this._config.title;
    if (importAllBtn) {
      importAllBtn.disabled = this._busyAll || this._blueprints.length === 0;
      importAllBtn.textContent = this._busyAll ? "Importiert…" : "Alle importieren";
    }
    if (statusEl) {
      statusEl.textContent = this._statusMsg;
      statusEl.className = `bp-status ${this._statusType}`;
      statusEl.style.display = this._statusMsg ? "block" : "none";
    }
    if (!listEl) return;

    listEl.innerHTML = "";
    const q = this._searchQuery.trim().toLowerCase();
    const filtered = this._blueprints.filter(
      (bp) =>
        !q ||
        bp.title.toLowerCase().includes(q) ||
        (bp.description || "").toLowerCase().includes(q)
    );

    if (!filtered.length) {
      const empty = document.createElement("div");
      empty.className = "empty-hint";
      empty.textContent = "Keine Blueprints gefunden.";
      listEl.appendChild(empty);
      return;
    }

    filtered.forEach((bp) => {
      const item = document.createElement("div");
      item.className = "bp-item";

      const head = document.createElement("div");
      head.className = "bp-head";

      const tWrap = document.createElement("div");
      tWrap.className = "bp-title-wrap";

      const t = document.createElement("div");
      t.className = "bp-title";
      t.textContent = bp.title;
      tWrap.appendChild(t);

      if (bp.update_available) {
        const badge = document.createElement("span");
        badge.className = "bp-badge update";
        badge.textContent = "⬆ Update verfügbar";
        tWrap.appendChild(badge);
      } else if (bp.installed) {
        const badge = document.createElement("span");
        badge.className = "bp-badge";
        badge.textContent = "✓ Aktuell";
        tWrap.appendChild(badge);
      }

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `bp-btn ${bp.installed && !bp.update_available ? "secondary" : ""}`;
      const busy = this._busyIds.has(bp.id) || this._busyAll;
      btn.disabled = busy;
      btn.textContent = busy
        ? "…"
        : bp.update_available
        ? "Update"
        : bp.installed
        ? "Neu laden"
        : "Importieren";
      btn.addEventListener("click", () => this._importOne(bp));

      head.appendChild(tWrap);
      head.appendChild(btn);
      item.appendChild(head);

      if (bp.description) {
        const desc = document.createElement("div");
        desc.className = "bp-desc";
        desc.textContent = bp.description;
        item.appendChild(desc);
      }
      listEl.appendChild(item);
    });
  }

  _renderShell() {
    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding: 14px; color: var(--primary-text-color); }
        .top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
        .title { font-size: 15px; font-weight: 600; }
        .subbar { display: flex; align-items: center; justify-content: space-between; margin-top: 6px; }
        .link { font-size: 12px; color: var(--primary-color); text-decoration: none; }
        .search { width: 100%; box-sizing: border-box; padding: 8px 10px; border-radius: 8px; border: 1px solid var(--divider-color); background: var(--secondary-background-color); color: var(--primary-text-color); font-family: inherit; font-size: 13px; margin-top: 8px; }
        .bp-status { display: none; margin-top: 8px; padding: 7px 10px; border-radius: 8px; font-size: 12px; background: var(--secondary-background-color); }
        .bp-status.ok { color: var(--success-color, #4caf50); background: rgba(76, 175, 80, 0.12); }
        .bp-status.error { color: var(--error-color, #db4437); background: rgba(219, 68, 55, 0.12); }
        .bp-list { margin-top: 8px; max-height: 300px; overflow-y: auto; }
        .empty-hint { font-size: 12px; color: var(--secondary-text-color); padding: 10px 4px; text-align: center; }
        .bp-item { padding: 10px 6px; border-bottom: 1px solid var(--divider-color); }
        .bp-item:last-child { border-bottom: none; }
        .bp-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
        .bp-title-wrap { min-width: 0; flex: 1; }
        .bp-title { font-size: 13px; font-weight: 600; }
        .bp-badge { display: inline-block; margin-top: 3px; font-size: 10px; font-weight: 600; padding: 2px 6px; border-radius: 999px; color: var(--success-color, #4caf50); background: rgba(76, 175, 80, 0.14); } .bp-badge.update { color: var(--warning-color, #ff9800); background: rgba(255, 152, 0, 0.16); }
        .bp-desc { font-size: 12px; color: var(--secondary-text-color); margin-top: 4px; line-height: 1.35; }
        button { border: none; cursor: pointer; font-family: inherit; }
        .bp-btn { padding: 6px 11px; border-radius: 8px; font-size: 12px; font-weight: 600; background: var(--primary-color); color: var(--text-primary-color, #fff); flex-shrink: 0; }
        .bp-btn.secondary { background: var(--secondary-background-color); color: var(--primary-text-color); border: 1px solid var(--divider-color); }
        .bp-btn:disabled { opacity: 0.55; cursor: default; }
      </style>
      <ha-card>
        <div class="top">
          <div id="card-title" class="title">Wohnsinnig vernetzt Blueprints</div>
          <button id="bp-import-all" class="bp-btn" type="button">Alle importieren</button>
        </div>
        <div class="subbar">
          <a class="link" href="/config/blueprint/dashboard">Zu HA-Blueprints ↗</a>
        </div>
        <div id="bp-status" class="bp-status"></div>
        <input id="bp-search" class="search" type="search" placeholder="Blueprints durchsuchen…" />
        <div id="bp-list" class="bp-list"></div>
      </ha-card>
    `;
    this.shadowRoot.getElementById("bp-import-all").addEventListener("click", () => this._importAll());
    this.shadowRoot.getElementById("bp-search").addEventListener("input", (e) => {
      this._searchQuery = e.target.value || "";
      this._renderList();
    });
  }
}

if (!customElements.get("wohnsinnig-vernetzt-card")) {
  customElements.define("wohnsinnig-vernetzt-card", WohnsinnigVernetztCard);
}
if (!customElements.get("wohnsinnig-vernetzt-blueprints-card")) {
  customElements.define("wohnsinnig-vernetzt-blueprints-card", WohnsinnigVernetztBlueprintsCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "wohnsinnig-vernetzt-card")) {
  window.customCards.push({
    type: "wohnsinnig-vernetzt-card",
    name: "Wohnsinnig vernetzt Player",
    description: "Kompakter Podcast-Player für Wohnsinnig vernetzt – Folge auswählen und Play drücken.",
  });
}
if (!window.customCards.some((c) => c.type === "wohnsinnig-vernetzt-blueprints-card")) {
  window.customCards.push({
    type: "wohnsinnig-vernetzt-blueprints-card",
    name: "Wohnsinnig vernetzt Blueprints",
    description: "Blueprints von wohnsinnigvernetzt.de direkt in Home Assistant importieren.",
  });
}
class WohnsinnigVernetztBatteryCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {
      title: "Batterie-Check",
      open_default: false,
    };
    this._open = false;
    this._showExcluded = false;
    this._busy = false;
    this._liveData = null;
    this._lastKey = null;
  }

  static getStubConfig() {
    return {
      title: "Batterie-Check",
      open_default: false,
    };
  }

  connectedCallback() {
    if (this.shadowRoot.innerHTML === "") {
      this._renderShell();
    }
    this._render();
  }

  setConfig(config) {
    this._config = {
      title: "Batterie-Check",
      open_default: false,
      ...(config || {}),
    };
    this._open = Boolean(this._config.open_default);
    if (this.shadowRoot.innerHTML === "") {
      this._renderShell();
    }
    this._render();
  }

  _findBatterySensor(hass) {
    if (!hass || !hass.states) return null;
    if (hass.states["sensor.wohnsinnig_vernetzt_batterie_check"]) {
      return hass.states["sensor.wohnsinnig_vernetzt_batterie_check"];
    }
    return Object.values(hass.states).find(
      (s) =>
        s.entity_id.startsWith("sensor.wohnsinnig_vernetzt") &&
        s.attributes &&
        "schwellwert" in s.attributes &&
        "devices" in s.attributes
    );
  }

  set hass(hass) {
    this._hass = hass;
    if (this.shadowRoot.innerHTML === "") {
      this._renderShell();
    }
    const sensor = this._findBatterySensor(hass);
    const key = sensor
      ? `${sensor.state}|${sensor.attributes.geprueft_am || ""}|${sensor.attributes.anzahl ?? ""}|${sensor.attributes.ausgeschlossen_anzahl ?? ""}`
      : "none";
    if (key !== this._lastKey) {
      this._lastKey = key;
      this._liveData = null;
      this._render();
    }
  }

  getCardSize() {
    return this._open ? 5 : 2;
  }

  _openMoreInfo(entityId) {
    if (!entityId) return;
    this.dispatchEvent(
      new CustomEvent("hass-more-info", {
        bubbles: true,
        composed: true,
        detail: { entityId },
      })
    );
  }

  async _fetchLiveCheck() {
    if (!this._hass || this._busy) return;
    this._busy = true;
    this._render();
    try {
      const data = await this._hass.callApi("GET", "wohnsinnig_vernetzt/battery_check");
      if (data && Array.isArray(data.devices)) {
        this._liveData = data;
      }
    } catch (_) {
      // Fallback auf Sensor-Attribute
    } finally {
      this._busy = false;
      this._render();
    }
  }

  async _updateExclusion(action, key, ev) {
    if (ev) ev.stopPropagation();
    if (!this._hass || this._busy || !key) return;
    this._busy = true;
    this._render();
    try {
      const resp = await this._hass.callApi(
        "POST",
        "wohnsinnig_vernetzt/battery_exclusions",
        { action, key }
      );
      if (resp && resp.battery_check) {
        this._liveData = resp.battery_check;
      }
    } catch (_) {
      // ignore
    } finally {
      this._busy = false;
      this._render();
    }
  }

  _toggleOpen() {
    this._open = !this._open;
    this._render();
    if (this._open) {
      this._fetchLiveCheck();
    }
  }

  _render() {
    if (!this.shadowRoot || this.shadowRoot.innerHTML === "") return;
    const sensor = this._findBatterySensor(this._hass);
    const titleEl = this.shadowRoot.getElementById("bc-title");
    const subEl = this.shadowRoot.getElementById("bc-sub");
    const badgeEl = this.shadowRoot.getElementById("bc-badge");
    const chevronEl = this.shadowRoot.getElementById("bc-chevron");
    const listWrap = this.shadowRoot.getElementById("bc-list-wrap");
    const listEl = this.shadowRoot.getElementById("bc-list");
    const refreshBtn = this.shadowRoot.getElementById("bc-refresh");
    const exclWrap = this.shadowRoot.getElementById("bc-excl-wrap");
    const exclToggle = this.shadowRoot.getElementById("bc-excl-toggle");
    const exclList = this.shadowRoot.getElementById("bc-excl-list");

    if (titleEl) titleEl.textContent = this._config.title || "Batterie-Check";
    if (refreshBtn) {
      refreshBtn.disabled = this._busy;
      refreshBtn.textContent = this._busy ? "…" : "↻";
    }

    const attrs = sensor?.attributes || {};
    const devices = this._liveData
      ? this._liveData.devices
      : Array.isArray(attrs.devices)
      ? attrs.devices
      : [];
    const excludedDevices = this._liveData
      ? this._liveData.excluded_devices || []
      : Array.isArray(attrs.excluded_devices)
      ? attrs.excluded_devices
      : [];
    const count = this._liveData
      ? this._liveData.low_battery_count
      : Number.isFinite(attrs.anzahl)
      ? attrs.anzahl
      : devices.length;
    const threshold = this._liveData
      ? `< ${this._liveData.battery_threshold} %`
      : attrs.schwellwert || "< 15 %";
    const checkedAt = this._liveData
      ? this._liveData.checked_at
      : attrs.geprueft_am || "";
    const badgeText = this._liveData
      ? this._liveData.status
      : attrs.status || (count === 0 ? "OK" : `${count} ${count === 1 ? "Gerät" : "Geräte"} ${threshold}`);

    if (subEl) {
      const exclHint = excludedDevices.length
        ? ` • ${excludedDevices.length} ausgeschl.`
        : "";
      subEl.textContent = checkedAt
        ? `Grenze ${threshold} • Stand: ${checkedAt}${exclHint}`
        : `1 Klick zeigt alle Geräte ${threshold}${exclHint}`;
    }

    if (badgeEl) {
      badgeEl.textContent = badgeText;
      badgeEl.className = `bc-badge ${count > 0 ? "warn" : "ok"}`;
    }

    if (chevronEl) {
      chevronEl.textContent = this._open ? "▲" : "▼";
    }

    if (listWrap) {
      listWrap.style.display = this._open ? "block" : "none";
    }

    if (listEl) {
      listEl.innerHTML = "";

      if (!devices.length) {
        const okEl = document.createElement("div");
        okEl.className = "bc-empty";
        okEl.textContent = `Alle Batterien sind im grünen Bereich (keine Geräte ${threshold}).`;
        listEl.appendChild(okEl);
      } else {
        devices.forEach((dev) => {
          const row = document.createElement("div");
          row.className = "bc-row";

          const mainBtn = document.createElement("button");
          mainBtn.type = "button";
          mainBtn.className = "bc-row-main";
          mainBtn.addEventListener("click", () => this._openMoreInfo(dev.entity_id));

          const left = document.createElement("div");
          left.className = "bc-row-left";

          const name = document.createElement("div");
          name.className = "bc-row-name";
          name.textContent = dev.name || dev.entity_id;

          const barBg = document.createElement("div");
          barBg.className = "bc-bar-bg";
          const barFill = document.createElement("div");
          barFill.className = "bc-bar-fill";
          const pct = Math.max(0, Math.min(100, Number(dev.level) || 0));
          barFill.style.width = `${Math.max(4, pct)}%`;
          barBg.appendChild(barFill);

          left.appendChild(name);
          left.appendChild(barBg);

          const pctEl = document.createElement("div");
          pctEl.className = "bc-pct";
          pctEl.textContent = dev.level_formatted || `${pct} %`;

          mainBtn.appendChild(left);
          mainBtn.appendChild(pctEl);

          const exclBtn = document.createElement("button");
          exclBtn.type = "button";
          exclBtn.className = "bc-action-btn";
          exclBtn.title = "Gerät vom Batterie-Check ausschließen";
          exclBtn.disabled = this._busy;
          exclBtn.textContent = "✕";
          const exclKey = dev.dedup_key || dev.entity_id;
          exclBtn.addEventListener("click", (ev) =>
            this._updateExclusion("exclude", exclKey, ev)
          );

          row.appendChild(mainBtn);
          row.appendChild(exclBtn);
          listEl.appendChild(row);
        });
      }
    }

    if (exclWrap && exclToggle && exclList) {
      if (!excludedDevices.length) {
        exclWrap.style.display = "none";
      } else {
        exclWrap.style.display = "block";
        exclToggle.textContent = this._showExcluded
          ? `Ausgeschlossene Geräte ausblenden (${excludedDevices.length})`
          : `🚫 Ausgeschlossene Geräte anzeigen (${excludedDevices.length})`;
        exclList.style.display = this._showExcluded ? "block" : "none";
        exclList.innerHTML = "";

        if (this._showExcluded) {
          excludedDevices.forEach((dev) => {
            const row = document.createElement("div");
            row.className = "bc-excl-row";

            const info = document.createElement("div");
            info.className = "bc-excl-name";
            const lvlPart =
              dev.level !== null && dev.level !== undefined
                ? ` (${dev.level_formatted})`
                : "";
            info.textContent = `${dev.name}${lvlPart}`;

            const restoreBtn = document.createElement("button");
            restoreBtn.type = "button";
            restoreBtn.className = "bc-restore-btn";
            restoreBtn.disabled = this._busy;
            restoreBtn.textContent = "↩ Aufnehmen";
            restoreBtn.addEventListener("click", (ev) =>
              this._updateExclusion("include", dev.dedup_key || dev.entity_id, ev)
            );

            row.appendChild(info);
            row.appendChild(restoreBtn);
            exclList.appendChild(row);
          });
        }
      }
    }
  }

  _renderShell() {
    this.shadowRoot.innerHTML = `
      <style>
        ha-card {
          padding: 12px 14px;
          color: var(--primary-text-color);
        }
        .bc-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
          cursor: pointer;
          user-select: none;
        }
        .bc-left {
          display: flex;
          align-items: center;
          gap: 10px;
          min-width: 0;
          flex: 1;
        }
        .bc-icon {
          width: 36px;
          height: 36px;
          border-radius: 10px;
          background: var(--secondary-background-color);
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 18px;
          flex-shrink: 0;
        }
        .bc-titles {
          min-width: 0;
          flex: 1;
        }
        .bc-title {
          font-size: 14px;
          font-weight: 600;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .bc-sub {
          font-size: 11px;
          color: var(--secondary-text-color);
          margin-top: 2px;
        }
        .bc-right {
          display: flex;
          align-items: center;
          gap: 6px;
          flex-shrink: 0;
        }
        .bc-badge {
          font-size: 11px;
          font-weight: 600;
          padding: 3px 8px;
          border-radius: 999px;
        }
        .bc-badge.ok {
          color: var(--success-color, #4caf50);
          background: rgba(76, 175, 80, 0.14);
        }
        .bc-badge.warn {
          color: var(--error-color, #db4437);
          background: rgba(219, 68, 55, 0.15);
        }
        .bc-refresh {
          background: none;
          border: none;
          color: var(--secondary-text-color);
          cursor: pointer;
          font-size: 15px;
          padding: 4px 6px;
          border-radius: 6px;
        }
        .bc-refresh:hover {
          background: var(--secondary-background-color);
          color: var(--primary-text-color);
        }
        .bc-chevron {
          font-size: 10px;
          color: var(--secondary-text-color);
        }
        .bc-list-wrap {
          margin-top: 10px;
          padding-top: 8px;
          border-top: 1px solid var(--divider-color);
          display: none;
        }
        .bc-list {
          max-height: 260px;
          overflow-y: auto;
        }
        .bc-empty {
          font-size: 12px;
          color: var(--secondary-text-color);
          text-align: center;
          padding: 8px 4px;
        }
        .bc-row {
          display: flex;
          align-items: center;
          gap: 6px;
          border-bottom: 1px solid var(--divider-color);
          padding: 2px 0;
        }
        .bc-row:last-child {
          border-bottom: none;
        }
        .bc-row-main {
          flex: 1;
          min-width: 0;
          background: none;
          border: none;
          color: var(--primary-text-color);
          cursor: pointer;
          font-family: inherit;
          text-align: left;
          padding: 6px 6px;
          border-radius: 8px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
        }
        .bc-row-main:hover {
          background: var(--secondary-background-color);
        }
        .bc-row-left {
          min-width: 0;
          flex: 1;
        }
        .bc-row-name {
          font-size: 13px;
          font-weight: 500;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .bc-bar-bg {
          width: 100%;
          height: 4px;
          border-radius: 2px;
          background: var(--secondary-background-color);
          margin-top: 4px;
          overflow: hidden;
        }
        .bc-bar-fill {
          height: 100%;
          background: var(--error-color, #db4437);
          border-radius: 2px;
        }
        .bc-pct {
          font-size: 13px;
          font-weight: 700;
          color: var(--error-color, #db4437);
          font-variant-numeric: tabular-nums;
          flex-shrink: 0;
        }
        .bc-action-btn {
          background: none;
          border: 1px solid transparent;
          color: var(--secondary-text-color);
          cursor: pointer;
          font-size: 12px;
          width: 26px;
          height: 26px;
          border-radius: 6px;
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
        }
        .bc-action-btn:hover {
          background: var(--secondary-background-color);
          color: var(--error-color, #db4437);
          border-color: var(--divider-color);
        }
        .bc-action-btn:disabled {
          opacity: 0.45;
          cursor: default;
        }
        .bc-excl-wrap {
          display: none;
          margin-top: 8px;
          padding-top: 8px;
          border-top: 1px dashed var(--divider-color);
        }
        .bc-excl-toggle {
          width: 100%;
          background: none;
          border: none;
          color: var(--secondary-text-color);
          cursor: pointer;
          font-family: inherit;
          font-size: 11px;
          text-align: center;
          padding: 4px;
        }
        .bc-excl-toggle:hover {
          color: var(--primary-color);
        }
        .bc-excl-list {
          margin-top: 4px;
          max-height: 160px;
          overflow-y: auto;
        }
        .bc-excl-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
          padding: 5px 4px;
          font-size: 12px;
          color: var(--secondary-text-color);
        }
        .bc-excl-name {
          min-width: 0;
          flex: 1;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .bc-restore-btn {
          background: var(--secondary-background-color);
          border: 1px solid var(--divider-color);
          color: var(--primary-text-color);
          cursor: pointer;
          font-family: inherit;
          font-size: 11px;
          padding: 3px 8px;
          border-radius: 6px;
          flex-shrink: 0;
        }
        .bc-restore-btn:hover {
          border-color: var(--primary-color);
          color: var(--primary-color);
        }
        .bc-restore-btn:disabled {
          opacity: 0.5;
          cursor: default;
        }
      </style>
      <ha-card>
        <div id="bc-header" class="bc-header">
          <div class="bc-left">
            <div class="bc-icon">🔋</div>
            <div class="bc-titles">
              <div id="bc-title" class="bc-title">Batterie-Check</div>
              <div id="bc-sub" class="bc-sub"></div>
            </div>
          </div>
          <div class="bc-right">
            <span id="bc-badge" class="bc-badge ok">OK</span>
            <button id="bc-refresh" class="bc-refresh" type="button" title="Jetzt prüfen">↻</button>
            <span id="bc-chevron" class="bc-chevron">▼</span>
          </div>
        </div>
        <div id="bc-list-wrap" class="bc-list-wrap">
          <div id="bc-list" class="bc-list"></div>
          <div id="bc-excl-wrap" class="bc-excl-wrap">
            <button id="bc-excl-toggle" class="bc-excl-toggle" type="button"></button>
            <div id="bc-excl-list" class="bc-excl-list"></div>
          </div>
        </div>
      </ha-card>
    `;

    this.shadowRoot.getElementById("bc-header").addEventListener("click", () => {
      this._toggleOpen();
    });
    this.shadowRoot.getElementById("bc-refresh").addEventListener("click", (ev) => {
      ev.stopPropagation();
      this._open = true;
      this._fetchLiveCheck();
    });
    this.shadowRoot.getElementById("bc-excl-toggle").addEventListener("click", () => {
      this._showExcluded = !this._showExcluded;
      this._render();
    });
  }
}

if (!customElements.get("wohnsinnig-vernetzt-battery-card")) {
  customElements.define("wohnsinnig-vernetzt-battery-card", WohnsinnigVernetztBatteryCard);
}
if (!window.customCards.some((c) => c.type === "wohnsinnig-vernetzt-battery-card")) {
  window.customCards.push({
    type: "wohnsinnig-vernetzt-battery-card",
    name: "Wohnsinnig vernetzt Batterie-Check",
    description: "Zeigt auf einen Klick live alle Geräte unter der Batterie-Grenze – inkl. 1-Klick-Ausschluss.",
  });
}

class WohnsinnigVernetztSilentSensorsCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {
      title: "Stille Sensoren",
      open_default: false,
    };
    this._open = false;
    this._busy = false;
    this._liveData = null;
    this._lastKey = null;
  }

  static getStubConfig() {
    return {
      title: "Stille Sensoren",
      open_default: false,
    };
  }

  connectedCallback() {
    if (this.shadowRoot.innerHTML === "") {
      this._renderShell();
    }
    this._render();
  }

  setConfig(config) {
    this._config = {
      title: "Stille Sensoren",
      open_default: false,
      ...(config || {}),
    };
    this._open = Boolean(this._config.open_default);
    if (this.shadowRoot.innerHTML === "") {
      this._renderShell();
    }
    this._render();
  }

  _findSilentSensor(hass) {
    if (!hass || !hass.states) return null;
    if (hass.states["sensor.wohnsinnig_vernetzt_stille_sensoren"]) {
      return hass.states["sensor.wohnsinnig_vernetzt_stille_sensoren"];
    }
    return Object.values(hass.states).find(
      (s) =>
        s.entity_id.startsWith("sensor.wohnsinnig_vernetzt") &&
        s.attributes &&
        typeof s.attributes.schwellwert === "string" &&
        s.attributes.schwellwert.startsWith(">") &&
        "devices" in s.attributes
    );
  }

  set hass(hass) {
    this._hass = hass;
    if (this.shadowRoot.innerHTML === "") {
      this._renderShell();
    }
    const sensor = this._findSilentSensor(hass);
    const key = sensor
      ? `${sensor.state}|${sensor.attributes.geprueft_am || ""}|${sensor.attributes.anzahl ?? ""}`
      : "none";
    if (key !== this._lastKey) {
      this._lastKey = key;
      this._liveData = null;
      this._render();
    }
  }

  getCardSize() {
    return this._open ? 5 : 2;
  }

  _openMoreInfo(entityId) {
    if (!entityId) return;
    this.dispatchEvent(
      new CustomEvent("hass-more-info", {
        bubbles: true,
        composed: true,
        detail: { entityId },
      })
    );
  }

  async _fetchLiveCheck() {
    if (!this._hass || this._busy) return;
    this._busy = true;
    this._render();
    try {
      const data = await this._hass.callApi("GET", "wohnsinnig_vernetzt/silent_sensors");
      if (data && Array.isArray(data.devices)) {
        this._liveData = data;
      }
    } catch (_) {
      // Fallback auf Sensor-Attribute
    } finally {
      this._busy = false;
      this._render();
    }
  }

  _toggleOpen() {
    this._open = !this._open;
    this._render();
    if (this._open) {
      this._fetchLiveCheck();
    }
  }

  _render() {
    if (!this.shadowRoot || this.shadowRoot.innerHTML === "") return;
    const sensor = this._findSilentSensor(this._hass);
    const titleEl = this.shadowRoot.getElementById("ss-title");
    const subEl = this.shadowRoot.getElementById("ss-sub");
    const badgeEl = this.shadowRoot.getElementById("ss-badge");
    const chevronEl = this.shadowRoot.getElementById("ss-chevron");
    const listWrap = this.shadowRoot.getElementById("ss-list-wrap");
    const listEl = this.shadowRoot.getElementById("ss-list");
    const refreshBtn = this.shadowRoot.getElementById("ss-refresh");

    if (titleEl) titleEl.textContent = this._config.title || "Stille Sensoren";
    if (refreshBtn) {
      refreshBtn.disabled = this._busy;
      refreshBtn.textContent = this._busy ? "…" : "↻";
    }

    const attrs = sensor?.attributes || {};
    const devices = this._liveData
      ? this._liveData.devices
      : Array.isArray(attrs.devices)
      ? attrs.devices
      : [];
    const count = this._liveData
      ? this._liveData.silent_count
      : Number.isFinite(attrs.anzahl)
      ? attrs.anzahl
      : devices.length;
    const threshold = this._liveData
      ? `> ${this._liveData.silent_hours} h`
      : attrs.schwellwert || "> 24 h";
    const checkedAt = this._liveData
      ? this._liveData.checked_at
      : attrs.geprueft_am || "";
    const badgeText = this._liveData
      ? this._liveData.status
      : attrs.status || (count === 0 ? "Alle aktiv" : `${count} ${count === 1 ? "Sensor" : "Sensoren"} ${threshold}`);

    if (subEl) {
      subEl.textContent = checkedAt
        ? `Grenze ${threshold} • Stand: ${checkedAt}`
        : `1 Klick zeigt alle stillen Sensoren ${threshold}`;
    }

    if (badgeEl) {
      badgeEl.textContent = badgeText;
      badgeEl.className = `ss-badge ${count > 0 ? "warn" : "ok"}`;
    }

    if (chevronEl) {
      chevronEl.textContent = this._open ? "▲" : "▼";
    }

    if (listWrap) {
      listWrap.style.display = this._open ? "block" : "none";
    }

    if (!listEl) return;
    listEl.innerHTML = "";

    if (!devices.length) {
      const okEl = document.createElement("div");
      okEl.className = "ss-empty";
      okEl.textContent = `Alle überwachten Sensoren melden sich regelmäßig (keine Sensoren ${threshold} still).`;
      listEl.appendChild(okEl);
      return;
    }

    devices.forEach((dev) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "ss-row";
      row.addEventListener("click", () => this._openMoreInfo(dev.entity_id));

      const left = document.createElement("div");
      left.className = "ss-row-left";

      const name = document.createElement("div");
      name.className = "ss-row-name";
      name.textContent = dev.name || dev.entity_id;

      const meta = document.createElement("div");
      meta.className = "ss-row-meta";
      meta.textContent = dev.last_seen
        ? `Zuletzt gesehen: ${dev.last_seen}`
        : dev.entity_id;

      left.appendChild(name);
      left.appendChild(meta);

      const durEl = document.createElement("div");
      durEl.className = "ss-dur";
      durEl.textContent = dev.duration_formatted || `${Math.round(dev.hours_silent || 0)} h`;

      row.appendChild(left);
      row.appendChild(durEl);
      listEl.appendChild(row);
    });
  }

  _renderShell() {
    this.shadowRoot.innerHTML = `
      <style>
        ha-card {
          padding: 12px 14px;
          color: var(--primary-text-color);
        }
        .ss-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
          cursor: pointer;
          user-select: none;
        }
        .ss-left {
          display: flex;
          align-items: center;
          gap: 10px;
          min-width: 0;
          flex: 1;
        }
        .ss-icon {
          width: 36px;
          height: 36px;
          border-radius: 10px;
          background: var(--secondary-background-color);
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 18px;
          flex-shrink: 0;
        }
        .ss-titles {
          min-width: 0;
          flex: 1;
        }
        .ss-title {
          font-size: 14px;
          font-weight: 600;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .ss-sub {
          font-size: 11px;
          color: var(--secondary-text-color);
          margin-top: 2px;
        }
        .ss-right {
          display: flex;
          align-items: center;
          gap: 6px;
          flex-shrink: 0;
        }
        .ss-badge {
          font-size: 11px;
          font-weight: 600;
          padding: 3px 8px;
          border-radius: 999px;
        }
        .ss-badge.ok {
          color: var(--success-color, #4caf50);
          background: rgba(76, 175, 80, 0.14);
        }
        .ss-badge.warn {
          color: var(--warning-color, #ff9800);
          background: rgba(255, 152, 0, 0.16);
        }
        .ss-refresh {
          background: none;
          border: none;
          color: var(--secondary-text-color);
          cursor: pointer;
          font-size: 15px;
          padding: 4px 6px;
          border-radius: 6px;
        }
        .ss-refresh:hover {
          background: var(--secondary-background-color);
          color: var(--primary-text-color);
        }
        .ss-chevron {
          font-size: 10px;
          color: var(--secondary-text-color);
        }
        .ss-list-wrap {
          margin-top: 10px;
          padding-top: 8px;
          border-top: 1px solid var(--divider-color);
          display: none;
        }
        .ss-list {
          max-height: 260px;
          overflow-y: auto;
        }
        .ss-empty {
          font-size: 12px;
          color: var(--secondary-text-color);
          text-align: center;
          padding: 8px 4px;
        }
        .ss-row {
          width: 100%;
          background: none;
          border: none;
          color: var(--primary-text-color);
          cursor: pointer;
          font-family: inherit;
          text-align: left;
          padding: 7px 6px;
          border-radius: 8px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
          border-bottom: 1px solid var(--divider-color);
        }
        .ss-row:last-child {
          border-bottom: none;
        }
        .ss-row:hover {
          background: var(--secondary-background-color);
        }
        .ss-row-left {
          min-width: 0;
          flex: 1;
        }
        .ss-row-name {
          font-size: 13px;
          font-weight: 500;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .ss-row-meta {
          font-size: 11px;
          color: var(--secondary-text-color);
          margin-top: 2px;
        }
        .ss-dur {
          font-size: 12px;
          font-weight: 700;
          color: var(--warning-color, #ff9800);
          font-variant-numeric: tabular-nums;
          flex-shrink: 0;
        }
      </style>
      <ha-card>
        <div id="ss-header" class="ss-header">
          <div class="ss-left">
            <div class="ss-icon">🤫</div>
            <div class="ss-titles">
              <div id="ss-title" class="ss-title">Stille Sensoren</div>
              <div id="ss-sub" class="ss-sub"></div>
            </div>
          </div>
          <div class="ss-right">
            <span id="ss-badge" class="ss-badge ok">Alle aktiv</span>
            <button id="ss-refresh" class="ss-refresh" type="button" title="Jetzt prüfen">↻</button>
            <span id="ss-chevron" class="ss-chevron">▼</span>
          </div>
        </div>
        <div id="ss-list-wrap" class="ss-list-wrap">
          <div id="ss-list" class="ss-list"></div>
        </div>
      </ha-card>
    `;

    this.shadowRoot.getElementById("ss-header").addEventListener("click", () => {
      this._toggleOpen();
    });
    this.shadowRoot.getElementById("ss-refresh").addEventListener("click", (ev) => {
      ev.stopPropagation();
      this._open = true;
      this._fetchLiveCheck();
    });
  }
}

if (!customElements.get("wohnsinnig-vernetzt-silent-sensors-card")) {
  customElements.define("wohnsinnig-vernetzt-silent-sensors-card", WohnsinnigVernetztSilentSensorsCard);
}
if (!window.customCards.some((c) => c.type === "wohnsinnig-vernetzt-silent-sensors-card")) {
  window.customCards.push({
    type: "wohnsinnig-vernetzt-silent-sensors-card",
    name: "Wohnsinnig vernetzt Stille Sensoren",
    description: "Erkennt stumm eingefrorene Sensoren (Zigbee-Freeze) auf einen Klick.",
  });
}
class WohnsinnigVernetztPresenceCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {
      title: "Anwesenheitssimulation",
      show_schedule_default: false,
    };
    this._open = false;
    this._busy = false;
    this._errorMsg = "";
    this._lastKey = null;
  }

  static getStubConfig() {
    return {
      title: "Anwesenheitssimulation",
      show_schedule_default: false,
    };
  }

  connectedCallback() {
    if (this.shadowRoot.innerHTML === "") {
      this._renderShell();
    }
    this._render();
  }

  setConfig(config) {
    this._config = {
      title: "Anwesenheitssimulation",
      show_schedule_default: false,
      ...(config || {}),
    };
    this._open = Boolean(this._config.show_schedule_default);
    if (this.shadowRoot.innerHTML === "") {
      this._renderShell();
    }
    this._render();
  }

  _findEntities(hass) {
    if (!hass || !hass.states) return { sw: null, sensor: null };
    const sw =
      hass.states["switch.wohnsinnig_vernetzt_anwesenheitssimulation"] ||
      Object.values(hass.states).find(
        (s) =>
          s.entity_id.startsWith("switch.wohnsinnig_vernetzt") &&
          s.attributes &&
          "abgewehrte_eingriffe" in s.attributes
      );
    const sensor =
      hass.states["sensor.wohnsinnig_vernetzt_anwesenheitssimulation_status"] ||
      Object.values(hass.states).find(
        (s) =>
          s.entity_id.startsWith("sensor.wohnsinnig_vernetzt") &&
          s.attributes &&
          "geplante_schaltungen" in s.attributes
      );
    return { sw, sensor };
  }

  set hass(hass) {
    this._hass = hass;
    if (this.shadowRoot.innerHTML === "") {
      this._renderShell();
    }
    const { sw, sensor } = this._findEntities(hass);
    const key = [
      sw ? sw.state : "",
      sensor ? sensor.state : "",
      sensor?.attributes?.geplante_anzahl ?? "",
      sensor?.attributes?.abgewehrte_eingriffe ?? "",
      sensor?.attributes?.geraete_anzahl ?? "",
    ].join("|");
    if (key !== this._lastKey) {
      this._lastKey = key;
      this._render();
    }
  }

  getCardSize() {
    return this._open ? 6 : 3;
  }

  async _toggleMaster(ev) {
    if (ev) ev.stopPropagation();
    if (!this._hass || this._busy) return;
    const { sw } = this._findEntities(this._hass);
    if (!sw) return;

    this._busy = true;
    this._errorMsg = "";
    this._render();

    try {
      const targetSvc = sw.state === "on" ? "turn_off" : "turn_on";
      await this._hass.callService("switch", targetSvc, {
        entity_id: sw.entity_id,
      });
    } catch (err) {
      this._errorMsg =
        err?.message || "Bitte zuerst Lampen/Schalter in den Optionen auswählen.";
    } finally {
      this._busy = false;
      this._render();
    }
  }

  _render() {
    if (!this.shadowRoot || this.shadowRoot.innerHTML === "") return;
    const { sw, sensor } = this._findEntities(this._hass);

    const titleEl = this.shadowRoot.getElementById("ps-title");
    const subEl = this.shadowRoot.getElementById("ps-sub");
    const toggleBtn = this.shadowRoot.getElementById("ps-toggle");
    const errEl = this.shadowRoot.getElementById("ps-error");
    const statsEl = this.shadowRoot.getElementById("ps-stats");
    const listToggle = this.shadowRoot.getElementById("ps-list-toggle");
    const listWrap = this.shadowRoot.getElementById("ps-list-wrap");
    const listEl = this.shadowRoot.getElementById("ps-list");

    const isOn = sw?.state === "on";
    const attrs = sensor?.attributes || {};
    const devCount = attrs.geraete_anzahl ?? sw?.attributes?.geraete_anzahl ?? 0;
    const pausedCount = Array.isArray(attrs.pausierte_automationen)
      ? attrs.pausierte_automationen.length
      : 0;
    const blockedCount = attrs.abgewehrte_eingriffe ?? 0;
    const jitterMin = attrs.zufall_minuten ?? 7;
    const dataSource = attrs.datenquelle || "14-Tage-Verlauf";
    const upcoming = Array.isArray(attrs.upcoming) ? attrs.upcoming : [];

    if (titleEl) titleEl.textContent = this._config.title || "Anwesenheitssimulation";

    if (subEl) {
      if (devCount === 0) {
        subEl.textContent = "Noch keine Lampen/Schalter in den Optionen gewählt";
      } else if (isOn) {
        subEl.textContent = `${dataSource} • ±${jitterMin} Min`;
      } else {
        subEl.textContent = `${devCount} ${devCount === 1 ? "Gerät" : "Geräte"} bereit • Verlauf: ${attrs.verlauf_tage ?? 0} Tage`;
      }
    }

    if (toggleBtn) {
      toggleBtn.disabled = this._busy || !sw;
      toggleBtn.className = `ps-master ${isOn ? "on" : "off"}`;
      toggleBtn.textContent = this._busy ? "…" : isOn ? "AKTIV" : "AUS";
    }

    if (errEl) {
      errEl.textContent = this._errorMsg;
      errEl.style.display = this._errorMsg ? "block" : "none";
    }

    if (statsEl) {
      if (isOn) {
        statsEl.style.display = "flex";
        statsEl.innerHTML = `
          <span class="ps-pill">💡 ${devCount} Geräte</span>
          <span class="ps-pill">🛡️ ${pausedCount} Autom. pausiert</span>
          <span class="ps-pill">🚫 ${blockedCount} abgewehrt</span>
        `;
      } else {
        statsEl.style.display = "none";
      }
    }

    if (listToggle) {
      listToggle.style.display = isOn ? "block" : "none";
      listToggle.textContent = this._open
        ? `Geplante Schaltungen ausblenden (${upcoming.length})`
        : `Nächste geplante Schaltungen (${upcoming.length})`;
    }

    if (listWrap) {
      listWrap.style.display = isOn && this._open ? "block" : "none";
    }

    if (listEl) {
      listEl.innerHTML = "";
      if (!upcoming.length) {
        const empty = document.createElement("div");
        empty.className = "ps-empty";
        empty.textContent =
          "Keine weiteren Schaltvorgänge in den nächsten 24 Stunden geplant.";
        listEl.appendChild(empty);
      } else {
        upcoming.forEach((ev) => {
          const row = document.createElement("div");
          row.className = "ps-row";

          const left = document.createElement("div");
          left.className = "ps-row-left";
          const name = document.createElement("div");
          name.className = "ps-row-name";
          name.textContent = ev.name;
          const meta = document.createElement("div");
          meta.className = "ps-row-meta";
          const sign = ev.offset_min >= 0 ? "+" : "";
          meta.textContent = `${ev.time} (${sign}${ev.offset_min} Min)`;
          left.appendChild(name);
          left.appendChild(meta);

          const badge = document.createElement("span");
          badge.className = `ps-state ${ev.state === "on" ? "on" : "off"}`;
          badge.textContent = ev.state_de || (ev.state === "on" ? "AN" : "AUS");

          row.appendChild(left);
          row.appendChild(badge);
          listEl.appendChild(row);
        });
      }
    }
  }

  _renderShell() {
    this.shadowRoot.innerHTML = `
      <style>
        ha-card {
          padding: 12px 14px;
          color: var(--primary-text-color);
        }
        .ps-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
        }
        .ps-left {
          display: flex;
          align-items: center;
          gap: 10px;
          min-width: 0;
          flex: 1;
        }
        .ps-icon {
          width: 38px;
          height: 38px;
          border-radius: 10px;
          background: var(--secondary-background-color);
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 19px;
          flex-shrink: 0;
        }
        .ps-titles {
          min-width: 0;
          flex: 1;
        }
        .ps-title {
          font-size: 14px;
          font-weight: 600;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .ps-sub {
          font-size: 11px;
          color: var(--secondary-text-color);
          margin-top: 2px;
        }
        .ps-right-actions {
          display: flex;
          align-items: center;
          gap: 6px;
          flex-shrink: 0;
        }
        .ps-cfg-btn {
          background: var(--secondary-background-color);
          border: 1px solid var(--divider-color);
          color: var(--primary-text-color);
          cursor: pointer;
          width: 32px;
          height: 32px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 14px;
        }
        .ps-cfg-btn:hover {
          border-color: var(--primary-color);
        }
        .ps-master {
          border: none;
          cursor: pointer;
          font-family: inherit;
          font-size: 12px;
          font-weight: 700;
          padding: 7px 14px;
          border-radius: 999px;
          flex-shrink: 0;
          transition: opacity 0.15s;
        }
        .ps-master.on {
          background: var(--primary-color);
          color: var(--text-primary-color, #fff);
        }
        .ps-master.off {
          background: var(--secondary-background-color);
          color: var(--secondary-text-color);
          border: 1px solid var(--divider-color);
        }
        .ps-master:disabled {
          opacity: 0.55;
          cursor: default;
        }
        .ps-error {
          display: none;
          margin-top: 8px;
          padding: 7px 10px;
          border-radius: 8px;
          font-size: 12px;
          color: var(--error-color, #db4437);
          background: rgba(219, 68, 55, 0.12);
        }
        .ps-stats {
          display: none;
          flex-wrap: wrap;
          gap: 6px;
          margin-top: 10px;
        }
        .ps-pill {
          font-size: 11px;
          padding: 3px 8px;
          border-radius: 999px;
          background: var(--secondary-background-color);
          color: var(--secondary-text-color);
        }
        .ps-list-toggle {
          display: none;
          width: 100%;
          margin-top: 10px;
          padding-top: 8px;
          border: none;
          border-top: 1px solid var(--divider-color);
          background: none;
          color: var(--secondary-text-color);
          font-family: inherit;
          font-size: 12px;
          cursor: pointer;
          text-align: center;
        }
        .ps-list-toggle:hover {
          color: var(--primary-color);
        }
        .ps-list-wrap {
          display: none;
          margin-top: 6px;
        }
        .ps-list {
          max-height: 240px;
          overflow-y: auto;
        }
        .ps-empty {
          font-size: 12px;
          color: var(--secondary-text-color);
          text-align: center;
          padding: 8px 4px;
        }
        .ps-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
          padding: 7px 4px;
          border-bottom: 1px solid var(--divider-color);
        }
        .ps-row:last-child {
          border-bottom: none;
        }
        .ps-row-left {
          min-width: 0;
          flex: 1;
        }
        .ps-row-name {
          font-size: 13px;
          font-weight: 500;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .ps-row-meta {
          font-size: 11px;
          color: var(--secondary-text-color);
          margin-top: 2px;
        }
        .ps-state {
          font-size: 11px;
          font-weight: 700;
          padding: 2px 8px;
          border-radius: 999px;
          flex-shrink: 0;
        }
        .ps-state.on {
          color: var(--warning-color, #ff9800);
          background: rgba(255, 152, 0, 0.16);
        }
        .ps-state.off {
          color: var(--secondary-text-color);
          background: var(--secondary-background-color);
        }
      </style>
      <ha-card>
        <div class="ps-header">
          <div class="ps-left">
            <div class="ps-icon">🏠</div>
            <div class="ps-titles">
              <div id="ps-title" class="ps-title">Anwesenheitssimulation</div>
              <div id="ps-sub" class="ps-sub"></div>
            </div>
          </div>
          <div class="ps-right-actions">
            <button id="ps-config" class="ps-cfg-btn" type="button" title="Anwesenheitssimulation konfigurieren">⚙️</button>
            <button id="ps-toggle" class="ps-master off" type="button">AUS</button>
          </div>
        </div>
        <div id="ps-error" class="ps-error"></div>
        <div id="ps-stats" class="ps-stats"></div>
        <button id="ps-list-toggle" class="ps-list-toggle" type="button"></button>
        <div id="ps-list-wrap" class="ps-list-wrap">
          <div id="ps-list" class="ps-list"></div>
        </div>
      </ha-card>
    `;

    this.shadowRoot.getElementById("ps-toggle").addEventListener("click", (ev) => {
      this._toggleMaster(ev);
    });
    this.shadowRoot.getElementById("ps-config").addEventListener("click", (ev) => {
      ev.stopPropagation();
      if (window.__wvOpenPresenceConfigDialog) {
        window.__wvOpenPresenceConfigDialog(this._hass);
      }
    });
    this.shadowRoot.getElementById("ps-list-toggle").addEventListener("click", () => {
      this._open = !this._open;
      this._render();
    });
  }
}

if (!customElements.get("wohnsinnig-vernetzt-presence-card")) {
  customElements.define("wohnsinnig-vernetzt-presence-card", WohnsinnigVernetztPresenceCard);
}
if (!window.customCards.some((c) => c.type === "wohnsinnig-vernetzt-presence-card")) {
  window.customCards.push({
    type: "wohnsinnig-vernetzt-presence-card",
    name: "Wohnsinnig vernetzt Anwesenheitssimulation",
    description: "Hauptschalter, Schutz-Status & geplante Schaltungen (14-Tage-Verlauf ± 7 Min).",
  });
}
class WohnsinnigVernetztPresenceConfigDialog extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._loading = true;
    this._saving = false;
    this._error = "";
    this._savedMsg = "";
    this._entitySearch = "";
    this._autoSearch = "";
    this._selectedEntities = new Set();
    this._selectedAutomations = new Set();
    this._availableEntities = [];
    this._availableAutomations = [];
    this._jitterMinutes = 7;
    this._autoPauseMotion = true;
    this._isOpen = false;
  }

  open(hass) {
    this._hass = hass;
    this._loading = true;
    this._saving = false;
    this._error = "";
    this._savedMsg = "";
    this._entitySearch = "";
    this._autoSearch = "";
    if (this.shadowRoot.innerHTML === "") {
      this._renderShell();
    }

    const nativeDlg = this.shadowRoot.getElementById("dlg-native");
    this.style.display = "block";
    if (nativeDlg) {
      if (typeof nativeDlg.showModal === "function") {
        if (!nativeDlg.open) {
          try {
            nativeDlg.showModal();
          } catch (_) {
            nativeDlg.setAttribute("open", "");
          }
        }
      } else {
        nativeDlg.setAttribute("open", "");
      }
    }
    this._isOpen = true;
    this._renderBody();
    this._loadConfig();
  }

  close() {
    const nativeDlg = this.shadowRoot && this.shadowRoot.getElementById("dlg-native");
    if (nativeDlg) {
      if (typeof nativeDlg.close === "function" && nativeDlg.open) {
        try {
          nativeDlg.close();
        } catch (_) {
          nativeDlg.removeAttribute("open");
        }
      } else {
        nativeDlg.removeAttribute("open");
      }
    }
    this.style.display = "none";
    this._isOpen = false;
  }

  async _loadConfig() {
    if (!this._hass) return;
    try {
      const data = await this._hass.callApi("GET", "wohnsinnig_vernetzt/presence_config");
      this._selectedEntities = new Set(data.presence_entities || []);
      this._selectedAutomations = new Set(data.presence_pause_automations || []);
      this._jitterMinutes = Number.isFinite(data.presence_jitter_minutes)
        ? data.presence_jitter_minutes
        : 7;
      this._autoPauseMotion = data.presence_auto_pause_motion !== false;
      this._availableEntities = Array.isArray(data.available_entities)
        ? data.available_entities
        : [];
      this._availableAutomations = Array.isArray(data.available_automations)
        ? data.available_automations
        : [];
      this._loading = false;
      this._error = "";
      this._renderBody();
    } catch (err) {
      this._loading = false;
      this._error =
        err?.body?.error || err?.message || "Konfiguration konnte nicht geladen werden.";
      this._renderBody();
    }
  }

  async _saveConfig() {
    if (!this._hass || this._saving) return;
    this._saving = true;
    this._error = "";
    this._savedMsg = "";
    this._updateFooter();

    try {
      await this._hass.callApi("POST", "wohnsinnig_vernetzt/presence_config", {
        presence_entities: Array.from(this._selectedEntities),
        presence_jitter_minutes: this._jitterMinutes,
        presence_auto_pause_motion: this._autoPauseMotion,
        presence_pause_automations: Array.from(this._selectedAutomations),
      });
      this._saving = false;
      this._savedMsg = "Gespeichert! Integration übernimmt die neue Auswahl…";
      this._updateFooter();
      setTimeout(() => this.close(), 900);
    } catch (err) {
      this._saving = false;
      this._error =
        err?.body?.error || err?.message || "Speichern fehlgeschlagen.";
      this._updateFooter();
    }
  }

  _updateFooter() {
    const statusEl = this.shadowRoot.getElementById("dlg-status");
    const saveBtn = this.shadowRoot.getElementById("dlg-save");
    if (statusEl) {
      if (this._error) {
        statusEl.textContent = this._error;
        statusEl.className = "dlg-status error";
        statusEl.style.display = "block";
      } else if (this._savedMsg) {
        statusEl.textContent = this._savedMsg;
        statusEl.className = "dlg-status ok";
        statusEl.style.display = "block";
      } else {
        statusEl.style.display = "none";
      }
    }
    if (saveBtn) {
      saveBtn.disabled = this._loading || this._saving;
      saveBtn.textContent = this._saving ? "Speichert…" : "Speichern";
    }
  }

  _renderEntityChecklist() {
    const wrap = this.shadowRoot.getElementById("dlg-ent-list");
    const countEl = this.shadowRoot.getElementById("dlg-ent-count");
    if (countEl) {
      countEl.textContent = `${this._selectedEntities.size} gewählt`;
    }
    if (!wrap) return;
    wrap.innerHTML = "";

    const q = this._entitySearch.trim().toLowerCase();
    const sorted = [...this._availableEntities].sort((a, b) => {
      const aSel = this._selectedEntities.has(a.entity_id) ? 0 : 1;
      const bSel = this._selectedEntities.has(b.entity_id) ? 0 : 1;
      if (aSel !== bSel) return aSel - bSel;
      return a.name.localeCompare(b.name, "de");
    });

    const filtered = sorted.filter(
      (item) =>
        !q ||
        item.name.toLowerCase().includes(q) ||
        item.entity_id.toLowerCase().includes(q)
    );

    if (!filtered.length) {
      const empty = document.createElement("div");
      empty.className = "dlg-empty";
      empty.textContent = "Keine passende Lampe oder Steckdose gefunden.";
      wrap.appendChild(empty);
      return;
    }

    filtered.forEach((item) => {
      const label = document.createElement("label");
      label.className = `dlg-check-item ${this._selectedEntities.has(item.entity_id) ? "selected" : ""}`;

      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = this._selectedEntities.has(item.entity_id);
      cb.addEventListener("change", () => {
        if (cb.checked) {
          this._selectedEntities.add(item.entity_id);
        } else {
          this._selectedEntities.delete(item.entity_id);
        }
        label.classList.toggle("selected", cb.checked);
        const cEl = this.shadowRoot.getElementById("dlg-ent-count");
        if (cEl) cEl.textContent = `${this._selectedEntities.size} gewählt`;
      });

      const icon = document.createElement("span");
      icon.className = "dlg-item-icon";
      icon.textContent = item.domain === "light" ? "💡" : "🔌";

      const txt = document.createElement("div");
      txt.className = "dlg-item-txt";
      const n = document.createElement("div");
      n.className = "dlg-item-name";
      n.textContent = item.name;
      const sub = document.createElement("div");
      sub.className = "dlg-item-sub";
      sub.textContent = item.entity_id;
      txt.appendChild(n);
      txt.appendChild(sub);

      label.appendChild(cb);
      label.appendChild(icon);
      label.appendChild(txt);
      wrap.appendChild(label);
    });
  }

  _renderAutoChecklist() {
    const wrap = this.shadowRoot.getElementById("dlg-auto-list");
    const countEl = this.shadowRoot.getElementById("dlg-auto-count");
    if (countEl) {
      countEl.textContent = `${this._selectedAutomations.size} gewählt`;
    }
    if (!wrap) return;
    wrap.innerHTML = "";

    const q = this._autoSearch.trim().toLowerCase();
    const sorted = [...this._availableAutomations].sort((a, b) => {
      const aSel = this._selectedAutomations.has(a.entity_id) ? 0 : 1;
      const bSel = this._selectedAutomations.has(b.entity_id) ? 0 : 1;
      if (aSel !== bSel) return aSel - bSel;
      return a.name.localeCompare(b.name, "de");
    });

    const filtered = sorted.filter(
      (item) =>
        !q ||
        item.name.toLowerCase().includes(q) ||
        item.entity_id.toLowerCase().includes(q)
    );

    if (!filtered.length) {
      const empty = document.createElement("div");
      empty.className = "dlg-empty";
      empty.textContent = "Keine passende Automation gefunden.";
      wrap.appendChild(empty);
      return;
    }

    filtered.forEach((item) => {
      const label = document.createElement("label");
      label.className = `dlg-check-item ${this._selectedAutomations.has(item.entity_id) ? "selected" : ""}`;

      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = this._selectedAutomations.has(item.entity_id);
      cb.addEventListener("change", () => {
        if (cb.checked) {
          this._selectedAutomations.add(item.entity_id);
        } else {
          this._selectedAutomations.delete(item.entity_id);
        }
        label.classList.toggle("selected", cb.checked);
        const cEl = this.shadowRoot.getElementById("dlg-auto-count");
        if (cEl) cEl.textContent = `${this._selectedAutomations.size} gewählt`;
      });

      const txt = document.createElement("div");
      txt.className = "dlg-item-txt";
      const n = document.createElement("div");
      n.className = "dlg-item-name";
      n.textContent = item.name;
      const sub = document.createElement("div");
      sub.className = "dlg-item-sub";
      sub.textContent = item.entity_id;
      txt.appendChild(n);
      txt.appendChild(sub);

      label.appendChild(cb);
      label.appendChild(txt);
      wrap.appendChild(label);
    });
  }

_renderAlarmSelect() {
    const sel = this.shadowRoot.getElementById("wud-alarm");
    if (!sel) return;
    sel.innerHTML = "";

    const manualOpt = document.createElement("option");
    manualOpt.value = "";
    manualOpt.textContent = "🕒 Feste Uhrzeit (manuell)";
    sel.appendChild(manualOpt);

    this._availableAlarms.forEach((cand) => {
      const opt = document.createElement("option");
      opt.value = cand.entity_id;
      opt.textContent = cand.display_label || cand.name || cand.entity_id;
      sel.appendChild(opt);
    });

    sel.value = this._alarmEntity || "";
  }

  _updateManualTimeVisibility() {
    const hintEl = this.shadowRoot.getElementById("wud-alarm-hint");
    const timeField = this.shadowRoot.getElementById("wud-time-field");
    const daysField = this.shadowRoot.getElementById("wud-days-field");
    const usingPhone = Boolean(this._alarmEntity);

    if (timeField) timeField.style.opacity = usingPhone ? "0.45" : "1";
    if (daysField) daysField.style.opacity = usingPhone ? "0.45" : "1";

    if (hintEl) {
      if (!usingPhone) {
        hintEl.textContent =
          "Tipp: Wähle hier dein Handy, dann richtet sich das Licht automatisch nach deinem gestellten Wecker.";
      } else {
        const found = this._availableAlarms.find((a) => a.entity_id === this._alarmEntity);
        if (found && found.has_alarm) {
          hintEl.textContent = `✅ Erkannter Wecker: ${found.alarm_preview} (${this._mode === "start_at" ? "Startzeit" : "100 % Helligkeit"})`;
        } else {
          hintEl.textContent =
            "📱 Verknüpft – aktuell kein Wecker auf diesem Handy gestellt (Licht bleibt an freien Tagen aus).";
        }
      }
    }
  }

  _renderBody() {
    const loadingEl = this.shadowRoot.getElementById("dlg-loading");
    const formEl = this.shadowRoot.getElementById("dlg-form");
    const jitterInput = this.shadowRoot.getElementById("dlg-jitter");
    const autoPauseCb = this.shadowRoot.getElementById("dlg-autopause");
    const entSearch = this.shadowRoot.getElementById("dlg-ent-search");
    const autoSearch = this.shadowRoot.getElementById("dlg-auto-search");

    if (loadingEl) loadingEl.style.display = this._loading ? "block" : "none";
    if (formEl) formEl.style.display = this._loading ? "none" : "block";

    if (!this._loading) {
      if (jitterInput) jitterInput.value = String(this._jitterMinutes);
      if (autoPauseCb) autoPauseCb.checked = this._autoPauseMotion;
      if (entSearch) entSearch.value = this._entitySearch;
      if (autoSearch) autoSearch.value = this._autoSearch;
      this._renderEntityChecklist();
      this._renderAutoChecklist();
    }
    this._updateFooter();
  }

  _renderShell() {
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: none;
          font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif);
        }
        dialog#dlg-native {
          padding: 0;
          border: none;
          background: transparent;
          max-width: min(520px, calc(100vw - 24px));
          width: 100%;
          max-height: 88vh;
          overflow: visible;
          color: var(--primary-text-color, #e1e1e1);
        }
        dialog#dlg-native::backdrop {
          background: rgba(0, 0, 0, 0.62);
        }
        .modal {
          width: 100%;
          max-height: 88vh;
          background: var(--card-background-color, #1c1c1c);
          color: var(--primary-text-color, #e1e1e1);
          border-radius: 16px;
          box-shadow: 0 12px 40px rgba(0, 0, 0, 0.5);
          border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
          display: flex;
          flex-direction: column;
          overflow: hidden;
        }
        .modal-head {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 16px 18px;
          border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.12));
        }
        .modal-title {
          font-size: 16px;
          font-weight: 600;
        }
        .close-btn {
          background: none;
          border: none;
          color: var(--secondary-text-color, #9b9b9b);
          font-size: 18px;
          cursor: pointer;
          padding: 4px 8px;
          border-radius: 8px;
        }
        .close-btn:hover {
          background: var(--secondary-background-color, rgba(255,255,255,0.08));
          color: var(--primary-text-color);
        }
        .modal-body {
          padding: 14px 18px;
          overflow-y: auto;
          flex: 1;
        }
        .dlg-loading {
          text-align: center;
          padding: 28px 8px;
          color: var(--secondary-text-color);
          font-size: 13px;
        }
        .section {
          margin-bottom: 16px;
        }
        .section-head {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 6px;
        }
        .section-label {
          font-size: 13px;
          font-weight: 600;
        }
        .section-count {
          font-size: 11px;
          color: var(--primary-color, #03a9f4);
          font-weight: 600;
        }
        .dlg-search {
          width: 100%;
          box-sizing: border-box;
          padding: 8px 10px;
          border-radius: 8px;
          border: 1px solid var(--divider-color, rgba(255,255,255,0.15));
          background: var(--secondary-background-color, #282828);
          color: var(--primary-text-color);
          font-family: inherit;
          font-size: 13px;
          margin-bottom: 6px;
        }
        .dlg-list {
          max-height: 175px;
          overflow-y: auto;
          border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
          border-radius: 10px;
          padding: 4px;
          background: var(--secondary-background-color, rgba(255,255,255,0.03));
        }
        .dlg-check-item {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 6px 8px;
          border-radius: 8px;
          cursor: pointer;
        }
        .dlg-check-item:hover {
          background: rgba(var(--rgb-primary-color, 3, 169, 244), 0.08);
        }
        .dlg-check-item.selected {
          background: rgba(var(--rgb-primary-color, 3, 169, 244), 0.14);
        }
        .dlg-item-icon {
          font-size: 14px;
          flex-shrink: 0;
        }
        .dlg-item-txt {
          min-width: 0;
          flex: 1;
        }
        .dlg-item-name {
          font-size: 13px;
          font-weight: 500;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .dlg-item-sub {
          font-size: 11px;
          color: var(--secondary-text-color);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .dlg-empty {
          font-size: 12px;
          color: var(--secondary-text-color);
          text-align: center;
          padding: 12px 6px;
        }
        .inline-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          padding: 8px 10px;
          border-radius: 10px;
          background: var(--secondary-background-color, rgba(255,255,255,0.04));
          margin-bottom: 10px;
        }
        .inline-row label {
          font-size: 13px;
          cursor: pointer;
        }
        .jitter-input {
          width: 72px;
          padding: 6px 8px;
          border-radius: 8px;
          border: 1px solid var(--divider-color);
          background: var(--card-background-color);
          color: var(--primary-text-color);
          font-size: 13px;
          text-align: center;
        }
        .dlg-status {
          display: none;
          margin: 0 18px 10px;
          padding: 8px 10px;
          border-radius: 8px;
          font-size: 12px;
        }
        .dlg-status.ok {
          color: var(--success-color, #4caf50);
          background: rgba(76, 175, 80, 0.14);
        }
        .dlg-status.error {
          color: var(--error-color, #db4437);
          background: rgba(219, 68, 55, 0.14);
        }
        .modal-foot {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
          padding: 12px 18px;
          border-top: 1px solid var(--divider-color, rgba(255,255,255,0.12));
        }
        .foot-link {
          font-size: 12px;
          color: var(--primary-color, #03a9f4);
          text-decoration: none;
        }
        .foot-btns {
          display: flex;
          gap: 8px;
        }
        .btn {
          border: none;
          border-radius: 8px;
          padding: 8px 14px;
          font-family: inherit;
          font-size: 13px;
          font-weight: 600;
          cursor: pointer;
        }
        .btn.secondary {
          background: var(--secondary-background-color);
          color: var(--primary-text-color);
        }
        .btn.primary {
          background: var(--primary-color, #03a9f4);
          color: var(--text-primary-color, #fff);
        }
        .btn:disabled {
          opacity: 0.55;
          cursor: default;
        }
      </style>
      <dialog id="dlg-native">
        <div class="modal" role="document">
          <div class="modal-head">
            <div class="modal-title">🏠 Anwesenheitssimulation konfigurieren</div>
            <button id="dlg-close" class="close-btn" type="button" aria-label="Schließen">✕</button>
          </div>

          <div class="modal-body">
            <div id="dlg-loading" class="dlg-loading">Lade Lampen, Schalter & Automationen…</div>
            <div id="dlg-form" style="display:none;">
              <div class="section">
                <div class="section-head">
                  <span class="section-label">Lampen & Schalter (14-Tage-Verlauf)</span>
                  <span id="dlg-ent-count" class="section-count">0 gewählt</span>
                </div>
                <input id="dlg-ent-search" class="dlg-search" type="search" placeholder="Lampe oder Schalter suchen…" />
                <div id="dlg-ent-list" class="dlg-list"></div>
              </div>

              <div class="inline-row">
                <label for="dlg-jitter">Organische Zufalls-Abweichung (± Minuten)</label>
                <input id="dlg-jitter" class="jitter-input" type="number" min="0" max="30" value="7" />
              </div>

              <div class="inline-row">
                <label for="dlg-autopause">Bewegungsmelder-Automationen automatisch pausieren</label>
                <input id="dlg-autopause" type="checkbox" checked />
              </div>

              <div class="section" style="margin-bottom:0;">
                <div class="section-head">
                  <span class="section-label">Zusätzlich zu pausierende Automationen (optional)</span>
                  <span id="dlg-auto-count" class="section-count">0 gewählt</span>
                </div>
                <input id="dlg-auto-search" class="dlg-search" type="search" placeholder="Bewegungsmelder-Automation suchen…" />
                <div id="dlg-auto-list" class="dlg-list"></div>
              </div>
            </div>
          </div>

          <div id="dlg-status" class="dlg-status"></div>

          <div class="modal-foot">
            <a id="dlg-ext-link" class="foot-link" href="/config/integrations/integration/wohnsinnig_vernetzt">Alle Optionen ↗</a>
            <div class="foot-btns">
              <button id="dlg-cancel" class="btn secondary" type="button">Abbrechen</button>
              <button id="dlg-save" class="btn primary" type="button">Speichern</button>
            </div>
          </div>
        </div>
      </dialog>
    `;

    const nativeDlg = this.shadowRoot.getElementById("dlg-native");
    nativeDlg.addEventListener("click", (ev) => {
      if (ev.target === nativeDlg) this.close();
    });
    nativeDlg.addEventListener("close", () => {
      this.style.display = "none";
      this._isOpen = false;
    });

    this.shadowRoot.getElementById("dlg-close").addEventListener("click", () => this.close());
    this.shadowRoot.getElementById("dlg-cancel").addEventListener("click", () => this.close());
    this.shadowRoot.getElementById("dlg-ext-link").addEventListener("click", () => this.close());
    this.shadowRoot.getElementById("dlg-save").addEventListener("click", () => this._saveConfig());

    this.shadowRoot.getElementById("dlg-ent-search").addEventListener("input", (ev) => {
      this._entitySearch = ev.target.value || "";
      this._renderEntityChecklist();
    });
    this.shadowRoot.getElementById("dlg-auto-search").addEventListener("input", (ev) => {
      this._autoSearch = ev.target.value || "";
      this._renderAutoChecklist();
    });
    this.shadowRoot.getElementById("dlg-jitter").addEventListener("change", (ev) => {
      const val = parseInt(ev.target.value, 10);
      this._jitterMinutes = Number.isFinite(val) ? Math.max(0, Math.min(30, val)) : 7;
    });
    this.shadowRoot.getElementById("dlg-autopause").addEventListener("change", (ev) => {
      this._autoPauseMotion = Boolean(ev.target.checked);
    });
  }
}

if (!customElements.get("wohnsinnig-vernetzt-presence-config-dialog")) {
  customElements.define(
    "wohnsinnig-vernetzt-presence-config-dialog",
    WohnsinnigVernetztPresenceConfigDialog
  );
}

window.__wvLastPresenceOpenTs = 0;
window.__wvOpenPresenceConfigDialog = function (hass) {
  const now = Date.now();
  if (now - (window.__wvLastPresenceOpenTs || 0) < 1200) return;
  const activeHass = hass || document.querySelector("home-assistant")?.hass;
  if (!activeHass) return;
  window.__wvLastPresenceOpenTs = now;
  let dlg = document.getElementById("wv-presence-config-dialog");
  if (!dlg) {
    dlg = document.createElement("wohnsinnig-vernetzt-presence-config-dialog");
    dlg.id = "wv-presence-config-dialog";
    document.body.appendChild(dlg);
  }
  dlg.open(activeHass);
};

class WohnsinnigVernetztWakeUpCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = { title: "Wake-Up Light" };
    this._busy = false;
    this._errorMsg = "";
    this._lastKey = null;
  }

  static getStubConfig() {
    return { title: "Wake-Up Light" };
  }

  connectedCallback() {
    if (this.shadowRoot.innerHTML === "") {
      this._renderShell();
    }
    this._render();
  }

  setConfig(config) {
    this._config = {
      title: "Wake-Up Light",
      ...(config || {}),
    };
    if (this.shadowRoot.innerHTML === "") {
      this._renderShell();
    }
    this._render();
  }

  _findEntities(hass) {
    if (!hass || !hass.states) return { sw: null, sensor: null };
    const sw =
      hass.states["switch.wohnsinnig_vernetzt_wake_up_light_wake_up_light"] ||
      Object.values(hass.states).find(
        (s) =>
          s.entity_id.startsWith("switch.wohnsinnig_vernetzt") &&
          s.attributes &&
          "zielzeit" in s.attributes &&
          "lampen_anzahl" in s.attributes
      );
    const sensor =
      hass.states["sensor.wohnsinnig_vernetzt_wake_up_light_status"] ||
      Object.values(hass.states).find(
        (s) =>
          s.entity_id.startsWith("sensor.wohnsinnig_vernetzt") &&
          s.attributes &&
          "fortschritt_prozent" in s.attributes &&
          "zielzeit" in s.attributes
      );
    return { sw, sensor };
  }

  set hass(hass) {
    this._hass = hass;
    if (this.shadowRoot.innerHTML === "") {
      this._renderShell();
    }
    const { sw, sensor } = this._findEntities(hass);
    const key = [
      sw ? sw.state : "",
      sensor ? sensor.state : "",
      sensor?.attributes?.fortschritt_prozent ?? "",
      sensor?.attributes?.startzeit ?? "",
      sensor?.attributes?.zielzeit ?? "",
      sensor?.attributes?.lampen_anzahl ?? "",
      sensor?.attributes?.handy_wecker_entity ?? "",
      sensor?.attributes?.handy_wecker_zeit ?? "",
      sensor?.attributes?.auto_aus_minuten ?? "",
      sensor?.attributes?.auto_aus_aktiv ?? "",
      sensor?.attributes?.auto_aus_um ?? "",
    ].join("|");
    if (key !== this._lastKey) {
      this._lastKey = key;
      this._render();
    }
  }

  getCardSize() {
    return 3;
  }

  async _toggleMaster(ev) {
    if (ev) ev.stopPropagation();
    if (!this._hass || this._busy) return;
    const { sw } = this._findEntities(this._hass);
    if (!sw) return;

    this._busy = true;
    this._errorMsg = "";
    this._render();
    try {
      await this._hass.callService("switch", sw.state === "on" ? "turn_off" : "turn_on", {
        entity_id: sw.entity_id,
      });
    } catch (err) {
      this._errorMsg = err?.message || "Bitte zuerst Lampen über ⚙️ auswählen.";
    } finally {
      this._busy = false;
      this._render();
    }
  }

  async _triggerStartStop(ev) {
    if (ev) ev.stopPropagation();
    if (!this._hass || this._busy) return;
    const { sensor } = this._findEntities(this._hass);
    const running = Boolean(sensor?.attributes?.laeuft) || Boolean(sensor?.attributes?.auto_aus_aktiv);

    this._busy = true;
    this._errorMsg = "";
    this._render();
    try {
      await this._hass.callService(
        "wohnsinnig_vernetzt",
        running ? "stop_wakeup_light" : "start_wakeup_light",
        {}
      );
    } catch (err) {
      this._errorMsg = err?.message || "Aktion fehlgeschlagen.";
    } finally {
      this._busy = false;
      this._render();
    }
  }

  _render() {
    if (!this.shadowRoot || this.shadowRoot.innerHTML === "") return;
    const { sw, sensor } = this._findEntities(this._hass);

    const titleEl = this.shadowRoot.getElementById("wu-title");
    const subEl = this.shadowRoot.getElementById("wu-sub");
    const toggleBtn = this.shadowRoot.getElementById("wu-toggle");
    const runBtn = this.shadowRoot.getElementById("wu-run");
    const progWrap = this.shadowRoot.getElementById("wu-prog-wrap");
    const progFill = this.shadowRoot.getElementById("wu-prog-fill");
    const progLbl = this.shadowRoot.getElementById("wu-prog-lbl");
    const pillsEl = this.shadowRoot.getElementById("wu-pills");
    const errEl = this.shadowRoot.getElementById("wu-error");

    const isOn = sw?.state === "on";
    const attrs = sensor?.attributes || {};
    const running = Boolean(attrs.laeuft);
    const lampCount = attrs.lampen_anzahl ?? sw?.attributes?.lampen_anzahl ?? 0;
    const startHhmm = attrs.startzeit || sw?.attributes?.startzeit || "06:30";
    const endHhmm = attrs.zielzeit || sw?.attributes?.zielzeit || "07:00";
    const durMin = attrs.dauer_minuten ?? sw?.attributes?.dauer_minuten ?? 30;
    const pct = attrs.helligkeit_prozent ?? 0;
    const pausedCnt = Array.isArray(attrs.pausierte_automationen)
      ? attrs.pausierte_automationen.length
      : 0;

    if (titleEl) titleEl.textContent = this._config.title || "Wake-Up Light";
    const alarmEntity = attrs.handy_wecker_entity || "";
    const alarmName = attrs.handy_wecker_name || "Handy";
    const alarmTime = attrs.handy_wecker_zeit || "";
    const autoOffMin = Number(attrs.auto_aus_minuten || 0);
    const autoOffActive = Boolean(attrs.auto_aus_aktiv);
    const autoOffAt = attrs.auto_aus_um || "";

    if (subEl) {
      if (lampCount === 0) {
        subEl.textContent = "Noch keine Lampen gewählt – tippe auf ⚙️";
      } else if (running) {
        subEl.textContent = `Sonnenaufgang läuft (${startHhmm} → ${endHhmm})`;
      } else if (autoOffActive && autoOffAt) {
        subEl.textContent = `100 % erreicht – Lampen schalten um ${autoOffAt} automatisch aus`;
      } else if (alarmEntity) {
        if (alarmTime) {
          subEl.textContent = `📱 ${alarmName}: ${alarmTime} → Dimmt ${startHhmm}–${endHhmm}`;
        } else {
          subEl.textContent = `📱 ${alarmName}: Aktuell kein Wecker gestellt`;
        }
      } else if (isOn) {
        subEl.textContent = `Start ${startHhmm} → 100 % um ${endHhmm} (${durMin} Min)`;
      } else {
        subEl.textContent = `${lampCount} ${lampCount === 1 ? "Lampe" : "Lampen"} • ${durMin} Min Dimm-Dauer`;
      }
    }

    if (toggleBtn) {
      toggleBtn.disabled = this._busy || !sw;
      toggleBtn.className = `wu-master ${isOn ? "on" : "off"}`;
      toggleBtn.textContent = this._busy ? "…" : isOn ? "AKTIV" : "AUS";
    }

    if (progWrap && progFill && progLbl) {
      progWrap.style.display = running ? "block" : "none";
      progFill.style.width = `${Math.max(2, Math.min(100, pct))}%`;
      progLbl.textContent = `Helligkeit: ${pct} % • noch ca. ${attrs.verbleibende_minuten ?? 0} Min`;
    }

    if (pillsEl) {
      const sourcePill = alarmEntity
        ? `<span class="wu-pill accent">📱 ${alarmName}${alarmTime ? ` (${alarmTime.split(" ").pop()})` : " · kein Wecker"}</span>`
        : `<span class="wu-pill">🕒 ${attrs.modus === "start_at" ? `Start ${attrs.uhrzeit || startHhmm}` : `100 % um ${attrs.uhrzeit || endHhmm}`}</span>`;
      const autoOffPill = autoOffActive && autoOffAt
        ? `<span class="wu-pill accent">⏲️ Auto-Aus um ${autoOffAt}</span>`
        : autoOffMin > 0
        ? `<span class="wu-pill">⏲️ Auto-Aus: ${autoOffMin} Min</span>`
        : "";
      pillsEl.innerHTML = `
        ${sourcePill}
        <span class="wu-pill">💡 ${lampCount} ${lampCount === 1 ? "Lampe" : "Lampen"}</span>
        <span class="wu-pill">⏱️ ${durMin} Min</span>
        ${autoOffPill}
        ${running ? `<span class="wu-pill">🛡️ ${pausedCnt} Autom. pausiert</span>` : ""}
      `;
    }

    if (runBtn) {
      runBtn.disabled = this._busy || lampCount === 0;
      runBtn.className = `wu-run ${running || autoOffActive ? "stop" : ""}`;
      runBtn.textContent = running
        ? "⏹ Sonnenaufgang abbrechen"
        : autoOffActive
        ? `⏹ Auto-Aus (${autoOffAt}) abbrechen`
        : "🌅 Jetzt starten";
    }

    if (errEl) {
      errEl.textContent = this._errorMsg;
      errEl.style.display = this._errorMsg ? "block" : "none";
    }
  }

  _renderShell() {
    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding: 12px 14px; color: var(--primary-text-color); }
        .wu-header { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
        .wu-left { display: flex; align-items: center; gap: 10px; min-width: 0; flex: 1; }
        .wu-icon { width: 38px; height: 38px; border-radius: 10px; background: var(--secondary-background-color); display: flex; align-items: center; justify-content: center; font-size: 19px; flex-shrink: 0; }
        .wu-titles { min-width: 0; flex: 1; }
        .wu-title { font-size: 14px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .wu-sub { font-size: 11px; color: var(--secondary-text-color); margin-top: 2px; }
        .wu-actions { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
        .wu-cfg { background: var(--secondary-background-color); border: 1px solid var(--divider-color); color: var(--primary-text-color); cursor: pointer; width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; }
        .wu-cfg:hover { border-color: var(--primary-color); }
        .wu-master { border: none; cursor: pointer; font-family: inherit; font-size: 12px; font-weight: 700; padding: 7px 14px; border-radius: 999px; }
        .wu-master.on { background: var(--warning-color, #ff9800); color: #fff; }
        .wu-master.off { background: var(--secondary-background-color); color: var(--secondary-text-color); border: 1px solid var(--divider-color); }
        .wu-master:disabled, .wu-run:disabled { opacity: 0.55; cursor: default; }
        .wu-prog-wrap { display: none; margin-top: 10px; }
        .wu-prog-bg { width: 100%; height: 6px; border-radius: 3px; background: var(--secondary-background-color); overflow: hidden; }
        .wu-prog-fill { height: 100%; background: linear-gradient(90deg, #ff7043, #ffca28); border-radius: 3px; transition: width 0.3s; }
        .wu-prog-lbl { font-size: 11px; color: var(--secondary-text-color); margin-top: 4px; }
        .wu-pills { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
        .wu-pill { font-size: 11px; padding: 3px 8px; border-radius: 999px; background: var(--secondary-background-color); color: var(--secondary-text-color); } .wu-pill.accent { color: var(--primary-color); background: rgba(var(--rgb-primary-color, 3, 169, 244), 0.14); font-weight: 600; }
        .wu-run { width: 100%; margin-top: 10px; padding: 8px 12px; border-radius: 8px; border: 1px solid var(--divider-color); background: var(--secondary-background-color); color: var(--primary-text-color); font-family: inherit; font-size: 12px; font-weight: 600; cursor: pointer; }
        .wu-run:hover:not(:disabled) { border-color: var(--primary-color); color: var(--primary-color); }
        .wu-run.stop { border-color: var(--error-color, #db4437); color: var(--error-color, #db4437); }
        .wu-error { display: none; margin-top: 8px; padding: 7px 10px; border-radius: 8px; font-size: 12px; color: var(--error-color, #db4437); background: rgba(219, 68, 55, 0.12); }
      </style>
      <ha-card>
        <div class="wu-header">
          <div class="wu-left">
            <div class="wu-icon">🌅</div>
            <div class="wu-titles">
              <div id="wu-title" class="wu-title">Wake-Up Light</div>
              <div id="wu-sub" class="wu-sub"></div>
            </div>
          </div>
          <div class="wu-actions">
            <button id="wu-cfg" class="wu-cfg" type="button" title="Wake-Up Light konfigurieren">⚙️</button>
            <button id="wu-toggle" class="wu-master off" type="button">AUS</button>
          </div>
        </div>
        <div id="wu-prog-wrap" class="wu-prog-wrap">
          <div class="wu-prog-bg"><div id="wu-prog-fill" class="wu-prog-fill"></div></div>
          <div id="wu-prog-lbl" class="wu-prog-lbl"></div>
        </div>
        <div id="wu-pills" class="wu-pills"></div>
        <button id="wu-run" class="wu-run" type="button">🌅 Jetzt starten</button>
        <div id="wu-error" class="wu-error"></div>
      </ha-card>
    `;

    this.shadowRoot.getElementById("wu-toggle").addEventListener("click", (ev) => this._toggleMaster(ev));
    this.shadowRoot.getElementById("wu-run").addEventListener("click", (ev) => this._triggerStartStop(ev));
    this.shadowRoot.getElementById("wu-cfg").addEventListener("click", (ev) => {
      ev.stopPropagation();
      if (window.__wvOpenWakeUpConfigDialog) {
        window.__wvOpenWakeUpConfigDialog(this._hass);
      }
    });
  }
}

if (!customElements.get("wohnsinnig-vernetzt-wakeup-card")) {
  customElements.define("wohnsinnig-vernetzt-wakeup-card", WohnsinnigVernetztWakeUpCard);
}
if (!window.customCards.some((c) => c.type === "wohnsinnig-vernetzt-wakeup-card")) {
  window.customCards.push({
    type: "wohnsinnig-vernetzt-wakeup-card",
    name: "Wohnsinnig vernetzt Wake-Up Light",
    description: "Sonnenaufgangs-Steuerung (0 % → 100 %) mit Automations-Pause & Direkt-Konfiguration.",
  });
}

class WohnsinnigVernetztWakeUpConfigDialog extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._loading = true;
    this._saving = false;
    this._error = "";
    this._savedMsg = "";
    this._lightSearch = "";
    this._autoSearch = "";
    this._selectedLights = new Set();
    this._selectedAutomations = new Set();
    this._availableLights = [];
    this._availableAutomations = [];
    this._availableAlarms = [];
    this._alarmEntity = "";
    this._mode = "reach_100";
    this._time = "07:00";
    this._duration = 30;
    this._autoOffMinutes = 0;
    this._days = "daily";
    this._autoPause = true;
    this._sunriseColor = true;
  }

  open(hass) {
    this._hass = hass;
    this._loading = true;
    this._saving = false;
    this._error = "";
    this._savedMsg = "";
    this._lightSearch = "";
    this._autoSearch = "";
    if (this.shadowRoot.innerHTML === "") {
      this._renderShell();
    }
    const nativeDlg = this.shadowRoot.getElementById("wud-native");
    this.style.display = "block";
    if (nativeDlg) {
      if (typeof nativeDlg.showModal === "function") {
        if (!nativeDlg.open) {
          try {
            nativeDlg.showModal();
          } catch (_) {
            nativeDlg.setAttribute("open", "");
          }
        }
      } else {
        nativeDlg.setAttribute("open", "");
      }
    }
    this._renderBody();
    this._loadConfig();
  }

  close() {
    const nativeDlg = this.shadowRoot && this.shadowRoot.getElementById("wud-native");
    if (nativeDlg) {
      if (typeof nativeDlg.close === "function" && nativeDlg.open) {
        try {
          nativeDlg.close();
        } catch (_) {
          nativeDlg.removeAttribute("open");
        }
      } else {
        nativeDlg.removeAttribute("open");
      }
    }
    this.style.display = "none";
  }

  async _loadConfig() {
    if (!this._hass) return;
    try {
      const data = await this._hass.callApi("GET", "wohnsinnig_vernetzt/wakeup_config");
      this._selectedLights = new Set(data.wakeup_entities || []);
      this._selectedAutomations = new Set(data.wakeup_pause_automations || []);
      this._alarmEntity = data.wakeup_alarm_entity || "";
      this._availableAlarms = Array.isArray(data.available_alarm_sensors) ? data.available_alarm_sensors : [];
      this._mode = data.wakeup_mode || "reach_100";
      this._time = data.wakeup_time || "07:00";
      this._duration = Number.isFinite(data.wakeup_duration) ? data.wakeup_duration : 30;
      this._autoOffMinutes = Number.isFinite(data.wakeup_auto_off_minutes) ? data.wakeup_auto_off_minutes : 0;
      this._days = data.wakeup_days || "daily";
      this._autoPause = data.wakeup_auto_pause !== false;
      this._sunriseColor = data.wakeup_sunrise_color !== false;
      this._availableLights = Array.isArray(data.available_lights) ? data.available_lights : [];
      this._availableAutomations = Array.isArray(data.available_automations) ? data.available_automations : [];
      this._loading = false;
      this._error = "";
      this._renderBody();
    } catch (err) {
      this._loading = false;
      this._error = err?.body?.error || err?.message || "Konfiguration konnte nicht geladen werden.";
      this._renderBody();
    }
  }

  async _saveConfig() {
    if (!this._hass || this._saving) return;
    this._saving = true;
    this._error = "";
    this._savedMsg = "";
    this._updateFooter();

    try {
      await this._hass.callApi("POST", "wohnsinnig_vernetzt/wakeup_config", {
        wakeup_entities: Array.from(this._selectedLights),
        wakeup_alarm_entity: this._alarmEntity,
        wakeup_mode: this._mode,
        wakeup_time: this._time,
        wakeup_duration: this._duration,
        wakeup_auto_off_minutes: this._autoOffMinutes,
        wakeup_days: this._days,
        wakeup_auto_pause: this._autoPause,
        wakeup_pause_automations: Array.from(this._selectedAutomations),
        wakeup_sunrise_color: this._sunriseColor,
      });
      this._saving = false;
      this._savedMsg = "Gespeichert! Wake-Up Light übernimmt die Einstellungen…";
      this._updateFooter();
      setTimeout(() => this.close(), 900);
    } catch (err) {
      this._saving = false;
      this._error = err?.body?.error || err?.message || "Speichern fehlgeschlagen.";
      this._updateFooter();
    }
  }

  _updateFooter() {
    const statusEl = this.shadowRoot.getElementById("wud-status");
    const saveBtn = this.shadowRoot.getElementById("wud-save");
    if (statusEl) {
      if (this._error) {
        statusEl.textContent = this._error;
        statusEl.className = "dlg-status error";
        statusEl.style.display = "block";
      } else if (this._savedMsg) {
        statusEl.textContent = this._savedMsg;
        statusEl.className = "dlg-status ok";
        statusEl.style.display = "block";
      } else {
        statusEl.style.display = "none";
      }
    }
    if (saveBtn) {
      saveBtn.disabled = this._loading || this._saving;
      saveBtn.textContent = this._saving ? "Speichert…" : "Speichern";
    }
  }

  _renderLightList() {
    const wrap = this.shadowRoot.getElementById("wud-light-list");
    const cnt = this.shadowRoot.getElementById("wud-light-count");
    if (cnt) cnt.textContent = `${this._selectedLights.size} gewählt`;
    if (!wrap) return;
    wrap.innerHTML = "";

    const q = this._lightSearch.trim().toLowerCase();
    const sorted = [...this._availableLights].sort((a, b) => {
      const as = this._selectedLights.has(a.entity_id) ? 0 : 1;
      const bs = this._selectedLights.has(b.entity_id) ? 0 : 1;
      if (as !== bs) return as - bs;
      return a.name.localeCompare(b.name, "de");
    });
    const filtered = sorted.filter(
      (i) => !q || i.name.toLowerCase().includes(q) || i.entity_id.toLowerCase().includes(q)
    );
    if (!filtered.length) {
      const empty = document.createElement("div");
      empty.className = "dlg-empty";
      empty.textContent = "Keine passende Lampe gefunden.";
      wrap.appendChild(empty);
      return;
    }

    filtered.forEach((item) => {
      const label = document.createElement("label");
      label.className = `dlg-check-item ${this._selectedLights.has(item.entity_id) ? "selected" : ""}`;
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = this._selectedLights.has(item.entity_id);
      cb.addEventListener("change", () => {
        if (cb.checked) this._selectedLights.add(item.entity_id);
        else this._selectedLights.delete(item.entity_id);
        label.classList.toggle("selected", cb.checked);
        const cEl = this.shadowRoot.getElementById("wud-light-count");
        if (cEl) cEl.textContent = `${this._selectedLights.size} gewählt`;
      });
      const icon = document.createElement("span");
      icon.className = "dlg-item-icon";
      icon.textContent = "💡";
      const txt = document.createElement("div");
      txt.className = "dlg-item-txt";
      const n = document.createElement("div");
      n.className = "dlg-item-name";
      n.textContent = item.name;
      const sub = document.createElement("div");
      sub.className = "dlg-item-sub";
      sub.textContent = item.entity_id;
      txt.appendChild(n);
      txt.appendChild(sub);
      label.appendChild(cb);
      label.appendChild(icon);
      label.appendChild(txt);
      wrap.appendChild(label);
    });
  }

  _renderAutoList() {
    const wrap = this.shadowRoot.getElementById("wud-auto-list");
    const cnt = this.shadowRoot.getElementById("wud-auto-count");
    if (cnt) cnt.textContent = `${this._selectedAutomations.size} gewählt`;
    if (!wrap) return;
    wrap.innerHTML = "";

    const q = this._autoSearch.trim().toLowerCase();
    const sorted = [...this._availableAutomations].sort((a, b) => {
      const as = this._selectedAutomations.has(a.entity_id) ? 0 : 1;
      const bs = this._selectedAutomations.has(b.entity_id) ? 0 : 1;
      if (as !== bs) return as - bs;
      return a.name.localeCompare(b.name, "de");
    });
    const filtered = sorted.filter(
      (i) => !q || i.name.toLowerCase().includes(q) || i.entity_id.toLowerCase().includes(q)
    );
    if (!filtered.length) {
      const empty = document.createElement("div");
      empty.className = "dlg-empty";
      empty.textContent = "Keine passende Automation gefunden.";
      wrap.appendChild(empty);
      return;
    }

    filtered.forEach((item) => {
      const label = document.createElement("label");
      label.className = `dlg-check-item ${this._selectedAutomations.has(item.entity_id) ? "selected" : ""}`;
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = this._selectedAutomations.has(item.entity_id);
      cb.addEventListener("change", () => {
        if (cb.checked) this._selectedAutomations.add(item.entity_id);
        else this._selectedAutomations.delete(item.entity_id);
        label.classList.toggle("selected", cb.checked);
        const cEl = this.shadowRoot.getElementById("wud-auto-count");
        if (cEl) cEl.textContent = `${this._selectedAutomations.size} gewählt`;
      });
      const txt = document.createElement("div");
      txt.className = "dlg-item-txt";
      const n = document.createElement("div");
      n.className = "dlg-item-name";
      n.textContent = item.name;
      const sub = document.createElement("div");
      sub.className = "dlg-item-sub";
      sub.textContent = item.entity_id;
      txt.appendChild(n);
      txt.appendChild(sub);
      label.appendChild(cb);
      label.appendChild(txt);
      wrap.appendChild(label);
    });
  }

  _renderBody() {
    const loadingEl = this.shadowRoot.getElementById("wud-loading");
    const formEl = this.shadowRoot.getElementById("wud-form");
    if (loadingEl) loadingEl.style.display = this._loading ? "block" : "none";
    if (formEl) formEl.style.display = this._loading ? "none" : "block";

    if (!this._loading) {
      this._renderAlarmSelect();
      this.shadowRoot.getElementById("wud-mode").value = this._mode;
      this.shadowRoot.getElementById("wud-time").value = this._time;
      this.shadowRoot.getElementById("wud-dur").value = String(this._duration);
      this.shadowRoot.getElementById("wud-autooff").value = String(this._autoOffMinutes);
      this.shadowRoot.getElementById("wud-days").value = this._days;
      this.shadowRoot.getElementById("wud-autopause").checked = this._autoPause;
      this.shadowRoot.getElementById("wud-color").checked = this._sunriseColor;
      this._updateManualTimeVisibility();
      this._renderLightList();
      this._renderAutoList();
    }
    this._updateFooter();
  }

  _renderShell() {
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: none; font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
        dialog#wud-native { padding: 0; border: none; background: transparent; max-width: min(520px, calc(100vw - 24px)); width: 100%; max-height: 88vh; overflow: visible; color: var(--primary-text-color, #e1e1e1); }
        dialog#wud-native::backdrop { background: rgba(0, 0, 0, 0.62); }
        .modal { width: 100%; max-height: 88vh; background: var(--card-background-color, #1c1c1c); color: var(--primary-text-color, #e1e1e1); border-radius: 16px; box-shadow: 0 12px 40px rgba(0, 0, 0, 0.5); border: 1px solid var(--divider-color, rgba(255,255,255,0.12)); display: flex; flex-direction: column; overflow: hidden; }
        .modal-head { display: flex; align-items: center; justify-content: space-between; padding: 16px 18px; border-bottom: 1px solid var(--divider-color, rgba(255,255,255,0.12)); }
        .modal-title { font-size: 16px; font-weight: 600; }
        .close-btn { background: none; border: none; color: var(--secondary-text-color); font-size: 18px; cursor: pointer; padding: 4px 8px; border-radius: 8px; }
        .modal-body { padding: 14px 18px; overflow-y: auto; flex: 1; }
        .dlg-loading { text-align: center; padding: 28px 8px; color: var(--secondary-text-color); font-size: 13px; }
        .section { margin-bottom: 14px; }
        .section-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
        .section-label { font-size: 13px; font-weight: 600; }
        .section-count { font-size: 11px; color: var(--primary-color, #03a9f4); font-weight: 600; }
        .dlg-search { width: 100%; box-sizing: border-box; padding: 8px 10px; border-radius: 8px; border: 1px solid var(--divider-color); background: var(--secondary-background-color); color: var(--primary-text-color); font-family: inherit; font-size: 13px; margin-bottom: 6px; }
        .dlg-list { max-height: 155px; overflow-y: auto; border: 1px solid var(--divider-color); border-radius: 10px; padding: 4px; background: var(--secondary-background-color, rgba(255,255,255,0.03)); }
        .dlg-check-item { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 8px; cursor: pointer; }
        .dlg-check-item.selected { background: rgba(var(--rgb-primary-color, 3, 169, 244), 0.14); }
        .dlg-item-icon { font-size: 14px; flex-shrink: 0; }
        .dlg-item-txt { min-width: 0; flex: 1; }
        .dlg-item-name { font-size: 13px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .dlg-item-sub { font-size: 11px; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .dlg-empty { font-size: 12px; color: var(--secondary-text-color); text-align: center; padding: 10px 6px; }
        .alarm-box { padding: 10px 12px; border-radius: 10px; border: 1px solid rgba(var(--rgb-primary-color, 3, 169, 244), 0.35); background: rgba(var(--rgb-primary-color, 3, 169, 244), 0.08); margin-bottom: 12px; } .alarm-hint { font-size: 11px; color: var(--secondary-text-color); margin-top: 6px; line-height: 1.35; } .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 10px; }
        .field { display: flex; flex-direction: column; gap: 4px; }
        .field label { font-size: 11px; color: var(--secondary-text-color); font-weight: 600; }
        .field input, .field select { padding: 7px 9px; border-radius: 8px; border: 1px solid var(--divider-color); background: var(--secondary-background-color); color: var(--primary-text-color); font-family: inherit; font-size: 13px; }
        .inline-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 10px; border-radius: 10px; background: var(--secondary-background-color); margin-bottom: 8px; }
        .inline-row label { font-size: 13px; cursor: pointer; }
        .dlg-status { display: none; margin: 0 18px 10px; padding: 8px 10px; border-radius: 8px; font-size: 12px; }
        .dlg-status.ok { color: var(--success-color, #4caf50); background: rgba(76, 175, 80, 0.14); }
        .dlg-status.error { color: var(--error-color, #db4437); background: rgba(219, 68, 55, 0.14); }
        .modal-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 12px 18px; border-top: 1px solid var(--divider-color); }
        .foot-link { font-size: 12px; color: var(--primary-color, #03a9f4); text-decoration: none; }
        .foot-btns { display: flex; gap: 8px; }
        .btn { border: none; border-radius: 8px; padding: 8px 14px; font-family: inherit; font-size: 13px; font-weight: 600; cursor: pointer; }
        .btn.secondary { background: var(--secondary-background-color); color: var(--primary-text-color); }
        .btn.primary { background: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff); }
        .btn:disabled { opacity: 0.55; cursor: default; }
      </style>
      <dialog id="wud-native">
        <div class="modal" role="document">
          <div class="modal-head">
            <div class="modal-title">🌅 Wake-Up Light konfigurieren</div>
            <button id="wud-close" class="close-btn" type="button" aria-label="Schließen">✕</button>
          </div>
          <div class="modal-body">
            <div id="wud-loading" class="dlg-loading">Lade Lampen & Automationen…</div>
            <div id="wud-form" style="display:none;">
              <div class="section">
                <div class="section-head">
                  <span class="section-label">Lampen auswählen</span>
                  <span id="wud-light-count" class="section-count">0 gewählt</span>
                </div>
                <input id="wud-light-search" class="dlg-search" type="search" placeholder="Lampe suchen…" />
                <div id="wud-light-list" class="dlg-list"></div>
              </div>

              <div class="alarm-box">
                <div class="field">
                  <label for="wud-alarm">📱 Handy-Wecker (Next Alarm Sensor)</label>
                  <select id="wud-alarm">
                    <option value="">🕒 Feste Uhrzeit (manuell)</option>
                  </select>
                </div>
                <div id="wud-alarm-hint" class="alarm-hint"></div>
              </div>

              <div class="grid-2">
                <div class="field">
                  <label for="wud-mode">Zeitmodus</label>
                  <select id="wud-mode">
                    <option value="reach_100">100% um (Weckzeit)</option>
                    <option value="start_at">Startet um (Startzeit)</option>
                  </select>
                </div>
                <div class="field">
                  <label for="wud-dur">Dimm-Dauer (Minuten)</label>
                  <input id="wud-dur" type="number" min="1" max="120" value="30" />
                </div>
                <div class="field">
                  <label for="wud-autooff">Auto-Aus nach 100 % (Min, 0 = aus)</label>
                  <input id="wud-autooff" type="number" min="0" max="180" value="0" />
                </div>
                <div id="wud-time-field" class="field">
                  <label for="wud-time">Feste Uhrzeit (Fallback)</label>
                  <input id="wud-time" type="time" value="07:00" />
                </div>
                <div id="wud-days-field" class="field">
                  <label for="wud-days">Wochentage (bei fester Zeit)</label>
                  <select id="wud-days">
                    <option value="daily">Jeden Tag</option>
                    <option value="workdays">Werktags (Mo–Fr)</option>
                    <option value="weekend">Wochenende (Sa–So)</option>
                  </select>
                </div>
              </div>

              <div class="inline-row">
                <label for="wud-autopause">Betroffene Lampen-Automationen während des Dimmens deaktivieren</label>
                <input id="wud-autopause" type="checkbox" checked />
              </div>
              <div class="inline-row">
                <label for="wud-color">Sonnenaufgangs-Farbtemperatur (Warmweiß → Tageslicht)</label>
                <input id="wud-color" type="checkbox" checked />
              </div>

              <div class="section" style="margin-bottom:0;">
                <div class="section-head">
                  <span class="section-label">Zusätzliche Automationen pausieren (optional)</span>
                  <span id="wud-auto-count" class="section-count">0 gewählt</span>
                </div>
                <input id="wud-auto-search" class="dlg-search" type="search" placeholder="Automation suchen…" />
                <div id="wud-auto-list" class="dlg-list"></div>
              </div>
            </div>
          </div>

          <div id="wud-status" class="dlg-status"></div>

          <div class="modal-foot">
            <a id="wud-ext-link" class="foot-link" href="/config/integrations/integration/wohnsinnig_vernetzt">Alle Optionen ↗</a>
            <div class="foot-btns">
              <button id="wud-cancel" class="btn secondary" type="button">Abbrechen</button>
              <button id="wud-save" class="btn primary" type="button">Speichern</button>
            </div>
          </div>
        </div>
      </dialog>
    `;

    const nativeDlg = this.shadowRoot.getElementById("wud-native");
    nativeDlg.addEventListener("click", (ev) => {
      if (ev.target === nativeDlg) this.close();
    });
    nativeDlg.addEventListener("close", () => {
      this.style.display = "none";
    });
    this.shadowRoot.getElementById("wud-close").addEventListener("click", () => this.close());
    this.shadowRoot.getElementById("wud-cancel").addEventListener("click", () => this.close());
    this.shadowRoot.getElementById("wud-ext-link").addEventListener("click", () => this.close());
    this.shadowRoot.getElementById("wud-save").addEventListener("click", () => this._saveConfig());

    this.shadowRoot.getElementById("wud-light-search").addEventListener("input", (ev) => {
      this._lightSearch = ev.target.value || "";
      this._renderLightList();
    });
    this.shadowRoot.getElementById("wud-auto-search").addEventListener("input", (ev) => {
      this._autoSearch = ev.target.value || "";
      this._renderAutoList();
    });
    this.shadowRoot.getElementById("wud-alarm").addEventListener("change", (ev) => {
      this._alarmEntity = ev.target.value || "";
      this._updateManualTimeVisibility();
    });
    this.shadowRoot.getElementById("wud-mode").addEventListener("change", (ev) => {
      this._mode = ev.target.value;
      this._updateManualTimeVisibility();
    });
    this.shadowRoot.getElementById("wud-time").addEventListener("change", (ev) => {
      this._time = ev.target.value || "07:00";
    });
    this.shadowRoot.getElementById("wud-dur").addEventListener("change", (ev) => {
      const val = parseInt(ev.target.value, 10);
      this._duration = Number.isFinite(val) ? Math.max(1, Math.min(120, val)) : 30;
    });
    this.shadowRoot.getElementById("wud-autooff").addEventListener("change", (ev) => {
      const val = parseInt(ev.target.value, 10);
      this._autoOffMinutes = Number.isFinite(val) ? Math.max(0, Math.min(180, val)) : 0;
    });
    this.shadowRoot.getElementById("wud-days").addEventListener("change", (ev) => {
      this._days = ev.target.value;
    });
    this.shadowRoot.getElementById("wud-autopause").addEventListener("change", (ev) => {
      this._autoPause = Boolean(ev.target.checked);
    });
    this.shadowRoot.getElementById("wud-color").addEventListener("change", (ev) => {
      this._sunriseColor = Boolean(ev.target.checked);
    });
  }
}

if (!customElements.get("wohnsinnig-vernetzt-wakeup-config-dialog")) {
  customElements.define(
    "wohnsinnig-vernetzt-wakeup-config-dialog",
    WohnsinnigVernetztWakeUpConfigDialog
  );
}

window.__wvLastWakeUpOpenTs = 0;
window.__wvOpenWakeUpConfigDialog = function (hass) {
  const now = Date.now();
  if (now - (window.__wvLastWakeUpOpenTs || 0) < 1200) return;
  const activeHass = hass || document.querySelector("home-assistant")?.hass;
  if (!activeHass) return;
  window.__wvLastWakeUpOpenTs = now;
  let dlg = document.getElementById("wv-wakeup-config-dialog");
  if (!dlg) {
    dlg = document.createElement("wohnsinnig-vernetzt-wakeup-config-dialog");
    dlg.id = "wv-wakeup-config-dialog";
    document.body.appendChild(dlg);
  }
  dlg.open(activeHass);
};

// Doppelte Event- & State-Bridge für Anwesenheitssimulation UND Wake-Up Light
if (!window.__wvConfigBridgeV3Initialized) {
  window.__wvConfigBridgeV3Initialized = true;
  let subscribedConn = null;
  const seenReqBySection = {};
  const seenStateTsBySection = {};

  const openSectionDialog = (section, hass, reqUser) => {
    if (document.hidden) return;
    const curUser = hass?.user?.id;
    if (reqUser && curUser && reqUser !== curUser) return;
    if (section === "presence") {
      window.__wvOpenPresenceConfigDialog(hass);
    } else if (section === "wakeup") {
      window.__wvOpenWakeUpConfigDialog(hass);
    }
  };

  const subscribeWs = (conn) => {
    conn
      .subscribeEvents((ev) => {
        const currentHass = document.querySelector("home-assistant")?.hass;
        if (!currentHass) return;
        const section = ev?.data?.section;
        if (!section) return;
        const reqId = ev?.data?.request_id;
        if (typeof reqId === "number") {
          seenReqBySection[section] = Math.max(seenReqBySection[section] || 0, reqId);
        }
        openSectionDialog(section, currentHass, ev?.data?.user_id);
      }, "wohnsinnig_vernetzt_open_config")
      .catch(() => {
        subscribedConn = null;
      });
  };

  const checkBridge = () => {
    const ha = document.querySelector("home-assistant");
    const hass = ha && ha.hass;
    if (!hass || !hass.states) return;

    const conn = hass.connection;
    if (conn && conn !== subscribedConn) {
      subscribedConn = conn;
      subscribeWs(conn);
      if (typeof conn.addEventListener === "function") {
        conn.addEventListener("ready", () => subscribeWs(conn));
      }
    }

    for (const st of Object.values(hass.states)) {
      if (!st.entity_id.startsWith("button.") || !st.attributes || !st.attributes.wv_open_config) {
        continue;
      }
      const section = st.attributes.wv_open_config;
      const reqId = Number(st.attributes.open_request_id || 0);
      const stateTs = st.state || "";

      if (!(section in seenReqBySection)) {
        seenReqBySection[section] = reqId;
        seenStateTsBySection[section] = stateTs;
        continue;
      }

      if (
        reqId > seenReqBySection[section] ||
        (stateTs && stateTs !== seenStateTsBySection[section] && stateTs !== "unknown" && stateTs !== "unavailable")
      ) {
        seenReqBySection[section] = Math.max(seenReqBySection[section], reqId);
        seenStateTsBySection[section] = stateTs;
        openSectionDialog(section, hass, st.attributes.open_request_user);
      }
    }
  };

  setInterval(checkBridge, 350);
  checkBridge();
}
