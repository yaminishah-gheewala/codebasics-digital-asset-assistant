"""
Central configuration for the Codebasics Digital Asset Assistant (prototype).

Everything a reviewer might want to tweak lives here: where the data is, the
search thresholds that drive the confidence signals, the controlled tag
vocabulary, and the guard-rail switches that come straight from the PRD.
"""

import os

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# The sample dataset. By default we look one level up from this project folder
# (this project is meant to live inside the Dataset/ folder). Override with the
# DAA_DATA env var if your data lives elsewhere.
DATA_ROOT = os.environ.get(
    "DAA_DATA",
    os.path.abspath(os.path.join(PROJECT_DIR, "..")),
)
ASSETS_DIR = os.path.join(DATA_ROOT, "sample_assets", "sample_assets")
PUBLIC_LINKS_XLSX = os.path.join(DATA_ROOT, "public_links.xlsx")

INDEX_DIR = os.path.join(PROJECT_DIR, "index_data")
INDEX_FILE = os.path.join(INDEX_DIR, "index.json")
THUMBS_DIR = os.path.join(INDEX_DIR, "thumbs")
OVERRIDES_FILE = os.path.join(INDEX_DIR, "overrides.json")   # human-in-the-loop
AUDIT_FILE = os.path.join(INDEX_DIR, "audit.log")            # governance

# ---------------------------------------------------------------------------
# Guard-rail switches  (mapped to the ethics cards in the capstone exercise)
# ---------------------------------------------------------------------------
ENABLED = True          # CHECK & GOVERNANCE: master kill-switch. False => assistant is paused.
CURRENT_USER = "member" # PRIVACY: role used for permission filtering ("member" or "admin").

# ---------------------------------------------------------------------------
# Search / confidence thresholds  (drive the High / Medium / Low badges)
# ---------------------------------------------------------------------------
CONF_HIGH = 0.32        # cosine score at/above this => High confidence
CONF_MED = 0.16         # ... => Medium confidence ; below => Low
AMBIGUOUS_RATIO = 0.95  # if 2nd result >= this * top result (and both >= MED) => ambiguous
MAX_RESULTS = 12

# ---------------------------------------------------------------------------
# Controlled tag vocabulary for lightweight auto-tagging.
# topic keyword -> canonical topic label
# ---------------------------------------------------------------------------
TOPIC_KEYWORDS = {
    "power bi": "Power BI", "powerbi": "Power BI", "dax": "Power BI", "bi tool": "Power BI",
    "machine learning": "Machine Learning", "ml ": "Machine Learning", "what is ml": "Machine Learning",
    "linear regression": "Linear Regression", "regression": "Linear Regression",
    "svm": "SVM", "support vector": "SVM",
    "sql": "SQL",
    "python": "Python", "pandas": "Python", "numpy": "Python", "matplotlib": "Python",
    "deep learning": "Deep Learning", "neural": "Deep Learning", "cnn": "Deep Learning", "tensorflow": "Deep Learning",
    "langchain": "GenAI", "genai": "GenAI", "llm": "GenAI", "generative": "GenAI",
    "data analyst": "Data Analyst", "data analytics": "Data Analyst", "analyst roadmap": "Data Analyst",
    "data engineer": "Data Roles", "data scientist": "Data Roles",
    "star schema": "Data Modeling",
    "bootcamp": "Bootcamp",
    "resume": "Careers", "job": "Careers",
    "ai bubble": "AI Industry", "ai & data conference": "Event", "conference": "Event",
}

# Query synonym expansion so natural language ("photo", "deck") maps to our content.
SYNONYMS = {
    "photo": ["image", "picture", "thumbnail", "photograph"],
    "picture": ["image", "photo"],
    "pic": ["image", "photo"],
    "image": ["photo", "picture"],
    "thumbnail": ["thumb", "image", "cover"],
    "deck": ["slides", "presentation", "powerpoint", "ppt"],
    "slides": ["deck", "presentation"],
    "presentation": ["deck", "slides"],
    "video": ["youtube", "tutorial"],
    "link": ["url", "youtube", "video", "website"],
    "doc": ["pdf", "document", "handout"],
    "pdf": ["document", "handout"],
    "banner": ["promo", "enrollment"],
    "logo": ["brand"],
}

# ---------------------------------------------------------------------------
# Prompt-injection / misuse patterns  (IDENTITY + NO MISUSE guard rail)
# The query is only ever used as search text; if it looks like an attempt to
# hijack the tool we refuse and log it rather than "obeying" it.
# ---------------------------------------------------------------------------
INJECTION_PATTERNS = [
    r"ignore (all|previous|above)",
    r"disregard (the|all|previous)",
    r"system prompt",
    r"you are now",
    r"act as",
    r"drop\s+table",
    r"delete\s+(all|from)",
    r"<\s*script",
    r"rm\s+-rf",
    r"\bexec\b", r"\beval\(",
]
