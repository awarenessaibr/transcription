/**
 * llm-providers.js — shared LLM provider / model / API-key UI.
 *
 * Goals (see /v1/llm/* in src/llm/router.py):
 *   - The user never types an API endpoint. Base URLs and provider routing live
 *     server-side (src/llm/providers.py).
 *   - Only providers whose credentials are already stored (UI or .env) are
 *     offered for chat; unconfigured ones stay visible but "locked" so the user
 *     can add a key inline.
 *   - The model dropdown is a function of the selected provider.
 *
 * Any element with `data-provider-scope="<name>"` becomes a scope. Inside it:
 *   [data-role="provider-tabs"]  → provider pills (rendered here)
 *   [data-role="model-select"]   → <select> filled with that provider's models
 *   [data-role="provider-hint"]  → contextual status / warnings
 *   [data-role="model-meta"]     → context window / tier / best-for
 *   [data-role="inline-key"]     → inline "add key" row for locked providers
 *
 * Globals consumed by the template: openApiKeysModal(), closeApiKeysModal().
 */
(function (global) {
  'use strict';

  const API_BASE = '/v1/llm';
  const STORAGE_KEY = 'transcription.llm.selection';

  /** Order used to pick a sensible default provider (first usable wins). */
  const PROVIDER_PREFERENCE = [
    'deepseek', 'ollama', 'cerebras', 'xai', 'anthropic', 'openrouter', 'fireworks',
  ];

  const cache = { providers: null, promise: null };
  const scopes = new Map();

  // ── Small helpers ────────────────────────────────────────────────────────

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  function notify(message, type) {
    if (typeof global.showToast === 'function') {
      global.showToast(type === 'error' ? `⚠ ${message}` : message);
    } else if (typeof global.showNotification === 'function') {
      global.showNotification(message, type || 'info');
    } else {
      console.log(`[llm-providers] ${type || 'info'}: ${message}`);
    }
  }

  /** FastAPI returns `detail` as a string, or as a validation-error array. */
  function errorText(data, res) {
    if (!data) return `HTTP ${res.status}`;
    const detail = data.detail;
    if (typeof detail === 'string' && detail) return detail;
    if (Array.isArray(detail) && detail.length) {
      return detail.map((item) => item.msg || JSON.stringify(item)).join('; ');
    }
    if (data.error && data.error.message) return data.error.message;
    if (detail) return JSON.stringify(detail);
    return `HTTP ${res.status}`;
  }

  function readStored() {
    try {
      return JSON.parse(global.localStorage.getItem(STORAGE_KEY) || '{}') || {};
    } catch (e) {
      return {};
    }
  }

  function writeStored(patch) {
    try {
      global.localStorage.setItem(STORAGE_KEY, JSON.stringify(Object.assign(readStored(), patch)));
    } catch (e) {
      /* private mode — selection simply won't persist */
    }
  }

  // ── Provider data ────────────────────────────────────────────────────────

  async function loadProviders(force) {
    if (cache.providers && !force) return cache.providers;
    if (cache.promise && !force) return cache.promise;

    cache.promise = (async () => {
      const res = await fetch(`${API_BASE}/providers`, { headers: { Accept: 'application/json' } });
      if (!res.ok) throw new Error(`Failed to load LLM providers (HTTP ${res.status})`);
      const data = await res.json();
      cache.providers = Array.isArray(data) ? data : (data.providers || []);
      return cache.providers;
    })();

    try {
      return await cache.promise;
    } catch (err) {
      cache.providers = null;
      throw err;
    } finally {
      cache.promise = null;
    }
  }

  function providerById(id) {
    if (!cache.providers || !id) return null;
    return cache.providers.find((p) => p.id === id) || null;
  }

  function modelsOf(id) {
    const provider = providerById(id);
    return provider ? (provider.models || []) : [];
  }

  /** A provider is usable when its key requirement is satisfied and it has models. */
  function isUsable(provider) {
    if (!provider) return false;
    const hasCredentials = provider.configured || !provider.requires_key;
    return hasCredentials && (provider.models || []).length > 0;
  }

  function pickProvider(preferredId) {
    const all = cache.providers || [];
    if (preferredId) {
      const preferred = all.find((p) => p.id === preferredId);
      if (isUsable(preferred)) return preferred.id;
    }
    for (const id of PROVIDER_PREFERENCE) {
      const hit = all.find((p) => p.id === id);
      if (isUsable(hit)) return hit.id;
    }
    const usable = all.filter(isUsable);
    if (usable.length) return usable[0].id;
    return all.length ? all[0].id : '';
  }

  function credentialLabel(provider) {
    if (!provider) return 'Not configured';
    if (provider.id === 'ollama') return 'Local runtime — no key required';
    if (provider.key_source === 'ui') return `Configured in this app · ${provider.key_masked || '••••'}`;
    if (provider.key_source === 'env') return `Configured via .env · ${provider.key_masked || '••••'}`;
    return 'Not configured';
  }

  function modelLabel(model) {
    const name = model.name && model.name !== model.id ? `${model.name} — ${model.id}` : model.id;
    const suffix = model.tier && model.tier !== 'paid' ? `  [${model.tier}]` : '';
    return `${name}${suffix}`;
  }

  // ── Scope rendering ──────────────────────────────────────────────────────

  function renderTabs(scope) {
    const host = scope.root.querySelector('[data-role="provider-tabs"]');
    if (!host) return;

    host.innerHTML = '';
    (cache.providers || []).forEach((provider) => {
      const usable = isUsable(provider);
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.provider = provider.id;
      button.className = 'provider-tab'
        + (provider.id === scope.provider ? ' active' : '')
        + (provider.configured || !provider.requires_key ? ' configured' : '');
      button.title = provider.configured || !provider.requires_key
        ? `${provider.label} — ready`
        : `${provider.label} — needs an API key (click to add)`;
      button.innerHTML = '<span class="dot"></span>'
        + `<i class="fas ${esc(provider.icon || 'fa-server')}"></i>`
        + `<span>${esc(provider.label)}</span>`
        + (!provider.configured && provider.requires_key ? ' <i class="fas fa-lock lock"></i>' : '')
        + (usable ? '' : ' <i class="fas fa-triangle-exclamation lock"></i>');
      host.appendChild(button);
    });
  }

  function renderModels(scope) {
    const select = scope.modelSelect;
    if (!select) return;

    const models = modelsOf(scope.provider);
    select.innerHTML = '';

    if (!models.length) {
      const option = document.createElement('option');
      option.value = '';
      option.textContent = scope.provider ? 'No models available' : 'No providers available';
      select.appendChild(option);
      select.disabled = true;
      scope.model = '';
      return;
    }

    models.forEach((model) => {
      const option = document.createElement('option');
      option.value = model.id;
      option.textContent = modelLabel(model);
      select.appendChild(option);
    });

    select.disabled = false;
    select.value = scope.model && models.some((m) => m.id === scope.model)
      ? scope.model
      : models[0].id;
    scope.model = select.value;
  }

  function renderHint(scope) {
    const host = scope.root.querySelector('[data-role="provider-hint"]');
    if (!host) return;

    const provider = providerById(scope.provider);
    host.className = 'provider-hint';
    host.innerHTML = '';

    if (!provider) {
      host.classList.add('warn');
      host.textContent = 'No LLM providers available. Check the server logs for /v1/llm/providers.';
      return;
    }

    if (provider.requires_key && !provider.configured) {
      host.classList.add('warn');
      host.innerHTML = `<i class="fas fa-lock"></i> <strong>${esc(provider.label)}</strong> needs an API key. `
        + 'Add one below, or use <em>Manage API Keys</em> for all providers.';
      return;
    }

    if (!modelsOf(provider.id).length) {
      host.classList.add('warn');
      host.innerHTML = provider.id === 'ollama'
        ? '<i class="fas fa-plug"></i> No local models found — is Ollama running?'
        : `<i class="fas fa-circle-exclamation"></i> No models in the catalog for <strong>${esc(provider.label)}</strong>.`;
      return;
    }

    host.classList.add('ok');
    host.innerHTML = `<i class="fas fa-check-circle"></i> ${esc(credentialLabel(provider))}`;
  }

  function renderModelMeta(scope) {
    const host = scope.root.querySelector('[data-role="model-meta"]');
    if (!host) return;

    const model = modelsOf(scope.provider).find((m) => m.id === scope.model);
    if (!model) {
      host.innerHTML = '';
      return;
    }

    const bits = [];
    if (model.context_window) bits.push(`${Math.round(model.context_window / 1024)}k ctx`);
    if (model.supports_thinking) bits.push('thinking');
    if (model.supports_vision) bits.push('vision');
    if (model.input_cost_per_1m != null) bits.push(`in $${model.input_cost_per_1m}/1M`);
    if (model.output_cost_per_1m != null) bits.push(`out $${model.output_cost_per_1m}/1M`);

    host.innerHTML = `<span class="badge">${esc(model.tier || 'model')}</span>`
      + esc(bits.join(' · '))
      + (model.best_for ? ` — ${esc(model.best_for)}` : '');
  }

  function renderInlineKey(scope) {
    const host = scope.root.querySelector('[data-role="inline-key"]');
    if (!host) return;

    const provider = providerById(scope.provider);
    const needsKey = provider && provider.requires_key && !provider.configured;

    if (!needsKey) {
      host.hidden = true;
      host.innerHTML = '';
      return;
    }

    host.hidden = false;
    host.innerHTML = `
      <div class="apikey-row" data-provider="${esc(provider.id)}">
        <div class="pk-info">
          <div class="pk-name"><i class="fas fa-key"></i> ${esc(provider.label)} API key</div>
          <div class="pk-status">Not configured</div>
        </div>
        <input type="password" data-role="inline-key-input"
               name="llm_api_key_${esc(provider.id)}" autocomplete="off"
               placeholder="Paste API key…" spellcheck="false">
        <button type="button" class="btn small primary" data-action="save">Save</button>
        <button type="button" class="btn small" data-action="verify">Test</button>
      </div>`;
  }

  function renderScope(scope) {
    renderTabs(scope);
    renderModels(scope);
    renderHint(scope);
    renderModelMeta(scope);
    renderInlineKey(scope);
  }

  function renderAll() {
    scopes.forEach(renderScope);
  }

  function fireChange(scope) {
    const selection = { provider: scope.provider, model: scope.model };
    scope.listeners.forEach((cb) => {
      try {
        cb(selection, scope.name);
      } catch (err) {
        console.error('[llm-providers] onChange handler failed', err);
      }
    });
  }

  // ── Provider / model selection API ───────────────────────────────────────

  function selectProvider(name, providerId, modelId) {
    const scope = scopes.get(name);
    if (!scope) return;

    scope.provider = providerId;
    scope.touched = true;

    const models = modelsOf(providerId);
    const wanted = modelId || scope.model;
    scope.model = models.some((m) => m.id === wanted) ? wanted : (models[0] ? models[0].id : '');

    const patch = {};
    patch[name] = { provider: scope.provider, model: scope.model };
    writeStored(patch);

    renderScope(scope);
    fireChange(scope);
  }

  function getSelection(name) {
    const scope = scopes.get(name);
    if (!scope) return { provider: '', model: '' };
    return { provider: scope.provider, model: scope.model };
  }

  /** Canonical payload for POST /v1/llm/chat/completions. */
  function chatCompletions(selection, payload) {
    const body = Object.assign({}, payload, {
      provider: selection.provider,
      model: selection.model,
    });
    return fetch(`${API_BASE}/chat/completions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: body.stream ? 'text/event-stream' : 'application/json',
      },
      body: JSON.stringify(body),
    });
  }

  /** Selection for a scope, or a friendly error when it is not usable yet. */
  function requireSelection(name) {
    const scope = scopes.get(name);
    if (!scope) throw new Error(`Unknown LLM scope "${name}"`);
    const provider = providerById(scope.provider);
    if (!provider) throw new Error('No LLM provider selected.');
    if (provider.requires_key && !provider.configured) {
      throw new Error(`${provider.label} has no API key. Add one in Manage API Keys.`);
    }
    if (!scope.model) {
      throw new Error(`No model selected for ${provider.label}.`);
    }
    return { provider: scope.provider, model: scope.model };
  }

  function onChange(name, callback) {
    const scope = scopes.get(name);
    if (scope && typeof callback === 'function') scope.listeners.push(callback);
  }

  // ── API keys modal ───────────────────────────────────────────────────────

  function apiKeyRowHtml(provider) {
    const keyLine = credentialLabel(provider);
    const ok = provider.configured || !provider.requires_key;

    const controls = provider.requires_key
      ? `<input type="password" data-role="key-input" name="llm_api_key_${esc(provider.id)}"
                placeholder="Paste API key…" autocomplete="off" spellcheck="false">
         <button type="button" class="btn small primary" data-action="save">Save</button>
         <button type="button" class="btn small" data-action="verify">Test</button>
         <button type="button" class="btn small danger" data-action="clear">Remove</button>`
      : '<button type="button" class="btn small" data-action="verify">Test connection</button>';

    return `
      <div class="apikey-row" data-provider="${esc(provider.id)}">
        <div class="pk-info">
          <div class="pk-name">
            <i class="fas ${esc(provider.icon || 'fa-server')}"></i> ${esc(provider.label)}
            <span class="badge">${esc(provider.kind)}</span>
          </div>
          <div class="pk-status ${ok ? 'ok' : ''}">${esc(keyLine)}</div>
        </div>
        ${controls}
      </div>`;
  }

  function paintApiKeyRows(host, providers) {
    host.innerHTML = providers.map(apiKeyRowHtml).join('');
  }

  async function renderApiKeysModal(providers) {
    const host = document.getElementById('api-keys-list');
    if (!host) return;

    if (!providers) {
      // Paint whatever we already have so the modal never stalls on the network,
      // then refresh in the background (Ollama model discovery can be slow).
      if (cache.providers && cache.providers.length) {
        paintApiKeyRows(host, cache.providers);
        loadProviders(true)
          .then((fresh) => { if (isApiKeysModalOpen()) paintApiKeyRows(host, fresh); })
          .catch(() => { /* keep the cached rows on screen */ });
        return;
      }

      host.innerHTML = '<p style="color:var(--gray);font-size:12px;">Loading providers…</p>';
      try {
        providers = await loadProviders(true);
      } catch (err) {
        host.innerHTML = `<p style="color:var(--red);font-size:12px;">${esc(err.message)}</p>`;
        return;
      }
    }

    host.innerHTML = providers.map(apiKeyRowHtml).join('');
  }

  function isApiKeysModalOpen() {
    const modal = document.getElementById('api-keys-modal');
    if (!modal) return false;
    return global.getComputedStyle(modal).display !== 'none';
  }

  /** Re-render the modal only when it is actually visible. */
  function syncOpenApiKeysModal() {
    if (isApiKeysModalOpen()) {
      renderApiKeysModal(cache.providers || undefined);
    }
  }

  /**
   * Open the modal. Passing a scope name (the template does this) focuses the
   * row of the provider that scope currently has selected.
   */
  function openApiKeysModal(scopeName) {
    const modal = document.getElementById('api-keys-modal');
    if (!modal) return;

    const scope = typeof scopeName === 'string' ? scopes.get(scopeName) : null;
    // `.modal-backdrop` uses flex for centering, so don't override it with `block`.
    modal.style.display = 'flex';
    renderApiKeysModal();

    if (!scope || !scope.provider) return;

    const focusRow = () => {
      const row = document.querySelector(`#api-keys-list .apikey-row[data-provider="${scope.provider}"]`);
      if (!row) return;
      row.classList.add('highlight');
      row.scrollIntoView({ block: 'nearest' });
      const input = row.querySelector('[data-role="key-input"]');
      if (input && !input.value) input.focus();
    };
    focusRow();
    // The list may still be painting from a background refresh.
    global.setTimeout(focusRow, 400);
  }

  function closeApiKeysModal() {
    const modal = document.getElementById('api-keys-modal');
    if (modal) modal.style.display = 'none';
  }

  async function saveKey(providerId, rawKey, row, button) {
    const apiKey = (rawKey || '').trim();
    if (!apiKey) {
      notify('Please paste an API key first.', 'error');
      return;
    }

    if (button) button.disabled = true;
    try {
      const res = await fetch(`${API_BASE}/providers/${encodeURIComponent(providerId)}/key`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: apiKey }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(errorText(data, res));

      notify(`API key saved for ${providerId}.`);
      if (row) {
        const status = row.querySelector('.pk-status');
        if (status) {
          status.classList.add('ok');
          status.textContent = `Configured in this app · ${data.key_masked || '••••'}`;
        }
        const input = row.querySelector('[data-role="key-input"], [data-role="inline-key-input"]');
        if (input) input.value = '';
      }
      await refresh(true);
      syncOpenApiKeysModal();
    } catch (err) {
      notify(`Could not save key: ${err.message}`, 'error');
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function clearKey(providerId) {
    if (!global.confirm(`Remove the stored API key for ${providerId}?`)) return;
    try {
      const res = await fetch(`${API_BASE}/providers/${encodeURIComponent(providerId)}/key`, {
        method: 'DELETE',
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(errorText(data, res));
      }
      notify(`API key removed for ${providerId}.`);
      await refresh(true);
      syncOpenApiKeysModal();
    } catch (err) {
      notify(`Could not remove key: ${err.message}`, 'error');
    }
  }

  async function verifyKey(providerId, rawKey, row, button) {
    if (button) button.disabled = true;
    try {
      const body = rawKey && rawKey.trim() ? { api_key: rawKey.trim() } : {};
      const res = await fetch(`${API_BASE}/providers/${encodeURIComponent(providerId)}/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(errorText(data, res));

      if (data.ok) {
        const suffix = data.model_count != null ? ` (${data.model_count} models)` : '';
        notify(`Connection OK: ${providerId}${suffix}.`);
      } else {
        notify(`${providerId}: ${data.detail || 'verification failed'}`, 'error');
      }
      if (row) {
        const status = row.querySelector('.pk-status');
        if (status && data.ok && rawKey) status.textContent = 'Verified — save to use it';
      }
    } catch (err) {
      notify(`${providerId}: ${err.message}`, 'error');
    } finally {
      if (button) button.disabled = false;
    }
  }

  /** Delegated handler for both the modal and the inline per-scope key rows. */
  function handleKeyAction(event) {
    const button = event.target.closest('[data-action]');
    if (button) {
      const row = button.closest('.apikey-row');
      const providerId = row && row.dataset.provider;
      if (!providerId) return;

      const input = row.querySelector('[data-role="key-input"], [data-role="inline-key-input"]');
      const rawKey = input ? input.value : '';

      if (button.dataset.action === 'save') {
        event.preventDefault();
        saveKey(providerId, rawKey, row, button);
      } else if (button.dataset.action === 'verify') {
        event.preventDefault();
        verifyKey(providerId, rawKey, row, button);
      } else if (button.dataset.action === 'clear') {
        event.preventDefault();
        clearKey(providerId);
      }
      return;
    }

    // Provider pill click
    const tab = event.target.closest('.provider-tab');
    if (!tab) return;
    const scopeRoot = tab.closest('[data-provider-scope]');
    if (!scopeRoot) return;
    selectProvider(scopeRoot.getAttribute('data-provider-scope'), tab.dataset.provider);
  }

  // ── Wiring / lifecycle ───────────────────────────────────────────────────

  function registerScopes() {
    document.querySelectorAll('[data-provider-scope]').forEach((root) => {
      const name = root.getAttribute('data-provider-scope');
      const modelSelect = root.querySelector('[data-role="model-select"]');
      if (!name || !modelSelect || scopes.has(name)) return;

      const scope = {
        name,
        root,
        modelSelect,
        provider: '',
        model: '',
        touched: false,
        listeners: [],
      };
      scopes.set(name, scope);

      root.addEventListener('click', handleKeyAction);

      modelSelect.addEventListener('change', () => {
        scope.model = modelSelect.value;
        const patch = {};
        patch[name] = { provider: scope.provider, model: scope.model };
        writeStored(patch);
        renderModelMeta(scope);
        fireChange(scope);
      });
    });

    const modal = document.getElementById('api-keys-modal');
    if (modal) {
      modal.addEventListener('click', (event) => {
        if (event.target === modal) closeApiKeysModal();
        else handleKeyAction(event);
      });
    }
  }

  /** Fetch providers and (re)hydrate every registered scope. */
  async function refresh(force) {
    await loadProviders(force);

    const stored = readStored();
    const anyUsable = (cache.providers || []).some(isUsable);
    const patch = {};

    scopes.forEach((scope) => {
      const saved = stored[scope.name] || {};
      const current = providerById(scope.provider);

      // Re-pick when the provider vanished, or when the stored choice is unusable
      // but another provider became usable (e.g. the user just added an API key).
      // A provider the user picked in this session is never overridden.
      const stale = !current || (!isUsable(current) && anyUsable && !scope.touched);
      if (stale) {
        scope.provider = pickProvider(saved.provider);
      }

      const models = modelsOf(scope.provider);
      const wanted = scope.model || saved.model;
      scope.model = models.some((m) => m.id === wanted) ? wanted : (models[0] ? models[0].id : '');

      patch[scope.name] = { provider: scope.provider, model: scope.model };
      renderScope(scope);
    });

    writeStored(patch);
    return cache.providers;
  }

  function init() {
    registerScopes();
    refresh().catch((err) => {
      console.warn('[llm-providers] initial load failed', err);
      notify('Failed to load LLM providers — check the server.', 'error');
    });
  }

  // ── Public API ───────────────────────────────────────────────────────────

  global.LLMProviders = {
    init,
    refresh,
    loadProviders,
    getSelection,
    requireSelection,
    selectProvider,
    onChange,
    chatCompletions,
    providerById,
    modelsOf,
    isUsable,
    renderAll,
    openApiKeysModal,
    closeApiKeysModal,
  };

  // Template inline handlers reference these directly.
  global.openApiKeysModal = openApiKeysModal;
  global.closeApiKeysModal = closeApiKeysModal;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})(window);
