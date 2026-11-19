from pathlib import Path

path = Path("public/modules/github.js")
source = path.read_text(encoding="utf-8")

old = r'''  async uploadPair(pair) {
    const { release, assets } = await this.getDataRelease();
    if (assets.length > 997) throw new Error("This Release is too close to GitHub's 1,000-asset limit. A new Release is required.");
    const uploadedPdf = await this.uploadAsset(release, pair.assetFileName, pair.encryptedBlob);
    try {
      const uploadedMeta = await this.uploadAsset(release, pair.sidecarFileName, pair.sidecarBlob);
      return { release, pdfAsset: uploadedPdf, metaAsset: uploadedMeta };
    } catch (error) {
      error.partialUpload = { release, pdfAsset: uploadedPdf, pair };
      throw error;
    }
  }'''

new = r'''  async uploadPair(pair) {
    if (!this.token) throw new Error("Owner Token নেই। আগে Owner access verify করুন।");
    const pdfMatch = /^asset_([a-f0-9]{32})\.pvault$/i.exec(pair.assetFileName || "");
    const metaMatch = /^meta_([a-f0-9]{32})_v\d+\.pvmeta$/i.exec(pair.sidecarFileName || "");
    if (!pdfMatch || !metaMatch || pdfMatch[1].toLowerCase() !== metaMatch[1].toLowerCase()) throw new Error("Encrypted PDF/metadata filename pair is invalid.");
    const assetId = pdfMatch[1].toLowerCase();
    if (!(pair.encryptedBlob instanceof Blob) || !pair.encryptedBlob.size) throw new Error("Encrypted PDF file is empty.");
    if (!(pair.sidecarBlob instanceof Blob) || !pair.sidecarBlob.size) throw new Error("Encrypted metadata file is empty.");
    if (pair.encryptedBlob.size > 40*1024*1024 || pair.sidecarBlob.size > 8*1024*1024) throw new Error("Automatic browser upload supports encrypted PDF up to 40 MiB and metadata up to 8 MiB. Use encrypted download links for larger files.");

    const { release, assets } = await this.getDataRelease();
    if (assets.length > 997) throw new Error("This Release is too close to GitHub's 1,000-asset limit.");
    const repoPath = "/repos/" + encodeURIComponent(this.owner) + "/" + encodeURIComponent(this.repo);
    const branch = "pvault-upload-" + assetId;
    const dir = "upload-staging/" + assetId;
    let created = false;
    let ready = false;

    const encodeBlob = async blob => {
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let binary = "";
      for (let i=0; i<bytes.length; i+=0x8000) binary += String.fromCharCode(...bytes.subarray(i,i+0x8000));
      return btoa(binary);
    };
    const put = (name, content) => this.request(repoPath + "/contents/" + dir + "/" + name, {
      method:"PUT",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({message:"Stage encrypted PDF Vault upload",content,branch})
    });

    try {
      const mainRef = await this.request(repoPath + "/git/ref/heads/main");
      if (!mainRef?.object?.sha) throw new Error("Could not read the main branch commit.");
      await this.request(repoPath + "/git/refs", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({ref:"refs/heads/" + branch,sha:mainRef.object.sha})
      });
      created = true;

      await put(pair.assetFileName, await encodeBlob(pair.encryptedBlob));
      await put(pair.sidecarFileName, await encodeBlob(pair.sidecarBlob));

      const manifest = {assetId,releaseTag:release.tag_name,pdf:pair.assetFileName,meta:pair.sidecarFileName};
      const manifestBytes = new TextEncoder().encode(JSON.stringify(manifest));
      let manifestBinary = "";
      for (let i=0;i<manifestBytes.length;i+=0x8000) manifestBinary += String.fromCharCode(...manifestBytes.subarray(i,i+0x8000));
      await put("ready.json", btoa(manifestBinary));
      ready = true;

      for (let attempt=0; attempt<150; attempt++) {
        const currentAssets = await this.listAssets(release.id);
        const pdfAsset = currentAssets.find(a=>a.name===pair.assetFileName && a.state==="uploaded");
        const metaAsset = currentAssets.find(a=>a.name===pair.sidecarFileName && a.state==="uploaded");
        if (pdfAsset && metaAsset) return {release,pdfAsset,metaAsset,staged:true};
        await new Promise(resolve=>setTimeout(resolve,2000));
      }
      throw new Error("Encrypted files were staged, but GitHub Actions did not confirm the Release upload within 300 seconds. Check Actions: Publish encrypted Vault staging upload. Branch: " + branch);
    } catch (error) {
      if (created && !ready) {
        try { await this.request(repoPath + "/git/refs/heads/" + branch,{method:"DELETE"}); } catch (_) {}
      }
      throw error;
    }
  }'''

if old not in source:
    raise SystemExit("Original uploadPair method not found in generated github.js.")
source = source.replace(old, new, 1)
path.write_text(source, encoding="utf-8")
print("Installed encrypted staging upload method.")
