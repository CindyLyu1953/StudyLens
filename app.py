from pathlib import Path
from urllib.parse import urlencode

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
INPUT_CSV = DATA_DIR / "input" / "paper_extracted.csv"
TRACKING_DB = DATA_DIR / "output" / "tracking.db"
UPLOAD_DIR = DATA_DIR / "user_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
TRACKING_DB.parent.mkdir(parents=True, exist_ok=True)

SEARCH_RESULTS_PER_PAGE = 10

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    session,
    redirect,
    url_for,
    send_from_directory,
)
import csv
import os
import json
import secrets
import sqlite3
from datetime import datetime
from functools import wraps
import pytz
import re
import requests

import google.generativeai as genai
from markupsafe import Markup, escape


import hashlib
import pandas as pd
from groq import Groq
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)


CSV_PATH = "data/input/paper_extracted.csv"
TRACKING_DB_PATH = "data/output/tracking.db"

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

def normalize_text(value):
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def make_paper_key(title, year, journal):
    base = f"{normalize_text(title).lower()}||{normalize_text(year).lower()}||{normalize_text(journal).lower()}"
    return hashlib.md5(base.encode("utf-8")).hexdigest()


def load_papers_df():
    df = pd.read_csv(CSV_PATH)
    df = df.fillna("")

    # critical: remove bad spaces/newlines from column names
    df.columns = [str(c).strip() for c in df.columns]

    required = ["title", "year", "journal"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"CSV must contain '{col}' column")

    df["title"] = df["title"].apply(normalize_text)
    df["year"] = df["year"].apply(normalize_text)
    df["journal"] = df["journal"].apply(normalize_text)

    df["paper_key"] = df.apply(
        lambda row: make_paper_key(row["title"], row["year"], row["journal"]),
        axis=1
    )

    return df
# @app.route("/api/admin/refresh-citations", methods=["POST"])
# def refresh_citations():
#     for paper in papers_data:
#         if paper.get("doi"):
#             paper["citations"] = fetch_citation_count(paper["doi"])
#     return jsonify({"success": True})

def get_db_connection():
    conn = sqlite3.connect(TRACKING_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_compare_summary_table():
    os.makedirs("data/output", exist_ok=True)

    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS compare_ai_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            combination_key TEXT NOT NULL UNIQUE,
            paper_keys_json TEXT NOT NULL,
            paper_titles_json TEXT NOT NULL,
            research_design_sample TEXT,
            measurement_analysis TEXT,
            findings TEXT,
            context TEXT,
            model_name TEXT,
            prompt_version TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_compare_summary_table()

def word_count(value):
    """Return word count for a given string value."""
    if not value:
        return 0
    if isinstance(value, (list, tuple)):
        return len(value)
    return len(str(value).split())


def truncate_words(value, limit=30):
    """Truncate text to a specific number of words, adding ellipsis when needed."""
    if not value:
        return ""
    words = str(value).split()
    if len(words) <= limit:
        return str(value)
    return " ".join(words[:limit]) + "..."


def extract_url(value):
    """Extract URL from citation text."""
    if not value:
        return ""
    url_pattern = r"https?://[^\s\)]+(?:\([^\)]*\))?"
    match = re.search(url_pattern, str(value))
    if match:
        return match.group(0).rstrip(".,;:")
    return ""


def highlight_terms_html(text, feature_key=None):
    """Escape HTML; ``!!bold!!`` segments from CSV render as <strong>.

    feature_key is ignored (kept so templates can keep using
    ``|highlight_keywords(feature_key)``).
    """
    _ = feature_key
    s = str(text) if text is not None else ""

    def esc_chunk(plain: str) -> str:
        return escape(plain)

    if "!!" in s:
        parts = s.split("!!")
        if len(parts) >= 2 and len(parts) % 2 == 1:
            fragments = []
            for i, p in enumerate(parts):
                inner = esc_chunk(p)
                if i % 2 == 1:
                    fragments.append("<strong>")
                    fragments.append(inner)
                    fragments.append("</strong>")
                else:
                    fragments.append(inner)
            return Markup("".join(fragments))

    return Markup(esc_chunk(s))


def highlight_keywords_filter(text, feature_key=None):
    return highlight_terms_html(text, feature_key)


app.jinja_env.filters["word_count"] = word_count
app.jinja_env.filters["truncate_words"] = truncate_words
app.jinja_env.filters["extract_url"] = extract_url
app.jinja_env.filters["highlight_keywords"] = highlight_keywords_filter

# Admin login: set ADMIN_USERNAME and ADMIN_PASSWORD in the environment (do not commit values).
ADMIN_USERNAME = (os.environ.get("ADMIN_USERNAME") or "").strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD") or ""

# Global variable to store papers data
papers_data = []
_papers_csv_mtime_when_loaded = None


def get_papers_csv_path():
    """Return the first existing papers CSV (same precedence as the loader)."""
    candidates = (
        DATA_DIR / "input" / "paper_extracted.csv",
        DATA_DIR / "input" / "papers_extracted.csv",
        DATA_DIR / "input" / "papers.csv",
    )
    for path in candidates:
        if path.is_file():
            return path
    return None


def reload_papers_from_csv_if_changed():
    """Reload papers_data from disk when the CSV file changes (mtime). Cheap no-op if unchanged."""
    global _papers_csv_mtime_when_loaded
    csv_path = get_papers_csv_path()
    if not csv_path:
        return
    try:
        mtime = csv_path.stat().st_mtime
    except OSError:
        return
    if (
        _papers_csv_mtime_when_loaded is not None
        and _papers_csv_mtime_when_loaded == mtime
        and papers_data
    ):
        return
    load_papers_from_csv()
    _papers_csv_mtime_when_loaded = mtime


def extract_doi(text):
    if not text:
        return None
    match = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", text, re.I)
    return match.group(0) if match else None


# def fetch_citation_count(doi):
#     if not doi:
#         return 0

#     url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"
#     params = {"fields": "citationCount"}

#     try:
#         r = requests.get(url, params=params, timeout=10)
#         if r.status_code == 200:
#             return r.json().get("citationCount", 0)
#     except Exception as e:
#         print(f"Citation fetch failed for {doi}: {e}")

#     return 0


def load_papers_from_csv():
    """Load papers data from CSV file."""
    global papers_data
    papers_data = []

    csv_path = get_papers_csv_path()
    if not csv_path:
        print(
            "Error: No CSV file found in data/input/. Please ensure a CSV file exists."
        )
        return []

    try:
        seen_keys = set()

        with open(csv_path, "r", encoding="utf-8") as file:
            reader = csv.DictReader(file)

            print(f"CSV columns found: {len(reader.fieldnames)}")
            print(f"First few columns: {reader.fieldnames[:5]}")

            for i, row in enumerate(reader, 1):
                if i == 1:
                    print(f"First row keys: {list(row.keys())[:5]}")
                    print(f"Title from first row: '{row.get('title', 'NOT_FOUND')}'")
                # Normalize CSV row keys
                normalized_row = {}
                for k, v in row.items():
                    clean_key = str(k).strip().replace('"', "")
                    normalized_row[clean_key] = v
                row = normalized_row
                title = (row.get("title") or "").strip()
                citation = (row.get("citation") or "").strip()
                abstract = (row.get("abstract") or "").strip()

                doi = extract_doi(citation)

                # Skip fully empty rows
                if not title and not citation and not abstract:
                    continue

                # Skip rows without meaningful title
                if not title or title.lower() in {"nan", "none"}:
                    continue

                # Deduplicate: prefer DOI, otherwise normalized title
                dedupe_key = (
                    doi.lower()
                    if doi
                    else re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()
                )
                if dedupe_key in seen_keys:
                    print(f"Skipping duplicate: {title}")
                    continue
                seen_keys.add(dedupe_key)

                #citation_count = fetch_citation_count(doi)
                paper_key = make_paper_key(title, row.get("year", ""), row.get("journal", ""))
                paper = {
                    "id": f"paper_{str(len(papers_data) + 1).zfill(3)}",
                    "paper_key": paper_key,
                    "title": title,
                    "title_verbatim": row.get("title_verbatim", ""),
                    "authors": [
                        author.strip()
                        for author in row.get("authors", "").split(";")
                        if author.strip()
                    ],
                    "authors_verbatim": row.get("authors_verbatim", ""),
                    "journal": row.get("journal", ""),
                    "journal_verbatim": row.get("journal_verbatim", ""),
                    "year": (
                        int(row.get("year", 2023))
                        if row.get("year", "").isdigit()
                        else 2023
                    ),
                    "citation": citation,
                    "doi": doi,
                    #"citations": citation_count,
                    "abstract": abstract,
                    "abstract_verbatim": row.get("abstract_verbatim", ""),
                    "ai_context_summary": row.get("ai_context_summary", ""),
                    "sample_size": (
                        int(row.get("sample_size", "0").replace(",", ""))
                        if row.get("sample_size", "").replace(",", "").isdigit()
                        else 0
                    ),
                    "countries": (
                        [row.get("country_region", "USA")]
                        if row.get("country_region")
                        and row.get("country_region") != "NOT SPECIFIED"
                        else ["USA"]
                    ),
                    "methodology": row.get("study_type", "Unknown"),
                    "research_type": "Experimental Research",
                    "impact_factor": 0,
                    "keywords": ["social media", "politics"],
                    "extracted_features": {
                        "independent_variables": row.get("independent_variables", ""),
                        "independent_variables_verbatim": row.get(
                            "independent_variables_verbatim", ""
                        ),
                        "dependent_variables": row.get("dependent_variables", ""),
                        "dependent_variables_verbatim": row.get(
                            "dependent_variables_verbatim", ""
                        ),
                        "survey_questions": row.get("survey_questions", ""),
                        "survey_questions_verbatim": row.get(
                            "survey_questions_verbatim", ""
                        ),
                        "incentive": row.get("incentive", ""),
                        "incentive_verbatim": row.get("incentive_verbatim", ""),
                        "study_type": row.get("study_type", ""),
                        "study_type_verbatim": row.get("study_type_verbatim", ""),
                        "analysis_equations": row.get("analysis_equations", ""),
                        "analysis_equations_verbatim": row.get(
                            "analysis_equations_verbatim", ""
                        ),
                        "level_of_analysis": row.get("level_of_analysis", ""),
                        "level_of_analysis_verbatim": row.get(
                            "level_of_analysis_verbatim", ""
                        ),
                        "main_effects": row.get("main_effects", ""),
                        "main_effects_verbatim": row.get("main_effects_verbatim", ""),
                        "statistical_power": row.get("statistical_power", ""),
                        "statistical_power_verbatim": row.get(
                            "statistical_power_verbatim", ""
                        ),
                        "moderators": row.get("moderators", ""),
                        "moderators_verbatim": row.get("moderators_verbatim", ""),
                        "moderation_results": row.get("moderation_results", ""),
                        "moderation_results_verbatim": row.get(
                            "moderation_results_verbatim", ""
                        ),
                        "demographics": row.get("demographics", ""),
                        "demographics_verbatim": row.get("demographics_verbatim", ""),
                        "recruitment_source": row.get("recruitment_source", ""),
                        "recruitment_source_verbatim": row.get(
                            "recruitment_source_verbatim", ""
                        ),
                        "sample_size": row.get("sample_size", ""),
                        "sample_size_verbatim": row.get("sample_size_verbatim", ""),
                        "country_region": row.get("country_region", ""),
                        "temporal_context": row.get("temporal_context", ""),
                        "gdp_per_capita_usd": row.get("gdp_per_capita_usd", ""),
                        "gini_coefficient": row.get("gini_coefficient", ""),
                        "income_group": row.get("income_group", ""),
                        "study_language": row.get("study_language", ""),
                        "platform_language_optimization": row.get(
                            "platform_language_optimization", ""
                        ),
                        "traditional_media_strength": row.get(
                            "traditional_media_strength", ""
                        ),
                        "electoral_proximity": row.get("electoral_proximity", ""),
                        "recommended_moderators": row.get("recommended_moderators", ""),
                        "research_context": row.get("research_context", ""),
                        "intervention_insights": row.get("intervention_insights", ""),
                        # Context / system metrics
                        "democracy": row.get("democracy", ""),
                        "press_freedom": row.get("press_freedom", ""),
                        "internet_freedom": row.get("internet_freedom", ""),
                        "internet_penetration": row.get("internet_penetration", ""),
                        "governance": row.get("governance", ""),
                        "polarization": row.get("polarization", ""),
                        "deliberative_democracy": row.get("polarization", ""),
                        "economic_performance": row.get("economic_performance", ""),
                        "election_period": row.get("election_period", ""),
                        "covid_period": row.get("covid_period", ""),
                        "high_salience_period": row.get("high_salience_period", ""),
                        "interpersonal_trust": row.get("interpersonal_trust", ""),

                        "ai_context_summary": row.get("ai_context_summary", ""),

                        # Population / internet / platform metrics
                        "population_million": row.get("population_million", ""),
                        "internet_users_million": row.get("internet_users_million", ""),
                        "social_media_users_million": row.get(
                            "social_media_users_million", ""
                        ),
                        "youtube_users_million": row.get("youtube_users_million", ""),
                        "facebook_users_million": row.get("facebook_users_million", ""),
                        "instagram_users_million": row.get(
                            "instagram_users_million", ""
                        ),
                        "x_users_million": row.get("x_users_million", ""),
                        "tiktok_users_million": row.get("tiktok_users_million", ""),
                        "linkedin_users_million": row.get("linkedin_users_million", ""),
                        "messenger_users_million": row.get(
                            "messenger_users_million", ""
                        ),
                        "snapchat_users_million": row.get("snapchat_users_million", ""),
                        "pinterest_users_million": row.get(
                            "pinterest_users_million", ""
                        ),
                    },
                }

                papers_data.append(paper)

        print(f"Successfully loaded {len(papers_data)} unique papers from CSV")
        if papers_data:
            print(f"First paper title: '{papers_data[0]['title']}'")
        return papers_data

    except Exception as e:
        print(f"Error loading CSV: {e}")
        import traceback

        traceback.print_exc()
        return []


# Fields merged into free-text search (Option 1: broaden search beyond title/abstract).
SEARCH_CONTEXT_FEATURE_KEYS = (
    "country_region",
    "income_group",
    "study_language",
    "platform_language_optimization",
    "traditional_media_strength",
    "electoral_proximity",
    "gdp_per_capita_usd",
    "gini_coefficient",
    "temporal_context",
    "demographics",
    "recruitment_source",
    "sample_size",
    "study_type",
    "ai_context_summary",
)

# Normalized lowercase tokens -> substrings often used in country_region / text (for US ↔ United States, etc.)
COUNTRY_TERM_ALIASES = {
    "us": (
        "united states",
        "united states of america",
        "u.s.",
        "u.s.a.",
        "u.s.a",
        "usa",
        "america",
        "american",
    ),
    "usa": ("united states", "u.s.", "usa", "american"),
    "u.s.": ("united states", "usa", "american"),
    "u.s.a.": ("united states", "usa"),
    "america": ("united states", "usa", "american"),
    "uk": (
        "united kingdom",
        "great britain",
        "britain",
        "u.k.",
        "england",
        "scotland",
        "wales",
        "northern ireland",
        "british",
    ),
    "u.k.": ("united kingdom", "great britain", "britain"),
    "britain": ("united kingdom", "great britain", "britain"),
    "england": ("england", "united kingdom", "british"),
    "scotland": ("scotland", "united kingdom"),
    "wales": ("wales", "united kingdom"),
    "eu": ("european union", "europe"),
    "uae": ("united arab emirates", "uae", "emirates"),
    "de": ("germany", "german", "deutsch"),
    "germany": ("germany", "german"),
    "fr": ("france", "french", "français"),
    "france": ("france", "french"),
    "es": ("spain", "spanish"),
    "spain": ("spain", "spanish"),
    "cn": ("china", "chinese", "mainland china"),
    "china": ("china", "chinese"),
    "jp": ("japan", "japanese"),
    "japan": ("japan", "japanese"),
    "kr": ("south korea", "korea", "korean", "republic of korea"),
    "korea": ("south korea", "korea", "korean"),
    "india": ("india", "indian"),
    "br": ("brazil", "brazilian"),
    "brazil": ("brazil", "brazilian"),
    "ca": ("canada", "canadian"),
    "canada": ("canada", "canadian"),
    "au": ("australia", "australian"),
    "australia": ("australia", "australian"),
    "nz": ("new zealand", "zealand"),
    "mx": ("mexico", "mexican"),
    "sg": ("singapore", "singaporean"),
    "nl": ("netherlands", "dutch", " holland"),
    "se": ("sweden", "swedish"),
    "norway": ("norway", "norwegian"),
    "dk": ("denmark", "danish"),
    "fi": ("finland", "finnish"),
    "ie": ("ireland", "irish"),
    "be": ("belgium", "belgian"),
    "at": ("austria", "austrian"),
    "ch": ("switzerland", "swiss"),
    "pt": ("portugal", "portuguese"),
    "it": ("italy", "italian"),
    "pl": ("poland", "polish"),
    "ru": ("russia", "russian"),
    "tr": ("turkey", "turkish"),
    "sa": ("saudi arabia", "saudi"),
    "eg": ("egypt", "egyptian"),
    "za": ("south africa",),
    "ar": ("argentina", "argentine"),
    "cl": ("chile", "chilean"),
    "tw": ("taiwan", "taiwanese"),
    "hk": ("hong kong", "hongkong"),
}

# Longest phrases first — collapse to canonical alias keys used in COUNTRY_TERM_ALIASES
# so "united states" matches like "us", not two independent tokens ("united" AND "states").
COUNTRY_MULTIWORD_PHRASES = (
    ("united states of america", "us"),
    ("united arab emirates", "uae"),
    ("great britain", "uk"),
    ("united kingdom", "uk"),
    ("united states", "us"),
    ("south korea", "kr"),
    ("new zealand", "nz"),
    ("south africa", "za"),
    ("saudi arabia", "sa"),
    ("hong kong", "hk"),
)


def _collapse_country_phrases(query: str) -> str:
    """Replace known multi-word country phrases with canonical tokens (same as typing US, UK, …)."""
    if not query or not str(query).strip():
        return ""
    q = " ".join(query.lower().split())
    for phrase, canon in COUNTRY_MULTIWORD_PHRASES:
        if canon not in COUNTRY_TERM_ALIASES:
            continue
        parts = phrase.split()
        if len(parts) < 2:
            continue
        escaped = r"\s+".join(re.escape(p) for p in parts)
        try:
            q = re.sub(r"(?i)\b" + escaped + r"\b", " " + canon + " ", q)
        except re.error:
            continue
        q = " ".join(q.split())
    return q


def _normalize_search_token(raw: str) -> str:
    return raw.strip().lower().strip(".,;:()\"'")


def _term_matches_haystack(term: str, haystack: str) -> bool:
    """Match one query token against lowercase haystack; supports country synonyms."""
    if not term:
        return True
    if term in COUNTRY_TERM_ALIASES:
        if any(phrase in haystack for phrase in COUNTRY_TERM_ALIASES[term]):
            return True
        try:
            if re.search(r"\b" + re.escape(term) + r"\b", haystack):
                return True
        except re.error:
            pass
        return False
    if len(term) <= 3:
        try:
            return bool(re.search(r"\b" + re.escape(term) + r"\b", haystack))
        except re.error:
            return term in haystack
    return term in haystack


def _paper_search_text_blob(paper):
    """Lowercase haystack for substring matching (title, abstract, authors, journal,
    countries list, and selected contextual extracted_features)."""
    extracted = paper.get("extracted_features") or {}
    parts = [
        paper.get("title") or "",
        paper.get("abstract") or "",
        " ".join(paper.get("authors") or []),
        paper.get("journal") or "",
        " ".join(str(c) for c in (paper.get("countries") or [])),
    ]
    for key in SEARCH_CONTEXT_FEATURE_KEYS:
        val = extracted.get(key, "")
        if val is not None and str(val).strip():
            parts.append(str(val))
    return " ".join(parts).lower()


def search_papers(query="", filters=None):
    """Search papers based on query and filters."""
    if filters is None:
        filters = {}

    results = papers_data.copy()

    # Text search — title, abstract, authors, journal, countries, + context-related fields
    if query:
        collapsed = _collapse_country_phrases(query)
        search_terms = [
            t for t in (_normalize_search_token(w) for w in collapsed.split()) if t
        ]
        results = [
            paper
            for paper in results
            if all(
                _term_matches_haystack(term, _paper_search_text_blob(paper))
                for term in search_terms
            )
        ]

    # Apply filters
    if filters.get("year_from"):
        results = [
            paper for paper in results if paper["year"] >= int(filters["year_from"])
        ]

    if filters.get("year_to"):
        results = [
            paper for paper in results if paper["year"] <= int(filters["year_to"])
        ]

    if filters.get("journal"):
        results = [
            paper
            for paper in results
            if filters["journal"].lower() == paper["journal"].lower()
        ]

    if filters.get("country"):
        results = [
            paper
            for paper in results
            if filters["country"].lower()
            in paper.get("extracted_features", {}).get("country_region", "").lower()
        ]

    # Sort by year (most recent first) by default
    results.sort(key=lambda x: x["year"], reverse=True)

    return results


def get_statistics():
    """Get platform statistics."""
    total_studies = sum(paper["sample_size"] for paper in papers_data)
    total_countries = len(
        set(country for paper in papers_data for country in paper["countries"])
    )
    methodologies = list(set(paper["methodology"] for paper in papers_data))
    journals = list(set(paper["journal"] for paper in papers_data))
    years = sorted(list(set(paper["year"] for paper in papers_data)), reverse=True)

    return {
        "totalPapers": len(papers_data),
        "totalStudies": total_studies,
        "totalCountries": total_countries,
        "methodologies": methodologies,
        "journals": journals,
        "years": years,
    }


# Routes
@app.route("/")
def index():
    """Home page."""
    stats = get_statistics()
    return render_template("index.html", stats=stats)


def _build_search_page_url(query, filters, page):
    """URL for search results including pagination (page 1 omits ``page`` param)."""
    params = []
    if query:
        params.append(("q", query))
    for key in ("year_from", "year_to", "journal", "country"):
        val = filters.get(key)
        if val:
            params.append((key, str(val)))
    if page > 1:
        params.append(("page", str(page)))
    qs = urlencode(params)
    return url_for("search") + ("?" + qs if qs else "")


@app.route("/search")
def search():
    """Search page."""
    query = request.args.get("q", "")
    year_from = request.args.get("year_from", "")
    year_to = request.args.get("year_to", "")
    journal = request.args.get("journal", "")
    country = request.args.get("country", "")

    filters = {
        "year_from": year_from,
        "year_to": year_to,
        "journal": journal,
        "country": country,
    }

    filters = {k: v for k, v in filters.items() if v}

    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1

    results_all = search_papers(query, filters)
    total_results = len(results_all)
    journals = sorted(list(set(p["journal"] for p in papers_data if p["journal"])))

    if total_results == 0:
        paginated_results = []
        total_pages = 0
        pagination = None
        page = 1
    else:
        total_pages = max(
            1, (total_results + SEARCH_RESULTS_PER_PAGE - 1) // SEARCH_RESULTS_PER_PAGE
        )
        page = min(page, total_pages)
        start = (page - 1) * SEARCH_RESULTS_PER_PAGE
        paginated_results = results_all[start : start + SEARCH_RESULTS_PER_PAGE]
        pagination = None
        if total_pages > 1:
            pagination = {
                "page": page,
                "total_pages": total_pages,
                "prev_url": (
                    _build_search_page_url(query, filters, page - 1)
                    if page > 1
                    else None
                ),
                "next_url": (
                    _build_search_page_url(query, filters, page + 1)
                    if page < total_pages
                    else None
                ),
                "pages": [
                    {
                        "num": n,
                        "url": _build_search_page_url(query, filters, n),
                        "active": n == page,
                    }
                    for n in range(1, total_pages + 1)
                ],
            }

    return render_template(
        "search.html",
        query=query,
        results=paginated_results,
        total_results=total_results,
        filters=filters,
        journals=journals,
        pagination=pagination,
    )


@app.route("/article/<paper_id>")
def article(paper_id):
    """Article details page."""
    paper = next((p for p in papers_data if p["id"] == paper_id), None)
    if not paper:
        return "Paper not found", 404

    return render_template("article.html", paper=paper)


@app.route("/compare")
def compare():
    """Compare page."""
    ids_param = request.args.get("ids", "")
    if ids_param:
        comparison_ids = ids_param.split(",")
    else:
        comparison_ids = []

    comparison_papers = [p for p in papers_data if p["id"] in comparison_ids]
    return render_template("compare.html", papers=comparison_papers)


@app.route("/profile")
def profile():
    """Profile page."""
    return render_template("profile.html")


@app.route("/database")
def database():
    """Database page listing all papers; data stays in sync with paper_extracted.csv on each request."""
    paper_count = len(papers_data)
    return render_template("database.html", papers=papers_data, paper_count=paper_count)


# API endpoints
@app.route("/api/papers")
def api_papers():
    """API endpoint to get all papers."""
    return jsonify(papers_data)


@app.route("/api/search")
def api_search():
    """API endpoint for search."""
    query = request.args.get("q", "")
    filters = {
        "year": request.args.get("year", ""),
        "journal": request.args.get("journal", ""),
        "methodology": request.args.get("methodology", ""),
        "country": request.args.get("country", ""),
        "sampleSize": request.args.get("sampleSize", ""),
        "sortBy": request.args.get("sortBy", "relevance"),
    }

    filters = {k: v for k, v in filters.items() if v}
    results = search_papers(query, filters)
    return jsonify(results)


@app.route("/api/paper/<paper_id>")
def api_paper(paper_id):
    """API endpoint to get a specific paper."""
    paper = next((p for p in papers_data if p["id"] == paper_id), None)
    if not paper:
        return jsonify({"error": "Paper not found"}), 404

    return jsonify(paper)


@app.route("/api/statistics")
def api_statistics():
    """API endpoint to get statistics."""
    return jsonify(get_statistics())


# Database helper functions
# def get_db_connection():
#     """Get database connection."""
#     db_path = os.path.join("data", "output", "tracking.db")
#     conn = sqlite3.connect(db_path)
#     conn.row_factory = sqlite3.Row
#     return conn


def get_eastern_time():
    """Get current time in US Eastern timezone."""
    eastern = pytz.timezone("US/Eastern")
    return datetime.now(eastern).strftime("%Y-%m-%d %H:%M:%S")


def require_admin(f):
    """Decorator to require admin authentication."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("is_admin"):
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)

    return decorated_function


# Tracking functions
@app.route("/api/track/search", methods=["POST"])
def track_search():
    """Track a search query."""
    try:
        data = request.json or {}
        search_query = data.get("search_query", "")
        filters_used = json.dumps(data.get("filters_used", {}))
        num_results = data.get("num_results", 0)
        user_session = session.get("user_id", "anonymous")
        timestamp = get_eastern_time()

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO search_logs (timestamp, search_query, filters_used, num_results, user_session)
            VALUES (?, ?, ?, ?, ?)
            """,
            (timestamp, search_query, filters_used, num_results, user_session),
        )
        conn.commit()
        conn.close()

        return jsonify({"success": True, "message": "Search tracked"})
    except Exception as e:
        print(f"Error tracking search: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/track/compare_view", methods=["POST"])
def track_compare_view():
    """Track a comparison page view."""
    try:
        data = request.json or {}
        paper_ids = data.get("paper_ids", [])
        user_session = session.get("user_id", "anonymous")
        timestamp = get_eastern_time()

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO compare_view_logs (timestamp, paper_ids, num_papers, user_session)
            VALUES (?, ?, ?, ?)
            """,
            (timestamp, json.dumps(paper_ids), len(paper_ids), user_session),
        )
        conn.commit()
        conn.close()

        return jsonify({"success": True, "message": "Compare view tracked"})
    except Exception as e:
        print(f"Error tracking compare view: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/track/download", methods=["POST"])
def track_download():
    """Track a comparison download."""
    try:
        data = request.json or {}
        paper_ids = data.get("paper_ids", [])
        user_session = session.get("user_id", "anonymous")
        timestamp = get_eastern_time()

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO download_logs (timestamp, paper_ids, num_papers, user_session)
            VALUES (?, ?, ?, ?)
            """,
            (timestamp, json.dumps(paper_ids), len(paper_ids), user_session),
        )
        conn.commit()
        conn.close()

        return jsonify({"success": True, "message": "Download tracked"})
    except Exception as e:
        print(f"Error tracking download: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/tracking/stats")
def get_tracking_stats():
    """Get tracking statistics (public endpoint for Profile page)."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) as count FROM compare_view_logs")
        total_visits = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(*) as count FROM download_logs")
        total_downloads = cursor.fetchone()["count"]

        conn.close()

        return jsonify(
            {
                "total_visits": total_visits,
                "total_downloads": total_downloads,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Admin routes
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    """Admin login page."""
    if request.method == "POST":
        if not ADMIN_USERNAME or not ADMIN_PASSWORD:
            return render_template(
                "admin_login.html",
                error="Admin login is not configured on this server.",
            )
        username = request.form.get("username")
        password = request.form.get("password")

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["is_admin"] = True
            session["user_id"] = "admin"
            return redirect(url_for("admin_dashboard"))
        else:
            return render_template("admin_login.html", error="Invalid credentials")

    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    """Admin logout."""
    session.pop("is_admin", None)
    session.pop("user_id", None)
    return redirect(url_for("index"))


@app.route("/admin/dashboard")
@require_admin
def admin_dashboard():
    """Admin dashboard page."""
    return render_template("admin_dashboard.html")


@app.route("/admin/requests")
@require_admin
def admin_requests():
    """Admin requests review page."""
    return render_template("admin_requests.html")


@app.route("/api/admin/search_logs")
@require_admin
def get_search_logs():
    """Get search logs for admin."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM search_logs
            ORDER BY timestamp DESC
            LIMIT 1000
        """
        )
        logs = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return jsonify(logs)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/compare_view_logs")
@require_admin
def get_compare_view_logs():
    """Get compare view logs for admin."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM compare_view_logs
            ORDER BY timestamp DESC
            LIMIT 1000
        """
        )
        logs = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return jsonify(logs)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/download_logs")
@require_admin
def get_download_logs():
    """Get download logs for admin."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM download_logs
            ORDER BY timestamp DESC
            LIMIT 1000
        """
        )
        logs = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return jsonify(logs)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/stats")
@require_admin
def get_admin_stats():
    """Get statistics for admin dashboard."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) as count FROM search_logs")
        total_searches = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(*) as count FROM compare_view_logs")
        total_compares = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(*) as count FROM download_logs")
        total_downloads = cursor.fetchone()["count"]

        cursor.execute(
            """
            SELECT COUNT(*) as count FROM search_logs
            WHERE timestamp >= datetime('now', '-7 days')
        """
        )
        recent_searches = cursor.fetchone()["count"]

        cursor.execute(
            """
            SELECT COUNT(*) as count FROM compare_view_logs
            WHERE timestamp >= datetime('now', '-7 days')
        """
        )
        recent_compares = cursor.fetchone()["count"]

        cursor.execute(
            """
            SELECT COUNT(*) as count FROM download_logs
            WHERE timestamp >= datetime('now', '-7 days')
        """
        )
        recent_downloads = cursor.fetchone()["count"]

        cursor.execute(
            """
            SELECT search_query, COUNT(*) as count
            FROM search_logs
            WHERE search_query != ''
            GROUP BY search_query
            ORDER BY count DESC
            LIMIT 10
        """
        )
        top_searches = [dict(row) for row in cursor.fetchall()]

        conn.close()

        return jsonify(
            {
                "total_searches": total_searches,
                "total_compares": total_compares,
                "total_downloads": total_downloads,
                "recent_searches": recent_searches,
                "recent_compares": recent_compares,
                "recent_downloads": recent_downloads,
                "top_searches": top_searches,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/uploads/<filename>")
@require_admin
def download_upload(filename):
    """Serve uploaded PDF files (admin only)."""
    upload_dir = os.path.join("data", "user_uploads")
    return send_from_directory(upload_dir, filename, as_attachment=True)


@app.route("/api/upload-request", methods=["POST"])
def upload_request():
    """Handle paper upload requests."""
    try:
        request_name = request.form.get("requestName")
        institution = request.form.get("institution")
        email = request.form.get("email")
        paper_info = request.form.get("paperInfo")
        change_requests = request.form.get("changeRequests", "")

        pdf_file = request.files.get("pdfFile")
        pdf_filename = None
        if pdf_file and pdf_file.filename:
            upload_dir = os.path.join("data", "user_uploads")
            os.makedirs(upload_dir, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pdf_filename = f"upload_{timestamp}_{pdf_file.filename}"
            pdf_path = os.path.join(upload_dir, pdf_filename)
            pdf_file.save(pdf_path)

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO upload_requests
            (timestamp, request_name, institution, email, paper_info, change_requests, pdf_filename)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                get_eastern_time(),
                request_name,
                institution,
                email,
                paper_info,
                change_requests,
                pdf_filename,
            ),
        )

        conn.commit()
        conn.close()

        return jsonify(
            {"success": True, "message": "Upload request submitted successfully"}
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/admin/requests")
@require_admin
def get_admin_requests():
    """Get all upload requests for admin review."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, timestamp, request_name, institution, email, paper_info,
                   change_requests, pdf_filename, status
            FROM upload_requests
            ORDER BY timestamp DESC
        """
        )

        requests = []
        for row in cursor.fetchall():
            requests.append(
                {
                    "id": row[0],
                    "timestamp": row[1],
                    "request_name": row[2],
                    "institution": row[3],
                    "email": row[4],
                    "paper_info": row[5],
                    "change_requests": row[6],
                    "pdf_filename": row[7],
                    "status": row[8],
                }
            )

        conn.close()
        return jsonify({"requests": requests})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/requests/<int:request_id>/status", methods=["POST"])
@require_admin
def update_request_status(request_id):
    """Update request status (approve/reject)."""
    try:
        data = request.get_json()
        new_status = data.get("status")

        if new_status not in ["pending", "approved", "rejected"]:
            return jsonify({"error": "Invalid status"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            "UPDATE upload_requests SET status = ? WHERE id = ?",
            (new_status, request_id),
        )

        conn.commit()
        conn.close()

        return jsonify(
            {"success": True, "message": f"Request {new_status} successfully"}
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500

CATEGORY_FIELDS = {
    "Research Design & Sample": [
        "paper_key",
        "title",
        "study_type",
        "sample_size",
        "country_region",
        "recruitment_source",
        "demographics",
        "incentive"
    ],
    "Measurement & Analysis": [
        "paper_key",
        "title",
        "independent_variables",
        "dependent_variables",
        "survey_questions",
        "analysis_equations",
        "level_of_analysis"
    ],
    "Findings": [
        "paper_key",
        "title",
        "main_effects",
        "moderators",
        "moderation_results",
        "statistical_power"
    ],
    "Context": [
        "paper_key",
        "title",
        "temporal_context",
        "democracy",
        "press_freedom",
        "internet_freedom",
        "internet_penetration",
        "governance",
        "polarization",
        "ai_context_summary"
    ]
}

def clean_value(value, max_len=600):
    value = normalize_text(value)
    if len(value) > max_len:
        value = value[:max_len].rsplit(" ", 1)[0] + "..."
    return value


def build_category_payload(selected_rows, category_name):
    fields = CATEGORY_FIELDS[category_name]
    papers = []

    for _, row in selected_rows.iterrows():
        item = {}
        for field in fields:
            item[field] = clean_value(row.get(field, ""))
        papers.append(item)

    return papers


def make_combination_key(paper_keys):
    normalized = sorted(str(k).strip() for k in paper_keys)
    return "|".join(normalized)

def get_cached_compare_summary(paper_keys):
    combination_key = make_combination_key(paper_keys)

    conn = get_db_connection()
    row = conn.execute("""
        SELECT *
        FROM compare_ai_summaries
        WHERE combination_key = ?
    """, (combination_key,)).fetchone()
    conn.close()

    if not row:
        return None

    return {
        "paper_keys": json.loads(row["paper_keys_json"]),
        "paper_titles": json.loads(row["paper_titles_json"]),
        "results": {
            "Research Design & Sample": json.loads(row["research_design_sample"]) if row["research_design_sample"] else None,
            "Measurement & Analysis": json.loads(row["measurement_analysis"]) if row["measurement_analysis"] else None,
            "Findings": json.loads(row["findings"]) if row["findings"] else None,
            "Context": json.loads(row["context"]) if row["context"] else None,
        },
        "source": "cache"
    }


def save_compare_summary(paper_keys, paper_titles, results, model_name="llama-3.3-70b-versatile", prompt_version="v1"):
    combination_key = make_combination_key(paper_keys)

    conn = get_db_connection()
    conn.execute("""
        INSERT OR REPLACE INTO compare_ai_summaries (
            combination_key,
            paper_keys_json,
            paper_titles_json,
            research_design_sample,
            measurement_analysis,
            findings,
            context,
            model_name,
            prompt_version
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        combination_key,
        json.dumps(sorted(str(k).strip() for k in paper_keys)),
        json.dumps(paper_titles),
        json.dumps(results.get("Research Design & Sample")),
        json.dumps(results.get("Measurement & Analysis")),
        json.dumps(results.get("Findings")),
        json.dumps(results.get("Context")),
        model_name,
        prompt_version
    ))
    conn.commit()
    conn.close()

def build_prompt(category_name, papers_payload):
    return f"""
You are helping a researcher synthesize what a set of deactivation experiments, taken together, do and do not establish. Using the full study data provided, write a three-part synthesis:

"Held constant": What core features are shared across all or most studies?
"Varies": What differs meaningfully across studies? For each difference, name the theoretically meaningful dimension it reflects and cite specific values from the data — not surface features like "different countries" but what that difference theoretically represents. Prioritize: (1) politically/socially salient context, (2) country/political culture, (3) platform algorithmic context, (4) internet/social media penetration, (5) deactivation duration, (6) compliance verification, (7) outcome construct, (8) analytical method.
"What this leaves open": One genuinely open question — not a suggestion — that follows directly from what varies and what is held constant.
Word limits: held_constant 50, varies 100, what_this_leaves_open 40.

Rules: Use only the provided data. Name theoretical dimensions, not surface features. Plain prose, no bullets.

Return valid JSON only, no markdown fences:
{{"held_constant": "...", "varies": "...", "what_this_leaves_open": "..."}}

Study data:
{json.dumps(papers_payload, ensure_ascii=False, indent=2)}
""".strip()

# def call_groq_for_category(category_name, papers_payload):
#     prompt = build_prompt(category_name, papers_payload)

#     completion = client.chat.completions.create(
#         model="llama-3.3-70b-versatile",
#         messages=[
#             {
#                 "role": "system",
#                 "content": "You are a careful research comparison assistant. Return valid JSON only."
#             },
#             {
#                 "role": "user",
#                 "content": prompt
#             }
#         ],
#         temperature=0.2
#     )

#     text = completion.choices[0].message.content.strip()
#     text = re.sub(r"^```json\s*", "", text)
#     text = re.sub(r"^```\s*", "", text)
#     text = re.sub(r"\s*```$", "", text)

#     try:
#         return json.loads(text)
#     except json.JSONDecodeError:
#         return {
#             "held_constant": "",
#             "varies": "",
#             "what_this_leaves_open": "",
#             "error": "AI synthesis unavailable",
#             "raw_response": text
#         }


def call_gemini_for_category(category_name, papers_payload):
    prompt = build_prompt(category_name, papers_payload)

    model = genai.GenerativeModel("gemini-3-flash-preview")

    response = model.generate_content(
        prompt,
        generation_config={
            "temperature": 0.2,
        }
    )

    text = response.text.strip()

    # Clean JSON (Gemini often wraps in ```json)
    import re
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "category": category_name,
            "comparison": "AI comparison unavailable",
            "raw_response": text
        }

@app.route("/api/compare-ai-differences", methods=["POST"])
def compare_ai_differences():
    try:
        data = request.get_json(force=True)
        paper_keys = data.get("paper_keys", [])

        if not isinstance(paper_keys, list) or not paper_keys:
            return jsonify({"error": "paper_keys must be a non-empty list"}), 400

        if len(paper_keys) > 5:
            return jsonify({"error": "Maximum of 5 papers allowed"}), 400

        paper_keys = [str(k).strip() for k in paper_keys]

        cached = get_cached_compare_summary(paper_keys)
        if cached:
            return jsonify(cached)

        df = load_papers_df()
        selected_rows = df[df["paper_key"].isin(paper_keys)].copy()

        if selected_rows.empty:
            return jsonify({"error": "No matching papers found"}), 404

        selected_rows["__order"] = selected_rows["paper_key"].apply(lambda x: paper_keys.index(x))
        selected_rows = selected_rows.sort_values("__order").drop(columns="__order")

        results = {}
        from concurrent.futures import ThreadPoolExecutor

        def process_category(category_name):
            payload = build_category_payload(selected_rows, category_name)
            return category_name, call_gemini_for_category(category_name, payload)
            #return category_name, call_groq_for_category(category_name, payload)

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(process_category, c) for c in CATEGORY_FIELDS]

            for future in futures:
                category_name, result = future.result()
                results[category_name] = result

        paper_titles = selected_rows["title"].tolist()
        save_compare_summary(paper_keys, paper_titles, results)

        return jsonify({
            "paper_keys": paper_keys,
            "paper_titles": paper_titles,
            "results": results,
            "source": "generated"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.before_request
def sync_papers_data_with_csv():
    """Keep in-memory papers in sync with the CSV on disk when the file's modification time changes."""
    if request.endpoint in ("static", None):
        return
    reload_papers_from_csv_if_changed()


reload_papers_from_csv_if_changed()

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5001)