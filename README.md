# Personal PDF Vault (60-PDF batch)

A browser-based encrypted PDF vault prepared for the first batch of up to 60 PDFs (maximum 100 MiB each).

## Open the app

After GitHub Pages deployment completes, visit:

https://tareks04.github.io/personal-pdf-vault-60/

## Deploy

The GitHub Actions workflow in `.github/workflows/deploy-pages.yml` unpacks `site-bundle.tgz.b64` and publishes the static app to GitHub Pages whenever `main` is updated.

To check deployment: open the repository's **Actions** tab and inspect **Deploy Personal PDF Vault to GitHub Pages**.

## Storage and privacy notes

- PDF encryption and decryption happen in the browser.
- Encrypted PDF assets and encrypted metadata are stored in the configured GitHub Releases repository.
- The first import batch is limited to 60 PDFs; each PDF is limited to 100 MiB.
- The app targets 60 GiB total vault storage. This is an application target, not a guaranteed GitHub quota. GitHub Releases limits, account policies, and available storage still apply.
- By default, PDF contents are not cached in browser storage for offline use.
- Keep your vault password and GitHub token secure. Losing the password may make the encrypted PDFs unrecoverable.

## Source bundle

The deployable site files are included in `site-bundle.tgz.b64`; the workflow decodes and extracts that bundle into the Pages artifact.
