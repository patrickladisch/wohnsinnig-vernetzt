class WohnsinnigVernetztCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._episodes = [];
    this._podcastTitle = "Wohnsinnig vernetzt";
    this._podcastImage = "";
    this._feedbackConfigured = false;
    this._feedbackFallbackUrl = "https://www.wohnsinnigvernetzt.de";
    this._currentIndex = 0;
    this._listOpen = true;
    this._feedbackOpen = false;
    this._searchQuery = "";
    this._loaded = false;
    this._lastSensorState = null;
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
    const sensorState = sensor ? sensor.state : null;

    if (!this._loaded || (sensorState && sensorState !== this._lastSensorState)) {
      this._lastSensorState = sensorState;
      this._loaded = true;
      this._fetchEpisodes();
    }
  }

  getCardSize() {
    return this._listOpen ? 8 : 4;
  }

  async _fetchEpisodes() {
    if (!this._hass) return;
    try {
      const data = await this._hass.callApi("GET", "wohnsinnig_vernetzt/episodes");
      const currentGuid = this._episodes[this._currentIndex]?.guid;
      this._podcastTitle = this._config.title || data.title || "Wohnsinnig vernetzt";
      this._podcastImage = data.image || "";
      this._episodes = data.episodes || [];
      this._feedbackConfigured = Boolean(data.feedback_configured);
      this._feedbackFallbackUrl =
        data.feedback_fallback_url || "https://www.wohnsinnigvernetzt.de";

      if (currentGuid) {
        const idx = this._episodes.findIndex((e) => e.guid === currentGuid);
        this._currentIndex = idx >= 0 ? idx : 0;
      } else {
        this._currentIndex = 0;
      }

      if (this._episodes.length > 0 && !this._audio.src) {
        this._audio.src = this._episodes[this._currentIndex].audio_url;
      }
      this._updateUI();
    } catch (err) {
      this._showError("Podcast-Folgen konnten nicht geladen werden.");
    }
  }

  _setupAudioEvents() {
    this._audio.addEventListener("timeupdate", () => this._updateProgress());
    this._audio.addEventListener("loadedmetadata", () => this._updateProgress());
    this._audio.addEventListener("play", () => this._updatePlayIcon());
    this._audio.addEventListener("pause", () => this._updatePlayIcon());
    this._audio.addEventListener("ended", () => this._updatePlayIcon());
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

  _selectEpisode(index, autoplay = true) {
    if (index < 0 || index >= this._episodes.length) return;
    const ep = this._episodes[index];
    const sameTrack = this._currentIndex === index && this._audio.src === ep.audio_url;
    this._currentIndex = index;

    if (!sameTrack) {
      this._audio.src = ep.audio_url;
      this._audio.playbackRate = this._speeds[this._speedIdx];
    }

    if (autoplay) {
      this._audio.play().catch(() => {});
    }
    this._updateUI();
  }

  _togglePlay() {
    if (!this._episodes.length) return;
    if (!this._audio.src) {
      this._audio.src = this._episodes[this._currentIndex].audio_url;
    }
    if (this._audio.paused) {
      this._audio.playbackRate = this._speeds[this._speedIdx];
      this._audio.play().catch(() => {});
    } else {
      this._audio.pause();
    }
  }

  _skip(seconds) {
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
    btn.innerHTML = this._audio.paused
      ? `<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>`
      : `<svg viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>`;
  }

  _updateProgress() {
    const bar = this.shadowRoot.getElementById("progress");
    const cur = this.shadowRoot.getElementById("time-current");
    const dur = this.shadowRoot.getElementById("time-total");
    if (!bar || !cur || !dur) return;

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

  _showError(msg) {
    const titleEl = this.shadowRoot.getElementById("ep-title");
    if (titleEl) titleEl.textContent = msg;
  }

  async _submitFeedback() {
    const nameInput = this.shadowRoot.getElementById("fb-name");
    const msgInput = this.shadowRoot.getElementById("fb-message");
    const epCheck = this.shadowRoot.getElementById("fb-include-ep");
    const statusEl = this.shadowRoot.getElementById("fb-status");
    const submitBtn = this.shadowRoot.getElementById("fb-submit");

    const message = (msgInput?.value || "").trim();
    const sender = (nameInput?.value || "").trim();
    const epTitle = epCheck?.checked
      ? this._episodes[this._currentIndex]?.title || ""
      : "";

    if (!message) {
      statusEl.textContent = "Bitte schreibe kurz dein Feedback.";
      statusEl.className = "fb-status error";
      return;
    }

    if (!this._feedbackConfigured) {
      window.open(this._feedbackFallbackUrl, "_blank", "noopener");
      statusEl.textContent = "Feedback-Seite geöffnet (kein Webhook konfiguriert).";
      statusEl.className = "fb-status ok";
      return;
    }

    submitBtn.disabled = true;
    statusEl.textContent = "Wird gesendet…";
    statusEl.className = "fb-status";

    try {
      await this._hass.callApi("POST", "wohnsinnig_vernetzt/feedback", {
        sender,
        message,
        episode: epTitle,
      });
      msgInput.value = "";
      statusEl.textContent = "Danke! Dein Feedback wurde gesendet.";
      statusEl.className = "fb-status ok";
    } catch (err) {
      const detail = err?.body?.error || err?.message || "Senden fehlgeschlagen.";
      statusEl.textContent = detail;
      statusEl.className = "fb-status error";
    } finally {
      submitBtn.disabled = false;
    }
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

  _updateUI() {
    const ep = this._episodes[this._currentIndex];
    const cover = this.shadowRoot.getElementById("cover");
    const podcastLabel = this.shadowRoot.getElementById("podcast-label");
    const epTitle = this.shadowRoot.getElementById("ep-title");
    const epMeta = this.shadowRoot.getElementById("ep-meta");
    const listToggle = this.shadowRoot.getElementById("list-toggle");
    const listSection = this.shadowRoot.getElementById("list-section");
    const fbSection = this.shadowRoot.getElementById("feedback-section");
    const fbHint = this.shadowRoot.getElementById("fb-hint");

    if (podcastLabel) podcastLabel.textContent = this._podcastTitle;

    if (!ep) {
      if (epTitle) epTitle.textContent = "Keine Folgen verfügbar";
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

    if (fbSection) {
      fbSection.style.display = this._feedbackOpen ? "block" : "none";
    }

    if (fbHint) {
      fbHint.textContent = this._feedbackConfigured
        ? "Dein Feedback landet direkt bei Patrick & Niels."
        : "Hinweis: Noch kein Webhook hinterlegt – Klick öffnet wohnsinnigvernetzt.de.";
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
          width: 40px;
          height: 40px;
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
        .footer-bar {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-top: 10px;
          padding-top: 8px;
          border-top: 1px solid var(--divider-color);
          gap: 8px;
        }
        .footer-btn {
          font-size: 12px;
          color: var(--secondary-text-color);
          padding: 4px 6px;
          border-radius: 6px;
        }
        .footer-btn:hover {
          color: var(--primary-color);
          background: var(--secondary-background-color);
        }
        .search-input, .fb-input, .fb-textarea {
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
        .fb-textarea {
          min-height: 70px;
          resize: vertical;
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
        .feedback-section {
          margin-top: 10px;
          padding-top: 8px;
          border-top: 1px solid var(--divider-color);
        }
        .fb-hint {
          font-size: 11px;
          color: var(--secondary-text-color);
          margin-top: 2px;
        }
        .fb-check-row {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 12px;
          color: var(--secondary-text-color);
          margin-top: 8px;
        }
        .fb-actions {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
          margin-top: 8px;
        }
        .fb-submit {
          padding: 7px 14px;
          border-radius: 8px;
          background: var(--primary-color);
          color: var(--text-primary-color, #fff);
          font-size: 12px;
          font-weight: 600;
        }
        .fb-submit:disabled {
          opacity: 0.6;
        }
        .fb-status {
          font-size: 12px;
          color: var(--secondary-text-color);
        }
        .fb-status.ok {
          color: var(--success-color, #4caf50);
        }
        .fb-status.error {
          color: var(--error-color, #db4437);
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

        <div class="footer-bar">
          <button id="list-toggle" class="footer-btn" type="button">Alle Folgen</button>
          <button id="feedback-toggle" class="footer-btn" type="button">💬 Feedback senden</button>
        </div>

        <div id="feedback-section" class="feedback-section" style="display:none;">
          <div id="fb-hint" class="fb-hint"></div>
          <input id="fb-name" class="fb-input" type="text" placeholder="Dein Name (optional)" />
          <textarea id="fb-message" class="fb-textarea" placeholder="Dein Feedback, deine Frage oder Themenwunsch…"></textarea>
          <label class="fb-check-row">
            <input id="fb-include-ep" type="checkbox" checked />
            Aktuelle Folge als Bezug mitschicken
          </label>
          <div class="fb-actions">
            <span id="fb-status" class="fb-status"></span>
            <button id="fb-submit" class="fb-submit" type="button">Absenden</button>
          </div>
        </div>

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
      this._audio.currentTime = Number(e.target.value);
    });
    this.shadowRoot.getElementById("list-toggle").addEventListener("click", () => {
      this._listOpen = !this._listOpen;
      this._updateUI();
    });
    this.shadowRoot.getElementById("feedback-toggle").addEventListener("click", () => {
      this._feedbackOpen = !this._feedbackOpen;
      this._updateUI();
    });
    this.shadowRoot.getElementById("fb-submit").addEventListener("click", () => this._submitFeedback());
    this.shadowRoot.getElementById("search-input").addEventListener("input", (e) => {
      this._searchQuery = e.target.value || "";
      this._renderEpisodeList();
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
    name: "Wohnsinnig vernetzt Player",
    description: "Podcast-Player mit Episodenliste, Suche und Feedback-Formular.",
  });
}
