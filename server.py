"""scenegraph-review server."""
from __future__ import annotations
import argparse
import json
import os
import secrets
import shutil
import time
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory, make_response
from PIL import Image

ROOT = Path(__file__).parent
DATA_DIR    = ROOT / "data"
IMAGES_DIR  = DATA_DIR / "images"
SG_DIR      = DATA_DIR / "scenegraphs"
THUMB_DIR   = DATA_DIR / "thumbs"
BACKUP_DIR  = DATA_DIR / "backups"
# Auto-create runtime dirs on a fresh clone (data/ may not yet exist).
for _d in (DATA_DIR, IMAGES_DIR, SG_DIR, THUMB_DIR, BACKUP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB per request
TOKENS: set[str] = set()  # in-memory; one process

# --- Optional expert-gold labels integration ---
#
# When the environment variable GOLD_LABELS_DIR points to a directory containing
# per-question subdirectories with gold_labels_expert_*.json files, the UI shows
# per-verdict comparison pills + row-level color tints. When unset or pointing
# to a path without that structure, all gold-related UI is hidden and the
# /api/gold endpoint returns empty objects. This is intentionally OFF by
# default so the open-source deployment works without any extra config.
GOLD_LABELS_DIR = os.environ.get("GOLD_LABELS_DIR", "").strip()
GOLD_BASE = Path(GOLD_LABELS_DIR) if GOLD_LABELS_DIR else None
SHORT_KEY_TO_QFOLDER = {
    "blood_pool":   "q01_blood_pooling",
    "standing":     "q02_standing_moving",
    "prone_back":   "q03_lying_back",
    "prone_face":   "q04_lying_front",
    "side_lying":   "q05_lying_side",
    "sit_supp":     "q06_sitting_supported",
    "sit_unsupp":   "q07_sitting_unsupported",
    "tripod_pos":   "q08_tripod",
    "amp_leg":      "q09_amputation_leg",
    "amp_arm":      "q10_amputation_arm",
    "protect_hand": "q11_protective_hand",
    "is_medic":     "q12_medic_noncasualty",
}


def _probe_expert_gold() -> bool:
    """Returns True iff GOLD_BASE is set AND has at least one q*/gold_labels_expert_*.json file."""
    if GOLD_BASE is None or not GOLD_BASE.is_dir():
        return False
    for qfolder in SHORT_KEY_TO_QFOLDER.values():
        qdir = GOLD_BASE / qfolder
        if qdir.is_dir() and any(qdir.glob("gold_labels_expert_*.json")):
            return True
    return False


EXPERT_GOLD_ENABLED = _probe_expert_gold()


ACCESS_CODE = os.environ.get("ACCESS_CODE", "changeMe")
COOKIE_NAME = "sg_token"


def require_auth(f):
    @wraps(f)
    def w(*args, **kwargs):
        tok = request.cookies.get(COOKIE_NAME)
        if not tok or tok not in TOKENS:
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return w


def list_image_ids() -> list[str]:
    """All image_ids that have a scenegraph JSON, sorted."""
    return sorted(p.stem.removesuffix(".jpg") for p in SG_DIR.glob("*.jpg.json"))


def all_image_ids_on_disk() -> list[str]:
    """All 106 image filenames (basename .jpg) — even those without a scenegraph yet."""
    return sorted(p.name for p in IMAGES_DIR.glob("*.jpg"))


# --- Routes ---

@app.get("/")
def index():
    return send_from_directory(str(ROOT / "templates"), "index.html")


@app.post("/api/auth")
def api_auth():
    code = (request.json or {}).get("access_code", "").strip()
    if code != ACCESS_CODE:
        return jsonify({"ok": False, "error": "invalid code"}), 403
    tok = secrets.token_urlsafe(24)
    TOKENS.add(tok)
    resp = make_response(jsonify({"ok": True}))
    resp.set_cookie(COOKIE_NAME, tok, max_age=86400, httponly=True, samesite="Lax")
    return resp


@app.get("/api/list")
@require_auth
def api_list():
    """Cleaner list endpoint."""
    sg_stems = set(p.name.removesuffix(".json") for p in SG_DIR.glob("*.jpg.json"))
    items = []
    for img_path in sorted(IMAGES_DIR.glob("*.jpg")):
        items.append({
            "image_id": img_path.name,
            "has_scenegraph": (img_path.name in sg_stems),
        })
    return jsonify(items)


@app.get("/api/sg/<image_id>")
@require_auth
def api_get_sg(image_id):
    p = SG_DIR / f"{image_id}.json"
    if not p.exists():
        return jsonify({"error": "not_found"}), 404
    return send_file(p, mimetype="application/json")


@app.put("/api/sg/<image_id>")
@require_auth
def api_put_sg(image_id):
    p = SG_DIR / f"{image_id}.json"
    if not p.exists():
        return jsonify({"error": "not_found"}), 404
    try:
        new = request.get_json()
        if not isinstance(new, dict):
            raise ValueError("payload must be object")
    except Exception as e:
        return jsonify({"ok": False, "error": f"bad json: {e}"}), 400
    # Backup the prior version, then write the new one.
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = BACKUP_DIR / f"{image_id}.{ts}.json"
    shutil.copy2(p, backup)
    new["image_id"] = image_id  # force consistency
    p.write_text(json.dumps(new, indent=2))
    return jsonify({"ok": True, "backup": backup.name})


@app.get("/api/sg/<image_id>/download")
@require_auth
def api_download_sg(image_id):
    p = SG_DIR / f"{image_id}.json"
    if not p.exists():
        return jsonify({"error": "not_found"}), 404
    return send_file(
        p, mimetype="application/json",
        as_attachment=True, download_name=f"{image_id}.json",
    )


@app.get("/api/image/<image_id>")
@require_auth
def api_image(image_id):
    p = IMAGES_DIR / image_id
    if not p.exists():
        return jsonify({"error": "not_found"}), 404
    return send_file(p, mimetype="image/jpeg")


@app.get("/api/thumb/<image_id>")
@require_auth
def api_thumb(image_id):
    src = IMAGES_DIR / image_id
    if not src.exists():
        return jsonify({"error": "not_found"}), 404
    dst = THUMB_DIR / image_id
    if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
        with Image.open(src) as im:
            im.thumbnail((240, 160))
            im.save(dst, "JPEG", quality=80)
    return send_file(dst, mimetype="image/jpeg")



@app.get("/api/gold/<image_id>")
@require_auth
def api_gold(image_id):
    """Return per-question gold labels (all experts) for the given image.

    Output shape:  {short_key: {expert_id: "Yes"|"No", ...}, ...}
    Returns all empty per-expert dicts when EXPERT_GOLD_ENABLED is False.
    """
    if not EXPERT_GOLD_ENABLED:
        return jsonify({sk: {} for sk in SHORT_KEY_TO_QFOLDER})
    img_key = f"images/{image_id}"
    out = {}
    for sk, qfolder in SHORT_KEY_TO_QFOLDER.items():
        per_expert = {}
        qdir = GOLD_BASE / qfolder
        if qdir.is_dir():
            for gp in qdir.glob("gold_labels_expert_*.json"):
                try:
                    d = json.load(open(gp))
                    eid = d.get("expert_id") or gp.stem.removeprefix("gold_labels_")
                    val = d.get("labels", {}).get(img_key)
                    if val is not None:
                        per_expert[eid] = val
                except Exception:
                    continue
        out[sk] = per_expert
    return jsonify(out)



@app.get("/api/download_all")
@require_auth
def api_download_all():
    """Stream all scenegraph JSONs as a single NDJSON file (one record per line).

    Reflects on-disk saved state at the moment of the request. Any in-flight
    UI edits that haven't been Save'd are NOT included.
    """
    from datetime import datetime
    from flask import Response

    def gen():
        for p in sorted(SG_DIR.glob("*.jpg.json")):
            try:
                d = json.load(open(p))
            except Exception:
                continue
            d.pop("_diagnostics", None)
            yield json.dumps(d) + "\n"

    fname = f"scenegraphs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.ndjson"
    return Response(
        gen(),
        mimetype="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )



@app.get("/api/features")
def api_features():
    """Public feature flags consumed by the frontend at page load."""
    return jsonify({
        "expert_gold_enabled": EXPERT_GOLD_ENABLED,
    })


@app.get("/api/health")
def api_health():
    return jsonify({
        "ok": True,
        "scenegraphs": len(list_image_ids()),
        "images_on_disk": len(all_image_ids_on_disk()),
        "expert_gold_enabled": EXPERT_GOLD_ENABLED,
    })


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5590)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()
    print(f"scenegraph-review serving on {args.host}:{args.port} (access code: {'(env)' if os.environ.get('ACCESS_CODE') else 'changeMe'})")
    print(f"  scenegraphs dir: {SG_DIR}  ({len(list_image_ids())} files)")
    print(f"  images dir:      {IMAGES_DIR}  ({len(all_image_ids_on_disk())} files)")
    print(f"  expert gold:     {'ENABLED (' + str(GOLD_BASE) + ')' if EXPERT_GOLD_ENABLED else 'disabled'}")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
