# scenegraph-review

A Flask UI for reviewing and editing per-image scenegraphs produced by a VLM
(vision-language model). Built for triage / casualty-assessment imagery, but
the schema is generic enough to repurpose.

Each image is paired with a JSON scenegraph describing the scene, the primary
subject (highlighted by a bounding box), 12 binary observation verdicts, and
optional secondary entities + relations. The UI loads pairs side-by-side,
lets you edit every field, and saves changes back to disk with automatic
timestamped backups.

---

## Contents

1. [What you get](#what-you-get)
2. [First 5 minutes (no data needed)](#first-5-minutes-no-data-needed)
3. [Bringing your own data](#bringing-your-own-data)
4. [Using the UI](#using-the-ui)
5. [Production deployment](#production-deployment)
6. [Updating after first deploy](#updating-after-first-deploy)
7. [Security](#security)
8. [Troubleshooting / FAQ](#troubleshooting--faq)
9. [Reproducibility](#reproducibility)
10. [API reference](#api-reference)
11. [Repository layout](#repository-layout)
12. [License](#license)

---

## What you get

| Component                | Purpose                                                      |
|--------------------------|--------------------------------------------------------------|
| Browser UI on `:5590`    | Gallery, image viewer, editable form, save/download         |
| Single-file Flask server | Reads/writes JSONs on disk, serves images, auth cookie       |
| 12-key verdict schema    | Pre-wired for triage but adaptable (see [Adapting to a different domain](#adapting-to-a-different-domain)) |
| Example templates + validator | `examples/` — copy these, validate before serving      |

Tested on Python 3.12.3 and on any Docker host (multi-arch image: linux/amd64
+ linux/arm64).

---

## First 5 minutes (no data needed)

You can prove the install works end-to-end with the bundled minimal
template — no images, no scenegraph generation pipeline required:

```bash
git clone <repo-url> scenegraph-review && cd scenegraph-review

# Build the container
docker build -t scenegraph-review .

# Use the bundled minimal template as a single fake scenegraph
mkdir -p data/scenegraphs
cp examples/example_scenegraph.minimal.json data/scenegraphs/example_002.jpg.json

# Run
docker run -d --name sgreview -p 5590:5590 \
    -e ACCESS_CODE=demo123 \
    -v $(pwd)/data:/app/data \
    scenegraph-review

# Verify
curl -s http://localhost:5590/api/health
# → {"expert_gold_enabled":false,"images_on_disk":0,"ok":true,"scenegraphs":1}
```

Open `http://localhost:5590`, enter `demo123`, and you should see:
- A single thumbnail in the gallery, flagged **no SG** (no matching image
  on disk yet — that's the next step).
- The form panel populated from the minimal template.
- The status bar showing `idx: 1 / 1` and the filename.

If you see all of that, the install is working. Stop the container with
`docker rm -f sgreview` and proceed to onboard real data.

---

## Bringing your own data

The application reads from one folder: `data/`. Everything inside is supplied
by you. The server auto-creates the four subfolders on first launch if they
do not exist.

```
data/
├── images/        your input images        ── you populate
├── scenegraphs/   your scenegraph JSONs    ── you populate
├── thumbs/        240×160 cache, auto      ── leave empty; server writes
└── backups/       per-save snapshots, auto ── leave empty; server writes
```

### File-naming contract

| For an image                | The scenegraph JSON must be named                        |
|-----------------------------|----------------------------------------------------------|
| `data/images/foo.jpg`       | `data/scenegraphs/foo.jpg.json` *(include the `.jpg`)*   |
| `data/images/abc123.jpg`    | `data/scenegraphs/abc123.jpg.json`                       |

**Images must be JPEG with the `.jpg` extension.** Other formats are silently
ignored by the gallery. Convert with `ffmpeg -i input.png output.jpg` or
similar if needed.

If a `.jpg` exists without a matching `.jpg.json`, the gallery thumbnail
shows a red **no SG** badge — useful for tracking which images still need a
scenegraph from your generation pipeline. The reverse (a `.jpg.json` with no
matching `.jpg`) shows in the gallery but the image panel renders empty.

### Scenegraph JSON: use the templates

Two working examples ship in `examples/`:

| File                                       | What it is                                                      |
|--------------------------------------------|-----------------------------------------------------------------|
| `examples/example_scenegraph.full.json`    | Fully filled-out realistic example. Copy and modify per image.  |
| `examples/example_scenegraph.minimal.json` | Bare-minimum valid scenegraph — every required field present with safe defaults (`"unknown"`, empty strings/arrays). Useful as a starting skeleton or for programmatic generation. |

### Onboard one image manually

```bash
# 1. Copy the image
cp /path/to/your/source/foo.jpg data/images/foo.jpg

# 2. Copy the template and rename
cp examples/example_scenegraph.full.json data/scenegraphs/foo.jpg.json

# 3. Edit data/scenegraphs/foo.jpg.json:
#    - set "image_id": "foo.jpg"
#    - set "primary_subject.gt_bbox": [x1, y1, x2, y2] (your annotation)
#    - set "primary_subject.img_w" and "img_h" to your image dimensions
#    - fill in the rest, or leave fields blank and edit in the UI later

# 4. Validate before serving (catches schema mistakes early)
python examples/validate_scenegraph.py data/scenegraphs/foo.jpg.json
```

### Onboard many images programmatically

Generate one `data/scenegraphs/<image_id>.json` per image with your VLM
pipeline (or any script) following the schema. Then validate the whole
folder before serving:

```bash
python examples/validate_scenegraph.py data/scenegraphs/
```

A regression smoke test for the running server lives at
`examples/smoke_test.sh` — it exercises every API endpoint (health, auth,
list, sg fetch/PUT roundtrip, gold, image+thumb Cache-Control, download,
NDJSON bundle, auth rejection) and exits non-zero on the first failure:

```bash
bash examples/smoke_test.sh http://localhost:5590
ACCESS_CODE=mySecret bash examples/smoke_test.sh http://prod-host:5590
```

The validator (`examples/validate_scenegraph.py`) is a standalone script
with no dependencies beyond the Python standard library. It reports every
missing or type-wrong field per file and exits non-zero if any file fails,
so it slots into CI directly:

```yaml
- run: python scenegraph-review/examples/validate_scenegraph.py scenegraph-review/data/scenegraphs/
```

### Required fields summary

| Top-level         | Type                                                                                  |
|-------------------|---------------------------------------------------------------------------------------|
| `image_id`        | string (matches the JPG filename)                                                     |
| `modality`        | `"RGB"` or `"IR"`                                                                     |
| `scene`           | object (see below)                                                                    |
| `primary_subject` | object (see below)                                                                    |
| `secondary_entities` | array of objects (may be empty)                                                    |
| `relations`       | array of objects (may be empty)                                                       |

| `scene.*`                       | Type                                          |
|---------------------------------|-----------------------------------------------|
| `setting`, `lighting`, `terrain` | strings                                      |
| `hazards`, `medical_devices_visible`, `threats_visible`, `obstacles` | array of strings |
| `nearby_persons`, `nearby_vehicles` | `{"count": int, "details": str}`          |

| `primary_subject.*`              | Type                                                                |
|----------------------------------|---------------------------------------------------------------------|
| `gt_bbox`, `predicted_bbox`      | `[x1, y1, x2, y2]` — four ints, pixel coords                        |
| `predicted_bbox_confidence`      | `"low"` / `"medium"` / `"high"`                                     |
| `img_w`, `img_h`                 | int, in pixels                                                      |
| `posture_prose`, `emt_assessment_prose` | strings                                                      |
| `ambulatory`                     | `"yes"` / `"no"` / `"unknown"`                                      |
| 12 short-key verdict objects     | each `{"verdict": …, "confidence": …, "evidence": …}` (enums below) |

The 12 verdict short-keys (the subject-level binary observations the UI is
built around): `blood_pool`, `standing`, `prone_back`, `prone_face`,
`side_lying`, `sit_supp`, `sit_unsupp`, `tripod_pos`, `amp_leg`, `amp_arm`,
`protect_hand`, `is_medic`. Each verdict is `"yes" | "no" | "unknown"`,
confidence is `"low" | "medium" | "high"`.

### Bbox conventions

- All bboxes are `[x1, y1, x2, y2]` in **pixel coordinates** of the original
  image. `x1 < x2`, `y1 < y2`.
- `gt_bbox` is the *ground-truth* box for the primary subject. The UI draws
  this in **green solid**.
- `predicted_bbox` is the model's independent estimate of where the same
  subject is. The UI draws this in **magenta dashed**, and computes IoU
  against `gt_bbox`. Show or hide via the toolbar checkbox.
- If you have only one bbox source, set both to the same value.
- If you do not have ground truth at all, set `gt_bbox = [0, 0, 0, 0]` (the
  UI will report IoU = 0 against your predicted box — that is the honest
  signal).

### Adapting to a different domain

The 12 verdict short-keys are domain-specific (triage). To adapt to a
different domain, update the same list in three places:

- `SHORT_KEY_TO_QFOLDER` in `server.py` (top of file)
- `SHORT_KEYS` in `templates/index.html` (near the top of the `<script>` block)
- `SHORT_KEYS` in `examples/validate_scenegraph.py`

Each place is a short list literal; keep them in sync.

---

## Using the UI

What a typical session looks like:

1. **Open** `http://<host>:5590`. Enter the access code. Cookie lasts 24 h.
2. **Gallery**: scrollable strip at the top. Each thumbnail has a number
   (its 1-based index). The currently selected thumbnail has a **gold
   border**. The first image with a scenegraph is selected on load.
3. **Navigate**: click any thumbnail, or use ← / → arrow keys. The gallery
   auto-scrolls the selected thumb into view.
4. **Edit**: form panel on the right is the full scenegraph rendered as
   editable controls.
   - Free-text → text inputs / textareas
   - Enumerated → dropdowns (modality, ambulatory, verdict, confidence, entity type)
   - Numeric → number inputs (bbox coords, counts)
   - `secondary_entities` and `relations` arrays → use **+ Add** / **× remove**
     buttons to manage rows
5. **Save**: click **Save** (or Ctrl-S / Cmd-S). A timestamped backup of the
   previous version is written to `data/backups/`. A "saved ✓" indicator
   flashes for 1.5 s in the toolbar. The browser warns before navigating
   away with unsaved edits.
6. **Image overlay**: the **show predicted bbox** checkbox in the toolbar
   toggles the magenta-dashed predicted bbox on top of the image. The
   solid-green ground-truth box is always burned into the JPG (your data
   pipeline draws it; the UI does not redraw it).
7. **Download current**: dumps the visible scenegraph as a single `.json`
   to your browser's Downloads folder. Includes any unsaved edits.
8. **Download all (NDJSON)**: server reads every `data/scenegraphs/*.json`
   from disk and streams a newline-delimited bundle. Reflects on-disk saved
   state only — unsaved edits in your current session are **not** included.
9. **Status bar** (bottom): filename, modality, gt-vs-predicted IoU, and
   1-based image index out of total.

### Keyboard shortcuts

| Key       | Action                          |
|-----------|---------------------------------|
| ←         | Previous image                  |
| →         | Next image                      |
| Ctrl/Cmd-S | Save                           |

---

## Production deployment

### systemd (bare-metal venv)

```bash
# After cloning + setting up venv + populating data/:
sudo tee /etc/systemd/system/scenegraph-review.service > /dev/null <<EOF
[Unit]
Description=Scenegraph Review UI Server
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/scenegraph-review
Environment="ACCESS_CODE=changeMe"
ExecStart=/home/ubuntu/scenegraph-review/venv/bin/python server.py --port 5590
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=scenegraph-review

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now scenegraph-review.service
sudo systemctl status scenegraph-review.service
journalctl -u scenegraph-review -f       # follow logs
```

### Docker with restart policy

```bash
docker run -d --name scenegraph-review \
    -p 5590:5590 \
    -e ACCESS_CODE=changeMe \
    -v $(pwd)/data:/app/data \
    --restart unless-stopped \
    scenegraph-review:latest
```

### Cloud firewall

If your host is behind a cloud security group (AWS / GCP / Azure / OpenStack
/ etc.), remember to open **inbound TCP on the port you picked** (default
`5590`). The application binds to `0.0.0.0` and the container exposes
`5590`; both are useless until the cloud firewall lets the traffic through.

---

## Updating after first deploy

### Docker

```bash
cd scenegraph-review
git pull
docker build -t scenegraph-review .
docker rm -f scenegraph-review                # stops old container
docker run -d --name scenegraph-review \
    -p 5590:5590 \
    -e ACCESS_CODE=changeMe \
    -v $(pwd)/data:/app/data \
    --restart unless-stopped \
    scenegraph-review
```

The `-v $(pwd)/data:/app/data` mount means scenegraphs and backups survive
the container rebuild.

### systemd venv

```bash
cd ~/scenegraph-review
git pull
venv/bin/pip install --require-hashes -r requirements.txt   # only if deps changed
sudo systemctl restart scenegraph-review.service
sudo systemctl status scenegraph-review.service
```

`data/` is outside the venv and outside the git tree (gitignored), so it's
untouched by either step.

---

## Security

The access code is a **soft gate**, not real authentication:

- It's a single shared secret, stored unhashed in the systemd unit file or
  the `-e` flag. Anyone with shell access on the host can read it.
- It's transmitted over HTTP, not HTTPS, unless you put a reverse proxy in
  front.
- Session cookies are valid for 24 h with no revocation mechanism.

**Do not expose this directly to the public internet** as-is. For
anything sensitive:

- Put it behind a reverse proxy (nginx, Caddy, Traefik) that terminates
  TLS and adds real authentication (OAuth / SSO / mTLS).
- Restrict access at the network layer (cloud security group, VPN, WireGuard).
- Treat the access code as "keeps casual visitors out of an internal tool,"
  not "protects against a determined attacker."

The data on disk (`data/scenegraphs/`, `data/backups/`) is plain JSON. If
your scenegraphs contain sensitive information, secure the host filesystem
accordingly.

---

## Troubleshooting / FAQ

**Gallery is empty.**
- Run `curl -s http://localhost:5590/api/health` and look at `images_on_disk`
  and `scenegraphs`. If both are 0, you have no data in `data/images/` and
  `data/scenegraphs/`. If only `images_on_disk` is 0 but you copied JPGs
  in, check the extension is lowercase `.jpg`.

**I see thumbnails but they all say "no SG".**
- Each `foo.jpg` needs a matching `foo.jpg.json` in `data/scenegraphs/`.
  Note the JSON keeps the `.jpg` suffix in its name.

**Image shows but the form panel is blank.**
- The scenegraph JSON is missing or malformed. Run
  `python examples/validate_scenegraph.py data/scenegraphs/<that_id>.jpg.json`
  for the specific file.

**HTTP 401 immediately after login.**
- The access code you typed doesn't match the `ACCESS_CODE` env var on
  the server. Default is `changeMe`. Restart the container or service after
  changing the env var.

**Port 5590 already in use.**
- Pick another port: pass `--port 5591` to `server.py`, or
  `-p 5591:5590` to `docker run` (host-side 5591, container-side stays 5590).

**Container starts but I can't reach it from another machine.**
- Three things to check: (a) `docker run -p HOST_PORT:5590` actually mapped
  the port (`docker port scenegraph-review`); (b) host firewall lets the
  port through; (c) if cloud-hosted, the cloud security group allows
  inbound TCP on that port.

**I edited a JSON in the UI, clicked Save, but my changes "disappeared"
when I reload.**
- Most likely you reloaded in a different image's view. Each scenegraph
  is per-image. Use ← / → to revisit the same image and confirm.
- Otherwise, check `data/backups/` — every save writes a timestamped
  backup. Your changes are recoverable.

**Save is failing silently.**
- Open browser devtools → Network tab → click Save. The `PUT
  /api/sg/<id>` request shows the server's response. Common: the
  scenegraph JSON has additional/wrong keys the JS is choking on; the
  server logs an error in `journalctl -u scenegraph-review -n 50`.

**How do I adapt the 12 verdict keys to my own domain?**
- See [Adapting to a different domain](#adapting-to-a-different-domain) —
  it's three short list literals in three files.

---

## Reproducibility

Three artifacts make the environment recreatable bit-identically:

| File | Purpose |
|---|---|
| `.python-version` | Pins Python `3.12.3` — pyenv / asdf / uv / mise auto-pick. |
| `requirements.txt` | Hash-pinned (`--require-hashes`). Generated from `requirements.in` via `pip-compile --generate-hashes`. |
| `Dockerfile` | Pins the base image by sha256 digest. Multi-arch (linux/amd64 + linux/arm64). Runs as non-root user. |

### Regenerating hash-pinned requirements

After editing `requirements.in`:

```bash
python3 -m venv ~/VENVs/sg-piptools
~/VENVs/sg-piptools/bin/pip install pip-tools
~/VENVs/sg-piptools/bin/pip-compile --generate-hashes \
    --output-file=requirements.txt requirements.in
```

---

## API reference

All require an auth cookie except `/api/auth`, `/api/health`, and `/api/features`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth` | exchange access code for session cookie (24 h) |
| GET | `/api/features` | feature flags consumed by the frontend at page load |
| GET | `/api/list` | list image_ids + `has_scenegraph` flag |
| GET | `/api/sg/<image_id>` | fetch a scenegraph JSON |
| PUT | `/api/sg/<image_id>` | save a scenegraph JSON (creates timestamped backup) |
| GET | `/api/sg/<image_id>/download` | download a single scenegraph as JSON |
| GET | `/api/download_all` | stream all on-disk scenegraphs as NDJSON |
| GET | `/api/image/<image_id>` | serve the full-size image |
| GET | `/api/thumb/<image_id>` | serve 240×160 thumbnail (cached) |
| GET | `/api/health` | counts + flag visibility (no auth) |

---

## Repository layout

```
server.py                  Flask API (~250 lines, one file)
templates/index.html       single-page UI (vanilla JS + inline CSS, ~600 lines)
examples/
  example_scenegraph.full.json     realistic full example (copy and modify per image)
  example_scenegraph.minimal.json  bare-minimum valid skeleton
  validate_scenegraph.py           stdlib-only validator script
requirements.in            direct deps only (Flask, Pillow)
requirements.txt           hash-pinned, all transitives (generated)
.python-version            3.12.3
Dockerfile                 prod container
.env.example               sample environment configuration
.dockerignore              excludes runtime state + tooling from image
.gitignore                 excludes runtime state + venv from repo
data/                      runtime state (gitignored, dockerignored)
```

`data/` is intentionally runtime state, not source. Code goes in git; edited
data lives on disk.

---

## License

MIT — see `LICENSE`.
