from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

REPO = os.environ["GITHUB_REPOSITORY"]
BRANCH = os.environ["GITHUB_REF_NAME"]
ROOT = Path("upload-staging")
BRANCH_RE = re.compile(r"^pvault-upload-([a-f0-9]{32})$")
PDF_RE = re.compile(r"^asset_([a-f0-9]{32})\.pvault$")
META_RE = re.compile(r"^meta_([a-f0-9]{32})_v\d+\.pvmeta$")
TAG_RE = re.compile(r"^pdf-vault-\d{3,}$")


def gh(*args: str) -> str:
    result = subprocess.run(
        ["gh", *args, "--repo", REPO],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout or "GitHub CLI command failed").strip()
        raise RuntimeError(detail[:1200])
    return result.stdout.strip()


def main() -> None:
    match = BRANCH_RE.fullmatch(BRANCH)
    if not match:
        raise RuntimeError(f"Unexpected staging branch: {BRANCH}")
    asset_id = match.group(1)
    folder = ROOT / asset_id
    ready_path = folder / "ready.json"
    if not ready_path.is_file():
        raise RuntimeError("ready.json is missing from the encrypted staging branch.")

    manifest = json.loads(ready_path.read_text(encoding="utf-8"))
    if manifest.get("assetId") != asset_id:
        raise RuntimeError("Staging manifest assetId does not match the branch.")
    tag = str(manifest.get("releaseTag") or "")
    if not TAG_RE.fullmatch(tag):
        raise RuntimeError("Staging manifest contains an invalid Release tag.")

    pdf_name = str(manifest.get("pdf") or "")
    meta_name = str(manifest.get("meta") or "")
    pdf_match = PDF_RE.fullmatch(pdf_name)
    meta_match = META_RE.fullmatch(meta_name)
    if not pdf_match or not meta_match or pdf_match.group(1) != asset_id or meta_match.group(1) != asset_id:
        raise RuntimeError("Staging manifest contains an invalid encrypted file pair.")

    pdf_path = folder / pdf_name
    meta_path = folder / meta_name
    for path in (pdf_path, meta_path):
        if not path.is_file() or path.stat().st_size <= 0:
            raise RuntimeError(f"Missing or empty encrypted staged file: {path.name}")
    if pdf_path.stat().st_size > 40 * 1024 * 1024 or meta_path.stat().st_size > 8 * 1024 * 1024:
        raise RuntimeError("Staged encrypted files exceed the configured size limit.")

    # Upload binary assets from the runner, not from the browser.
    gh("release", "upload", tag, str(pdf_path), str(meta_path), "--clobber")

    release = json.loads(gh("api", f"repos/{REPO}/releases/tags/{tag}"))
    uploaded = {asset.get("name") for asset in release.get("assets", []) if asset.get("state") == "uploaded"}
    if pdf_name not in uploaded or meta_name not in uploaded:
        raise RuntimeError("Release upload verification failed; one or both encrypted assets are missing.")

    # Rebuild the static public index so readers can see the new PDF.
    gh("workflow", "run", "deploy-pages.yml", "--ref", "main")

    # Remove the short-lived staging branch after Release verification.
    gh("api", "--method", "DELETE", f"repos/{REPO}/git/refs/heads/{BRANCH}")
    print(f"Published {pdf_name} and {meta_name} to {tag}; Pages index refresh dispatched; deleted {BRANCH}.")


if __name__ == "__main__":
    main()
