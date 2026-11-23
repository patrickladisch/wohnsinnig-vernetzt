class WohnsinnigVernetztCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._episodes = [];
    this._blueprints = [];
    this._podcastTitle = "Wohnsinnig vernetzt";
    this._podcastImage = "/wohnsinnig_vernetzt/logo.png";
    this._spotifyShowId = "";
    this._spotifyShowUrl = "";
    this._activeTab = "podcast"; // "podcast" | "blueprints"
    this._mode = "direct"; // "direct" | "spotify"
    this._targetEntity = "__browser__";
    this._playerEntityId = null;
    this._currentIndex = 0;
    this._listOpen = true;
    this._searchQuery = "";
    this._bpSearchQuery = "";
    this._bpStatusMsg = "";
    this._bpStatusType = ""; // "" | "ok" | "error"
    this._bpBusyIds = new Set();
    this._bpBusyAll = false;
    this._loaded = false;
    this._lastSensorKey = null;
    this._lastCommandId = null;
    this._lastRemoteState = null;
    this._lastSpotifyIframeId = "";
    this._autoplayBlocked = false;
    this._speeds = [1, 1.25, 1.5, 2];
    this._speedIdx = 0;

    this._audio = new Audio();
    // Wichtig für IAB / Spotify-for-Creators-Zählung: kein Vorladen vor echtem Klick
    this._audio.preload = "none";
    this._setupAudioEvents();
  }

  static getStubConfig() {
    return {
      title: "Wohnsinnig vernetzt",
      show_list_default: true,
    };
  }

  setConfig(config) {
    this._config = {
      title: "Wohnsinnig vernetzt",
      show_list_default: true,
      ...config,
    };
    this._listOpen = Boolean(this._config.show_list_default);
    if (this.shadowRoot.innerHTML === "") {
      this._renderShell();
    }
  }

  _findPlayerEntity(hass) {
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
    const sensor =
      hass.states["sensor.wohnsinnig_vernetzt_neueste_folge"] ||
      Object.values(hass.states).find(
        (s) =>
          s.entity_id.startsWith("sensor.wohnsinnig_vernetzt") &&
          s.attributes &&
          "episode_count" in s.attributes
      );
    const bpSensor =
      hass.states["sensor.wohnsinnig_vernetzt_blueprints"] ||
      Object.values(hass.states).find(
        (s) =>
          s.entity_id.startsWith("sensor.wohnsinnig_vernetzt") &&
          s.attributes &&
          "installed_count" in s.attributes
      );

    const sensorKey = [
      sensor ? sensor.state : "",
      bpSensor ? `${bpSensor.state}:${bpSensor.attributes.installed_count}` : "",
    ].join("|");

    if (!this._loaded || (sensorKey && sensorKey !== this._lastSensorKey)) {
      this._lastSensorKey = sensorKey;
      this._loaded = true;
      this._fetchData();
    }

    const player = this._findPlayerEntity(hass);
    if (player) {
      this._playerEntityId = player.entity_id;
      const newTarget = player.attributes.target_entity || "__browser__";
      const targetChanged = newTarget !== this._targetEntity;
      this._targetEntity = newTarget;

      if (targetChanged) {
        if (this._targetEntity !== "__browser__" && !this._audio.paused) {
          this._audio.pause();
        }
        this._updateTargetIndicator();
      }

      const cmdId = player.attributes.play_command_id;
      const action = player.attributes.last_command_action;
      const selectedGuid = player.attributes.selected_guid;

      if (this._lastCommandId === null) {
        this._lastCommandId = cmdId;
      } else if (cmdId !== this._lastCommandId) {
        this._lastCommandId = cmdId;
        this._handleRemoteCommand(action, selectedGuid);
      }

      if (this._targetEntity !== "__browser__") {
        if (
          player.state !== this._lastRemoteState ||
          (selectedGuid &&
            this._episodes[this._currentIndex]?.guid !== selectedGuid)
        ) {
          this._lastRemoteState = player.state;
          if (selectedGuid) {
            const idx = this._episodes.findIndex((e) => e.guid === selectedGuid);
            if (idx >= 0) this._currentIndex = idx;
          }
          this._updateUI();
        }
      }
    }
  }

  getCardSize() {
    if (this._activeTab === "blueprints") return 8;
    if (this._mode === "spotify") return 7;
    return this._listOpen ? 8 : 4;
  }

  async _fetchData() {
    if (!this._hass) return;
    try {
      const data = await this._hass.callApi("GET", "wohnsinnig_vernetzt/episodes");
      const preferredGuid =
        data.selected_episode_guid || this._episodes[this._currentIndex]?.guid;

      this._podcastTitle = this._config.title || data.title || "Wohnsinnig vernetzt";
      this._podcastImage = data.image || "/wohnsinnig_vernetzt/logo.png";
      this._episodes = data.episodes || [];
      this._blueprints = data.blueprints || [];
      this._spotifyShowId = data.spotify_show_id || "";
      this._spotifyShowUrl = data.spotify_show_url || "";
      this._targetEntity = data.target_entity || "__browser__";

      if (preferredGuid) {
        const idx = this._episodes.findIndex((e) => e.guid === preferredGuid);
        this._currentIndex = idx >= 0 ? idx : 0;
      } else {
        this._currentIndex = 0;
      }

      this._updateUI();
    } catch (err) {
      this._showError("Daten konnten nicht geladen werden.");
    }
  }

  async _importBlueprint(bp) {
    if (!this._hass || !bp) return;
    this._bpBusyIds.add(bp.id);
    this._bpStatusMsg = `Importiere „${bp.title}“…`;
    this._bpStatusType = "";
    this._renderBlueprintsTab();

    try {
      const resp = await this._hass.callApi(
        "POST",
        "wohnsinnig_vernetzt/import_blueprint",
        { url: bp.url, blueprint_id: bp.id }
      );
      if (Array.isArray(resp.blueprints)) {
        this._blueprints = resp.blueprints;
      }
      this._bpStatusMsg = `„${bp.title}“ direkt in Home Assistant importiert!`;
      this._bpStatusType = "ok";
    } catch (err) {
      const detail = err?.body?.error || err?.message || "Import fehlgeschlagen.";
      this._bpStatusMsg = detail;
      this._bpStatusType = "error";
    } finally {
      this._bpBusyIds.delete(bp.id);
      this._renderBlueprintsTab();
    }
  }

  async _importAllBlueprints() {
    if (!this._hass || this._bpBusyAll) return;
    this._bpBusyAll = true;
    this._bpStatusMsg = "Importiere alle Blueprints…";
    this._bpStatusType = "";
    this._renderBlueprintsTab();

    try {
      const resp = await this._hass.callApi(
        "POST",
        "wohnsinnig_vernetzt/import_blueprint",
        { import_all: true }
      );
      if (Array.isArray(resp.blueprints)) {
        this._blueprints = resp.blueprints;
      }
      const count = Array.isArray(resp.imported) ? resp.imported.length : 0;
      this._bpStatusMsg = `${count} Blueprints direkt in Home Assistant importiert!`;
      this._bpStatusType = "ok";
    } catch (err) {
      const detail = err?.body?.error || err?.message || "Import fehlgeschlagen.";
      this._bpStatusMsg = detail;
      this._bpStatusType = "error";
    } finally {
      this._bpBusyAll = false;
      this._renderBlueprintsTab();
    }
  }

  _handleRemoteCommand(action, guid) {
    if (this._targetEntity !== "__browser__") return;
    if (guid) {
      const idx = this._episodes.findIndex((e) => e.guid === guid);
      if (idx >= 0) {
        this._currentIndex = idx;
      }
    }
    const ep = this._episodes[this._currentIndex];
    if (!ep) return;

    if (action === "play") {
      if (this._audio.src !== ep.audio_url) {
        this._audio.src = ep.audio_url;
      }
      this._audio.playbackRate = this._speeds[this._speedIdx];
      this._audio
        .play()
        .then(() => {
          this._autoplayBlocked = false;
          this._updateUI();
        })
        .catch(() => {
          this._autoplayBlocked = true;
          this._updateUI();
        });
    } else if (action === "pause") {
      this._audio.pause();
    } else if (action === "stop") {
      this._audio.pause();
      this._audio.currentTime = 0;
    }
    this._updateUI();
  }

  async _syncBrowserState(state) {
    if (!this._hass || this._targetEntity !== "__browser__") return;
    const ep = this._episodes[this._currentIndex];
    try {
      await this._hass.callApi("POST", "wohnsinnig_vernetzt/player_state", {
        state,
        guid: ep ? ep.guid : null,
      });
    } catch (_) {
      // Unkritisch
    }
  }

  _setupAudioEvents() {
    this._audio.addEventListener("timeupdate", () => this._updateProgress());
    this._audio.addEventListener("loadedmetadata", () => this._updateProgress());
    this._audio.addEventListener("play", () => {
      this._autoplayBlocked = false;
      this._updatePlayIcon();
      this._updateHint();
      this._syncBrowserState("playing");
    });
    this._audio.addEventListener("pause", () => {
      this._updatePlayIcon();
      this._syncBrowserState("paused");
    });
    this._audio.addEventListener("ended", () => {
      this._updatePlayIcon();
      this._syncBrowserState("idle");
    });
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

  _isPlaying() {
    if (this._targetEntity !== "__browser__" && this._hass && this._playerEntityId) {
      const st = this._hass.states[this._playerEntityId];
      return st && st.state === "playing";
    }
    return !this._audio.paused;
  }

  _selectEpisode(index, autoplay = true) {
    if (index < 0 || index >= this._episodes.length) return;
    const ep = this._episodes[index];
    this._currentIndex = index;

    if (this._targetEntity !== "__browser__" && this._hass && this._playerEntityId) {
      if (autoplay) {
        this._hass.callService("media_player", "play_media", {
          entity_id: this._playerEntityId,
          media_content_id: ep.guid,
          media_content_type: "episode",
        });
      }
      this._updateUI();
      return;
    }

    if (this._audio.src !== ep.audio_url) {
      this._audio.src = ep.audio_url;
      this._audio.playbackRate = this._speeds[this._speedIdx];
    }

    if (autoplay) {
      this._audio.play().catch(() => {
        this._autoplayBlocked = true;
        this._updateHint();
      });
    }
    this._updateUI();
  }

  _togglePlay() {
    if (!this._episodes.length) return;

    if (this._targetEntity !== "__browser__" && this._hass && this._playerEntityId) {
      if (this._isPlaying()) {
        this._hass.callService("media_player", "media_pause", {
          entity_id: this._playerEntityId,
        });
      } else {
        const ep = this._episodes[this._currentIndex];
        this._hass.callService("media_player", "play_media", {
          entity_id: this._playerEntityId,
          media_content_id: ep.guid,
          media_content_type: "episode",
        });
      }
      return;
    }

    const ep = this._episodes[this._currentIndex];
    if (this._audio.src !== ep.audio_url) {
      this._audio.src = ep.audio_url;
    }
    if (this._audio.paused) {
      this._audio.playbackRate = this._speeds[this._speedIdx];
      this._audio.play().catch(() => {});
    } else {
      this._audio.pause();
    }
  }

  _skip(seconds) {
    if (this._targetEntity !== "__browser__") return;
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
    const playing = this._isPlaying();
    btn.innerHTML = playing
      ? `<svg viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>`
      : `<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>`;
  }

  _updateProgress() {
    const bar = this.shadowRoot.getElementById("progress");
    const cur = this.shadowRoot.getElementById("time-current");
    const dur = this.shadowRoot.getElementById("time-total");
    const wrap = this.shadowRoot.getElementById("progress-wrap");
    if (!bar || !cur || !dur || !wrap) return;

    const isBrowser = this._targetEntity === "__browser__";
    wrap.style.display = isBrowser ? "flex" : "none";
    if (!isBrowser) return;

    const duration = this._audio.duration || 0;
    const current = this._audio.currentTime || 0;
    bar.max = duration || 100;
    bar.value = current;
    cur.textContent = this._formatTime(current);
    dur.textContent =
      duration > 0
        ? this._formatTime(duration)
        : this._episodes[this._currentIndex]?.duration || "0:00";
  }

  _updateTargetIndicator() {
    const badge = this.shadowRoot.getElementById("target-badge");
    const skipControls = this.shadowRoot.querySelectorAll(".browser-only");
    const isBrowser = this._targetEntity === "__browser__";

    skipControls.forEach((el) => {
      el.style.visibility = isBrowser ? "visible" : "hidden";
    });

    if (!badge) return;
    if (isBrowser) {
      badge.textContent = "🔊 Browser";
    } else {
      const targetState = this._hass?.states?.[this._targetEntity];
      const name = targetState?.attributes?.friendly_name || this._targetEntity;
      badge.textContent = `🔊 ${name}`;
    }
    this._updateProgress();
  }

  _updateHint() {
    const hint = this.shadowRoot.getElementById("autoplay-hint");
    if (!hint) return;
    hint.style.display = this._autoplayBlocked ? "block" : "none";
  }

  _showError(msg) {
    const titleEl = this.shadowRoot.getElementById("ep-title");
    if (titleEl) titleEl.textContent = msg;
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
      empty.textContent = "Keine passende Folge gefunden.";
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

      row.addEventListener("click", () => this._selectEpisode(idx, true));
      listWrap.appendChild(row);
    });
  }

  _renderBlueprintsTab() {
    const tabBpBtn = this.shadowRoot.getElementById("tab-blueprints");
    const listEl = this.shadowRoot.getElementById("bp-list");
    const statusEl = this.shadowRoot.getElementById("bp-status");
    const importAllBtn = this.shadowRoot.getElementById("bp-import-all");

    if (tabBpBtn) {
      tabBpBtn.textContent = `Blueprints (${this._blueprints.length})`;
    }
    if (importAllBtn) {
      importAllBtn.disabled = this._bpBusyAll || this._blueprints.length === 0;
      importAllBtn.textContent = this._bpBusyAll
        ? "Importiert…"
        : "Alle importieren";
    }
    if (statusEl) {
      statusEl.textContent = this._bpStatusMsg;
      statusEl.className = `bp-status ${this._bpStatusType}`;
      statusEl.style.display = this._bpStatusMsg ? "block" : "none";
    }
    if (!listEl) return;

    listEl.innerHTML = "";
    const query = this._bpSearchQuery.trim().toLowerCase();
    const filtered = this._blueprints.filter(
      (bp) =>
        !query ||
        bp.title.toLowerCase().includes(query) ||
        (bp.description || "").toLowerCase().includes(query)
    );

    if (!filtered.length) {
      const empty = document.createElement("div");
      empty.className = "empty-hint";
      empty.textContent = this._blueprints.length
        ? "Kein passender Blueprint gefunden."
        : "Noch keine Blueprints von wohnsinnigvernetzt.de geladen.";
      listEl.appendChild(empty);
      return;
    }

    filtered.forEach((bp) => {
      const card = document.createElement("div");
      card.className = "bp-item";

      const head = document.createElement("div");
      head.className = "bp-head";

      const titleWrap = document.createElement("div");
      titleWrap.className = "bp-title-wrap";

      const title = document.createElement("div");
      title.className = "bp-title";
      title.textContent = bp.title;
      titleWrap.appendChild(title);

      if (bp.installed) {
        const badge = document.createElement("span");
        badge.className = "bp-badge";
        badge.textContent = "✓ Importiert";
        titleWrap.appendChild(badge);
      }

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `bp-btn ${bp.installed ? "secondary" : ""}`;
      const busy = this._bpBusyIds.has(bp.id) || this._bpBusyAll;
      btn.disabled = busy;
      btn.textContent = busy
        ? "…"
        : bp.installed
        ? "Aktualisieren"
        : "Importieren";
      btn.addEventListener("click", () => this._importBlueprint(bp));

      head.appendChild(titleWrap);
      head.appendChild(btn);
      card.appendChild(head);

      if (bp.description) {
        const desc = document.createElement("div");
        desc.className = "bp-desc";
        desc.textContent = bp.description;
        card.appendChild(desc);
      }

      listEl.appendChild(card);
    });
  }

  _updateTabs() {
    const tabPodcast = this.shadowRoot.getElementById("tab-podcast");
    const tabBlueprints = this.shadowRoot.getElementById("tab-blueprints");
    const panePodcast = this.shadowRoot.getElementById("pane-podcast");
    const paneBlueprints = this.shadowRoot.getElementById("pane-blueprints");

    if (tabPodcast) tabPodcast.classList.toggle("active", this._activeTab === "podcast");
    if (tabBlueprints) tabBlueprints.classList.toggle("active", this._activeTab === "blueprints");
    if (panePodcast) panePodcast.style.display = this._activeTab === "podcast" ? "block" : "none";
    if (paneBlueprints) paneBlueprints.style.display = this._activeTab === "blueprints" ? "block" : "none";
  }

  _updateSpotifyEmbed() {
    const modeBar = this.shadowRoot.getElementById("mode-bar");
    const directWrap = this.shadowRoot.getElementById("direct-wrap");
    const spotifyWrap = this.shadowRoot.getElementById("spotify-wrap");
    const iframe = this.shadowRoot.getElementById("spotify-iframe");
    const btnDirect = this.shadowRoot.getElementById("mode-direct");
    const btnSpotify = this.shadowRoot.getElementById("mode-spotify");

    const hasSpotify = Boolean(this._spotifyShowId);
    if (modeBar) modeBar.style.display = hasSpotify ? "flex" : "none";

    if (!hasSpotify) {
      this._mode = "direct";
    }

    if (btnDirect) btnDirect.classList.toggle("active", this._mode === "direct");
    if (btnSpotify) btnSpotify.classList.toggle("active", this._mode === "spotify");

    if (directWrap) directWrap.style.display = this._mode === "direct" ? "block" : "none";
    if (spotifyWrap) spotifyWrap.style.display = this._mode === "spotify" ? "block" : "none";

    if (
      hasSpotify &&
      this._mode === "spotify" &&
      iframe &&
      this._lastSpotifyIframeId !== this._spotifyShowId
    ) {
      this._lastSpotifyIframeId = this._spotifyShowId;
      iframe.src = `https://open.spotify.com/embed/show/${this._spotifyShowId}?utm_source=generator&theme=0`;
    }
  }

  _updateUI() {
    const ep = this._episodes[this._currentIndex];
    const cover = this.shadowRoot.getElementById("cover");
    const podcastLabel = this.shadowRoot.getElementById("podcast-label");
    const epTitle = this.shadowRoot.getElementById("ep-title");
    const epMeta = this.shadowRoot.getElementById("ep-meta");
    const listToggle = this.shadowRoot.getElementById("list-toggle");
    const listSection = this.shadowRoot.getElementById("list-section");

    if (podcastLabel) podcastLabel.textContent = this._podcastTitle;

    if (ep) {
      if (cover) {
        cover.src = ep.image || this._podcastImage || "";
        cover.style.display = cover.src ? "block" : "none";
      }
      if (epTitle) epTitle.textContent = ep.title;
      if (epMeta) {
        epMeta.textContent = [ep.pub_date, ep.duration].filter(Boolean).join(" • ");
      }
    } else if (epTitle) {
      epTitle.textContent = "Keine Folgen verfügbar";
    }

    if (listToggle) {
      listToggle.textContent = this._listOpen
        ? `Alle Folgen ausblenden (${this._episodes.length})`
        : `Alle Folgen anzeigen (${this._episodes.length})`;
    }

    if (listSection) {
      listSection.style.display = this._listOpen ? "block" : "none";
    }

    this._updateTabs();
    this._updateSpotifyEmbed();
    this._updateTargetIndicator();
    this._renderEpisodeList();
    this._renderBlueprintsTab();
    this._updatePlayIcon();
    this._updateProgress();
    this._updateHint();
  }

  _renderShell() {
    this.shadowRoot.innerHTML = `
      <style>
        ha-card {
          padding: 14px;
          color: var(--primary-text-color);
        }
        .tabs-bar, .mode-bar {
          display: flex;
          gap: 6px;
          margin-bottom: 10px;
          background: var(--secondary-background-color);
          padding: 4px;
          border-radius: 10px;
        }
        .mode-bar {
          display: none;
        }
        .tab-btn, .mode-btn {
          flex: 1;
          padding: 6px 10px;
          border-radius: 8px;
          font-size: 12px;
          font-weight: 600;
          color: var(--secondary-text-color);
        }
        .tab-btn.active, .mode-btn.active {
          background: var(--primary-color);
          color: var(--text-primary-color, #fff);
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
        .top-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
        }
        .podcast-label {
          font-size: 11px;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          color: var(--primary-color);
          font-weight: 600;
        }
        .target-badge {
          font-size: 11px;
          color: var(--secondary-text-color);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          max-width: 140px;
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
        .autoplay-hint {
          display: none;
          margin-top: 8px;
          padding: 6px 10px;
          border-radius: 8px;
          font-size: 12px;
          background: rgba(var(--rgb-primary-color, 3, 169, 244), 0.14);
          color: var(--primary-color);
          text-align: center;
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
        .episode-list, .bp-list {
          margin-top: 8px;
          max-height: 290px;
          overflow-y: auto;
        }
        .empty-hint {
          font-size: 12px;
          color: var(--secondary-text-color);
          padding: 12px 4px;
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
        .spotify-iframe {
          width: 100%;
          height: 352px;
          border: none;
          border-radius: 12px;
        }
        .bp-toolbar {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
        }
        .bp-open-link {
          font-size: 12px;
          color: var(--primary-color);
          text-decoration: none;
          font-weight: 500;
        }
        .bp-open-link:hover {
          text-decoration: underline;
        }
        .bp-status {
          display: none;
          margin-top: 8px;
          padding: 7px 10px;
          border-radius: 8px;
          font-size: 12px;
          background: var(--secondary-background-color);
        }
        .bp-status.ok {
          color: var(--success-color, #4caf50);
          background: rgba(76, 175, 80, 0.12);
        }
        .bp-status.error {
          color: var(--error-color, #db4437);
          background: rgba(219, 68, 55, 0.12);
        }
        .bp-item {
          padding: 10px 8px;
          border-bottom: 1px solid var(--divider-color);
        }
        .bp-item:last-child {
          border-bottom: none;
        }
        .bp-head {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 8px;
        }
        .bp-title-wrap {
          min-width: 0;
          flex: 1;
        }
        .bp-title {
          font-size: 13px;
          font-weight: 600;
          line-height: 1.3;
        }
        .bp-badge {
          display: inline-block;
          margin-top: 3px;
          font-size: 10px;
          font-weight: 600;
          padding: 2px 6px;
          border-radius: 999px;
          color: var(--success-color, #4caf50);
          background: rgba(76, 175, 80, 0.14);
        }
        .bp-desc {
          font-size: 12px;
          color: var(--secondary-text-color);
          margin-top: 4px;
          line-height: 1.35;
        }
        .bp-btn {
          padding: 6px 11px;
          border-radius: 8px;
          font-size: 12px;
          font-weight: 600;
          background: var(--primary-color);
          color: var(--text-primary-color, #fff);
          flex-shrink: 0;
        }
        .bp-btn.secondary {
          background: var(--secondary-background-color);
          color: var(--primary-text-color);
          border: 1px solid var(--divider-color);
        }
        .bp-btn:disabled {
          opacity: 0.55;
          cursor: default;
        }
      </style>
      <ha-card>
        <div class="tabs-bar">
          <button id="tab-podcast" class="tab-btn active" type="button">Podcast</button>
          <button id="tab-blueprints" class="tab-btn" type="button">Blueprints</button>
        </div>

        <div id="pane-podcast">
          <div id="mode-bar" class="mode-bar">
            <button id="mode-direct" class="mode-btn active" type="button">Direkt-Player</button>
            <button id="mode-spotify" class="mode-btn" type="button">Spotify Player</button>
          </div>

          <div id="direct-wrap">
            <div class="header">
              <img id="cover" class="cover" alt="Podcast Cover" />
              <div class="info">
                <div class="top-row">
                  <div id="podcast-label" class="podcast-label">Wohnsinnig vernetzt</div>
                  <div id="target-badge" class="target-badge">🔊 Browser</div>
                </div>
                <div id="ep-title" class="ep-title">Lade Folgen…</div>
                <div id="ep-meta" class="ep-meta"></div>
              </div>
            </div>

            <div id="autoplay-hint" class="autoplay-hint">
              Folge bereit – tippe auf Play zum Starten.
            </div>

            <div id="progress-wrap" class="progress-wrap">
              <span id="time-current">0:00</span>
              <input id="progress" type="range" min="0" max="100" value="0" />
              <span id="time-total">0:00</span>
            </div>

            <div class="controls">
              <button id="speed-btn" class="icon-btn browser-only" type="button">1x</button>
              <div class="controls-center">
                <button id="back-btn" class="icon-btn browser-only" type="button">-15s</button>
                <button id="play-btn" class="play-btn" type="button" aria-label="Abspielen / Pause"></button>
                <button id="fwd-btn" class="icon-btn browser-only" type="button">+30s</button>
              </div>
              <div style="width: 34px;"></div>
            </div>

            <button id="list-toggle" class="list-toggle" type="button">Alle Folgen</button>
            <div id="list-section">
              <input id="search-input" class="search-input" type="search" placeholder="Folgen durchsuchen…" />
              <div id="episode-list" class="episode-list"></div>
            </div>
          </div>

          <div id="spotify-wrap" style="display:none;">
            <iframe
              id="spotify-iframe"
              class="spotify-iframe"
              allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture"
              loading="lazy"
            ></iframe>
          </div>
        </div>

        <div id="pane-blueprints" style="display:none;">
          <div class="bp-toolbar">
            <a class="bp-open-link" href="/config/blueprint/dashboard">Zu HA-Blueprints ↗</a>
            <button id="bp-import-all" class="bp-btn" type="button">Alle importieren</button>
          </div>
          <div id="bp-status" class="bp-status"></div>
          <input id="bp-search-input" class="search-input" type="search" placeholder="Blueprints durchsuchen…" />
          <div id="bp-list" class="bp-list"></div>
        </div>
      </ha-card>
    `;

    this.shadowRoot.getElementById("tab-podcast").addEventListener("click", () => {
      this._activeTab = "podcast";
      this._updateTabs();
    });
    this.shadowRoot.getElementById("tab-blueprints").addEventListener("click", () => {
      this._activeTab = "blueprints";
      this._updateTabs();
      this._renderBlueprintsTab();
    });
    this.shadowRoot.getElementById("mode-direct").addEventListener("click", () => {
      this._mode = "direct";
      this._updateSpotifyEmbed();
    });
    this.shadowRoot.getElementById("mode-spotify").addEventListener("click", () => {
      this._mode = "spotify";
      if (!this._audio.paused) this._audio.pause();
      this._updateSpotifyEmbed();
    });
    this.shadowRoot.getElementById("play-btn").addEventListener("click", () => this._togglePlay());
    this.shadowRoot.getElementById("back-btn").addEventListener("click", () => this._skip(-15));
    this.shadowRoot.getElementById("fwd-btn").addEventListener("click", () => this._skip(30));
    this.shadowRoot.getElementById("speed-btn").addEventListener("click", () => this._cycleSpeed());
    this.shadowRoot.getElementById("progress").addEventListener("input", (e) => {
      this._audio.currentTime = Number(e.target.value);
    });
    this.shadowRoot.getElementById("list-toggle").addEventListener("click", () => {
      this._listOpen = !this._listOpen;
      this._updateUI();
    });
    this.shadowRoot.getElementById("search-input").addEventListener("input", (e) => {
      this._searchQuery = e.target.value || "";
      this._renderEpisodeList();
    });
    this.shadowRoot.getElementById("bp-search-input").addEventListener("input", (e) => {
      this._bpSearchQuery = e.target.value || "";
      this._renderBlueprintsTab();
    });
    this.shadowRoot.getElementById("bp-import-all").addEventListener("click", () => {
      this._importAllBlueprints();
    });

    this._updatePlayIcon();
  }
}

if (!customElements.get("wohnsinnig-vernetzt-card")) {
  customElements.define("wohnsinnig-vernetzt-card", WohnsinnigVernetztCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "wohnsinnig-vernetzt-card")) {
  window.customCards.push({
    type: "wohnsinnig-vernetzt-card",
    name: "Wohnsinnig vernetzt Player & Blueprints",
    description: "Podcast-Player, Episodenliste, Lautsprecher-Steuerung und 1-Klick-Blueprint-Import.",
  });
}
