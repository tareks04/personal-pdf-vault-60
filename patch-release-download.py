from pathlib import Path

module = Path('public/modules/github.js')
source = module.read_text(encoding='utf-8')
old = '''  async downloadAsset(asset) {
    const url = asset.browser_download_url || asset.url;
    if (!url) throw new Error("GitHub did not provide an asset download URL.");
    let response;
    try { response = await fetch(url, { cache: "no-store" }); }
    catch { throw new Error("Could not download this public Release asset. Check the network or browser CORS settings."); }
    if (!response.ok) throw new Error(`Could not download Release asset (${response.status}).`);
    return response.blob();
  }
'''
new = '''  async downloadAsset(asset) {
    // Request the binary through GitHub's REST asset endpoint instead of the
    // browser_download_url redirect chain, which can fail CORS in some browsers.
    const url = asset?.url || (asset?.id
      ? `${API}/repos/${encodeURIComponent(this.owner)}/${encodeURIComponent(this.repo)}/releases/assets/${asset.id}`
      : "");
    if (!url) throw new Error("GitHub did not provide a Release asset API URL.");
    let response;
    try {
      response = await fetch(url, {
        method: "GET",
        headers: this.headers({ Accept: "application/octet-stream" }),
        cache: "no-store"
      });
    } catch {
      throw new Error("Could not download the public Release asset through GitHub's binary API. Check the network, browser extensions, or GitHub availability.");
    }
    if (!response.ok) {
      let detail = "";
      try {
        const parsed = JSON.parse(await response.clone().text());
        detail = parsed?.message ? `: ${parsed.message}` : "";
      } catch { /* The error body may be binary or empty. */ }
      throw new Error(`Could not download Release asset (${response.status})${detail}.`);
    }
    // Vault configuration assets are JSON; preserve GitHub's content type.
    // GitHub may return the binary directly (200) or follow its documented redirect.
    return response.blob();
  }
'''
if old not in source:
    raise SystemExit('Expected old downloadAsset method was not found in extracted site bundle.')
module.write_text(source.replace(old, new), encoding='utf-8')

worker = Path('public/service-worker.js')
worker_source = worker.read_text(encoding='utf-8')
old_caches = ('personal-pdf-vault-shell-v1', 'personal-pdf-vault-shell-v2-owner-lock')
new_cache = 'personal-pdf-vault-shell-v3-release-asset-api'
matched_cache = next((name for name in old_caches if name in worker_source), None)
if not matched_cache:
    raise SystemExit('Expected service worker cache version was not found.')
worker.write_text(worker_source.replace(matched_cache, new_cache), encoding='utf-8')
print('Patched GitHub Release asset download and bumped the service-worker cache.')
