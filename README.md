# scenegraph-review

Flask UI for reviewing & editing per-image EMT scenegraphs produced by
gemma-4-31b-it (see `dtc-vlm-server:/external/gemma4-31b-it/scenegraph-pipeline/`).

Deployed on `vlm-image-review:5590` as `scenegraph-review.service`
(systemd; access code `sgreview2026`).

## Features

- Login via access code (env var `ACCESS_CODE`, default `sgreview2026`).
- 106-image gallery with thumbnails; selected thumb highlighted; default = first
  image with a scenegraph.
- Left/right arrow navigation; click thumb to jump.
- Toggleable predicted-bbox overlay (green = GT burned into JPG, magenta dashed
  = gemma predicted).
- Editable form for every scenegraph field:
  - text inputs for free-text fields, dropdowns for enumerated fields
    (modality, ambulatory, verdict, confidence, entity type),
  - number inputs for bbox + counts,
  - add/remove rows for `secondary_entities` and `relations`.
- Per-question expert-gold comparison pills (e.g. `E1:Y✓`, `E3:N✗`) +
  row-level color tint (green=agree, red=differ, orange=mixed/unknown,
  none=no gold). Pulled live from
  `~/vqa_labeling_Apr2026/q*/gold_labels_expert_*.json` on the same VM.
- Save (PUT) writes the in-memory JSON back to disk with a timestamped backup.
- Download current (in-memory; includes unsaved edits) — one JSON file.
- Download all (NDJSON) — server reads all 106 from disk, streams a single
  newline-delimited bundle.
- Bottom status bar: filename, modality, gt-vs-predicted IoU, index.

## Layout

```
server.py                  Flask API (~190 lines)
templates/index.html       single-page UI (vanilla JS, ~500 lines)
static/                    (reserved; UI is fully self-contained in templates/index.html)
data/                      runtime state on the VM (gitignored)
  ├── images/              symlink farm to ~/vqa_labeling_Apr2026/q01_blood_pooling/images/
  ├── scenegraphs/         the 106 JSONs being edited
  ├── thumbs/              regenerated 240×160 JPEGs
  └── backups/             per-save snapshots
venv/                      project venv (gitignored)
logs/                      server stdout/stderr (gitignored)
```

## Endpoints (all require auth cookie except /api/auth)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth` | exchange access code for session cookie |
| GET | `/api/list2` | list 106 image_ids + `has_scenegraph` flag |
| GET | `/api/sg/<image_id>` | fetch a scenegraph JSON |
| PUT | `/api/sg/<image_id>` | save a scenegraph JSON (creates backup) |
| GET | `/api/sg/<image_id>/download` | download a single scenegraph |
| GET | `/api/download_all` | stream all on-disk scenegraphs as NDJSON |
| GET | `/api/gold/<image_id>` | expert gold verdicts for an image |
| GET | `/api/image/<image_id>` | serve full-size image |
| GET | `/api/thumb/<image_id>` | serve 240×160 thumbnail (cached) |
| GET | `/api/health` | counts of scenegraphs and images on disk |

## Local dev / re-deploy

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
ACCESS_CODE=sgreview2026 venv/bin/python server.py --port 5590
```

`requirements.txt` pins exact versions verified on the live deployment
(Flask 3.1.3, Pillow 12.2.0, Python 3.12.3).

Deployment unit on the VM:

```
[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/scenegraph-review
Environment="ACCESS_CODE=sgreview2026"
ExecStart=/home/ubuntu/scenegraph-review/venv/bin/python server.py --port 5590
Restart=on-failure
```
