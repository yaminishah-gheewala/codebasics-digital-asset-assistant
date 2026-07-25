"""
Guard rails for the Digital Asset Assistant.

Each function here is the *code* behind an ethics card from the capstone
exercise, so the mitigation is real rather than aspirational:

  IDENTITY / NO MISUSE ....... screen_query()  - the query is treated as data;
                               adversarial input is refused and logged.
  EXPLAINABILITY ............. classify_confidence() + match reasons in search.
  CHECK & GOVERNANCE ......... audit()          - every query/action is logged.
  HUMAN CONTROL / ACCOUNTAB. . mark_final / correct_tag write who did what.
"""

import re
import json
import os
import datetime
import config


# --- IDENTITY + NO MISUSE ---------------------------------------------------
_INJECTION_RE = [re.compile(p, re.I) for p in config.INJECTION_PATTERNS]


def screen_query(q):
    """Return (clean_query, ok, message).

    ok=False means the input looked like a misuse / injection attempt and must
    not be processed as a normal search.
    """
    if q is None:
        return "", False, "Empty query."
    q = q.strip()
    if not q:
        return "", False, "Please type what you are looking for."
    if len(q) > 300:
        q = q[:300]
    for rx in _INJECTION_RE:
        if rx.search(q):
            audit("BLOCKED_INJECTION", q)
            return q, False, (
                "That request looks like an attempt to change how the assistant "
                "behaves. This tool only searches the asset library, so the input "
                "was ignored and logged."
            )
    return q, True, ""


# --- EXPLAINABILITY: confidence signal --------------------------------------
def classify_confidence(score):
    if score >= config.CONF_HIGH:
        return "High"
    if score >= config.CONF_MED:
        return "Medium"
    return "Low"


# --- CHECK & GOVERNANCE: audit log ------------------------------------------
def audit(event, detail=""):
    os.makedirs(config.INDEX_DIR, exist_ok=True)
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    line = f"{ts}\t{event}\t{detail}\n"
    with open(config.AUDIT_FILE, "a", encoding="utf-8") as fh:
        fh.write(line)


def read_audit(limit=200):
    if not os.path.exists(config.AUDIT_FILE):
        return []
    with open(config.AUDIT_FILE, encoding="utf-8") as fh:
        lines = fh.readlines()
    return [l.rstrip("\n") for l in lines[-limit:]][::-1]


# --- HUMAN CONTROL: overrides (final version, tag corrections) --------------
def load_overrides():
    if not os.path.exists(config.OVERRIDES_FILE):
        return {"final": {}, "tags": {}}
    try:
        with open(config.OVERRIDES_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        data = {}
    data.setdefault("final", {})
    data.setdefault("tags", {})
    return data


def save_overrides(data):
    os.makedirs(config.INDEX_DIR, exist_ok=True)
    with open(config.OVERRIDES_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def mark_final(family, asset_id, user=None):
    """A human confirms which version in an asset family is the canonical one."""
    user = user or config.CURRENT_USER
    ov = load_overrides()
    ov["final"][family] = asset_id
    save_overrides(ov)
    audit("MARK_FINAL", f"user={user} family={family} asset={asset_id}")


def correct_tag(asset_id, tag, user=None):
    """A human adds/confirms a tag; this feeds back into the index for everyone."""
    user = user or config.CURRENT_USER
    ov = load_overrides()
    tags = ov["tags"].setdefault(asset_id, [])
    if tag and tag not in tags:
        tags.append(tag)
    save_overrides(ov)
    audit("CORRECT_TAG", f"user={user} asset={asset_id} tag={tag}")
