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

## Data layout

Everything you bring lives in `data/`:

```
data/
├── images/        your JPEGs (one per scenegraph; filename = image_id)
├── scenegraphs/   your scenegraph JSONs, named `<image_id>.json`
├── thumbs/        regenerated on demand (240×160 cache); leave empty
└── backups/       per-save snapshots written by the server; leave empty
```

The server matches each `data/scenegraphs/<name>.jpg.json` to its
`data/images/<name>.jpg`. If a scenegraph references an image that's not
on disk, the gallery shows it with a "no SG" badge.

## Scenegraph JSON shape

```json
{
  "image_id": "example.jpg",
  "modality": "RGB",
  "scene": {
    "setting": "outdoor wooded area",
    "lighting": "daylight",
    "terrain": "dirt with sparse grass",
    "hazards": ["debris"],
    "nearby_persons":  {"count": 0, "details": "none visible"},
    "nearby_vehicles": {"count": 0, "details": "none visible"},
    "medical_devices_visible": [],
    "threats_visible": [],
    "obstacles": []
  },
  "primary_subject": {
    "gt_bbox":        [x1, y1, x2, y2],
    "predicted_bbox": [x1, y1, x2, y2],
    "predicted_bbox_confidence": "low|medium|high",
    "img_w": 1920,
    "img_h": 1080,
    "posture_prose": "...",
    "ambulatory": "yes|no|unknown",
    "emt_assessment_prose": "...",
    "<short_key_1>": {"verdict": "yes|no|unknown", "confidence": "low|medium|high", "evidence": "..."},
    "<short_key_2>": { ... },
    ...
  },
  "secondary_entities": [
    {"id": "e1", "type": "person|vehicle|object|threat|structure|animal",
     "count": 1, "relation": "...", "attrs": {...}}
  ],
  "relations": [
    {"from": "primary", "rel": "...", "to": "e1"}
  ]
}
```

See `server.py` for the full JSON schema enforced by the server, and the
`SHORT_KEY_TO_QFOLDER` mapping for the 12 binary subject-level keys the UI
expects (`blood_pool`, `standing`, `prone_back`, `prone_face`, `side_lying`,
`sit_supp`, `sit_unsupp`, `tripod_pos`, `amp_leg`, `amp_arm`, `protect_hand`,
`is_medic`). You can adapt these to your domain by editing the mapping +
the corresponding HTML constants in `templates/index.html`.

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
