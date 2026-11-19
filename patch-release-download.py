from pathlib import Path

# Patch the Release asset downloader. No Authorization header is sent for
# public assets; write operations still use the Owner token in GitHubClient.
module = Path('public/modules/github.js')
source = module.read_text(encoding='utf-8')
old_download = '''  async downloadAsset(asset) {
    const url = asset.browser_download_url || asset.url;
    if (!url) throw new Error("GitHub did not provide an asset download URL.");
    let response;
    try { response = await fetch(url, { cache: "no-store" }); }
    catch { throw new Error("Could not download this public Release asset. Check the network or browser CORS settings."); }
    if (!response.ok) throw new Error(`Could not download Release asset (${response.status}).`);
    return response.blob();
  }
'''
new_download = '''  async downloadAsset(asset) {
    const urls = [
      asset?.url || (asset?.id
        ? `${API}/repos/${encodeURIComponent(this.owner)}/${encodeURIComponent(this.repo)}/releases/assets/${asset.id}`
        : ""),
      asset?.browser_download_url || ""
    ].filter(Boolean);
    if (!urls.length) throw new Error("GitHub did not provide a Release asset download URL.");
    let lastError = null;
    for (const url of urls) {
      try {
        const response = await fetch(url, {
          method: "GET",
          headers: { Accept: "application/octet-stream" },
          cache: "no-store"
        });
        if (response.ok) return response.blob();
        lastError = new Error(`HTTP ${response.status}`);
      } catch (error) {
        lastError = error;
      }
    }
    throw new Error("Browser could not read the public GitHub Release asset. The Owner Token was verified separately. Try downloading the JSON file from the Release page and importing it below, or test in a private window with extensions disabled.");
  }
'''
if old_download not in source:
    raise SystemExit('Expected original downloadAsset function not found.')
module.write_text(source.replace(old_download, new_download), encoding='utf-8')

# Add a manual import route for the tiny encrypted control JSON file. This
# does not initialize a new vault or alter the published Release.
app = Path('public/app.js')
app_source = app.read_text(encoding='utf-8')
verify_marker = 'async function verifyLockOwnerAction() {'
helper = '''async function importOwnerConfigFile() {
  if (!state.isOwner || !state.token) {
    showMessage("শুধু যাচাইকৃত repository owner configuration import করতে পারবেন।", "error");
    return;
  }
  const input = $("#owner-config-file");
  const file = input?.files?.[0];
  if (!file) {
    showMessage("প্রথমে vault-config JSON ফাইলটি নির্বাচন করুন।", "error");
    return;
  }
  try {
    const config = JSON.parse(await file.text());
    validateConfig(config);
    if (!Number.isInteger(Number(config.configVersion))) {
      throw new Error("Configuration version is missing or invalid.");
    }
    state.config = config;
    localStorage.setItem("pvault-public-config", JSON.stringify(config));
    togglePanel("recovery");
    showMessage("Configuration file লোড হয়েছে। এখন Recovery Key দিয়ে Vault পুনরুদ্ধার করুন।", "success");
  } catch (error) {
    showMessage("Configuration file গ্রহণ করা যায়নি: " + (error.message || "Invalid JSON"), "error");
  }
}

'''
if verify_marker not in app_source:
    raise SystemExit('Owner verification handler not found in app.js.')
if 'async function importOwnerConfigFile()' not in app_source:
    app_source = app_source.replace(verify_marker, helper + verify_marker, 1)

fetch_line = '    const remote = await state.client.fetchLatestConfig();'
fetch_replacement = '''    let remote;
    try {
      remote = await state.client.fetchLatestConfig();
    } catch (configError) {
      // Keep the already-verified Owner session. Do not treat a CORS/network
      // failure as "no config" and never offer first-time setup in this case.
      state.config = null;
      $("#owner-config-import")?.classList.remove("hidden");
      togglePanel("owner");
      showMessage("Owner account যাচাই সফল হয়েছে, কিন্তু browser GitHub Release থেকে configuration পড়তে পারেনি। নতুন Vault তৈরি করবেন না। Release page থেকে vault-config JSON ডাউনলোড করে নিচে import করুন।", "error");
      return;
    }'''
if fetch_line not in app_source:
    raise SystemExit('Expected fetchLatestConfig call not found in owner verification handler.')
app_source = app_source.replace(fetch_line, fetch_replacement, 1)

event_marker = '  $("#verify-lock-owner").onclick=verifyLockOwnerAction;'
if event_marker not in app_source:
    raise SystemExit('Owner verification event binding not found.')
if 'import-owner-config-btn' not in app_source:
    app_source = app_source.replace(event_marker, event_marker + '\n  $("#import-owner-config-btn").onclick=importOwnerConfigFile;', 1)

app.write_text(app_source, encoding='utf-8')

# Inject the owner-only file import controls.
html = Path('public/index.html')
html_source = html.read_text(encoding='utf-8')
button = '        <button id="verify-lock-owner" type="button" class="primary-btn full" data-i18n="verifyOwner">Verify owner account</button>\n'
import_panel = '''        <div id="owner-config-import" class="hidden">
          <p class="security-hint">Configuration download blocked? Download the current encrypted JSON asset from the Vault Release page, then select it here. Do not create a new Vault.</p>
          <p><a href="https://github.com/tareks04/personal-pdf-vault-60/releases/tag/vault-control" target="_blank" rel="noopener">Open Vault configuration Release ↗</a></p>
          <label class="field-label" for="owner-config-file">Import existing Vault configuration (.json)</label>
          <input id="owner-config-file" type="file" accept=".json,application/json">
          <button id="import-owner-config-btn" type="button" class="secondary-btn full">Import configuration and continue</button>
        </div>
'''
if 'id="owner-config-import"' not in html_source:
    if button not in html_source:
        raise SystemExit('Owner Verify button not found in index.html.')
    html_source = html_source.replace(button, button + import_panel, 1)
html.write_text(html_source, encoding='utf-8')

# Invalidate the previously cached shell.
worker = Path('public/service-worker.js')
worker_source = worker.read_text(encoding='utf-8')
old_caches = ('personal-pdf-vault-shell-v1', 'personal-pdf-vault-shell-v2-owner-lock')
new_cache = 'personal-pdf-vault-shell-v5-owner-config-import'
matched = next((name for name in old_caches if name in worker_source), None)
if not matched:
    raise SystemExit('Expected original service worker cache name not found.')
worker.write_text(worker_source.replace(matched, new_cache), encoding='utf-8')

print('Applied owner-session preservation and manual encrypted configuration import.')

# TEMP: inspect unlock form handler and state initialization.
app_rows = Path('public/app.js').read_text(encoding='utf-8').splitlines()
for i, row in enumerate(app_rows):
    if re.search(r'unlock-form|unlockVault|unlock-password|async function unlock|function unlock', row, re.I):
        print(f'UNLOCK HIT {i+1}: {row[:500]}')
        for j in range(max(0,i-3), min(len(app_rows),i+8)):
            print(f'UNLOCK {j+1}: {app_rows[j][:500]}')
