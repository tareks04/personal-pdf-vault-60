from pathlib import Path
import re

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
    state.manualConfigImport = true;
    localStorage.setItem("pvault-public-config", JSON.stringify(config));
    togglePanel(null);
    showMessage("বিদ্যমান Vault configuration লোড হয়েছে। Recovery Key প্রয়োজন নেই, যদি আপনার বর্তমান Master Password মনে থাকে। এখন উপরের Master Password দিয়ে Unlock করুন।", "success");
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

unlock_old = '''async function unlockWithPassword(password) {
  const config = await getLatestConfig(true);'''
unlock_new = '''async function unlockWithPassword(password) {
  const config = state.manualConfigImport && state.config
    ? state.config
    : await getLatestConfig(true);
  state.manualConfigImport = false;'''
if unlock_old not in app_source:
    raise SystemExit('unlockWithPassword implementation was not found.')
app_source = app_source.replace(unlock_old, unlock_new, 1)

old_reader = '''async function fetchEncryptedPdf(doc) {
  const cached = await getCachedPair(doc.assetId);
  if (cached?.pdfBlob) return cached.pdfBlob;
  const asset = doc.pdfAsset;
  if (!asset?.browser_download_url) throw new Error("Encrypted PDF asset is not cached on this device.");
  const blob = await state.client.downloadAsset(asset);
  return blob;
}'''
new_reader = '''async function fetchEncryptedPdf(doc) {
  const cached = await getCachedPair(doc.assetId).catch(() => null);
  if (cached?.pdfBlob) return cached.pdfBlob;

  // A public Release asset can be fetched by its REST asset id/url even when
  // GitHub omits browser_download_url from the in-memory object.
  const asset = doc.pdfAsset || (
    doc.pdfAssetId || cached?.pdfAssetId
      ? {
          id: doc.pdfAssetId || cached?.pdfAssetId,
          url: doc.pdfUrl || cached?.pdfUrl || undefined,
          browser_download_url: doc.pdfUrl || cached?.pdfUrl || undefined
        }
      : null
  );
  if (!asset || !(asset.id || asset.url || asset.browser_download_url)) {
    throw new Error("Encrypted PDF asset reference is missing. Sync the library and try again.");
  }
  if (!state.client) throw new Error("GitHub connection is not initialized. Unlock the Vault again.");

  const blob = await state.client.downloadAsset(asset);
  if (!(blob instanceof Blob) || !blob.size) {
    throw new Error("GitHub returned an empty encrypted PDF asset.");
  }

  // Keep only the encrypted bytes in IndexedDB. Decryption still happens locally
  // immediately after this function returns.
  const cacheRecord = cached || {
    assetId: doc.assetId,
    vaultId: state.config?.vaultId,
    metaBlob: null,
    pdfAssetId: asset.id || null,
    metaAssetId: doc.metaAsset?.id || doc.metaAssetId || null,
    pdfUrl: asset.browser_download_url || asset.url || null,
    metaUrl: doc.metaAsset?.browser_download_url || null
  };
  await saveCachedPair({
    ...cacheRecord,
    pdfBlob: blob,
    offlineAvailable: true,
    updatedAt: new Date().toISOString()
  });
  doc.pdfBlob = blob;
  doc.offlineAvailable = true;
  return blob;
}'''
if old_reader not in app_source:
    raise SystemExit('Expected fetchEncryptedPdf function was not found.')
app_source = app_source.replace(old_reader, new_reader, 1)

# Cache the encrypted PDF itself on this device before attempting the cloud upload.
# The PDF remains encrypted in IndexedDB; plaintext exists only during local reading.
transformations = [
    (
        'const cached = await cacheSidecar({ ...localRecord, localOnly:true }, pair.sidecarBlob, null);',
        'const cached = await cacheSidecar({ ...localRecord, localOnly:true }, pair.sidecarBlob, pair.encryptedBlob);',
        'local encrypted PDF cache'
    ),
    (
        'if (hash && state.docs.some(d=>d.descriptor.sha256 === hash)) {',
        'if (hash && state.docs.some(d=>d.descriptor.sha256 === hash && !d.localOnly)) {',
        'allow retry of a prior local-only PDF'
    ),
    (
        '  const tags = ($("#upload-tags")?.value || "").split(",").map(s=>s.trim()).filter(Boolean);\n  let done = 0;',
        '  const tags = ($("#upload-tags")?.value || "").split(",").map(s=>s.trim()).filter(Boolean);\n  let done = 0;\n  let uploadSuccessCount = 0;\n  let uploadFallbackCount = 0;',
        'upload result counters'
    ),
    (
        '      const localRecord = { assetId:pair.assetId, descriptor:pair.descriptor, source:"local", localOnly:true, envelope:null };',
        '      const priorLocalOnly = hash ? state.docs.filter(d => d.localOnly && d.descriptor?.sha256 === hash) : [];\n      const localRecord = { assetId:pair.assetId, descriptor:pair.descriptor, source:"local", localOnly:true, envelope:null };',
        'track previous local-only copy for retry'
    ),
    (
        '        if (!state.token) {\n          appendEncryptedDownloads(results, pair, T("noToken"));',
        '        if (!state.token) {\n          uploadFallbackCount++;\n          appendEncryptedDownloads(results, pair, T("noToken"));',
        'count missing-token upload'
    ),
    (
        '            upsertDoc({ ...record, ...parsed, ...cloudCache });\n            results?.insertAdjacentHTML("beforeend", `<div class="success-box">${esc(file.name)} — ${T("success")}</div>`);',
        '            for (const stale of priorLocalOnly) {\n              await deleteCachedPair(stale.assetId).catch(() => {});\n              state.docs = state.docs.filter(d => d.assetId !== stale.assetId);\n            }\n            upsertDoc({ ...record, ...parsed, ...cloudCache });\n            uploadSuccessCount++;\n            results?.insertAdjacentHTML("beforeend", `<div class="success-box">${esc(file.name)} — ${T("success")}</div>`);',
        'count confirmed upload and replace previous local-only copy'
    ),
    (
        '          } catch (error) {\n            const partial = error.partialUpload;',
        '          } catch (error) {\n            uploadFallbackCount++;\n            const partial = error.partialUpload;',
        'count failed cloud upload'
    ),
    (
        '    $("#nav-book-count").textContent = visibleDocs().length;\n    toast(T("completed"), "success");',
        '    $("#nav-book-count").textContent = visibleDocs().length;\n    if (mode === "upload" && uploadFallbackCount > 0) {\n      const message = uploadSuccessCount > 0\n        ? ` ${uploadSuccessCount} PDF GitHub-এ upload হয়েছে; ${uploadFallbackCount}টি হয়নি। ব্যর্থ ফাইলগুলোর encrypted download link নিচে আছে।`\n        : `${uploadFallbackCount}টি PDF GitHub-এ upload হয়নি। নিচের দুইটি encrypted file download করে Release-এ publish করতে হবে।`;\n      toast(message, "error");\n    } else {\n      toast(T("completed"), "success");\n    }',
        'do not show a success toast for failed uploads'
    )
]
for old_text, new_text, description in transformations:
    if old_text not in app_source:
        raise SystemExit('Expected app.js section not found: ' + description)
    app_source = app_source.replace(old_text, new_text, 1)

# Give a clear manual Release target whenever browser upload fails.
fallback_line = '  target.insertAdjacentHTML("beforeend", `<div class="workflow-note">${esc(note)}</div><div class="result-files"><div class="result-file"><span>${esc(pair.assetFileName)}</span><a href="${pdfUrl}" download="${esc(pair.assetFileName)}">↓ Download</a></div><div class="result-file"><span>${esc(pair.sidecarFileName)}</span><a href="${metaUrl}" download="${esc(pair.sidecarFileName)}">↓ Download</a></div></div>`);'
fallback_new = fallback_line + '\n  target.insertAdjacentHTML("beforeend", \'<div class="warning-box">Manual publish: create/open GitHub Release with tag <strong>pdf-vault-001</strong> and upload any missing encrypted files above. Then return to the Vault and press Sync Now.</div>\');'
if fallback_line not in app_source:
    raise SystemExit('Expected encrypted download markup not found.')
app_source = app_source.replace(fallback_line, fallback_new, 1)

# Remove the Reader modal's explicit Download and Print buttons and
# their click handlers. Keep the Close button and native reading frame.
reader_action_pattern = r'<button id="reader-download" class="secondary-btn">.*?</button>\s*<button id="reader-print" class="secondary-btn">.*?</button>'
app_source, reader_action_count = re.subn(
    reader_action_pattern,
    '',
    app_source,
    count=1,
    flags=re.S
)
if reader_action_count != 1:
    raise SystemExit(f'Expected to remove one Reader Download/Print button pair, found {reader_action_count}.')

reader_handlers = '''    $("#reader-download").addEventListener("click", ()=>downloadDecrypted(url, doc.descriptor.originalFilename || title));
    $("#reader-print").addEventListener("click", ()=>{
      const frame = $("#reader-frame");
      try { frame.contentWindow.focus(); frame.contentWindow.print(); } catch { window.open(url, "_blank", "noopener"); }
    });
'''
if reader_handlers not in app_source:
    raise SystemExit('Expected Reader Download/Print click handlers not found.')
app_source = app_source.replace(reader_handlers, '', 1)

# Replace the native browser PDF iframe with a PDF.js canvas reader.
reader_pattern = r'async function openReader\(assetId\) \{.*?\n\}\nfunction closeReader\(\) \{.*?\n\}'
reader_code = r'''async function loadPdfJsLibrary() {
  if (window.pdfjsLib) return window.pdfjsLib;
  if (!window.__pvaultPdfJsLoading) {
    window.__pvaultPdfJsLoading = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = new URL("vendor/pdfjs/pdf.min.js", document.baseURI).href;
      script.async = true;
      script.onload = () => window.pdfjsLib ? resolve(window.pdfjsLib) : reject(new Error("PDF.js did not initialize."));
      script.onerror = () => reject(new Error("Could not load the built-in PDF reading engine. Refresh the page and try again."));
      document.head.append(script);
    });
  }
  const lib = await window.__pvaultPdfJsLoading;
  lib.GlobalWorkerOptions.workerSrc = new URL("vendor/pdfjs/pdf.worker.min.js", document.baseURI).href;
  return lib;
}

async function openReader(assetId) {
  const doc = state.docs.find(d => d.assetId === assetId);
  if (!doc) return;
  toast(String(T("working")) + ": " + String(T("read")));
  try {
    const encryptedBlob = await fetchEncryptedPdf(doc);
    const pdfBlob = await decryptPdfBlob(encryptedBlob, doc.descriptor, state.masterKey, () => {});
    const pdfjsLib = await loadPdfJsLibrary();

    const title = doc.descriptor.title || doc.descriptor.originalFilename || "PDF";
    const modal = document.createElement("div");
    modal.className = "modal-backdrop";
    modal.id = "reader-modal";
    modal.innerHTML =
      '<div class="modal pdfjs-reader-modal" style="width:min(96vw,1160px);max-width:none;height:min(94vh,1000px);max-height:94vh;display:flex;flex-direction:column;overflow:hidden;padding:0">' +
        '<div class="modal-head" style="flex:0 0 auto;padding:12px 16px">' +
          '<div><strong>' + esc(title) + '</strong><div class="sub-note">Read-only PDF reader</div></div>' +
          '<div class="reader-actions"><button id="reader-close" class="modal-close" type="button" aria-label="Close reader">×</button></div>' +
        '</div>' +
        '<div class="pdfjs-toolbar" style="flex:0 0 auto;display:flex;align-items:center;justify-content:center;gap:8px;flex-wrap:wrap;padding:9px 12px;border-bottom:1px solid rgba(128,128,128,.28)">' +
          '<button id="reader-prev" class="secondary-btn" type="button">‹ Previous</button>' +
          '<span id="reader-page-indicator" style="min-width:105px;text-align:center;font-variant-numeric:tabular-nums">Loading…</span>' +
          '<button id="reader-next" class="secondary-btn" type="button">Next ›</button>' +
          '<span aria-hidden="true" style="width:10px"></span>' +
          '<button id="reader-zoom-out" class="secondary-btn" type="button" aria-label="Zoom out">−</button>' +
          '<span id="reader-zoom-label" style="min-width:48px;text-align:center">100%</span>' +
          '<button id="reader-zoom-in" class="secondary-btn" type="button" aria-label="Zoom in">+</button>' +
        '</div>' +
        '<div id="reader-pages" style="flex:1 1 auto;min-height:0;overflow:auto;display:flex;justify-content:center;align-items:flex-start;padding:18px;background:#3b3b3b">' +
          '<div id="reader-loading" style="color:#fff;padding:28px;text-align:center">Rendering PDF…</div>' +
          '<canvas id="reader-canvas" style="display:none;max-width:none;height:auto;background:#fff;box-shadow:0 2px 18px rgba(0,0,0,.38)"></canvas>' +
        '</div>' +
      '</div>';

    $("#modal-root").append(modal);
    $("#reader-close").addEventListener("click", closeReader);
    modal.addEventListener("click", event => {
      if (event.target === modal) closeReader();
    });

    const bytes = new Uint8Array(await pdfBlob.arrayBuffer());
    const loadingTask = pdfjsLib.getDocument({
      data: bytes,
      isEvalSupported: false,
      useSystemFonts: true
    });
    state.activePdfJsTask = loadingTask;
    const pdfDocument = await loadingTask.promise;
    if (!modal.isConnected) {
      try { await loadingTask.destroy(); } catch (_) {}
      return;
    }
    state.activeReaderPdfDoc = pdfDocument;

    const canvas = $("#reader-canvas");
    const container = $("#reader-pages");
    const loadingLabel = $("#reader-loading");
    const pageIndicator = $("#reader-page-indicator");
    const zoomLabel = $("#reader-zoom-label");
    const previousButton = $("#reader-prev");
    const nextButton = $("#reader-next");
    let pageNumber = 1;
    let zoom = 1;
    let renderTask = null;
    let renderSequence = 0;

    async function renderCurrentPage() {
      const sequence = ++renderSequence;
      if (renderTask) {
        try { renderTask.cancel(); } catch (_) {}
        try { await renderTask.promise; } catch (_) {}
        renderTask = null;
      }
      if (!modal.isConnected || sequence !== renderSequence) return;

      const page = await pdfDocument.getPage(pageNumber);
      if (!modal.isConnected || sequence !== renderSequence) return;

      const naturalViewport = page.getViewport({ scale: 1 });
      const availableWidth = Math.max(260, container.clientWidth - 44);
      const availableHeight = Math.max(280, container.clientHeight - 44);
      const fitScale = Math.min(
        availableWidth / naturalViewport.width,
        availableHeight / naturalViewport.height
      );
      const scale = Math.max(0.25, Math.min(4, fitScale * zoom));
      const viewport = page.getViewport({ scale });
      const outputScale = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.floor(viewport.width * outputScale);
      canvas.height = Math.floor(viewport.height * outputScale);
      canvas.style.width = Math.floor(viewport.width) + "px";
      canvas.style.height = Math.floor(viewport.height) + "px";

      const context = canvas.getContext("2d", { alpha: false });
      context.setTransform(outputScale, 0, 0, outputScale, 0, 0);
      renderTask = page.render({ canvasContext: context, viewport });
      state.activeReaderRenderTask = renderTask;
      try {
        await renderTask.promise;
      } catch (error) {
        if (!error || error.name !== "RenderingCancelledException") throw error;
      }
      if (!modal.isConnected || sequence !== renderSequence) return;

      loadingLabel.style.display = "none";
      canvas.style.display = "block";
      pageIndicator.textContent = "Page " + pageNumber + " of " + pdfDocument.numPages;
      zoomLabel.textContent = Math.round(zoom * 100) + "%";
      previousButton.disabled = pageNumber <= 1;
      nextButton.disabled = pageNumber >= pdfDocument.numPages;
    }

    previousButton.addEventListener("click", () => {
      if (pageNumber > 1) {
        pageNumber--;
        renderCurrentPage().catch(error => toast(error.message || "Could not render this PDF page.", "error"));
      }
    });
    nextButton.addEventListener("click", () => {
      if (pageNumber < pdfDocument.numPages) {
        pageNumber++;
        renderCurrentPage().catch(error => toast(error.message || "Could not render this PDF page.", "error"));
      }
    });
    $("#reader-zoom-out").addEventListener("click", () => {
      zoom = Math.max(0.5, Math.round((zoom - 0.2) * 100) / 100);
      renderCurrentPage().catch(error => toast(error.message || "Could not zoom this PDF page.", "error"));
    });
    $("#reader-zoom-in").addEventListener("click", () => {
      zoom = Math.min(3, Math.round((zoom + 0.2) * 100) / 100);
      renderCurrentPage().catch(error => toast(error.message || "Could not zoom this PDF page.", "error"));
    });

    const resizeHandler = () => {
      if (state.readerResizeFrame) cancelAnimationFrame(state.readerResizeFrame);
      state.readerResizeFrame = requestAnimationFrame(() => {
        state.readerResizeFrame = null;
        if (modal.isConnected) {
          renderCurrentPage().catch(error => toast(error.message || "Could not resize this PDF page.", "error"));
        }
      });
    };
    state.activeReaderResizeHandler = resizeHandler;
    window.addEventListener("resize", resizeHandler);

    await renderCurrentPage();
    const recent = [assetId, ...state.prefs.recent.filter(id => id !== assetId)].slice(0, 30);
    state.prefs.recent = recent;
    await persistPrefs();
  } catch (error) {
    closeReader();
    toast(error.message || "PDF could not be opened.", "error");
  }
}

function closeReader() {
  const renderTask = state.activeReaderRenderTask;
  state.activeReaderRenderTask = null;
  if (renderTask) {
    try { renderTask.cancel(); } catch (_) {}
  }
  const resizeHandler = state.activeReaderResizeHandler;
  state.activeReaderResizeHandler = null;
  if (resizeHandler) window.removeEventListener("resize", resizeHandler);
  if (state.readerResizeFrame) {
    cancelAnimationFrame(state.readerResizeFrame);
    state.readerResizeFrame = null;
  }
  const loadingTask = state.activePdfJsTask;
  state.activePdfJsTask = null;
  if (loadingTask && loadingTask.destroy) {
    try { loadingTask.destroy(); } catch (_) {}
  }
  const pdfDocument = state.activeReaderPdfDoc;
  state.activeReaderPdfDoc = null;
  if (pdfDocument && pdfDocument.destroy) {
    try { pdfDocument.destroy(); } catch (_) {}
  }
  $("#reader-modal")?.remove();
  if (state.activeReaderUrl) URL.revokeObjectURL(state.activeReaderUrl);
  state.activeReaderUrl = null;
}
'''
app_source, reader_count = re.subn(reader_pattern, lambda match: reader_code, app_source, count=1, flags=re.S)
if reader_count != 1:
    raise SystemExit(f'Expected one native PDF reader block; found {reader_count}.')

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

# Best-effort reader-only mode: hide in-reader export controls and suppress
# common save/print/share/copy actions while a PDF is open. This is a
# deterrent only; browser-side viewing cannot provide DRM or stop screenshots.
readonly_markup = r"""<style id="pvault-readonly-style">
.pvault-readonly-root {
  -webkit-user-select: none !important;
  user-select: none !important;
}
.pvault-readonly-root a[download],
.pvault-readonly-root #download,
.pvault-readonly-root #print,
.pvault-readonly-root #secondaryDownload,
.pvault-readonly-root #secondaryPrint,
.pvault-readonly-root .download,
.pvault-readonly-root .print,
.pvault-readonly-root .share,
.pvault-readonly-root [data-l10n-id="download"],
.pvault-readonly-root [data-l10n-id="print"],
.pvault-readonly-root [aria-label*="download" i],
.pvault-readonly-root [aria-label*="print" i],
.pvault-readonly-root [title*="download" i],
.pvault-readonly-root [title*="print" i],
.pvault-readonly-root [data-action*="download" i],
.pvault-readonly-root [data-action*="print" i] {
  display: none !important;
}
@media print {
  body.pvault-reader-print-block * { display: none !important; }
}
</style>
<script id="pvault-readonly-guard">
(() => {
  if (window.__pvaultReadonlyGuardInstalled) return;
  window.__pvaultReadonlyGuardInstalled = true;
  const roots = [];
  const originalPrint = window.print ? window.print.bind(window) : null;
  const actionPattern = /(download|print|share|save|export)/i;

  function visible(el) {
    if (!el || !el.isConnected) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }

  function getRoot(node) {
    if (!node || !node.closest) return null;
    return node.closest(".pvault-readonly-root");
  }

  function markRoot(node) {
    if (!node || !node.isConnected) return;
    // Prefer the complete dialog/modal, not the inner iframe wrapper:
    // PDF action buttons are often siblings of the actual PDF frame.
    let root = node.closest(
      'dialog,[role="dialog"],[class*="modal"],[id*="modal"],' +
      '[class*="preview"],[id*="preview"],[class*="reader"],[id*="reader"]'
    );
    if (!root) {
      root = node;
      for (let level = 0; level < 5 && root.parentElement; level++) {
        root = root.parentElement;
      }
    }
    if (!(root instanceof Element)) return;
    if (!root.classList.contains("pvault-readonly-root")) {
      root.classList.add("pvault-readonly-root");
      roots.push(root);
    }

    if (node instanceof HTMLIFrameElement) {
      const src = node.getAttribute("src") || "";
      if (/^(blob:|data:application\/pdf)/i.test(src) && !/toolbar=0/i.test(src)) {
        node.setAttribute("src", src + (src.includes("#") ? "&" : "#") + "toolbar=0&navpanes=0&statusbar=0");
      }
    }

    root.querySelectorAll('a,button,[role="button"],input[type="button"],input[type="submit"]').forEach(el => {
      const label = [
        el.innerText || "",
        el.textContent || "",
        el.getAttribute("aria-label") || "",
        el.getAttribute("title") || "",
        el.getAttribute("data-action") || "",
        el.id || "",
        typeof el.className === "string" ? el.className : "",
        el.hasAttribute("download") ? "download" : ""
      ].join(" ");
      if (actionPattern.test(label)) {
        el.setAttribute("aria-hidden", "true");
        el.setAttribute("tabindex", "-1");
        el.style.setProperty("display", "none", "important");
      }
    });
  }

  function scan() {
    document.querySelectorAll(
      'iframe,object,embed,.pdfViewer,#viewerContainer,' +
      '[class*="pdf-viewer"],[id*="pdf-viewer"],[class*="pdf-reader"],[id*="pdf-reader"]'
    ).forEach(node => {
      const src = [
        node.getAttribute("src") || "",
        node.getAttribute("data") || "",
        node.getAttribute("type") || "",
        node.id || "",
        typeof node.className === "string" ? node.className : ""
      ].join(" ").toLowerCase();
      const pdfNode =
        /application\/pdf|\.pdf(?:[?#]|$)|^blob:/.test(src) ||
        /pdfviewer|pdf-viewer|pdf-reader/.test(src);
      if (pdfNode && visible(node)) markRoot(node);
    });

    document.querySelectorAll(".pvault-readonly-root").forEach(root => {
      if (root.isConnected) {
        root.querySelectorAll('a,button,[role="button"],input[type="button"],input[type="submit"]').forEach(el => {
          const label = [
            el.innerText || "", el.textContent || "",
            el.getAttribute("aria-label") || "", el.getAttribute("title") || "",
            el.getAttribute("data-action") || "", el.id || "",
            typeof el.className === "string" ? el.className : "",
            el.hasAttribute("download") ? "download" : ""
          ].join(" ");
          if (actionPattern.test(label)) el.style.setProperty("display", "none", "important");
        });
      }
    });

    while (roots.length && !roots[0].isConnected) roots.shift();
    document.body.classList.toggle("pvault-reader-print-block", roots.some(r => r.isConnected));
    if (window.print && roots.some(r => r.isConnected)) {
      window.print = function () {
        window.dispatchEvent(new CustomEvent("pvault:print-blocked"));
      };
    } else if (originalPrint) {
      window.print = originalPrint;
    }
  }

  function blockedTarget(target) {
    const root = getRoot(target instanceof Element ? target : target && target.parentElement);
    return root;
  }

  document.addEventListener("contextmenu", event => {
    if (blockedTarget(event.target)) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);

  document.addEventListener("dragstart", event => {
    if (blockedTarget(event.target)) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);

  ["copy", "cut"].forEach(type => {
    document.addEventListener(type, event => {
      if (blockedTarget(event.target)) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    }, true);
  });

  document.addEventListener("keydown", event => {
    const root = blockedTarget(event.target);
    if (!root) return;
    const key = String(event.key || "").toLowerCase();
    const mod = event.ctrlKey || event.metaKey;
    if (mod && ["s", "p", "c", "x"].includes(key)) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);

  document.addEventListener("click", event => {
    const root = blockedTarget(event.target);
    if (!root) return;
    const el = event.target instanceof Element
      ? event.target.closest('a,button,[role="button"]')
      : null;
    if (!el) return;
    const label = [
      el.innerText || "", el.textContent || "",
      el.getAttribute("aria-label") || "", el.getAttribute("title") || "",
      el.getAttribute("data-action") || "", el.id || "",
      el.hasAttribute("download") ? "download" : ""
    ].join(" ");
    if (actionPattern.test(label)) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);

  const observer = new MutationObserver(scan);
  observer.observe(document.documentElement, {
    childList: true, subtree: true, attributes: true,
    attributeFilter: ["src", "data", "class", "id", "download", "aria-label", "title"]
  });
  scan();
})();
</script>
"""
index_path = Path('public/index.html')
index_source = index_path.read_text(encoding='utf-8')
if 'id="pvault-readonly-guard"' not in index_source:
    if '</body>' not in index_source:
        raise SystemExit('Could not find </body> in index.html for reader protection.')
    index_source = index_source.replace('</body>', readonly_markup + '\n</body>', 1)
    index_path.write_text(index_source, encoding='utf-8')

# Invalidate the previously cached shell.
worker = Path('public/service-worker.js')
worker_source = worker.read_text(encoding='utf-8')
old_caches = ('personal-pdf-vault-shell-v1', 'personal-pdf-vault-shell-v2-owner-lock')
new_cache = 'personal-pdf-vault-shell-v11-pdfjs-canvas-reader'
matched = next((name for name in old_caches if name in worker_source), None)
if not matched:
    raise SystemExit('Expected original service worker cache name not found.')
worker.write_text(worker_source.replace(matched, new_cache), encoding='utf-8')

print('Applied owner-session preservation and manual encrypted configuration import.')
