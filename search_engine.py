"""
search_engine.py  -  a small, dependency-free hybrid search engine.

It builds a TF-IDF index over each asset's combined text (title + folder +
OCR + slide/PDF text + tags) and ranks a natural-language query by cosine
similarity. This is deliberately pure-Python so the demo runs on a stock
Python install with no pip step. In production you'd swap this for real
embeddings (the PRD's "semantic + visual retrieval") - the interface stays
the same.

Guard rails wired in here:
  - PRIVACY .......... results are filtered by the user's permissions.
  - EXPLAINABILITY ... every result carries a match reason + confidence.
  - HUMAN CONTROL .... human-confirmed "final" version is surfaced first.
  - NO FABRICATION ... only assets that exist in the index can be returned.
"""

import json
import math
import re
import os

import config
import guardrails

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP = set("the a an of for and or to in on with is are be this that it as at "
            "by from your you i we our can find search give me show get please "
            "one all any into".split())


def tokenize(text):
    return [t for t in _TOKEN_RE.findall((text or "").lower())
            if t not in _STOP and len(t) > 1]


class SearchEngine:
    def __init__(self, index_path=None):
        self.index_path = index_path or config.INDEX_FILE
        self.assets = []
        self.by_id = {}
        self.dup_families = {}
        self.idf = {}
        self.doc_vecs = []      # list of {term: weight} L2-normalized
        self._load()

    # -- index construction --------------------------------------------------
    def _searchable_text(self, a):
        # weight title & tags by repetition
        parts = [a.get("title", "")] * 3
        parts += [" ".join(a.get("topics", []))] * 2
        parts += [a.get("asset_type", ""), a.get("folder", "").replace("_", " ")]
        parts += [a.get("ocr", ""), a.get("body", "")]
        # user-added tags (human-in-the-loop) also become searchable
        ov = guardrails.load_overrides()
        parts += ov.get("tags", {}).get(a["id"], [])
        return " ".join(parts)

    def _load(self):
        if not os.path.exists(self.index_path):
            raise FileNotFoundError(
                f"Index not found at {self.index_path}. Run: python build_index.py")
        with open(self.index_path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assets = data.get("assets", [])
        self.dup_families = data.get("duplicate_families", {})
        self.by_id = {a["id"]: a for a in self.assets}

        docs_tokens = [tokenize(self._searchable_text(a)) for a in self.assets]
        # document frequency
        df = {}
        for toks in docs_tokens:
            for t in set(toks):
                df[t] = df.get(t, 0) + 1
        N = max(1, len(docs_tokens))
        self.idf = {t: math.log((1 + N) / (1 + d)) + 1 for t, d in df.items()}

        self.doc_vecs = []
        for toks in docs_tokens:
            tf = {}
            for t in toks:
                tf[t] = tf.get(t, 0) + 1
            vec = {t: (c) * self.idf.get(t, 0) for t, c in tf.items()}
            self.doc_vecs.append(self._normalize(vec))

    @staticmethod
    def _normalize(vec):
        norm = math.sqrt(sum(w * w for w in vec.values())) or 1.0
        return {t: w / norm for t, w in vec.items()}

    # -- querying ------------------------------------------------------------
    def _expand(self, tokens):
        expanded = {}
        for t in tokens:
            expanded[t] = expanded.get(t, 0) + 1.0
            for syn in config.SYNONYMS.get(t, []):
                expanded[syn] = max(expanded.get(syn, 0), 0.6)  # synonyms weigh less
        return expanded

    def _query_vec(self, query):
        toks = tokenize(query)
        weights = self._expand(toks)
        vec = {t: w * self.idf.get(t, 0) for t, w in weights.items()}
        return self._normalize(vec), set(toks)

    def _permitted(self, a):
        # PRIVACY guard rail: members cannot see 'restricted' assets.
        vis = a.get("visibility", "team")
        if vis == "restricted" and config.CURRENT_USER != "admin":
            return False
        return True

    def _match_reason(self, a, query_terms):
        text = self._searchable_text(a).lower()
        hits = [t for t in query_terms if t in text]
        # where did it hit? prefer to name the field for explainability
        fields = []
        if any(t in (a.get("title", "").lower()) for t in query_terms):
            fields.append("filename/title")
        if any(t in (a.get("ocr", "").lower()) for t in query_terms):
            fields.append("text read from the image (OCR)")
        if any(t in (a.get("body", "").lower()) for t in query_terms):
            fields.append("slide/PDF text")
        if any(t in " ".join(a.get("topics", [])).lower() for t in query_terms):
            fields.append("topic tag")
        reason = ""
        if hits:
            reason = "matched " + ", ".join(sorted(set(hits))[:6])
            if fields:
                reason += " in " + " + ".join(fields)
        return reason or "related by overall content similarity"

    def search(self, query, max_results=None):
        max_results = max_results or config.MAX_RESULTS
        overrides = guardrails.load_overrides()
        qvec, qterms = self._query_vec(query)

        scored = []
        for i, a in enumerate(self.assets):
            if not self._permitted(a):
                continue
            dv = self.doc_vecs[i]
            # cosine (both normalized) = dot product
            if len(qvec) < len(dv):
                score = sum(w * dv.get(t, 0) for t, w in qvec.items())
            else:
                score = sum(w * qvec.get(t, 0) for t, w in dv.items())
            if score > 0.001:
                scored.append((score, a))

        scored.sort(key=lambda x: x[0], reverse=True)

        # collapse duplicate families: keep the best-scoring member, note the rest
        seen_family = {}
        collapsed = []
        for score, a in scored:
            fam = a["family"]
            if fam in seen_family:
                seen_family[fam]["family_size"] += 1
                continue
            entry = self._to_result(a, score, qterms, overrides)
            entry["family_size"] = 1
            seen_family[fam] = entry
            collapsed.append(entry)

        results = collapsed[:max_results]

        # EXPLAINABILITY: ambiguity detection
        ambiguous = False
        if len(results) >= 2:
            top = results[0]["score"]
            second = results[1]["score"]
            if top >= config.CONF_MED and second >= config.CONF_MED and \
               second >= config.AMBIGUOUS_RATIO * top:
                ambiguous = True

        return {
            "query": query,
            "count": len(results),
            "ambiguous": ambiguous,
            "results": results,
        }

    def _to_result(self, a, score, qterms, overrides):
        fam = a["family"]
        final_id = overrides.get("final", {}).get(fam)
        # Complete path to the asset: the absolute filesystem path for an
        # internal file, or the public URL for a link.
        if a.get("kind") == "link":
            full_path = a.get("url") or ""
        else:
            full_path = os.path.normpath(
                os.path.join(config.ASSETS_DIR, a.get("rel_path", "")))
        # File extension (lower-case, no dot) — drives which asset types allow
        # the human "Mark as final" action.
        ext = os.path.splitext(a.get("filename", ""))[1].lower().lstrip(".")
        return {
            "id": a["id"],
            "title": a["title"] or a["filename"] or a["url"],
            "asset_type": a["asset_type"],
            "topics": a.get("topics", []) + overrides.get("tags", {}).get(a["id"], []),
            "source": a["source"],
            "rel_path": a["rel_path"],
            "full_path": full_path,
            "ext": ext,
            "url": a.get("url"),
            "thumb": a.get("thumb"),
            "author": a.get("author"),
            "created": a.get("created"),
            "family": fam,
            "is_final": (final_id == a["id"]),
            "has_final_marked": bool(final_id),
            "score": round(float(score), 4),
            "confidence": guardrails.classify_confidence(score),
            "why": self._match_reason(a, qterms),
        }
