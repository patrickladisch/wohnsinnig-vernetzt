// Wohnsinnig vernetzt Dashboard Player & Blueprints Cards v2.2.0

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
      subEl.textContent = checkedAt
        ? `Schwellwert ${threshold} • Stand: ${checkedAt}`
        : `1 Klick zeigt alle Geräte ${threshold}`;
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

    if (!listEl) return;
    listEl.innerHTML = "";

    if (!devices.length) {
      const okEl = document.createElement("div");
      okEl.className = "bc-empty";
      okEl.textContent = `Alle Batterien sind im grünen Bereich (keine Geräte ${threshold}).`;
      listEl.appendChild(okEl);
      return;
    }

    devices.forEach((dev) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "bc-row";
      row.addEventListener("click", () => this._openMoreInfo(dev.entity_id));

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

      row.appendChild(left);
      row.appendChild(pctEl);
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
        .bc-row:last-child {
          border-bottom: none;
        }
        .bc-row:hover {
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
  }
}

if (!customElements.get("wohnsinnig-vernetzt-battery-card")) {
  customElements.define("wohnsinnig-vernetzt-battery-card", WohnsinnigVernetztBatteryCard);
}
if (!window.customCards.some((c) => c.type === "wohnsinnig-vernetzt-battery-card")) {
  window.customCards.push({
    type: "wohnsinnig-vernetzt-battery-card",
    name: "Wohnsinnig vernetzt Batterie-Check",
    description: "Zeigt auf einen Klick live alle Geräte mit weniger als 15 % Batteriestand an.",
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
