#!/usr/bin/env python3
"""Validate scenegraph JSON file(s) against the shape the UI expects.

Usage:
    python validate_scenegraph.py <file_or_dir> [<file_or_dir> ...]

Examples:
    python examples/validate_scenegraph.py examples/example_scenegraph.full.json
    python examples/validate_scenegraph.py data/scenegraphs/

Exit codes:
    0  all files valid
    1  one or more files failed validation
    2  no files found
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterable

SHORT_KEYS = [
    "blood_pool", "standing", "prone_back", "prone_face", "side_lying",
    "sit_supp", "sit_unsupp", "tripod_pos", "amp_leg", "amp_arm",
    "protect_hand", "is_medic",
]
VERDICT_ENUM = {"yes", "no", "unknown"}
CONFIDENCE_ENUM = {"low", "medium", "high"}
MODALITY_ENUM = {"RGB", "IR"}
AMBULATORY_ENUM = {"yes", "no", "unknown"}
ENTITY_TYPE_ENUM = {"person", "vehicle", "object", "threat", "structure", "animal"}


def validate_scenegraph(d: dict, path: str = "") -> list[str]:
    """Return a list of error strings; empty list means valid."""
    errs: list[str] = []

    def need(parent: dict, key: str, prefix: str, type_check=None, enum=None):
        if key not in parent:
            errs.append(f"{prefix}: missing required key {key!r}")
            return None
        v = parent[key]
        if type_check is not None and not isinstance(v, type_check):
            errs.append(f"{prefix}.{key}: expected {type_check.__name__}, got {type(v).__name__}")
        if enum is not None and v not in enum:
            errs.append(f"{prefix}.{key}: value {v!r} not in {sorted(enum)}")
        return v

    if not isinstance(d, dict):
        return [f"{path or 'root'}: not a JSON object"]

    need(d, "image_id", path or "root", str)
    need(d, "modality", path or "root", str, MODALITY_ENUM)

    # scene
    scene = need(d, "scene", path or "root", dict)
    if isinstance(scene, dict):
        need(scene, "setting", "scene", str)
        need(scene, "lighting", "scene", str)
        need(scene, "terrain", "scene", str)
        need(scene, "hazards", "scene", list)
        for compound in ("nearby_persons", "nearby_vehicles"):
            sub = need(scene, compound, "scene", dict)
            if isinstance(sub, dict):
                need(sub, "count", f"scene.{compound}", int)
                need(sub, "details", f"scene.{compound}", str)
        for arr in ("medical_devices_visible", "threats_visible", "obstacles"):
            need(scene, arr, "scene", list)

    # primary_subject
    ps = need(d, "primary_subject", path or "root", dict)
    if isinstance(ps, dict):
        need(ps, "gt_bbox", "primary_subject", list)
        need(ps, "predicted_bbox", "primary_subject", list)
        need(ps, "predicted_bbox_confidence", "primary_subject", str, CONFIDENCE_ENUM)
        need(ps, "img_w", "primary_subject", int)
        need(ps, "img_h", "primary_subject", int)
        need(ps, "posture_prose", "primary_subject", str)
        need(ps, "ambulatory", "primary_subject", str, AMBULATORY_ENUM)
        need(ps, "emt_assessment_prose", "primary_subject", str)
        for sk in SHORT_KEYS:
            v = need(ps, sk, "primary_subject", dict)
            if isinstance(v, dict):
                need(v, "verdict", f"primary_subject.{sk}", str, VERDICT_ENUM)
                need(v, "confidence", f"primary_subject.{sk}", str, CONFIDENCE_ENUM)
                need(v, "evidence", f"primary_subject.{sk}", str)
        for bbox_key in ("gt_bbox", "predicted_bbox"):
            b = ps.get(bbox_key)
            if isinstance(b, list):
                if len(b) != 4:
                    errs.append(f"primary_subject.{bbox_key}: expected 4 ints, got {len(b)}")
                if not all(isinstance(x, int) for x in b):
                    errs.append(f"primary_subject.{bbox_key}: all elements must be int")

    # secondary_entities
    ents = need(d, "secondary_entities", path or "root", list)
    if isinstance(ents, list):
        for i, e in enumerate(ents):
            if not isinstance(e, dict):
                errs.append(f"secondary_entities[{i}]: not a JSON object")
                continue
            need(e, "id", f"secondary_entities[{i}]", str)
            need(e, "type", f"secondary_entities[{i}]", str, ENTITY_TYPE_ENUM)
            need(e, "count", f"secondary_entities[{i}]", int)
            need(e, "relation", f"secondary_entities[{i}]", str)
            need(e, "attrs", f"secondary_entities[{i}]", dict)

    # relations
    rels = need(d, "relations", path or "root", list)
    if isinstance(rels, list):
        for i, r in enumerate(rels):
            if not isinstance(r, dict):
                errs.append(f"relations[{i}]: not a JSON object")
                continue
            need(r, "from", f"relations[{i}]", str)
            need(r, "rel", f"relations[{i}]", str)
            need(r, "to", f"relations[{i}]", str)

    return errs


def collect_files(paths: Iterable[str]) -> list[Path]:
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            out.extend(sorted(p.glob("*.json")))
        elif p.is_file():
            out.append(p)
        else:
            print(f"warning: {p} does not exist", file=sys.stderr)
    return out


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    files = collect_files(argv)
    if not files:
        print("no JSON files found", file=sys.stderr)
        return 2
    n_ok = n_bad = 0
    for p in files:
        try:
            d = json.loads(p.read_text())
        except json.JSONDecodeError as e:
            print(f"FAIL  {p}: invalid JSON ({e})")
            n_bad += 1
            continue
        errs = validate_scenegraph(d)
        if errs:
            n_bad += 1
            print(f"FAIL  {p}:")
            for err in errs[:20]:
                print(f"  - {err}")
            if len(errs) > 20:
                print(f"  ... and {len(errs)-20} more")
        else:
            n_ok += 1
            print(f"OK    {p}")
    print(f"\n{n_ok} valid, {n_bad} invalid")
    return 0 if n_bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
