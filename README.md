# Personal PDF Vault (60-PDF batch)

A browser-based encrypted PDF vault prepared for the first batch of up to 60 PDFs (maximum 100 MiB each).

## First-time GitHub Pages setup

The repository owner must enable Pages once:

1. Open **Settings** in this repository.
2. Select **Pages** under **Code and automation**.
3. Under **Build and deployment**, set **Source** to **GitHub Actions**.

Then open the **Actions** tab and check **Deploy Personal PDF Vault to GitHub Pages**. Future pushes to `main` trigger deployment automatically.

## Open the app

After the workflow succeeds, visit:

https://tareks04.github.io/personal-pdf-vault-60/

## Storage and privacy notes

- PDF encryption and decryption happen in the browser.
- Encrypted PDF assets and encrypted metadata are stored in the configured GitHub Releases repository.
- The first import batch is limited to 60 PDFs; each PDF is limited to 100 MiB.
- The app targets 60 GiB total vault storage. This is an application target, not a guaranteed GitHub quota. GitHub Releases limits, account policies, and available storage still apply.
- By default, PDF contents are not cached in browser storage for offline use.
- Keep your vault password and GitHub token secure. Losing the password may make the encrypted PDFs unrecoverable.

## Deployment source

The deployable site is stored in twelve ordered Base64 parts under `bundle/`. The workflow joins, decodes, and extracts them into the Pages artifact.
