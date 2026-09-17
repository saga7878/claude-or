(() => {
  const COPY = {
    zh: {
      tagline: "下次启动生效。已经开着的会话不会换网关。",
      lcd: "今天还剩",
      utc: "免费请求 · UTC 日切",
      noQuota: "这家没有免费次数接口",
      noKey: "还没钥匙，次数未知",
      quotaFail: "次数接口读不到",
      exhausted: "今天用完了",
      stale: "目录超过 24 小时",
      missingCatalog: "还没目录，先刷新。",
      sync: "刷新目录",
      probe: "探活（不花聊天额度）",
      launch: "在终端打开",
      key: "钥匙",
      saveKey: "存钥匙",
      signup: "去开一把",
      keyPlaceholder: "粘贴 API key",
      keyMissing: "还没钥匙",
      roles: "下次默认",
      session: "会话",
      patch: "/model",
      search: "搜 id 或名字",
      use: "设为默认",
      emptyFilter: "没有匹配的模型。",
      envPin: (id) => `shell 里的 CLAUDE_OR_PROVIDER=${id} 压过了这里的选择。`,
      switched: (name) => `已切到 ${name}。下次 claude-or 走这家。`,
      savedKey: "钥匙已存。下一步：刷新目录。",
      savedModel: (id) => `已把会话默认设成 ${id}。`,
      savedRole: "下次默认已写进 profile。",
      launched: "已在终端启动。这个页面管不了已经开着的会话。",
      launchHint: (cmd) => `在终端运行：${cmd}`,
      up: "在线",
      down: "挂了",
      unknown: "未知",
      active: "当前",
      syncing: "刷新中…",
      theme: { system: "自动", light: "浅色", dark: "深色" },
      themeHint: {
        system: "外观跟随系统，点击改为浅色",
        light: "浅色，点击改为深色",
        dark: "深色，点击改为跟随系统",
      },
    },
    en: {
      tagline: "Applies to the next launch. A running session will not change gateway.",
      lcd: "left today",
      utc: "free requests · UTC reset",
      noQuota: "this provider has no free-request counter",
      noKey: "no key, quota unknown",
      quotaFail: "could not read quota",
      exhausted: "exhausted today",
      stale: "catalog older than 24h",
      missingCatalog: "no catalog yet — refresh.",
      sync: "Refresh catalog",
      probe: "Probe (does not spend chat quota)",
      launch: "Open in terminal",
      key: "Key",
      saveKey: "Store key",
      signup: "Get a key",
      keyPlaceholder: "Paste API key",
      keyMissing: "no key yet",
      roles: "Next defaults",
      session: "session",
      patch: "/model",
      search: "search id or name",
      use: "Set default",
      emptyFilter: "no matching models.",
      envPin: (id) => `CLAUDE_OR_PROVIDER=${id} in the shell overrides this page.`,
      switched: (name) => `Active provider is ${name}. Next claude-or uses it.`,
      savedKey: "Key stored. Next: refresh catalog.",
      savedModel: (id) => `Session default is ${id}.`,
      savedRole: "Defaults written to the profile.",
      launched: "Opened a terminal. This page cannot control a session already running.",
      launchHint: (cmd) => `Run in a terminal: ${cmd}`,
      up: "up",
      down: "down",
      unknown: "unknown",
      active: "live",
      syncing: "syncing…",
      theme: { system: "Auto", light: "Light", dark: "Dark" },
      themeHint: {
        system: "Appearance follows system. Click for light.",
        light: "Light. Click for dark.",
        dark: "Dark. Click to follow system.",
      },
    },
  };

  const ROLE_ORDER = [
    ["model", "session"],
    ["sonnet", "sonnet"],
    ["opus", "opus"],
    ["fable", "fable"],
    ["haiku", "haiku"],
  ];

  let state = null;
  let lang = "zh";
  let t = COPY.zh;

  const $ = (id) => document.getElementById(id);
  const THEME_KEY = "claude-or-theme";
  const THEME_ORDER = ["system", "light", "dark"];

  function systemTheme() {
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }

  function themePref() {
    const stored = localStorage.getItem(THEME_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") return stored;
    return "system";
  }

  function applyTheme() {
    const pref = themePref();
    const resolved = pref === "system" ? systemTheme() : pref;
    document.documentElement.dataset.theme = resolved;
    document.documentElement.style.colorScheme = resolved;
    const button = $("theme");
    if (!button) return;
    button.dataset.pref = pref;
    button.textContent = t.theme[pref];
    button.setAttribute("aria-label", t.themeHint[pref]);
  }

  function pickLang(stateLang) {
    const nav = String(navigator.language || "").toLowerCase();
    if (nav.startsWith("zh")) return "zh";
    if (stateLang === "en" || stateLang === "zh") return stateLang;
    return "zh";
  }

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
    ));
  }

  let toastTimer = 0;
  function toast(message) {
    const el = $("toast");
    window.clearTimeout(toastTimer);
    if (!message) {
      el.classList.remove("is-on");
      el.setAttribute("aria-hidden", "true");
      return;
    }
    el.textContent = message;
    el.setAttribute("aria-hidden", "false");
    el.classList.add("is-on");
    toastTimer = window.setTimeout(() => {
      el.classList.remove("is-on");
      el.setAttribute("aria-hidden", "true");
    }, 4000);
  }

  function activeProvider() {
    return (state.providers || []).find((item) => item.id === state.active) || state.providers[0];
  }

  async function api(path, options) {
    const response = await fetch(path, options);
    const text = await response.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch (err) {
      throw new Error(text || response.statusText);
    }
    if (!response.ok) {
      throw new Error((data && data.error) || text || response.statusText);
    }
    return data;
  }

  function applyCopy() {
    $("tagline").textContent = t.tagline;
    $("lcd-label").textContent = t.lcd;
    $("sync").textContent = t.sync;
    $("probe-label").textContent = t.probe;
    $("launch").textContent = t.launch;
    $("key-heading").textContent = t.key;
    $("key-save").textContent = t.saveKey;
    $("signup").textContent = t.signup;
    $("key-input").placeholder = t.keyPlaceholder;
    $("roles-heading").textContent = t.roles;
    $("patch-heading").textContent = t.patch;
    $("search").placeholder = t.search;
    $("th-id").textContent = "id";
    $("th-name").textContent = lang === "zh" ? "名字" : "name";
    $("th-ctx").textContent = "ctx";
    $("th-health").textContent = lang === "zh" ? "状态" : "health";
    applyTheme();
  }

  function formatReadout(text) {
    const match = /^(\d+)\s*\/\s*(\d+)$/.exec(text);
    if (!match) return esc(text);
    return `<span class="n">${esc(match[1])}</span><span class="slash">/</span><span class="n">${esc(match[2])}</span>`;
  }

  function setDigits(text, empty) {
    const digits = $("lcd-digits");
    const changed = digits.dataset.readout !== text;
    digits.classList.toggle("is-empty", empty);
    if (changed) {
      digits.classList.remove("is-tick");
      void digits.offsetWidth;
      digits.dataset.readout = text;
      digits.innerHTML = formatReadout(text);
      if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        digits.classList.add("is-tick");
      }
    }
  }

  function renderLcd(provider) {
    const meter = $("lcd");
    const sub = $("lcd-sub");
    const label = $("lcd-label");
    const quota = provider.quota || {};
    const hasNumbers =
      provider.quota_kind === "openrouter-key" &&
      provider.has_key &&
      quota.remaining != null &&
      quota.limit != null;
    meter.classList.toggle("is-quiet", !hasNumbers);
    if (provider.quota_kind !== "openrouter-key") {
      label.textContent = provider.name;
      setDigits("", true);
      sub.textContent = t.noQuota;
      return;
    }
    label.textContent = t.lcd;
    if (!provider.has_key) {
      setDigits("", true);
      sub.textContent = t.noKey;
      return;
    }
    if (!hasNumbers) {
      setDigits("", true);
      sub.textContent = t.quotaFail;
      return;
    }
    setDigits(`${quota.remaining} / ${quota.limit}`, false);
    const bits = [t.utc];
    if (quota.used != null) bits.unshift(lang === "zh" ? `已用 ${quota.used}` : `used ${quota.used}`);
    if (quota.remaining <= 0) bits.push(t.exhausted);
    if (provider.catalog.stale && provider.catalog.fetched_at) bits.push(t.stale);
    sub.textContent = bits.join(" · ");
  }

  function renderGates() {
    const root = $("gates");
    const providers = state.providers || [];
    const existing = [...root.querySelectorAll(".gate")];
    const same =
      existing.length === providers.length &&
      existing.every((el, index) => el.getAttribute("data-provider") === providers[index].id);
    if (same) {
      providers.forEach((provider, index) => {
        existing[index].setAttribute("aria-pressed", provider.active ? "true" : "false");
      });
      return;
    }
    root.innerHTML = providers.map((provider) => `
      <button type="button" class="gate" data-provider="${esc(provider.id)}" aria-pressed="${provider.active}">
        <i class="led" aria-hidden="true"></i>
        <b>${esc(provider.name)}</b>
      </button>
    `).join("");
  }

  function renderKey(provider) {
    if (provider.has_key) {
      $("key-status").textContent = `${provider.key_source} · ${provider.key_hint}`;
    } else {
      $("key-status").textContent = t.keyMissing;
    }
    $("signup").href = provider.signup;
    $("probe-wrap").hidden = provider.probe === "none";
  }

  function optionList(provider, selected) {
    return (provider.models || []).map((model) => (
      `<option value="${esc(model.id)}" ${model.id === selected ? "selected" : ""}>${esc(model.label || model.id)}</option>`
    )).join("");
  }

  function renderRoles(provider) {
    const labels = { model: t.session, sonnet: "Sonnet", opus: "Opus", fable: "Fable", haiku: "Haiku" };
    $("role-grid").innerHTML = ROLE_ORDER.map(([key, fallback]) => {
      const selected = (provider.defaults && provider.defaults[key]) || "";
      return `<label class="role">${esc(labels[key] || fallback)}
        <select data-role="${esc(key)}" ${provider.models.length ? "" : "disabled"}>
          ${optionList(provider, selected)}
        </select>
      </label>`;
    }).join("");
  }

  function healthLabel(health) {
    if (health === "up") return t.up;
    if (health === "down") return t.down;
    return t.unknown;
  }

  function ctxLabel(tokens) {
    const n = Number(tokens) || 0;
    if (n >= 1_000_000) return "1M";
    if (n >= 1000) return `${Math.round(n / 1000)}k`;
    return String(n);
  }

  function renderModels(provider) {
    const q = ($("search").value || "").trim().toLowerCase();
    const rows = (provider.models || []).filter((model) => {
      if (!q) return true;
      return `${model.id} ${model.name} ${model.label}`.toLowerCase().includes(q);
    });
    $("empty").hidden = rows.length > 0;
    $("empty").textContent = provider.models.length ? t.emptyFilter : t.missingCatalog;
    $("models").innerHTML = rows.map((model) => `
      <tr class="${model.health === "down" ? "down" : ""} ${model.stealth ? "stealth" : ""}">
        <td class="id">${esc(model.id)}</td>
        <td class="name">${esc(model.label || model.name || model.id)}</td>
        <td>${esc(ctxLabel(model.context_length))}</td>
        <td>${esc(healthLabel(model.health))}${model.probe_reason ? ` · ${esc(model.probe_reason)}` : ""}</td>
        <td><button type="button" class="linkish" data-use="${esc(model.id)}">${esc(t.use)}</button></td>
      </tr>
    `).join("");
  }

  function render() {
    if (!state) return;
    lang = pickLang(state.lang);
    t = COPY[lang];
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
    applyCopy();
    const provider = activeProvider();
    $("meta").textContent = state.provider_env
      ? `${state.bind} · v${state.version} · ${t.envPin(state.provider_env)}`
      : `${state.bind} · v${state.version}`;
    renderLcd(provider);
    renderGates();
    renderKey(provider);
    renderRoles(provider);
    renderModels(provider);
  }

  async function refresh() {
    state = await api("/api/state");
    render();
  }

  $("gates").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-provider]");
    if (!button) return;
    try {
      state = await api("/api/provider", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: button.getAttribute("data-provider") }),
      });
      render();
      toast(t.switched(activeProvider().name));
    } catch (err) {
      toast(String(err.message || err));
    }
  });

  $("sync").addEventListener("click", async () => {
    const button = $("sync");
    button.disabled = true;
    button.textContent = t.syncing;
    if (!$("lcd").classList.contains("is-quiet")) setDigits("SYNC", true);
    try {
      state = await api("/api/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: state.active, probe: $("probe").checked }),
      });
      render();
    } catch (err) {
      toast(String(err.message || err));
      render();
    } finally {
      button.disabled = false;
      button.textContent = t.sync;
    }
  });

  $("launch").addEventListener("click", async () => {
    try {
      const result = await api("/api/launch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: state.active }),
      });
      toast(t.launched);
      if (result && result.command) {
        $("toast").textContent = `${t.launched} ${result.command}`;
      }
    } catch (err) {
      const message = String(err.message || err);
      toast(message.startsWith("open a terminal") ? t.launchHint(message.replace(/^open a terminal and run:\s*/, "")) : message);
    }
  });

  $("key-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const key = $("key-input").value;
    try {
      state = await api("/api/key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: state.active, key }),
      });
      $("key-input").value = "";
      render();
      toast(t.savedKey);
    } catch (err) {
      toast(String(err.message || err));
    }
  });

  $("role-grid").addEventListener("change", async (event) => {
    const select = event.target.closest("select[data-role]");
    if (!select) return;
    try {
      state = await api("/api/defaults", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: state.active, [select.getAttribute("data-role")]: select.value }),
      });
      render();
      toast(t.savedRole);
    } catch (err) {
      toast(String(err.message || err));
    }
  });

  $("models").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-use]");
    if (!button) return;
    const id = button.getAttribute("data-use");
    try {
      state = await api("/api/defaults", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: state.active, model: id }),
      });
      render();
      toast(t.savedModel(id));
    } catch (err) {
      toast(String(err.message || err));
    }
  });

  $("search").addEventListener("input", () => {
    if (state) renderModels(activeProvider());
  });

  document.addEventListener("pointerdown", (event) => {
    if (event.button) return;
    const button = event.target.closest(".key, .gate, .linkish, .theme");
    if (!button || button.disabled) return;
    button.classList.add("is-pressed");
    const release = () => {
      button.classList.remove("is-pressed");
      window.removeEventListener("pointerup", release);
      window.removeEventListener("pointercancel", release);
    };
    window.addEventListener("pointerup", release);
    window.addEventListener("pointercancel", release);
  });

  $("theme").addEventListener("click", () => {
    const next = THEME_ORDER[(THEME_ORDER.indexOf(themePref()) + 1) % THEME_ORDER.length];
    localStorage.setItem(THEME_KEY, next);
    applyTheme();
  });

  window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => {
    if (themePref() === "system") applyTheme();
  });

  applyTheme();
  refresh().catch((err) => toast(String(err.message || err)));
})();
