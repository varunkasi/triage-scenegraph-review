# scenegraph-review

A Flask UI for reviewing and editing per-image scenegraphs produced by a VLM
(vision-language model). Built for triage / casualty-assessment imagery, but
the schema is generic enough to repurpose.

The UI shows your image with the ground-truth and (optionally) predicted
bounding box, lets you edit every field in the scenegraph JSON (text fields,
dropdowns for enumerated values, add/remove rows for entities and relations),
and saves changes back to disk with automatic timestamped backups.

---

## Quickstart (Docker)

```bash
git clone <repo-url> scenegraph-review && cd scenegraph-review
docker build -t scenegraph-review .

# Put your data in place:
mkdir -p data/{images,scenegraphs,thumbs,backups}
cp /path/to/your/images/*.jpg     data/images/
cp /path/to/your/scenegraphs/*.json  data/scenegraphs/

docker run -d --name scenegraph-review \
    -p 5590:5590 \
    -e ACCESS_CODE=changeMe \
    -v $(pwd)/data:/app/data \
    --restart unless-stopped \
    scenegraph-review
```

Open `http://localhost:5590`, enter the access code, and start reviewing.

## Quickstart (bare-metal venv)

```bash
git clone <repo-url> scenegraph-review && cd scenegraph-review
python3 -m venv venv
venv/bin/pip install --require-hashes -r requirements.txt

mkdir -p data/{images,scenegraphs,thumbs,backups}
cp /path/to/your/images/*.jpg     data/images/
cp /path/to/your/scenegraphs/*.json  data/scenegraphs/

ACCESS_CODE=changeMe venv/bin/python server.py --port 5590
```

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

If a `.jpg` exists without a matching `.jpg.json`, it shows in the gallery
with a red **no SG** badge — useful for tracking which images still need a
scenegraph from your generation pipeline.

### Scenegraph JSON: use the templates

Two working examples ship with this repo in `examples/`:

| File                                       | What it is                                                      |
|--------------------------------------------|-----------------------------------------------------------------|
| `examples/example_scenegraph.full.json`    | Fully filled-out realistic example. Copy and modify per image.  |
| `examples/example_scenegraph.minimal.json` | Bare-minimum valid scenegraph — every required field present with safe defaults (`"unknown"`, empty strings/arrays). Useful as a starting skeleton or for programmatic generation. |

**To onboard a new image manually**:

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

**To onboard many images programmatically**: generate one
`data/scenegraphs/<image_id>.json` per image with your VLM pipeline (or any
script) following the schema. Then validate the whole folder:

```bash
python examples/validate_scenegraph.py data/scenegraphs/
```

The validator (`examples/validate_scenegraph.py`) is a 168-line standalone
script with no dependencies beyond the Python standard library. It reports
every missing/typed-wrong field per file and exits non-zero if any file
fails, so it slots into CI cleanly:

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
| 12 short-key verdict objects     | each is `{"verdict": …, "confidence": …, "evidence": …}` (enums below) |

The 12 verdict short-keys (the subject-level binary observations the UI is
built around): `blood_pool`, `standing`, `prone_back`, `prone_face`,
`side_lying`, `sit_supp`, `sit_unsupp`, `tripod_pos`, `amp_leg`, `amp_arm`,
`protect_hand`, `is_medic`. Each verdict is `"yes" | "no" | "unknown"` and
confidence is `"low" | "medium" | "high"`.

If you need to adapt the 12 keys to a different domain, update both:
- `SHORT_KEY_TO_QFOLDER` in `server.py` (top of file)
- `SHORT_KEYS` in `templates/index.html` (near the top of the `<script>` block)
- `SHORT_KEYS` in `examples/validate_scenegraph.py`

### Bbox conventions

- All bboxes are `[x1, y1, x2, y2]` in **pixel coordinates** of the original
  image. `x1 < x2`, `y1 < y2`.
- `gt_bbox` is the *ground-truth* box for the primary subject. The UI draws
  this in **green solid**.
- `predicted_bbox` is the model's independent estimate of where the same
  subject is. The UI draws this in **magenta dashed**, and computes IoU
  against `gt_bbox`. Show or hide via the toolbar checkbox.
- If you have only one bbox source, set both to the same value.
- If you do not have ground truth at all, set `gt_bbox = [0,0,0,0]` (the UI
  will report IoU = 0 against your predicted box, which is the honest signal).

---

## Features

- Access-code-gated login (`ACCESS_CODE` env var; default `changeMe`).
- Thumbnail gallery; selected thumb has gold border.
- Left/right arrow keys navigate prev/next. Click any thumb to jump.
- Toggleable predicted-bbox overlay:
  - **Green solid** box = GT (typically already burned into the JPG by your data pipeline).
  - **Magenta dashed** box = model-predicted bbox (toggled via toolbar checkbox).
- Editable form for every scenegraph field:
  - Text inputs / textareas for free-text fields.
  - Dropdowns for enumerated fields (modality, ambulatory, verdict, confidence, entity type).
  - Number inputs for bbox coordinates and counts.
  - Add/remove rows for `secondary_entities` and `relations`.
- **Save** writes the in-memory JSON to disk with a timestamped backup in
  `data/backups/`. Backups are kept forever — clean them up yourself if disk
  is tight.
- **Download current** — single JSON for the visible image, includes any
  unsaved edits.
- **Download all (NDJSON)** — server reads all on-disk scenegraphs and
  streams a single newline-delimited bundle. Excludes unsaved edits.
- Bottom status bar: filename, modality, gt-vs-predicted IoU, image index.
- Ctrl/Cmd-S as keyboard shortcut for Save. Unsaved-edits warning before
  navigating away.

---

## API endpoints

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

## Production deployment (systemd)

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
```

If your host is behind a cloud security group (AWS / GCP / OpenStack / etc.),
remember to open inbound TCP on the port you picked.

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

## Layout

```
server.py                  Flask API (~250 lines)
templates/index.html       single-page UI (vanilla JS + inline CSS, ~600 lines)
requirements.in            direct deps only
requirements.txt           hash-pinned, all transitives (generated)
.python-version            3.12.3
Dockerfile                 prod container
.env.example               sample environment configuration
.dockerignore              excludes runtime state + tooling from image
.gitignore                 excludes runtime state + venv from repo
data/                      runtime state (gitignored)
```

`data/` is intentionally treated as runtime state, not source. Code goes in
git; edited data lives on disk.

---

## License

MIT — see `LICENSE`.
