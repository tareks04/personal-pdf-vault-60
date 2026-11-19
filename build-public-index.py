#!/usr/bin/env python3
"""Generate the public, static PDF Vault index using the Actions token."""
import base64
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OWNER = "tareks04"
REPO = "personal-pdf-vault-60"
API = f"https://api.github.com/repos/{OWNER}/{REPO}"
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
if not TOKEN:
    raise SystemExit("GH_TOKEN is required.")

def api_json(url):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + TOKEN,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "personal-pdf-vault-index-builder",
    })
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))

def public_asset(asset):
    url = asset.get("browser_download_url")
    if not url:
        raise RuntimeError("Missing browser_download_url for " + str(asset.get("name")))
    req = urllib.request.Request(url, headers={"User-Agent": "personal-pdf-vault-index-builder"})
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read()

def main():
    releases = []
    for page in range(1, 21):
        batch = api_json(f"{API}/releases?per_page=100&page={page}")
        if not isinstance(batch, list):
            raise RuntimeError("Invalid GitHub Releases response.")
        releases.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise RuntimeError("Release pagination exceeded safety limit.")

    control = next((r for r in releases if r.get("tag_name") == "vault-control" and not r.get("draft")), None)
    if not control:
        raise RuntimeError("vault-control Release is missing; refusing to create an empty index.")

    cfgs = []
    for asset in control.get("assets", []):
        m = re.fullmatch(r"vault-config-v(\d+)\.json", asset.get("name", ""), re.I)
        if m:
            cfgs.append((int(m.group(1)), asset))
    if not cfgs:
        raise RuntimeError("No vault-config JSON asset found in vault-control.")
    version, config_asset = max(cfgs, key=lambda item: item[0])
    config = json.loads(public_asset(config_asset).decode("utf-8"))
    if int(config.get("configVersion", -1)) != version:
        raise RuntimeError("Vault config version mismatch.")

    data_releases = [r for r in releases if not r.get("draft") and str(r.get("tag_name", "")).startswith("pdf-vault-")]
    data_releases.sort(key=lambda r: r.get("tag_name", ""), reverse=True)
    entries, problems, usage = [], [], 0

    for release in data_releases:
        assets = release.get("assets", [])
        usage += sum(int(a.get("size", 0)) for a in assets if re.search(r"\.(pvault|pvmeta)$", a.get("name", ""), re.I))
        pdfs = [a for a in assets if re.fullmatch(r"asset_[a-f0-9]{32}\.pvault", a.get("name", ""), re.I)]
        metas = [a for a in assets if re.fullmatch(r"meta_[a-f0-9]{32}_v\d+\.pvmeta", a.get("name", ""), re.I)]
        pdf_ids = set()

        for pdf in pdfs:
            pm = re.fullmatch(r"asset_([a-f0-9]{32})\.pvault", pdf["name"], re.I)
            asset_id = pm.group(1)
            pdf_ids.add(asset_id.lower())
            candidates = [a for a in metas if re.match(r"meta_" + re.escape(asset_id) + r"_v", a.get("name", ""), re.I)]
            candidates.sort(key=lambda a: (
                int(re.search(r"_v(\d+)\.pvmeta$", a.get("name", ""), re.I).group(1)),
                a.get("created_at", "")
            ), reverse=True)
            if not candidates:
                problems.append({"type":"missing-sidecar","assetId":asset_id,"filename":pdf.get("name"),"release":release.get("tag_name"),"asset":pdf})
                continue
            sidecar_contents = []
            for sidecar in candidates:
                sidecar_contents.append({
                    "id": sidecar.get("id"),
                    "base64": base64.b64encode(public_asset(sidecar)).decode("ascii")
                })
            entries.append({
                "assetId": asset_id,
                "pdfAsset": pdf,
                "metaAsset": candidates[0],
                "release": release,
                "otherSidecars": candidates[1:],
                "sidecarContents": sidecar_contents
            })

        for meta in metas:
            mm = re.fullmatch(r"meta_([a-f0-9]{32})_v\d+\.pvmeta", meta.get("name", ""), re.I)
            if mm and mm.group(1).lower() not in pdf_ids:
                problems.append({"type":"missing-pdf","assetId":mm.group(1).lower(),"filename":meta.get("name"),"release":release.get("tag_name"),"asset":meta})
        if len(assets) >= 900:
            problems.append({"type":"release-near-limit","release":release.get("tag_name"),"count":len(assets)})

    index = {
        "schemaVersion": 1,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "config": config,
        "controlRelease": control,
        "configAsset": config_asset,
        "entries": entries,
        "problems": problems,
        "releases": data_releases,
        "usageBytes": usage
    }
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "public/vault-index.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(index, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print(f"Built Vault index: {len(entries)} PDF(s), {len(data_releases)} data Release(s), {usage} encrypted bytes, config v{version}.")

if __name__ == "__main__":
    main()
