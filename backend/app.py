"""
Academic Research Information Management System - Backend
Dr. Md Yeasin, Scientist, ICAR-IASRI

Run:
    pip install -r requirements.txt
    python app.py

Everything runs from ONE server, ONE port, ONE terminal:
    http://localhost:5000        -> the web app (frontend)
    http://localhost:5000/api/*  -> the API (backend)
"""
import os
import shutil
import re
import json
import sqlite3
import random
import string
import time
import threading
import uuid
from functools import wraps

from flask import Flask, request, jsonify, g, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS

try:
    import bibtexparser
except ImportError:
    bibtexparser = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "research.db")
SEED_PATH = os.path.join(BASE_DIR, "papers_seed.json")
RANJIT_SEED_PATH = os.path.join(BASE_DIR, "ranjit_papers_seed.json")
FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
CORS(app)


@app.errorhandler(403)
def handle_403(e):
    return jsonify({"error": e.description or "Forbidden."}), 403


@app.route("/")
def serve_index():
    return send_from_directory(FRONTEND_DIR, "index.html")


# ---------------------------------------------------------------------------
# Admin credentials (for testing). In production, store a hashed password
# and move this to environment variables / a proper user table.
# ---------------------------------------------------------------------------
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "borapushkar1999@gmail.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Pushkar@123")

# In-memory OTP + session store (swap for Redis/DB in production)
# Sessions and OTP codes now live in the database (sessions / otp_codes
# tables) instead of in-memory dicts — this matters because free hosting
# tiers like Render spin the server down after inactivity and restart it
# on the next request, which would silently wipe any in-memory state and
# log everyone out mid-session.
OTP_TTL_SECONDS = 300      # 5 minutes
SESSION_TTL_SECONDS = 3600  # 1 hour

# Tracks background JCR-upload jobs: job_id -> {"status": ..., "message": ...}.
# In-memory is fine here (unlike sessions) — if the server restarts mid-job,
# the admin just re-uploads; nothing sensitive or hard to redo is lost.
JCR_JOBS = {}


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        # timeout=30: if the DB is briefly locked (e.g. a background job like
        # the JCR upload is mid-write), retry for up to 30s instead of
        # immediately raising "database is locked".
        db = g._database = sqlite3.connect(DB_PATH, timeout=30)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_db(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS scientists (
    scientist_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    slug              TEXT UNIQUE,
    name              TEXT,
    designation       TEXT,
    institute         TEXT,
    address           TEXT,
    dob               TEXT,
    mobile            TEXT DEFAULT '[]',
    email             TEXT DEFAULT '[]',
    research_interest TEXT DEFAULT '',
    education         TEXT DEFAULT '[]',
    accolades         TEXT DEFAULT '[]',
    employment        TEXT DEFAULT '[]',
    other_records     TEXT DEFAULT '[]',
    photo_filename    TEXT DEFAULT 'yeasin-photo.png',
    scholar_url       TEXT DEFAULT '',
    linkedin_url      TEXT DEFAULT '',
    login_email       TEXT DEFAULT '',
    login_password_hash TEXT DEFAULT '',
    current_work      TEXT DEFAULT '[]',
    created_at        TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS papers (
    publication_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    scientist_id         INTEGER DEFAULT 1,
    complete_reference   TEXT,
    title                TEXT,
    authors              TEXT,
    author_position      TEXT,
    year                 TEXT,
    journal              TEXT,
    publisher            TEXT,
    issn                 TEXT,
    doi                  TEXT,
    article_type         TEXT,
    impact_factor        TEXT,
    quartile              TEXT,
    domain               TEXT,
    field                TEXT DEFAULT '',
    hidden               INTEGER DEFAULT 0,
    abstract             TEXT DEFAULT '',
    keywords             TEXT DEFAULT '',
    naas_score           TEXT DEFAULT '',
    selected             INTEGER DEFAULT 0,
    cv_included          INTEGER DEFAULT 1,
    created_at           TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS awards (
    award_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    scientist_id  INTEGER DEFAULT 1,
    title         TEXT,
    awarding_body TEXT,
    year          TEXT,
    description   TEXT DEFAULT '',
    hidden        INTEGER DEFAULT 0,
    cv_included   INTEGER DEFAULT 1,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS projects (
    project_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    scientist_id    INTEGER DEFAULT 1,
    sl_no           TEXT,
    investigators   TEXT,
    project_title   TEXT,
    funding_agency  TEXT,
    date_start      TEXT,
    date_end        TEXT DEFAULT '',
    status          TEXT,
    hidden          INTEGER DEFAULT 0,
    cv_included     INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS book_chapters (
    book_chapter_id INTEGER PRIMARY KEY AUTOINCREMENT,
    scientist_id    INTEGER DEFAULT 1,
    title           TEXT,
    authors         TEXT,
    editor          TEXT DEFAULT '',
    book_title      TEXT,
    publisher       TEXT,
    year            TEXT,
    pages           TEXT,
    isbn            TEXT,
    doi             TEXT DEFAULT '',
    hidden          INTEGER DEFAULT 0,
    cv_included     INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS software (
    software_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    scientist_id INTEGER DEFAULT 1,
    package_name TEXT,
    reference    TEXT,
    year         TEXT,
    downloads    TEXT DEFAULT '',
    cran_url     TEXT DEFAULT '',
    hidden       INTEGER DEFAULT 0,
    cv_included  INTEGER DEFAULT 1,
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS courses_taught (
    course_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    scientist_id INTEGER DEFAULT 1,
    sl_no        TEXT,
    course_name  TEXT,
    hidden       INTEGER DEFAULT 0,
    cv_included  INTEGER DEFAULT 1,
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS students_guided (
    student_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    scientist_id INTEGER DEFAULT 1,
    name         TEXT,
    student_type TEXT DEFAULT '',
    start_date   TEXT,
    end_date     TEXT,
    description  TEXT DEFAULT '',
    hidden       INTEGER DEFAULT 0,
    cv_included  INTEGER DEFAULT 1,
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS technology (
    tech_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    scientist_id INTEGER DEFAULT 1,
    category     TEXT DEFAULT 'Technology',
    authors      TEXT,
    year         TEXT,
    title        TEXT,
    id_number    TEXT,
    hidden       INTEGER DEFAULT 0,
    cv_included  INTEGER DEFAULT 1,
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS popular_articles (
    article_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    scientist_id INTEGER DEFAULT 1,
    authors      TEXT,
    year         TEXT,
    title        TEXT,
    publication  TEXT,
    details      TEXT DEFAULT '',
    hidden       INTEGER DEFAULT 0,
    cv_included  INTEGER DEFAULT 1,
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS policy_papers (
    paper_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    scientist_id INTEGER DEFAULT 1,
    authors      TEXT,
    year         TEXT,
    title        TEXT,
    publisher    TEXT DEFAULT '',
    id_number    TEXT DEFAULT '',
    hidden       INTEGER DEFAULT 0,
    cv_included  INTEGER DEFAULT 1,
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS manuals (
    manual_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    scientist_id INTEGER DEFAULT 1,
    authors      TEXT,
    year         TEXT,
    title        TEXT,
    publisher    TEXT DEFAULT '',
    hidden       INTEGER DEFAULT 0,
    cv_included  INTEGER DEFAULT 1,
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS research_team (
    member_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    scientist_id  INTEGER DEFAULT 1,
    sort_order    INTEGER DEFAULT 0,
    name          TEXT,
    designation   TEXT DEFAULT '',
    photo_filename TEXT DEFAULT '',
    hidden        INTEGER DEFAULT 0,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS journal_scores (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    journal_name   TEXT UNIQUE,
    issn           TEXT DEFAULT '',
    jid            TEXT DEFAULT '',
    impact_factor  TEXT DEFAULT '',
    naas_score     TEXT DEFAULT '',
    quartile       TEXT DEFAULT '',
    year_updated   TEXT DEFAULT '',
    updated_at     TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    token   TEXT PRIMARY KEY,
    email   TEXT,
    expires REAL,
    role    TEXT DEFAULT 'super_admin',
    scoped_scientist_id INTEGER
);

CREATE TABLE IF NOT EXISTS otp_codes (
    email   TEXT PRIMARY KEY,
    otp     TEXT,
    expires REAL,
    role    TEXT DEFAULT 'super_admin',
    scoped_scientist_id INTEGER
);

CREATE TABLE IF NOT EXISTS profile_layout (
    scientist_id INTEGER PRIMARY KEY,
    config       TEXT DEFAULT '{}'
);
"""


def migrate_db(conn):
    """Add new columns to an existing database without losing data."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(papers)")}
    if "abstract" not in existing:
        conn.execute("ALTER TABLE papers ADD COLUMN abstract TEXT DEFAULT ''")
    if "keywords" not in existing:
        conn.execute("ALTER TABLE papers ADD COLUMN keywords TEXT DEFAULT ''")
    if "field" not in existing:
        conn.execute("ALTER TABLE papers ADD COLUMN field TEXT DEFAULT ''")
    if "hidden" not in existing:
        conn.execute("ALTER TABLE papers ADD COLUMN hidden INTEGER DEFAULT 0")
    conn.commit()

    # Backfill "field" for any paper that predates this column (e.g. a
    # research.db from before this feature existed) using its existing
    # "domain" value, so old data doesn't sit blank after an upgrade.
    blank_field_rows = conn.execute(
        "SELECT publication_id, domain FROM papers WHERE field IS NULL OR field = ''"
    ).fetchall()
    for pub_id, domain in blank_field_rows:
        domains = [d.strip() for d in (domain or "").split(",") if d.strip()]
        field = classify_field(domains)
        conn.execute("UPDATE papers SET field = ? WHERE publication_id = ?", (field, pub_id))
    if blank_field_rows:
        conn.commit()

    # Add "hidden" to the four simple record tables too, for older databases.
    for table in ("awards", "projects", "book_chapters", "software"):
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if "hidden" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN hidden INTEGER DEFAULT 0")
    conn.commit()

    book_chapter_cols = {row[1] for row in conn.execute("PRAGMA table_info(book_chapters)")}
    if "doi" not in book_chapter_cols:
        conn.execute("ALTER TABLE book_chapters ADD COLUMN doi TEXT DEFAULT ''")
    conn.commit()

    if "naas_score" not in existing:
        conn.execute("ALTER TABLE papers ADD COLUMN naas_score TEXT DEFAULT ''")
    conn.commit()

    if "selected" not in existing:
        conn.execute("ALTER TABLE papers ADD COLUMN selected INTEGER DEFAULT 0")
    conn.commit()

    if "cv_included" not in existing:
        conn.execute("ALTER TABLE papers ADD COLUMN cv_included INTEGER DEFAULT 1")
    conn.commit()

    proj_cols = {row[1] for row in conn.execute("PRAGMA table_info(projects)")}
    if "date_end" not in proj_cols:
        conn.execute("ALTER TABLE projects ADD COLUMN date_end TEXT DEFAULT ''")
    conn.commit()

    bc_cols = {row[1] for row in conn.execute("PRAGMA table_info(book_chapters)")}
    if "editor" not in bc_cols:
        conn.execute("ALTER TABLE book_chapters ADD COLUMN editor TEXT DEFAULT ''")
    conn.commit()

    # cv_included on every simple-CRUD record table (awards, projects,
    # book_chapters, software, courses_taught, students_guided, technology)
    for _tbl in ("awards", "projects", "book_chapters", "software", "courses_taught", "students_guided", "technology",
                 "popular_articles", "policy_papers", "manuals"):
        _cols = {row[1] for row in conn.execute(f"PRAGMA table_info({_tbl})")}
        if "cv_included" not in _cols:
            conn.execute(f"ALTER TABLE {_tbl} ADD COLUMN cv_included INTEGER DEFAULT 1")
    conn.commit()

    sg_cols = {row[1] for row in conn.execute("PRAGMA table_info(students_guided)")}
    if "student_type" not in sg_cols:
        conn.execute("ALTER TABLE students_guided ADD COLUMN student_type TEXT DEFAULT ''")
    conn.commit()

    sci_cols = {row[1] for row in conn.execute("PRAGMA table_info(scientists)")}
    if "scholar_url" not in sci_cols:
        conn.execute("ALTER TABLE scientists ADD COLUMN scholar_url TEXT DEFAULT ''")
    if "linkedin_url" not in sci_cols:
        conn.execute("ALTER TABLE scientists ADD COLUMN linkedin_url TEXT DEFAULT ''")
    if "login_email" not in sci_cols:
        conn.execute("ALTER TABLE scientists ADD COLUMN login_email TEXT DEFAULT ''")
    if "login_password_hash" not in sci_cols:
        conn.execute("ALTER TABLE scientists ADD COLUMN login_password_hash TEXT DEFAULT ''")
    if "current_work" not in sci_cols:
        conn.execute("ALTER TABLE scientists ADD COLUMN current_work TEXT DEFAULT '[]'")
    conn.commit()

    # research_interest used to be a single paragraph of plain text; convert
    # any row still in that old format into a one-item JSON array (a single
    # bullet), so it now displays and edits the same way as Education/
    # Accolades/etc instead of crashing the JSON parse on read.
    for row in conn.execute("SELECT scientist_id, research_interest FROM scientists WHERE research_interest != ''"):
        val = row["research_interest"]
        try:
            json.loads(val)
        except (json.JSONDecodeError, TypeError):
            conn.execute(
                "UPDATE scientists SET research_interest = ? WHERE scientist_id = ?",
                (json.dumps([val]), row["scientist_id"]),
            )
    conn.commit()

    sess_cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
    if "role" not in sess_cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN role TEXT DEFAULT 'super_admin'")
    if "scoped_scientist_id" not in sess_cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN scoped_scientist_id INTEGER")
    conn.commit()

    otp_cols = {row[1] for row in conn.execute("PRAGMA table_info(otp_codes)")}
    if "role" not in otp_cols:
        conn.execute("ALTER TABLE otp_codes ADD COLUMN role TEXT DEFAULT 'super_admin'")
    if "scoped_scientist_id" not in otp_cols:
        conn.execute("ALTER TABLE otp_codes ADD COLUMN scoped_scientist_id INTEGER")
    conn.commit()

    js_cols = {row[1] for row in conn.execute("PRAGMA table_info(journal_scores)")}
    if "issn" not in js_cols:
        conn.execute("ALTER TABLE journal_scores ADD COLUMN issn TEXT DEFAULT ''")
    conn.commit()

    # scientist_id on every content table, for multi-profile support. Existing
    # rows default to 1 (the original/first scientist), so nothing already in
    # the database gets orphaned or reassigned.
    for _tbl in ("papers", "awards", "projects", "book_chapters", "software",
                 "courses_taught", "students_guided", "technology"):
        _cols = {row[1] for row in conn.execute(f"PRAGMA table_info({_tbl})")}
        if "scientist_id" not in _cols:
            conn.execute(f"ALTER TABLE {_tbl} ADD COLUMN scientist_id INTEGER DEFAULT 1")
    conn.commit()

    # profile_layout used to be a single fixed row (id=1). Rebuild it as a
    # per-scientist table, carrying over any existing saved layout to
    # scientist_id=1 so nothing already configured is lost.
    pl_cols = {row[1] for row in conn.execute("PRAGMA table_info(profile_layout)")}
    if "scientist_id" not in pl_cols:
        old_row = conn.execute("SELECT config FROM profile_layout WHERE id = 1").fetchone() if "id" in pl_cols else None
        conn.execute("DROP TABLE profile_layout")
        conn.execute("CREATE TABLE profile_layout (scientist_id INTEGER PRIMARY KEY, config TEXT DEFAULT '{}')")
        if old_row:
            conn.execute("INSERT INTO profile_layout (scientist_id, config) VALUES (1, ?)", (old_row["config"],))
    conn.commit()


PROJECTS_SEED_PATH = os.path.join(BASE_DIR, "projects_seed.json")
SOFTWARE_SEED_PATH = os.path.join(BASE_DIR, "software_seed.json")
AWARDS_SEED_PATH = os.path.join(BASE_DIR, "awards_seed.json")
BOOK_CHAPTERS_SEED_PATH = os.path.join(BASE_DIR, "book_chapters_seed.json")
COURSES_TAUGHT_SEED_PATH = os.path.join(BASE_DIR, "courses_taught_seed.json")
STUDENTS_GUIDED_SEED_PATH = os.path.join(BASE_DIR, "students_guided_seed.json")
TECHNOLOGY_SEED_PATH = os.path.join(BASE_DIR, "technology_seed.json")


DB_BACKUP_PATH = os.path.join(BASE_DIR, "research_backup.db")


def init_db(force_reseed=False):
    fresh = not os.path.exists(DB_PATH)

    restored_from_backup = fresh and os.path.exists(DB_BACKUP_PATH)
    if restored_from_backup:
        shutil.copyfile(DB_BACKUP_PATH, DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # supports both row[0] and row["col"] access
    # WAL mode lets read requests (like the status-polling endpoint) proceed
    # while a background job (like the JCR upload) is mid-write, instead of
    # blocking and risking "database is locked" — this setting is stored in
    # the database file itself, so it only needs to be set once, but it's
    # harmless/idempotent to run on every startup.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    migrate_db(conn)  # safe no-op if columns already exist

    # ---- Seed the scientists table (profiles) if empty ----
    sci_count = conn.execute("SELECT COUNT(*) FROM scientists").fetchone()[0]
    if sci_count == 0:
        for s in SCIENTISTS_SEED:
            conn.execute(
                """INSERT INTO scientists
                (slug, name, designation, institute, address, dob, mobile, email,
                 research_interest, education, accolades, employment, other_records,
                 photo_filename, scholar_url, linkedin_url, current_work)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    s["slug"], s["name"], s["designation"], s["institute"], s["address"], s["dob"],
                    json.dumps(s["mobile"]), json.dumps(s["email"]), json.dumps(s["research_interest"]),
                    json.dumps(s["education"]), json.dumps(s["accolades"]), json.dumps(s["employment"]),
                    json.dumps(s["other_records"]), s["photo_filename"],
                    s.get("scholar_url", ""), s.get("linkedin_url", ""), json.dumps(s.get("current_work", [])),
                ),
            )
        conn.commit()

    # Backfill scholar_url/linkedin_url on scientist rows that already existed
    # before these columns were added, or were seeded with blank/outdated
    # links — matched by slug. This lets updating SCIENTISTS_SEED in code
    # actually take effect on a database that was already seeded once,
    # instead of only applying to a brand-new empty database.
    for s in SCIENTISTS_SEED:
        row = conn.execute("SELECT scholar_url, linkedin_url FROM scientists WHERE slug = ?", (s["slug"],)).fetchone()
        if row and not row["scholar_url"] and not row["linkedin_url"]:
            conn.execute(
                "UPDATE scientists SET scholar_url = ?, linkedin_url = ? WHERE slug = ?",
                (s.get("scholar_url", ""), s.get("linkedin_url", ""), s["slug"]),
            )
    conn.commit()

    # ---- Seed each scientist's papers, if that scientist has none yet ----
    # (Gated the same way every other section is: per-scientist row count,
    # not overall database "freshness" — otherwise dropping in an existing
    # research.db that predates a given scientist silently skips seeding
    # their papers, even though every other section still seeds correctly.)
    if force_reseed:
        conn.execute("DELETE FROM papers")

    for scientist_id, seed_path in ((1, SEED_PATH), (2, RANJIT_SEED_PATH)):
        if not os.path.exists(seed_path):
            continue
        count = conn.execute("SELECT COUNT(*) FROM papers WHERE scientist_id = ?", (scientist_id,)).fetchone()[0]
        if count > 0 and not force_reseed:
            continue
        with open(seed_path, encoding="utf-8") as f:
            records = json.load(f)
        for r in records:
            domains = classify_domains(r["title"])
            domain = ", ".join(domains)
            field = classify_field(domains)
            conn.execute(
                """INSERT INTO papers
                (scientist_id, complete_reference, title, authors, author_position, year,
                 journal, publisher, issn, doi, article_type, impact_factor,
                 quartile, domain, field, hidden)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
                (
                    scientist_id, r["complete_reference"], r["title"], r["authors"],
                    r["author_position"], r["year"], r["journal"],
                    r.get("publisher", ""), r.get("issn", ""), r["doi"],
                    r["article_type"], r["impact_factor"], r["quartile"],
                    domain, field,
                ),
            )
        conn.commit()

    # Seed Awards / Projects / Book Chapters / Software / Courses Taught /
    # Students Guided / Technology independently of the papers table's
    # freshness, per scientist — this matters when someone drops in an
    # older research.db that predates these tables: each one still gets
    # seeded here as long as it's empty for that scientist, rather than
    # silently staying blank forever.
    simple_seed_map = {
        "awards": ["title", "awarding_body", "year", "description"],
        "projects": ["investigators", "project_title", "funding_agency", "date_start", "date_end", "status"],
        "book_chapters": ["title", "authors", "editor", "book_title", "publisher", "year", "pages", "isbn", "doi"],
        "software": ["package_name", "reference", "year", "downloads", "cran_url"],
        "courses_taught": ["course_name"],
        "students_guided": ["name", "student_type", "start_date", "end_date", "description"],
        "technology": ["category", "authors", "year", "title", "id_number"],
        "popular_articles": ["authors", "year", "title", "publication", "details"],
        "policy_papers": ["authors", "year", "title", "publisher", "id_number"],
        "manuals": ["authors", "year", "title", "publisher"],
    }
    for scientist_id, path_prefix in ((1, ""), (2, "ranjit_")):
        for table, cols in simple_seed_map.items():
            path = os.path.join(BASE_DIR, f"{path_prefix}{table}_seed.json")
            if not os.path.exists(path):
                continue
            count = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE scientist_id = ?", (scientist_id,)).fetchone()[0]
            if count > 0 and not force_reseed:
                continue
            with open(path, encoding="utf-8") as f:
                items = json.load(f)
            all_cols = cols + ["scientist_id"]
            placeholders = ",".join(["?"] * len(all_cols))
            for item in items:
                values = tuple(item.get(c, "") for c in cols) + (scientist_id,)
                conn.execute(f"INSERT INTO {table} ({','.join(all_cols)}) VALUES ({placeholders})", values)
    conn.commit()

    _load_journal_scores_snapshot(conn)

    conn.close()


# ---------------------------------------------------------------------------
# Lightweight NLP domain classifier (keyword / rule based).
# This gives each paper a "research domain" tag from its title so the
# frontend can offer a "Domain" filter without needing an external NLP API.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# NLP domain classifier — keyword-weighted scoring over title, abstract, and
# keywords (Crossref "subject" categories). Title matches count for more
# since the title is the most deliberately-chosen, information-dense text;
# abstract/keyword matches add supporting evidence once available.
# ---------------------------------------------------------------------------
DOMAIN_KEYWORDS = {
    "Time Series & Forecasting": [
        "time series", "forecast", "arima", "garch", "wavelet", "volatility",
        "prediction", "sarima", "nardl",
    ],
    "Machine Learning & Deep Learning": [
        "machine learning", "deep learning", "neural network", "lstm",
        "ensemble", "svr", "random forest", "gradient boosting", "fuzzy",
        "extreme learning", "cnn", "convolutional",
    ],
    "Agricultural Economics & Price Analysis": [
        "price", "market", "economics", "volatility", "agribusiness",
        "cauliflower", "mustard", "oilseed", "spice", "brinjal", "potato",
    ],
    "Remote Sensing & Geospatial": [
        "remote sensing", "sar", "spectroscopy", "spatial", "satellite",
        "geospatial", "vegetation",
    ],
    "Climate, Weather & Hydrology": [
        "rainfall", "climate", "weather", "evapotranspiration", "hydrology",
        "precipitation", "cyclone",
    ],
    "Genomics & Bioinformatics": [
        "dna", "methylation", "genom", "gene", "bioinformatics", "6ma",
        "5mc", "sequence",
    ],
    "Precision & Smart Agriculture": [
        "iot", "hydroponic", "sensor", "precision", "smart", "vertical farm",
        "nitrogen",
    ],
    "Plant & Crop Science": [
        "crop yield", "seed germination", "blight", "tomato", "rice",
        "phenology", "sugarcane",
    ],
    "Statistics & Genetics": [
        "heritability", "genotype", "stability", "copula", "regression",
        "estimator",
    ],
}

# Crossref's own subject/category vocabulary, mapped onto the same domain
# labels. When present, these are a stronger, cleaner signal than keyword
# guesses off free text, so they're weighted higher below.
CROSSREF_SUBJECT_MAP = {
    "statistics and probability": "Statistics & Genetics",
    "genetics": "Statistics & Genetics",
    "agricultural and biological sciences": "Plant & Crop Science",
    "agronomy and crop science": "Plant & Crop Science",
    "plant science": "Plant & Crop Science",
    "atmospheric science": "Climate, Weather & Hydrology",
    "water science and technology": "Climate, Weather & Hydrology",
    "artificial intelligence": "Machine Learning & Deep Learning",
    "computer science applications": "Machine Learning & Deep Learning",
    "computer vision and pattern recognition": "Machine Learning & Deep Learning",
    "economics and econometrics": "Agricultural Economics & Price Analysis",
    "earth and planetary sciences": "Remote Sensing & Geospatial",
    "geography, planning and development": "Remote Sensing & Geospatial",
    "molecular biology": "Genomics & Bioinformatics",
    "genetics (clinical)": "Genomics & Bioinformatics",
    "biochemistry, genetics and molecular biology": "Genomics & Bioinformatics",
}

TITLE_WEIGHT = 3
ABSTRACT_WEIGHT = 1
SUBJECT_WEIGHT = 4  # Crossref's own categorization — trust it the most
MAX_DOMAINS = 4
DOMAIN_SCORE_FLOOR = 1  # any domain scoring at least this much is included


def classify_domains(title: str = "", abstract: str = "", keywords: str = "") -> list:
    """
    Returns up to MAX_DOMAINS domain labels, ranked by score, for a paper.
    A paper commonly touches more than one research area (e.g. a machine
    learning method applied to rainfall forecasting), so this returns a
    ranked list rather than forcing a single label.
    """
    title = title or ""
    abstract = abstract or ""
    keywords = keywords or ""

    if not (title or abstract or keywords):
        return ["General / Other"]

    scores = {}
    title_l = title.lower()
    abstract_l = abstract.lower()

    for domain, kws in DOMAIN_KEYWORDS.items():
        title_hits = sum(1 for kw in kws if kw in title_l)
        abstract_hits = sum(1 for kw in kws if kw in abstract_l)
        score = title_hits * TITLE_WEIGHT + abstract_hits * ABSTRACT_WEIGHT
        if score:
            scores[domain] = scores.get(domain, 0) + score

    for subject in [s.strip().lower() for s in keywords.split(",") if s.strip()]:
        mapped = CROSSREF_SUBJECT_MAP.get(subject)
        if mapped:
            scores[mapped] = scores.get(mapped, 0) + SUBJECT_WEIGHT

    if not scores:
        return ["General / Other"]

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top = [d for d, s in ranked if s >= DOMAIN_SCORE_FLOOR][:MAX_DOMAINS]
    return top or ["General / Other"]


def classify_domain(title: str = "", abstract: str = "", keywords: str = "") -> str:
    """Back-compat single-domain accessor — returns just the top domain."""
    return classify_domains(title, abstract, keywords)[0]


# ---------------------------------------------------------------------------
# "Field" classification — Statistical vs. Interdisciplinary. A paper whose
# domains are purely methodological/statistical is "Statistical"; a paper
# that applies statistics/ML to another subject area (agriculture, biology,
# climate, etc.) is "Interdisciplinary".
# ---------------------------------------------------------------------------
STATISTICAL_DOMAINS = {"Time Series & Forecasting", "Statistics & Genetics"}


def classify_field(domains: list) -> str:
    if not domains:
        return "Interdisciplinary"
    if all(d in STATISTICAL_DOMAINS for d in domains):
        return "Statistical"
    return "Interdisciplinary"


# ---------------------------------------------------------------------------
# Crossref enrichment — pulls abstract + subject categories for a paper
# using its DOI, via the free public Crossref REST API (no key required).
# ---------------------------------------------------------------------------
CROSSREF_CONTACT_EMAIL = os.environ.get("CROSSREF_CONTACT_EMAIL", "example@example.com")
JATS_TAG_RE = re.compile(r"<[^>]+>")


def _clean_doi(raw_doi: str) -> str:
    """Accepts a bare DOI or a full https://doi.org/... URL and returns the bare DOI."""
    if not raw_doi:
        return ""
    doi = raw_doi.strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    return doi.strip()


def fetch_crossref_metadata(raw_doi: str) -> dict:
    """
    Looks up a DOI on Crossref and returns {"abstract": str, "keywords": str}.
    Returns empty strings (not an exception) if the DOI isn't found or the
    record has no abstract/subjects, so callers can always trust the shape.
    """
    doi = _clean_doi(raw_doi)
    if not doi:
        return {"abstract": "", "keywords": ""}

    import urllib.request
    import urllib.error

    url = f"https://api.crossref.org/works/{doi}"
    # Crossref's "polite pool" wants a descriptive User-Agent with contact info
    headers = {"User-Agent": f"AcademicIMS/1.0 (mailto:{CROSSREF_CONTACT_EMAIL})"}
    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
        return {"abstract": "", "keywords": ""}

    msg = data.get("message", {})

    abstract_raw = msg.get("abstract", "")
    abstract = JATS_TAG_RE.sub(" ", abstract_raw)
    abstract = re.sub(r"\s+", " ", abstract).strip()

    subjects = msg.get("subject", []) or []
    keywords = ", ".join(subjects)

    return {"abstract": abstract, "keywords": keywords}


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def generate_otp():
    return "".join(random.choices(string.digits, k=6))


def generate_token():
    return "".join(random.choices(string.ascii_letters + string.digits, k=40))


def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        db = get_db()
        row = db.execute("SELECT expires, role, scoped_scientist_id FROM sessions WHERE token = ?", (token,)).fetchone()
        if not row or row["expires"] < time.time():
            return jsonify({"error": "Unauthorized. Please log in again."}), 401
        g.session_role = row["role"] or "super_admin"
        g.session_scientist_id = row["scoped_scientist_id"]
        return f(*args, **kwargs)
    return wrapper


def _enforce_scientist_scope(target_scientist_id):
    """
    Aborts with 403 if the logged-in session belongs to a single scientist
    (not the super admin) and they're trying to touch someone else's data.
    Call this from any @require_auth endpoint that acts on a specific
    scientist_id. No-op for super_admin sessions and for unauthenticated
    calls (require_auth already blocks those before this ever runs).
    """
    role = getattr(g, "session_role", "super_admin")
    if role == "scientist" and getattr(g, "session_scientist_id", None) != target_scientist_id:
        from flask import abort
        abort(403, description="You can only manage your own profile.")


def _require_super_admin():
    """Aborts with 403 unless the logged-in session is the super admin — for
    site-wide actions (Add User, NAAS/JCR upload, backups) that no single
    scientist's login should be able to do."""
    role = getattr(g, "session_role", "super_admin")
    if role != "super_admin":
        from flask import abort
        abort(403, description="Only the site admin can do this.")


def send_otp_email(email: str, otp: str):
    """
    Sends the OTP by email, trying methods in order:
      1. Resend (HTTPS API) if RESEND_API_KEY is set — works on hosts that
         block outbound SMTP ports, like Render's free tier.
      2. Traditional SMTP if SMTP_HOST is set — good for local testing.
    Falls back to dev-mode (OTP returned directly in the API response,
    shown in the login popup) if neither is configured or both fail.
    """
    resend_api_key = os.environ.get("RESEND_API_KEY")
    if resend_api_key:
        try:
            return _send_via_resend(email, otp, resend_api_key)
        except Exception as e:
            print(f"[RESEND ERROR] Failed to send OTP email: {e}")
            return False

    smtp_host = os.environ.get("SMTP_HOST")
    if not smtp_host:
        print(f"[DEV MODE] OTP for {email}: {otp}  (configure RESEND_API_KEY or SMTP_* env vars to send real emails)")
        return False
    import smtplib
    from email.mime.text import MIMEText
    msg = MIMEText(f"Your OTP for the Academic Research Information Management System is: {otp}\nIt expires in 5 minutes.")
    msg["Subject"] = "Your Admin Login OTP"
    msg["From"] = os.environ.get("SMTP_USER")
    msg["To"] = email
    with smtplib.SMTP(smtp_host, int(os.environ.get("SMTP_PORT", 587)), timeout=8) as server:
        server.starttls()
        server.login(os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD"))
        server.send_message(msg)
    return True


def _send_via_resend(email: str, otp: str, api_key: str) -> bool:
    """Sends the OTP via Resend's HTTPS API — bypasses SMTP-port blocking."""
    import urllib.request

    sender = os.environ.get("RESEND_FROM", "onboarding@resend.dev")
    payload = json.dumps({
        "from": sender,
        "to": [email],
        "subject": "Your Admin Login OTP",
        "text": (
            f"Your OTP for the Academic Research Information Management "
            f"System is: {otp}\nIt expires in 5 minutes."
        ),
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"Resend API returned status {resp.status}")
    return True


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------
@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    login_type = data.get("login_type", "any")  # "admin", "user", or "any" (back-compat)

    role, scoped_scientist_id = None, None

    if login_type in ("admin", "any"):
        if email == ADMIN_EMAIL.lower() and password == ADMIN_PASSWORD:
            role, scoped_scientist_id = "super_admin", None

    if role is None and login_type in ("user", "any"):
        db = get_db()
        row = db.execute(
            "SELECT scientist_id, login_password_hash FROM scientists WHERE lower(login_email) = ? AND login_email != ''",
            (email,),
        ).fetchone()
        if row and row["login_password_hash"] and check_password_hash(row["login_password_hash"], password):
            role, scoped_scientist_id = "scientist", row["scientist_id"]

    if role is None:
        return jsonify({"error": "Invalid email or password"}), 401

    otp = generate_otp()
    db = get_db()
    db.execute(
        "INSERT INTO otp_codes (email, otp, expires, role, scoped_scientist_id) VALUES (?,?,?,?,?) "
        "ON CONFLICT(email) DO UPDATE SET otp=excluded.otp, expires=excluded.expires, role=excluded.role, scoped_scientist_id=excluded.scoped_scientist_id",
        (email, otp, time.time() + OTP_TTL_SECONDS, role, scoped_scientist_id),
    )
    db.commit()
    try:
        delivered = send_otp_email(email, otp)
    except Exception as e:
        print(f"[SMTP ERROR] Failed to send OTP email: {e}")
        delivered = False

    resp = {"message": "OTP sent to your registered email."}
    if not delivered:
        # DEV MODE ONLY: expose the OTP directly since no SMTP is configured.
        # Remove this in production once real email delivery is set up.
        resp["dev_otp"] = otp
    return jsonify(resp)


@app.route("/api/verify-otp", methods=["POST"])
def verify_otp():
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    otp = (data.get("otp") or "").strip()

    db = get_db()
    record = db.execute("SELECT otp, expires, role, scoped_scientist_id FROM otp_codes WHERE email = ?", (email,)).fetchone()
    if not record or record["expires"] < time.time():
        return jsonify({"error": "OTP expired. Please log in again."}), 400
    if record["otp"] != otp:
        return jsonify({"error": "Incorrect OTP."}), 400

    role = record["role"] or "super_admin"
    scoped_scientist_id = record["scoped_scientist_id"]

    db.execute("DELETE FROM otp_codes WHERE email = ?", (email,))
    token = generate_token()
    db.execute(
        "INSERT INTO sessions (token, email, expires, role, scoped_scientist_id) VALUES (?,?,?,?,?)",
        (token, email, time.time() + SESSION_TTL_SECONDS, role, scoped_scientist_id),
    )
    db.commit()
    return jsonify({"token": token, "message": "Login successful.", "role": role, "scientist_id": scoped_scientist_id})


def is_admin_request():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    db = get_db()
    row = db.execute("SELECT expires FROM sessions WHERE token = ?", (token,)).fetchone()
    return bool(row and row["expires"] >= time.time())


# ---------------------------------------------------------------------------
# Paper (research article table) routes
# ---------------------------------------------------------------------------
@app.route("/api/papers", methods=["GET"])
def get_papers():
    db = get_db()
    query = "SELECT * FROM papers WHERE scientist_id = ?"
    params = [_get_scientist_id()]

    if not is_admin_request():
        query += " AND hidden = 0"

    year = request.args.get("year")
    if year:
        query += " AND year = ?"
        params.append(year)

    year_min = request.args.get("year_min")
    if year_min:
        query += " AND year != '' AND CAST(year AS INTEGER) >= ?"
        params.append(int(year_min))

    year_max = request.args.get("year_max")
    if year_max:
        query += " AND year != '' AND CAST(year AS INTEGER) <= ?"
        params.append(int(year_max))

    journal = request.args.get("journal")
    if journal:
        query += " AND journal = ?"
        params.append(journal)

    quartile = request.args.get("quartile")
    if quartile:
        query += " AND quartile = ?"
        params.append(quartile)

    field = request.args.get("field")
    if field:
        query += " AND field = ?"
        params.append(field)

    # domains: comma-separated list, e.g. ?domains=Time Series & Forecasting,Genomics & Bioinformatics
    # matches any paper whose own (comma-joined) domain field contains ANY of the requested domains.
    domains_param = request.args.get("domains")
    if domains_param:
        requested = [d.strip() for d in domains_param.split(",") if d.strip()]
        if requested:
            query += " AND (" + " OR ".join(["domain LIKE ?"] * len(requested)) + ")"
            params.extend([f"%{d}%" for d in requested])

    search = request.args.get("q")
    if search:
        query += " AND (title LIKE ? OR authors LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])

    sort = request.args.get("sort", "year_desc")
    sort_map = {
        "year_desc": "year DESC",
        "year_asc": "year ASC",
        "if_desc": "CAST(impact_factor AS FLOAT) DESC",
        "title_asc": "title ASC",
    }
    query += f" ORDER BY {sort_map.get(sort, 'year DESC')}"

    rows = db.execute(query, params).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/papers/filters", methods=["GET"])
def get_filter_options():
    db = get_db()
    admin = is_admin_request()
    sid = _get_scientist_id()
    hidden_clause = "" if admin else "AND hidden = 0"

    years = [r[0] for r in db.execute(f"SELECT DISTINCT year FROM papers WHERE scientist_id = ? AND year != '' {hidden_clause} ORDER BY year DESC", (sid,))]
    journals = [r[0] for r in db.execute(f"SELECT DISTINCT journal FROM papers WHERE scientist_id = ? AND journal != '' {hidden_clause} ORDER BY journal", (sid,))]
    quartiles = [r[0] for r in db.execute(f"SELECT DISTINCT quartile FROM papers WHERE scientist_id = ? AND quartile != '' {hidden_clause} ORDER BY quartile", (sid,))]
    fields = [r[0] for r in db.execute(f"SELECT DISTINCT field FROM papers WHERE scientist_id = ? AND field != '' {hidden_clause} ORDER BY field", (sid,))]

    domain_rows = db.execute(f"SELECT domain FROM papers WHERE scientist_id = ? AND domain != '' {hidden_clause}", (sid,))
    domain_set = set()
    for (d,) in domain_rows:
        for part in d.split(","):
            part = part.strip()
            if part:
                domain_set.add(part)
    domains = sorted(domain_set)

    numeric_years = [int(y) for y in years if y.isdigit()]
    year_bounds = {"min": min(numeric_years), "max": max(numeric_years)} if numeric_years else {"min": None, "max": None}

    return jsonify({
        "years": years, "journals": journals, "quartiles": quartiles,
        "domains": domains, "fields": fields, "year_bounds": year_bounds,
    })


@app.route("/api/papers/stats", methods=["GET"])
def get_stats():
    db = get_db()
    sid = _get_scientist_id()
    hidden_clause = "" if is_admin_request() else "AND hidden = 0"
    year_clause = "year != ''" if is_admin_request() else "year != '' AND hidden = 0"
    quartile_clause = "quartile != ''" if is_admin_request() else "quartile != '' AND hidden = 0"

    total = db.execute(f"SELECT COUNT(*) FROM papers WHERE scientist_id = ? {hidden_clause}", (sid,)).fetchone()[0]
    by_year = db.execute(f"SELECT year, COUNT(*) c FROM papers WHERE scientist_id = ? AND {year_clause} GROUP BY year ORDER BY year", (sid,)).fetchall()
    by_quartile = db.execute(f"SELECT quartile, COUNT(*) c FROM papers WHERE scientist_id = ? AND {quartile_clause} GROUP BY quartile", (sid,)).fetchall()
    by_domain = db.execute(f"SELECT domain, COUNT(*) c FROM papers WHERE scientist_id = ? {hidden_clause} GROUP BY domain ORDER BY c DESC", (sid,)).fetchall()
    return jsonify({
        "total": total,
        "by_year": [dict(r) for r in by_year],
        "by_quartile": [dict(r) for r in by_quartile],
        "by_domain": [dict(r) for r in by_domain],
    })


@app.route("/api/papers", methods=["POST"])
@require_auth
def add_paper():
    """
    Accepts either:
      { "bibtex": "@article{...}" }
    or a plain JSON object with the paper fields directly.
    """
    data = request.get_json(force=True)
    db = get_db()
    scientist_id = _get_scientist_id()
    _enforce_scientist_scope(scientist_id)

    if "bibtex" in data:
        if bibtexparser is None:
            return jsonify({"error": "bibtexparser not installed on server"}), 500
        bib_db = bibtexparser.loads(data["bibtex"])
        if not bib_db.entries:
            return jsonify({"error": "Could not parse any entries from the BibTeX provided."}), 400
        pre_selected = 1 if data.get("selected") else 0
        added = []
        for entry in bib_db.entries:
            title = entry.get("title", "").strip("{}")
            authors = entry.get("author", "").replace(" and ", ", ")
            year = entry.get("year", "")
            journal = entry.get("journal", entry.get("booktitle", ""))
            doi = entry.get("doi", "")
            issn = entry.get("issn", "")
            publisher = entry.get("publisher", "")
            domains = classify_domains(title)
            domain = ", ".join(domains)
            field = classify_field(domains)
            cur = db.execute(
                """INSERT INTO papers
                (scientist_id, complete_reference, title, authors, author_position, year,
                 journal, publisher, issn, doi, article_type, impact_factor,
                 quartile, domain, field, hidden, selected, abstract, keywords)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?)""",
                (
                    scientist_id, f"{authors} ({year}). {title}. {journal}.",
                    title, authors, "", year, journal, publisher, issn, doi,
                    entry.get("ENTRYTYPE", "article"), "", "", domain, field, pre_selected, "", "",
                ),
            )
            added.append(cur.lastrowid)
        db.commit()
        _apply_journal_scores_to_papers(db)  # pick up IF/Quartile/NAAS if the journal is already in the lookup table
        return jsonify({"message": f"{len(added)} entr(y/ies) added.", "ids": added}), 201

    # plain field-based insert (manual admin form)
    required_ok = data.get("title")
    if not required_ok:
        return jsonify({"error": "Title is required."}), 400
    domains = classify_domains(data.get("title", ""), data.get("abstract", ""), data.get("keywords", ""))
    domain = ", ".join(domains)
    field = data.get("field") or classify_field(domains)
    cur = db.execute(
        """INSERT INTO papers
        (scientist_id, complete_reference, title, authors, author_position, year, journal,
         publisher, issn, doi, article_type, impact_factor, quartile, domain,
         field, hidden, selected, abstract, keywords)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?)""",
        (
            scientist_id, data.get("complete_reference", ""), data.get("title", ""),
            data.get("authors", ""), data.get("author_position", ""),
            data.get("year", ""), data.get("journal", ""),
            data.get("publisher", ""), data.get("issn", ""),
            data.get("doi", ""), data.get("article_type", "Research Article"),
            data.get("impact_factor", ""), data.get("quartile", ""), domain,
            field, 1 if data.get("selected") else 0, data.get("abstract", ""), data.get("keywords", ""),
        ),
    )
    db.commit()
    _apply_journal_scores_to_papers(db)  # pick up IF/Quartile/NAAS if the journal is already in the lookup table
    return jsonify({"message": "Paper added.", "id": cur.lastrowid}), 201


@app.route("/api/papers/<int:pub_id>", methods=["PUT"])
@require_auth
def update_paper(pub_id):
    data = request.get_json(force=True)
    db = get_db()
    owner = db.execute("SELECT scientist_id FROM papers WHERE publication_id = ?", (pub_id,)).fetchone()
    if not owner:
        return jsonify({"error": "Paper not found."}), 404
    _enforce_scientist_scope(owner["scientist_id"])
    fields = [
        "complete_reference", "title", "authors", "author_position", "year",
        "journal", "publisher", "issn", "doi", "article_type",
        "impact_factor", "quartile", "naas_score", "abstract", "keywords", "field", "domain",
    ]
    updates, params = [], []
    for f in fields:
        if f in data:
            updates.append(f"{f} = ?")
            params.append(data[f])
    # Reclassify domain/field automatically UNLESS the caller explicitly set
    # them (e.g. admin manually picked a Field in the edit form).
    if ("title" in data or "abstract" in data or "keywords" in data) and "domain" not in data:
        current = db.execute(
            "SELECT title, abstract, keywords FROM papers WHERE publication_id = ?", (pub_id,)
        ).fetchone()
        title = data.get("title", current["title"] if current else "")
        abstract = data.get("abstract", current["abstract"] if current else "")
        keywords = data.get("keywords", current["keywords"] if current else "")
        domains = classify_domains(title, abstract, keywords)
        updates.append("domain = ?")
        params.append(", ".join(domains))
        if "field" not in data:
            updates.append("field = ?")
            params.append(classify_field(domains))
    if not updates:
        return jsonify({"error": "No fields to update."}), 400
    params.append(pub_id)
    db.execute(f"UPDATE papers SET {', '.join(updates)} WHERE publication_id = ?", params)
    db.commit()
    return jsonify({"message": "Paper updated."})


@app.route("/api/papers/<int:pub_id>/toggle-hidden", methods=["POST"])
@require_auth
def toggle_paper_hidden(pub_id):
    db = get_db()
    row = db.execute("SELECT hidden, scientist_id FROM papers WHERE publication_id = ?", (pub_id,)).fetchone()
    if not row:
        return jsonify({"error": "Paper not found."}), 404
    _enforce_scientist_scope(row["scientist_id"])
    new_val = 0 if row["hidden"] else 1
    db.execute("UPDATE papers SET hidden = ? WHERE publication_id = ?", (new_val, pub_id))
    db.commit()
    return jsonify({"message": "Paper hidden." if new_val else "Paper visible again.", "hidden": bool(new_val)})


@app.route("/api/papers/<int:pub_id>/toggle-selected", methods=["POST"])
@require_auth
def toggle_paper_selected(pub_id):
    """Toggles whether a paper appears in the 'Selected' view. Every paper always stays in 'All' regardless."""
    db = get_db()
    row = db.execute("SELECT selected, scientist_id FROM papers WHERE publication_id = ?", (pub_id,)).fetchone()
    if not row:
        return jsonify({"error": "Paper not found."}), 404
    _enforce_scientist_scope(row["scientist_id"])
    new_val = 0 if row["selected"] else 1
    db.execute("UPDATE papers SET selected = ? WHERE publication_id = ?", (new_val, pub_id))
    db.commit()
    return jsonify({"message": "Added to Selected." if new_val else "Removed from Selected.", "selected": bool(new_val)})


@app.route("/api/papers/<int:pub_id>/toggle-cv-included", methods=["POST"])
@require_auth
def toggle_paper_cv_included(pub_id):
    """Toggles whether a paper is included in the downloadable CV."""
    db = get_db()
    row = db.execute("SELECT cv_included, scientist_id FROM papers WHERE publication_id = ?", (pub_id,)).fetchone()
    if not row:
        return jsonify({"error": "Paper not found."}), 404
    _enforce_scientist_scope(row["scientist_id"])
    new_val = 0 if row["cv_included"] else 1
    db.execute("UPDATE papers SET cv_included = ? WHERE publication_id = ?", (new_val, pub_id))
    db.commit()
    return jsonify({"message": "Added to CV." if new_val else "Removed from CV.", "cv_included": bool(new_val)})


@app.route("/api/papers/<int:pub_id>/enrich", methods=["POST"])
@require_auth
def enrich_paper(pub_id):
    """Fetches abstract + subject keywords from Crossref for one paper (by its DOI) and reclassifies its domain."""
    db = get_db()
    row = db.execute("SELECT title, doi, scientist_id FROM papers WHERE publication_id = ?", (pub_id,)).fetchone()
    if not row:
        return jsonify({"error": "Paper not found."}), 404
    _enforce_scientist_scope(row["scientist_id"])
    if not row["doi"]:
        return jsonify({"error": "This paper has no DOI to look up."}), 400

    meta = fetch_crossref_metadata(row["doi"])
    domains = classify_domains(row["title"], meta["abstract"], meta["keywords"])
    domain = ", ".join(domains)
    field = classify_field(domains)
    db.execute(
        "UPDATE papers SET abstract = ?, keywords = ?, domain = ?, field = ? WHERE publication_id = ?",
        (meta["abstract"], meta["keywords"], domain, field, pub_id),
    )
    db.commit()
    found = bool(meta["abstract"] or meta["keywords"])
    return jsonify({
        "message": "Enriched from Crossref." if found else "Crossref had no abstract/subjects for this DOI.",
        "abstract": meta["abstract"],
        "keywords": meta["keywords"],
        "domain": domain,
        "field": field,
    })


@app.route("/api/papers/enrich-all", methods=["POST"])
@require_auth
def enrich_all_papers():
    """
    Bulk-enriches every paper that has a DOI but no abstract yet.
    Pass {"force": true} in the body to re-fetch even papers that already
    have an abstract (e.g. after improving the classifier).
    """
    data = request.get_json(silent=True) or {}
    force = bool(data.get("force", False))
    scientist_id = _get_scientist_id()
    _enforce_scientist_scope(scientist_id)
    db = get_db()

    if force:
        rows = db.execute("SELECT publication_id, title, doi FROM papers WHERE scientist_id = ? AND doi != ''", (scientist_id,)).fetchall()
    else:
        rows = db.execute(
            "SELECT publication_id, title, doi FROM papers WHERE scientist_id = ? AND doi != '' AND (abstract IS NULL OR abstract = '')",
            (scientist_id,)
        ).fetchall()

    updated, skipped = 0, 0
    for row in rows:
        meta = fetch_crossref_metadata(row["doi"])
        if not (meta["abstract"] or meta["keywords"]):
            skipped += 1
            time.sleep(0.2)
            continue
        domains = classify_domains(row["title"], meta["abstract"], meta["keywords"])
        domain = ", ".join(domains)
        field = classify_field(domains)
        db.execute(
            "UPDATE papers SET abstract = ?, keywords = ?, domain = ?, field = ? WHERE publication_id = ?",
            (meta["abstract"], meta["keywords"], domain, field, row["publication_id"]),
        )
        updated += 1
        time.sleep(0.2)  # be polite to Crossref's public rate limit
    db.commit()

    return jsonify({
        "message": f"Enriched {updated} paper(s) from Crossref, {skipped} had no abstract available.",
        "updated": updated,
        "skipped": skipped,
        "total_checked": len(rows),
    })


@app.route("/api/papers/<int:pub_id>", methods=["DELETE"])
@require_auth
def delete_paper(pub_id):
    db = get_db()
    owner = db.execute("SELECT scientist_id FROM papers WHERE publication_id = ?", (pub_id,)).fetchone()
    if not owner:
        return jsonify({"error": "Paper not found."}), 404
    _enforce_scientist_scope(owner["scientist_id"])
    db.execute("DELETE FROM papers WHERE publication_id = ?", (pub_id,))
    db.commit()
    return jsonify({"message": "Paper deleted."})


def _get_scientist_id():
    """Reads scientist_id from the query string (GET) or JSON body (POST/PUT), default 1."""
    val = request.args.get("scientist_id")
    if val is None and request.is_json:
        val = (request.get_json(silent=True) or {}).get("scientist_id")
    try:
        return int(val)
    except (TypeError, ValueError):
        return 1


@app.route("/api/scientists", methods=["GET"])
def list_scientists():
    """Lightweight list for the profile switcher — id, slug, name, designation, photo.
    Super admins also get each profile's assigned login_email, so they can see
    who has a login set up without needing to open each one."""
    db = get_db()
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    session_row = db.execute("SELECT expires, role FROM sessions WHERE token = ?", (token,)).fetchone()
    is_super_admin = bool(session_row and session_row["expires"] >= time.time() and (session_row["role"] or "super_admin") == "super_admin")

    cols = "scientist_id, slug, name, designation, photo_filename" + (", login_email" if is_super_admin else "")
    rows = db.execute(f"SELECT {cols} FROM scientists ORDER BY scientist_id ASC").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/scientist", methods=["GET"])
def scientist_info():
    scientist_id = _get_scientist_id()
    db = get_db()
    row = db.execute("SELECT * FROM scientists WHERE scientist_id = ?", (scientist_id,)).fetchone()
    if not row:
        return jsonify({"error": "Scientist not found."}), 404
    d = dict(row)
    for key in ("mobile", "email", "education", "accolades", "employment", "other_records", "current_work"):
        d[key] = json.loads(d[key]) if d[key] else []
    try:
        d["research_interest"] = json.loads(d["research_interest"]) if d["research_interest"] else []
    except (json.JSONDecodeError, TypeError):
        # Old plain-text format (pre-bullet-list) — wrap as a single item.
        d["research_interest"] = [d["research_interest"]] if d["research_interest"] else []
    return jsonify(d)


@app.route("/api/scientist", methods=["PUT"])
@require_auth
def update_scientist():
    """Updates any subset of the active scientist's profile fields (Home tab content)."""
    scientist_id = _get_scientist_id()
    _enforce_scientist_scope(scientist_id)
    data = request.get_json(force=True)
    db = get_db()

    row = db.execute("SELECT scientist_id FROM scientists WHERE scientist_id = ?", (scientist_id,)).fetchone()
    if not row:
        return jsonify({"error": "Scientist not found."}), 404

    text_fields = ["name", "designation", "institute", "address", "dob", "scholar_url", "linkedin_url"]
    json_fields = ["mobile", "email", "education", "accolades", "employment", "other_records", "research_interest", "current_work"]

    updates, params = [], []
    for f in text_fields:
        if f in data:
            updates.append(f"{f} = ?")
            params.append(data[f])
    for f in json_fields:
        if f in data:
            updates.append(f"{f} = ?")
            params.append(json.dumps(data[f]))

    if not updates:
        return jsonify({"error": "No fields to update."}), 400

    params.append(scientist_id)
    db.execute(f"UPDATE scientists SET {', '.join(updates)} WHERE scientist_id = ?", params)
    db.commit()
    return jsonify({"message": "Profile updated."})


@app.route("/api/scientists", methods=["POST"])
@require_auth
def add_scientist():
    """Creates a brand-new, entirely blank profile — no papers, awards, or any
    other content — for a new person to fill in themselves via admin login.
    Only the site admin can do this, not an individual scientist's own login."""
    _require_super_admin()
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name is required."}), 400

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "user"
    db = get_db()
    base_slug = slug
    n = 1
    while db.execute("SELECT 1 FROM scientists WHERE slug = ?", (slug,)).fetchone():
        n += 1
        slug = f"{base_slug}-{n}"

    cur = db.execute(
        """INSERT INTO scientists
        (slug, name, designation, institute, address, dob, mobile, email,
         research_interest, education, accolades, employment, other_records,
         photo_filename, scholar_url, linkedin_url, current_work)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            slug, name, data.get("designation", ""), data.get("institute", ""), "", "",
            "[]", "[]", "[]", "[]", "[]", "[]", "[]",
            "yeasin-photo.png", "", "", "[]",
        ),
    )
    db.commit()
    return jsonify({"message": f"{name}'s profile created — blank and ready to fill in.", "scientist_id": cur.lastrowid}), 201


@app.route("/api/scientists/<int:target_id>", methods=["DELETE"])
@require_auth
def delete_scientist(target_id):
    """
    Super-admin only: permanently deletes a profile and everything in it —
    papers, awards, projects, book chapters, software, courses taught,
    students guided, technology, its layout settings, and its own login if
    it has one. This cannot be undone.
    """
    _require_super_admin()
    db = get_db()

    row = db.execute("SELECT name FROM scientists WHERE scientist_id = ?", (target_id,)).fetchone()
    if not row:
        return jsonify({"error": "Profile not found."}), 404

    total_count = db.execute("SELECT COUNT(*) FROM scientists").fetchone()[0]
    if total_count <= 1:
        return jsonify({"error": "Can't delete the only remaining profile."}), 400

    for table in ("papers", "awards", "projects", "book_chapters", "software",
                  "courses_taught", "students_guided", "technology"):
        db.execute(f"DELETE FROM {table} WHERE scientist_id = ?", (target_id,))
    db.execute("DELETE FROM profile_layout WHERE scientist_id = ?", (target_id,))
    db.execute("DELETE FROM scientists WHERE scientist_id = ?", (target_id,))
    db.commit()
    return jsonify({"message": f"{row['name']}'s profile and all its content have been deleted."})


@app.route("/api/scientist/login", methods=["PUT"])
@require_auth
def set_scientist_login():
    """
    Super-admin only: sets or resets the login email/password for one
    scientist's profile, so that person can log in and manage only their
    own content. Passwords are stored hashed — if a user forgets theirs,
    the admin sets a new one here rather than the system revealing the old
    one, which would mean storing it in a reversible, less safe form.
    """
    _require_super_admin()
    scientist_id = _get_scientist_id()
    data = request.get_json(force=True)
    login_email = (data.get("login_email") or "").strip().lower()
    password = data.get("password") or ""

    if not login_email or not password:
        return jsonify({"error": "Both a login email and password are required."}), 400
    if len(password) < 6:
        return jsonify({"error": "Password should be at least 6 characters."}), 400
    if login_email == ADMIN_EMAIL.lower():
        return jsonify({"error": "That email is already used for the site admin login — pick a different one."}), 400

    db = get_db()
    row = db.execute("SELECT scientist_id FROM scientists WHERE scientist_id = ?", (scientist_id,)).fetchone()
    if not row:
        return jsonify({"error": "Scientist not found."}), 404

    clash = db.execute(
        "SELECT scientist_id FROM scientists WHERE lower(login_email) = ? AND login_email != '' AND scientist_id != ?",
        (login_email, scientist_id),
    ).fetchone()
    if clash:
        return jsonify({"error": "That email is already assigned to another profile's login."}), 400

    db.execute(
        "UPDATE scientists SET login_email = ?, login_password_hash = ? WHERE scientist_id = ?",
        (login_email, generate_password_hash(password), scientist_id),
    )
    db.commit()
    return jsonify({"message": "Login credentials saved."})


@app.route("/api/scientist/login", methods=["DELETE"])
@require_auth
def remove_scientist_login():
    """Super-admin only: removes a scientist's own login, leaving only the site admin able to manage that profile."""
    _require_super_admin()
    scientist_id = _get_scientist_id()
    db = get_db()
    db.execute("UPDATE scientists SET login_email = '', login_password_hash = '' WHERE scientist_id = ?", (scientist_id,))
    db.commit()
    return jsonify({"message": "Login removed."})


@app.route("/api/scientist/photo", methods=["POST"])
@require_auth
def upload_scientist_photo():
    """Accepts an image upload for the active scientist's profile photo."""
    scientist_id = _get_scientist_id()
    _enforce_scientist_scope(scientist_id)
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded (expected form field 'file')."}), 400
    file = request.files["file"]
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        return jsonify({"error": "Please upload a PNG, JPG, or WEBP image."}), 400

    filename = f"scientist-{scientist_id}-photo{ext}"
    save_path = os.path.join(FRONTEND_DIR, filename)
    file.save(save_path)

    db = get_db()
    db.execute("UPDATE scientists SET photo_filename = ? WHERE scientist_id = ?", (filename, scientist_id))
    db.commit()
    return jsonify({"message": "Photo updated.", "photo_filename": filename})


# ---------------------------------------------------------------------------
# Research Team — a per-scientist list of team members (photo + name +
# designation), shown on the Home tab. Bespoke rather than the generic
# simple-CRUD system because it needs photo upload and drag-to-reorder.
# ---------------------------------------------------------------------------

@app.route("/api/research-team", methods=["GET"])
def list_research_team():
    scientist_id = _get_scientist_id()
    db = get_db()
    hidden_clause = "" if is_admin_request() else "AND hidden = 0"
    rows = db.execute(
        f"SELECT * FROM research_team WHERE scientist_id = ? {hidden_clause} ORDER BY sort_order ASC, member_id ASC",
        (scientist_id,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/research-team", methods=["POST"])
@require_auth
def add_research_team_member():
    scientist_id = _get_scientist_id()
    _enforce_scientist_scope(scientist_id)
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name is required."}), 400
    db = get_db()
    max_order = db.execute("SELECT COALESCE(MAX(sort_order), -1) FROM research_team WHERE scientist_id = ?", (scientist_id,)).fetchone()[0]
    cur = db.execute(
        "INSERT INTO research_team (scientist_id, sort_order, name, designation) VALUES (?,?,?,?)",
        (scientist_id, max_order + 1, name, data.get("designation", "")),
    )
    db.commit()
    return jsonify({"message": "Team member added.", "id": cur.lastrowid}), 201


@app.route("/api/research-team/<int:member_id>", methods=["PUT"])
@require_auth
def update_research_team_member(member_id):
    db = get_db()
    owner = db.execute("SELECT scientist_id FROM research_team WHERE member_id = ?", (member_id,)).fetchone()
    if not owner:
        return jsonify({"error": "Not found."}), 404
    _enforce_scientist_scope(owner["scientist_id"])
    data = request.get_json(force=True)
    updates, params = [], []
    for f in ("name", "designation"):
        if f in data:
            updates.append(f"{f} = ?")
            params.append(data[f])
    if not updates:
        return jsonify({"error": "No fields to update."}), 400
    params.append(member_id)
    db.execute(f"UPDATE research_team SET {', '.join(updates)} WHERE member_id = ?", params)
    db.commit()
    return jsonify({"message": "Updated."})


@app.route("/api/research-team/<int:member_id>", methods=["DELETE"])
@require_auth
def delete_research_team_member(member_id):
    db = get_db()
    owner = db.execute("SELECT scientist_id FROM research_team WHERE member_id = ?", (member_id,)).fetchone()
    if not owner:
        return jsonify({"error": "Not found."}), 404
    _enforce_scientist_scope(owner["scientist_id"])
    db.execute("DELETE FROM research_team WHERE member_id = ?", (member_id,))
    db.commit()
    return jsonify({"message": "Removed."})


@app.route("/api/research-team/<int:member_id>/toggle-hidden", methods=["POST"])
@require_auth
def toggle_research_team_hidden(member_id):
    db = get_db()
    row = db.execute("SELECT hidden, scientist_id FROM research_team WHERE member_id = ?", (member_id,)).fetchone()
    if not row:
        return jsonify({"error": "Not found."}), 404
    _enforce_scientist_scope(row["scientist_id"])
    new_val = 0 if row["hidden"] else 1
    db.execute("UPDATE research_team SET hidden = ? WHERE member_id = ?", (new_val, member_id))
    db.commit()
    return jsonify({"message": "Hidden." if new_val else "Visible again.", "hidden": bool(new_val)})


@app.route("/api/research-team/reorder", methods=["PUT"])
@require_auth
def reorder_research_team():
    """Body: {"order": [member_id, member_id, ...]} in the new display order."""
    scientist_id = _get_scientist_id()
    _enforce_scientist_scope(scientist_id)
    data = request.get_json(force=True)
    order = data.get("order", [])
    db = get_db()
    for idx, member_id in enumerate(order):
        db.execute(
            "UPDATE research_team SET sort_order = ? WHERE member_id = ? AND scientist_id = ?",
            (idx, member_id, scientist_id),
        )
    db.commit()
    return jsonify({"message": "Order saved."})


@app.route("/api/research-team/<int:member_id>/photo", methods=["POST"])
@require_auth
def upload_research_team_photo(member_id):
    db = get_db()
    owner = db.execute("SELECT scientist_id FROM research_team WHERE member_id = ?", (member_id,)).fetchone()
    if not owner:
        return jsonify({"error": "Not found."}), 404
    _enforce_scientist_scope(owner["scientist_id"])
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded (expected form field 'file')."}), 400
    file = request.files["file"]
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        return jsonify({"error": "Please upload a PNG, JPG, or WEBP image."}), 400

    filename = f"team-{member_id}-photo{ext}"
    file.save(os.path.join(FRONTEND_DIR, filename))
    db.execute("UPDATE research_team SET photo_filename = ? WHERE member_id = ?", (filename, member_id))
    db.commit()
    return jsonify({"message": "Photo updated.", "photo_filename": filename})


@app.route("/api/profile-layout", methods=["GET"])
def get_profile_layout():
    scientist_id = _get_scientist_id()
    db = get_db()
    row = db.execute("SELECT config FROM profile_layout WHERE scientist_id = ?", (scientist_id,)).fetchone()
    if row:
        return jsonify(json.loads(row["config"]))
    return jsonify({})


@app.route("/api/profile-layout", methods=["PUT"])
@require_auth
def save_profile_layout():
    scientist_id = _get_scientist_id()
    _enforce_scientist_scope(scientist_id)
    data = request.get_json(force=True)
    data.pop("scientist_id", None)
    db = get_db()
    config_json = json.dumps(data)
    db.execute(
        "INSERT INTO profile_layout (scientist_id, config) VALUES (?, ?) "
        "ON CONFLICT(scientist_id) DO UPDATE SET config = excluded.config",
        (scientist_id, config_json),
    )
    db.commit()
    return jsonify({"message": "Layout saved."})


SCIENTISTS_SEED = [
    {
        "slug": "yeasin",
        "name": "Dr. Md Yeasin",
        "designation": "Scientist",
        "institute": "ICAR-Indian Agricultural Statistics Research Institute (IASRI)",
        "address": "304, TAC Building, ICAR-IASRI, Library Avenue, New Delhi-110012",
        "dob": "27th January 1994",
        "mobile": ["8926261427", "9136309898"],
        "email": ["yeasin.iasri@gmail.com", "mdyeasin.iasri@icar.org.in"],
        "research_interest": [
            "Time series and machine learning models for agriculture and allied sciences",
            "Modelling and forecasting temporal behaviour of environmental parameters",
            "Quantifying the effect of environmental change on agricultural productivity and sustainability",
        ],
        "education": [
            {"degree": "Ph.D. in Agricultural Statistics", "year": "2021", "institution": "ICAR-Indian Agricultural Research Institute"},
            {"degree": "M.Sc. in Agricultural Statistics", "year": "2017", "institution": "ICAR-Indian Agricultural Research Institute"},
            {"degree": "Graduation in Agriculture", "year": "2015", "institution": "Visva-Bharati (A Central University)"},
            {"degree": "Higher Secondary (12th)", "year": "2011", "institution": "West Bengal Council of Higher Secondary Education (from MPV)"},
            {"degree": "Secondary (10th)", "year": "2009", "institution": "West Bengal Board of Secondary Education (from CHS)"},
        ],
        "accolades": [
            "Successfully qualified UGC-NET 2017",
            "Successfully qualified ICAR-NET 2017 and 2018",
            "Successfully qualified IARI-SRF 2017 from ICAR, Government of India",
            "Successfully qualified IARI-JRF 2015 from ICAR, Government of India",
            "Got National Fellowship for OBC (NFOBC) 2018",
            "Got Maulana Azad Fellowship Scheme (MANF) in 2018",
        ],
        "employment": [
            {"period": "Jan 2021 - till date", "role": "Scientist (Agricultural Statistics)", "institution": "Indian Agricultural Statistics Research Institute (IASRI), New Delhi, India"},
            {"period": "Oct 2020 - Jan 2021", "role": "Scientist (Agricultural Statistics)", "institution": "National Academy of Agricultural Research Management (NAARM), Hyderabad, India"},
        ],
        "other_records": [
            "Selected in ISS (Indian Statistical Service)-UPSC in 2019.",
            "Selected as Assistant Professor by West Bengal College Service Commission in 2018.",
        ],
        "photo_filename": "yeasin-photo.png",
        "scholar_url": "https://scholar.google.com/citations?user=xejMKD0AAAAJ&hl=en&oi=sra",
        "linkedin_url": "https://www.linkedin.com/in/dr-yeasin/",
    },
    {
        "slug": "ranjit",
        "name": "Dr. Ranjit Kumar Paul",
        "designation": "ICAR NATIONAL FELLOW",
        "institute": "ICAR-Indian Agricultural Statistics Research Institute (IASRI)",
        "address": "Library Avenue, PUSA, New Delhi, India-110012",
        "dob": "25th April 1982",
        "mobile": ["+91-8287778896"],
        "email": ["ranjitstat@gmail.com", "ranjit.paul@icar.gov.in"],
        "research_interest": [
            "Time series analysis and forecasting for agriculture",
            "Nonlinear models (GARCH/EGARCH), wavelet-based and hybrid machine learning methods",
            "Agricultural price and yield forecasting, market integration, and climate variability",
        ],
        "education": [
            {"degree": "Ph.D. in Agricultural Statistics", "year": "2009", "institution": "Indian Agricultural Statistics Research Institute (IASRI)"},
            {"degree": "M.Sc. in Agricultural Statistics", "year": "2006", "institution": "Indian Agricultural Statistics Research Institute (IASRI)"},
            {"degree": "B.Sc. in Agriculture", "year": "2004", "institution": "Uttar Banga Krishi Viswavidyalaya"},
            {"degree": "Higher Secondary", "year": "2000", "institution": "West Bengal Council of Higher Secondary Education"},
            {"degree": "Secondary", "year": "1998", "institution": "West Bengal Board of Secondary Education"},
        ],
        "accolades": [
            "Fellow of National Academy of Agricultural Sciences (NAAS), since 2018",
            "Fellow of Indian Society of Agricultural Statistics, since 2022",
            "Fellow of Agricultural Economics Research Association, since 2025",
            "ICAR Lal Bahadur Shastri Outstanding Young Scientist Award in Social Sciences, 2016",
        ],
        "employment": [
            {"period": "May 2011 - till date", "role": "Scientist (Agricultural Statistics)", "institution": "Indian Agricultural Statistics Research Institute (IASRI), New Delhi, India"},
            {"period": "Oct 2009 - Apr 2011", "role": "Scientist (Agricultural Statistics)", "institution": "Central Inland Fisheries Research Institute (CIFRI), Kolkata, India"},
            {"period": "Jun 2009 - Oct 2009", "role": "Scientist (Agricultural Statistics)", "institution": "National Academy of Agricultural Research Management (NAARM), Hyderabad, India"},
        ],
        "other_records": [
            "Previously served in the Indian Statistical Service, Central Statistical Organization, Ministry of Statistics and Programme Implementation, Government of India.",
        ],
        "photo_filename": "ranjit-photo.png",
        "scholar_url": "https://scholar.google.com/citations?user=wBWuZJgAAAAJ&hl=en&oi=ao",
        "linkedin_url": "https://www.linkedin.com/in/ranjit-kumar-paul-72b42320/",
    },
]


# ---------------------------------------------------------------------------
# Simple CRUD for the other CV sections: Awards, Projects, Book Chapters,
# Software/Packages. Same pattern as Papers (public GET, admin-only
# add/edit/delete) but without domain/hide logic, since those are specific
# to the Papers table.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# CRAN auto-fill — given just a CRAN package URL, fetches Package Name,
# Reference (citation-style string), and Year automatically via the
# unofficial but widely-used crandb.r-pkg.org metadata API, so the admin
# doesn't have to type them in by hand.
# ---------------------------------------------------------------------------
def _fetch_cran_metadata(cran_url: str):
    """Returns {package_name, reference, year} for a CRAN URL, or None if it can't be resolved."""
    import urllib.request

    m = re.search(r"[/?&]package=([A-Za-z0-9.]+)", cran_url) or re.search(r"/packages?/([A-Za-z0-9.]+)", cran_url)
    if not m:
        return None
    pkg = m.group(1)

    req = urllib.request.Request(
        f"https://crandb.r-pkg.org/{pkg}",
        headers={"User-Agent": "AcademicIMS/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    title = (data.get("Title") or "").strip()
    version = data.get("Version", "")
    date_published = data.get("Date/Published", "") or data.get("Packaged", "")
    year = date_published[:4] if date_published else ""

    author_raw = data.get("Author", "") or ""
    authors_clean = re.sub(r"\[[^\]]*\]", "", author_raw)  # strip [aut, cre] role tags
    authors_clean = re.sub(r"\s+", " ", authors_clean).strip().strip(",")

    parts = []
    if authors_clean:
        parts.append(authors_clean)
    if year:
        parts.append(f"({year}).")
    parts.append(f"{pkg}: {title} (R package version {version}).")
    parts.append(cran_url)
    reference = " ".join(parts).strip()

    return {"package_name": pkg, "reference": reference, "year": year}


def _fetch_cran_downloads(package_name: str):
    """
    Returns the all-time total download count for a CRAN package (int),
    or None if it can't be fetched. Uses the same official RStudio/R-hub
    CRAN download-logs API (cranlogs.r-pkg.org) that CRAN's own "grand
    total downloads" badges use — total since October 2012, when this
    logging began.
    """
    import urllib.request
    import urllib.parse
    import datetime

    if not package_name:
        return None
    today = datetime.date.today().isoformat()
    pkg = urllib.parse.quote(package_name)
    url = f"https://cranlogs.r-pkg.org/downloads/total/2012-10-01:{today}/{pkg}"
    req = urllib.request.Request(url, headers={"User-Agent": "AcademicIMS/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if isinstance(data, list) and data and "downloads" in data[0]:
            return int(data[0]["downloads"])
    except Exception:
        pass
    return None


@app.route("/api/software/update-downloads", methods=["POST"])
@require_auth
def update_software_downloads():
    """Refreshes the Downloads count for every software package from CRAN's live download logs."""
    scientist_id = _get_scientist_id()
    _enforce_scientist_scope(scientist_id)
    db = get_db()
    rows = db.execute("SELECT software_id, package_name FROM software WHERE scientist_id = ? AND package_name != ''", (scientist_id,)).fetchall()
    updated, failed = 0, 0
    for r in rows:
        count = _fetch_cran_downloads(r["package_name"])
        if count is not None:
            db.execute("UPDATE software SET downloads = ? WHERE software_id = ?", (f"{count:,}", r["software_id"]))
            updated += 1
        else:
            failed += 1
        time.sleep(0.3)  # be polite to the public API
    db.commit()
    return jsonify({
        "message": f"Updated download counts for {updated} package(s)." + (f" {failed} could not be fetched." if failed else ""),
        "updated": updated,
        "failed": failed,
    })


SIMPLE_TABLES = {
    "awards": {
        "id_col": "award_id",
        "columns": ["title", "awarding_body", "year", "description"],
        "order_by": "year DESC",
    },
    "projects": {
        "id_col": "project_id",
        "columns": ["investigators", "project_title", "funding_agency", "date_start", "date_end", "status"],
        "order_by": "date_start DESC",
    },
    "book-chapters": {
        "table": "book_chapters",
        "id_col": "book_chapter_id",
        "columns": ["title", "authors", "editor", "book_title", "publisher", "year", "pages", "isbn", "doi"],
        "order_by": "year DESC",
    },
    "software": {
        "id_col": "software_id",
        "columns": ["package_name", "reference", "year", "downloads", "cran_url"],
        "order_by": "year DESC",
    },
    "courses-taught": {
        "table": "courses_taught",
        "id_col": "course_id",
        "columns": ["course_name"],
        "order_by": "course_id ASC",
    },
    "students-guided": {
        "table": "students_guided",
        "id_col": "student_id",
        "columns": ["name", "student_type", "start_date", "end_date", "description"],
        "order_by": "start_date DESC",
    },
    "technology": {
        "table": "technology",
        "id_col": "tech_id",
        "columns": ["category", "authors", "year", "title", "id_number"],
        "order_by": "tech_id ASC",
    },
    "popular-articles": {
        "table": "popular_articles",
        "id_col": "article_id",
        "columns": ["authors", "year", "title", "publication", "details"],
        "order_by": "article_id ASC",
    },
    "policy-papers": {
        "table": "policy_papers",
        "id_col": "paper_id",
        "columns": ["authors", "year", "title", "publisher", "id_number"],
        "order_by": "paper_id ASC",
    },
    "manuals": {
        "table": "manuals",
        "id_col": "manual_id",
        "columns": ["authors", "year", "title", "publisher"],
        "order_by": "manual_id ASC",
    },
}


def _register_simple_crud(endpoint_name, config):
    table = config.get("table", endpoint_name.replace("-", "_"))
    id_col = config["id_col"]
    columns = config["columns"]
    order_by = config["order_by"]

    def list_items():
        db = get_db()
        scientist_id = _get_scientist_id()
        hidden_clause = "AND hidden = 0" if not is_admin_request() else ""
        rows = db.execute(f"SELECT * FROM {table} WHERE scientist_id = ? {hidden_clause} ORDER BY {order_by}", (scientist_id,)).fetchall()
        return jsonify([dict(r) for r in rows])

    def add_item():
        data = request.get_json(force=True)
        db = get_db()
        scientist_id = _get_scientist_id()
        _enforce_scientist_scope(scientist_id)
        if table == "software" and data.get("cran_url") and not data.get("package_name"):
            meta = _fetch_cran_metadata(data["cran_url"])
            if meta:
                data["package_name"] = meta["package_name"]
                data["reference"] = data.get("reference") or meta["reference"]
                data["year"] = data.get("year") or meta["year"]
        vals = [data.get(c, "") for c in columns] + [scientist_id]
        all_cols = columns + ["scientist_id"]
        placeholders = ",".join(["?"] * len(all_cols))
        cur = db.execute(f"INSERT INTO {table} ({','.join(all_cols)}) VALUES ({placeholders})", vals)
        db.commit()
        return jsonify({"message": "Added.", "id": cur.lastrowid}), 201

    def update_item(item_id):
        data = request.get_json(force=True)
        db = get_db()
        owner = db.execute(f"SELECT scientist_id FROM {table} WHERE {id_col} = ?", (item_id,)).fetchone()
        if not owner:
            return jsonify({"error": "Not found."}), 404
        _enforce_scientist_scope(owner["scientist_id"])
        if table == "software" and data.get("cran_url") and not data.get("package_name"):
            meta = _fetch_cran_metadata(data["cran_url"])
            if meta:
                data["package_name"] = meta["package_name"]
                data["reference"] = data.get("reference") or meta["reference"]
                data["year"] = data.get("year") or meta["year"]
        updates, params = [], []
        for c in columns:
            if c in data:
                updates.append(f"{c} = ?")
                params.append(data[c])
        if not updates:
            return jsonify({"error": "No fields to update."}), 400
        params.append(item_id)
        db.execute(f"UPDATE {table} SET {', '.join(updates)} WHERE {id_col} = ?", params)
        db.commit()
        return jsonify({"message": "Updated."})

    def delete_item(item_id):
        db = get_db()
        owner = db.execute(f"SELECT scientist_id FROM {table} WHERE {id_col} = ?", (item_id,)).fetchone()
        if not owner:
            return jsonify({"error": "Not found."}), 404
        _enforce_scientist_scope(owner["scientist_id"])
        db.execute(f"DELETE FROM {table} WHERE {id_col} = ?", (item_id,))
        db.commit()
        return jsonify({"message": "Deleted."})

    def toggle_hidden(item_id):
        db = get_db()
        row = db.execute(f"SELECT hidden, scientist_id FROM {table} WHERE {id_col} = ?", (item_id,)).fetchone()
        if not row:
            return jsonify({"error": "Not found."}), 404
        _enforce_scientist_scope(row["scientist_id"])
        new_val = 0 if row["hidden"] else 1
        db.execute(f"UPDATE {table} SET hidden = ? WHERE {id_col} = ?", (new_val, item_id))
        db.commit()
        return jsonify({"message": "Hidden." if new_val else "Visible again.", "hidden": bool(new_val)})

    def toggle_cv_included(item_id):
        db = get_db()
        row = db.execute(f"SELECT cv_included, scientist_id FROM {table} WHERE {id_col} = ?", (item_id,)).fetchone()
        if not row:
            return jsonify({"error": "Not found."}), 404
        _enforce_scientist_scope(row["scientist_id"])
        new_val = 0 if row["cv_included"] else 1
        db.execute(f"UPDATE {table} SET cv_included = ? WHERE {id_col} = ?", (new_val, item_id))
        db.commit()
        return jsonify({"message": "Added to CV." if new_val else "Removed from CV.", "cv_included": bool(new_val)})

    app.add_url_rule(f"/api/{endpoint_name}", f"list_{table}", list_items, methods=["GET"])
    app.add_url_rule(f"/api/{endpoint_name}", f"add_{table}", require_auth(add_item), methods=["POST"])
    app.add_url_rule(f"/api/{endpoint_name}/<int:item_id>", f"update_{table}", require_auth(update_item), methods=["PUT"])
    app.add_url_rule(f"/api/{endpoint_name}/<int:item_id>", f"delete_{table}", require_auth(delete_item), methods=["DELETE"])
    app.add_url_rule(f"/api/{endpoint_name}/<int:item_id>/toggle-hidden", f"toggle_{table}", require_auth(toggle_hidden), methods=["POST"])
    app.add_url_rule(f"/api/{endpoint_name}/<int:item_id>/toggle-cv-included", f"toggle_cv_{table}", require_auth(toggle_cv_included), methods=["POST"])


for _endpoint, _config in SIMPLE_TABLES.items():
    _register_simple_crud(_endpoint, _config)


# ---------------------------------------------------------------------------
# Journal scores (Impact Factor / NAAS score / JID) — PDF-linked lookup
# table. Upload the official NAAS list and/or JCR list once a year (as
# published PDFs) and every paper's Impact Factor / Quartile / NAAS Score
# is refreshed automatically, matched primarily by ISSN.
# ---------------------------------------------------------------------------
def _norm_journal(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def _norm_issn(issn: str) -> str:
    issn = (issn or "").strip().upper()
    return issn if re.match(r"^\d{4}-\d{3}[\dX]$", issn) else ""


NAAS_LINE_RE = re.compile(r"^\d+\s+(\S+)\s+(\d{4}-\d{3}[\dXx])\s+(.+?)\s+([\d.]+)$")

# JCR rows vary in shape: full row (both JIF years + quartile), a row
# missing last year's JIF, or a row with no usable JIF at all (skipped).
JCR_LINE_FULL_RE = re.compile(
    r"^(.+?)\s+(\d{4}-\d{3}[\dXx]|N/A)\s+([A-Za-z, ]+?)\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+(Q\d|N/A)$"
)
JCR_LINE_SHORT_RE = re.compile(
    r"^(.+?)\s+(\d{4}-\d{3}[\dXx]|N/A)\s+([A-Za-z, ]+?)\s+(\d+)\s+([\d.]+)\s+(Q\d|N/A)$"
)


PDF_CHUNK_SIZE = 50  # pages per pdfplumber.open() cycle — keeps memory bounded on low-RAM hosts


def _iter_pdf_lines(pdf_path):
    """
    Yields every text line from every page of a PDF, processing pages in
    small batches and re-opening the document between batches. This keeps
    peak memory flat regardless of PDF size — pdfplumber otherwise
    accumulates internal caches across the whole document that
    page.flush_cache() alone doesn't fully release, which was blowing past
    Render free tier's 512MB limit on large files (confirmed: ~530MB for a
    43-page file without this, vs. ~190MB for a 731-page file with it).
    """
    import pdfplumber
    import gc

    with pdfplumber.open(pdf_path) as probe:
        total_pages = len(probe.pages)

    for start in range(0, total_pages, PDF_CHUNK_SIZE):
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages[start:start + PDF_CHUNK_SIZE]:
                text = page.extract_text() or ""
                page.flush_cache()
                for line in text.split("\n"):
                    yield line
        gc.collect()


def _parse_naas_pdf(file_stream):
    """Returns a list of {issn, jid, journal_name, naas_score} dicts."""
    import tempfile
    import os
    results = []
    tmp_fd = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp_path = tmp_fd.name
    tmp_fd.close()  # release the handle before writing — NamedTemporaryFile keeps
                     # its own handle open, which Windows won't let a second writer
                     # (file_stream.save) touch; this bug never showed up on Linux/Render.
    try:
        file_stream.save(tmp_path)
        for line in _iter_pdf_lines(tmp_path):
            m = NAAS_LINE_RE.match(line.strip())
            if not m:
                continue
            jid, issn, name, score = m.groups()
            results.append({
                "issn": _norm_issn(issn), "jid": jid,
                "journal_name": name.strip(), "naas_score": score,
            })
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return results


def _parse_jcr_pdf(file_stream):
    """Returns a list of {issn, journal_name, impact_factor, quartile} dicts."""
    import tempfile
    import os
    results = []
    tmp_fd = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp_path = tmp_fd.name
    tmp_fd.close()
    try:
        file_stream.save(tmp_path)
        for line in _iter_pdf_lines(tmp_path):
            line = line.strip()
            m = JCR_LINE_FULL_RE.match(line)
            if m:
                name, issn, _index, _cit, jif_latest, _jif_prev, quartile = m.groups()
            else:
                m = JCR_LINE_SHORT_RE.match(line)
                if not m:
                    continue
                name, issn, _index, _cit, jif_latest, quartile = m.groups()
            results.append({
                "issn": _norm_issn(issn), "journal_name": name.strip(),
                "impact_factor": jif_latest,
                "quartile": quartile if quartile != "N/A" else "",
            })
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return results


def _apply_naas_fallback_formula(db):
    """
    For any journal with a known Impact Factor but no NAAS score on file,
    estimate one as NAAS = min(6.0 + Impact Factor, 20.0), per NAAS
    convention for newly-indexed journals.
    """
    rows = db.execute(
        "SELECT id, impact_factor FROM journal_scores WHERE (naas_score IS NULL OR naas_score = '') AND impact_factor != ''"
    ).fetchall()
    for r in rows:
        try:
            jif = float(r["impact_factor"])
        except (TypeError, ValueError):
            continue
        estimated = round(min(6.0 + jif, 20.0), 2)
        db.execute("UPDATE journal_scores SET naas_score = ? WHERE id = ?", (str(estimated), r["id"]))
    if rows:
        db.commit()
    return len(rows)


@app.route("/api/journal-scores", methods=["GET"])
def list_journal_scores():
    db = get_db()
    rows = db.execute("SELECT * FROM journal_scores ORDER BY journal_name").fetchall()
    return jsonify([dict(r) for r in rows])


def _upsert_journal_score(db, journal_name, issn="", jid="", impact_factor="", naas_score="", quartile=""):
    """
    Upserts into journal_scores. Matches on ISSN when available (most
    reliable, since journal names get renamed/abbreviated differently
    across lists); falls back to matching on normalized journal name.
    """
    existing = None
    if issn:
        existing = db.execute("SELECT id FROM journal_scores WHERE issn = ?", (issn,)).fetchone()
    if not existing:
        existing = db.execute(
            "SELECT id FROM journal_scores WHERE lower(journal_name) = lower(?)", (journal_name,)
        ).fetchone()

    if existing:
        updates, params = [], []
        if issn:
            updates.append("issn = ?"); params.append(issn)
        if jid:
            updates.append("jid = ?"); params.append(jid)
        if impact_factor:
            updates.append("impact_factor = ?"); params.append(impact_factor)
        if naas_score:
            updates.append("naas_score = ?"); params.append(naas_score)
        if quartile:
            updates.append("quartile = ?"); params.append(quartile)
        updates.append("updated_at = datetime('now')")
        params.append(existing["id"])
        db.execute(f"UPDATE journal_scores SET {', '.join(updates)} WHERE id = ?", params)
    else:
        db.execute(
            """INSERT INTO journal_scores (journal_name, issn, jid, impact_factor, naas_score, quartile, updated_at)
               VALUES (?,?,?,?,?,?, datetime('now'))""",
            (journal_name, issn, jid, impact_factor, naas_score, quartile),
        )


@app.route("/api/journal-scores/upload-naas", methods=["POST"])
@require_auth
def upload_naas_scores():
    """Accepts the official NAAS 'Score of Science Journals' PDF and loads it into journal_scores."""
    _require_super_admin()
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded (expected form field 'file')."}), 400
    file = request.files["file"]

    try:
        rows = _parse_naas_pdf(file)
    except Exception as e:
        return jsonify({"error": f"Could not read the NAAS PDF: {e}"}), 400

    if not rows:
        return jsonify({"error": "No journal rows could be parsed from this PDF. Is it the NAAS Score list?"}), 400

    db = get_db()
    for r in rows:
        _upsert_journal_score(db, r["journal_name"], issn=r["issn"], jid=r["jid"], naas_score=r["naas_score"])
    db.commit()

    updated_papers = _apply_journal_scores_to_papers(db)
    return jsonify({
        "message": f"Loaded {len(rows)} journal(s) from the NAAS list. Updated {updated_papers} paper(s).",
        "loaded": len(rows),
        "papers_updated": updated_papers,
    })


@app.route("/api/journal-scores/upload-jcr", methods=["POST"])
@require_auth
def upload_jcr_scores():
    """
    Accepts the JCR 'Journal Impact Factor' PDF (hundreds of pages, can take
    several minutes to process) and runs the parsing/loading in a background
    thread instead of one long HTTP request — this sidesteps every kind of
    request-duration limit (gunicorn's own --timeout, and any proxy/load
    balancer limit in front of it on hosts like Render) rather than trying
    to out-guess how long is "long enough". The frontend polls
    /api/journal-scores/upload-status/<job_id> for progress.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded (expected form field 'file')."}), 400
    _require_super_admin()
    file = request.files["file"]

    import tempfile
    tmp_fd = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp_path = tmp_fd.name
    tmp_fd.close()
    file.save(tmp_path)

    job_id = str(uuid.uuid4())
    JCR_JOBS[job_id] = {"status": "processing", "message": "Parsing PDF... this can take a few minutes."}

    thread = threading.Thread(target=_run_jcr_job, args=(job_id, tmp_path), daemon=True)
    thread.start()

    return jsonify({"job_id": job_id}), 202


def _run_jcr_job(job_id, tmp_path):
    import os
    try:
        rows = []
        for line in _iter_pdf_lines(tmp_path):
            line = line.strip()
            m = JCR_LINE_FULL_RE.match(line)
            if m:
                name, issn, _index, _cit, jif_latest, _jif_prev, quartile = m.groups()
            else:
                m = JCR_LINE_SHORT_RE.match(line)
                if not m:
                    continue
                name, issn, _index, _cit, jif_latest, quartile = m.groups()
            rows.append({
                "issn": _norm_issn(issn), "journal_name": name.strip(),
                "impact_factor": jif_latest,
                "quartile": quartile if quartile != "N/A" else "",
            })

        if not rows:
            JCR_JOBS[job_id] = {"status": "error", "message": "No journal rows could be parsed from this PDF. Is it the JCR Impact Factor list?"}
            return

        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        for r in rows:
            _upsert_journal_score(conn, r["journal_name"], issn=r["issn"], impact_factor=r["impact_factor"], quartile=r["quartile"])
        conn.commit()

        naas_estimated = _apply_naas_fallback_formula(conn)
        updated_papers = _apply_journal_scores_to_papers(conn)
        conn.close()

        JCR_JOBS[job_id] = {
            "status": "done",
            "message": (
                f"Loaded {len(rows)} journal(s) from the JCR list. "
                f"Estimated a NAAS score for {naas_estimated} journal(s) with no official NAAS rating. "
                f"Updated {updated_papers} paper(s)."
            ),
            "loaded": len(rows),
            "naas_estimated": naas_estimated,
            "papers_updated": updated_papers,
        }
    except Exception as e:
        JCR_JOBS[job_id] = {"status": "error", "message": f"Could not process the JCR PDF: {e}"}
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@app.route("/api/journal-scores/upload-status/<job_id>", methods=["GET"])
@require_auth
def jcr_upload_status(job_id):
    job = JCR_JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Unknown job (the server may have restarted since it started)."}), 404
    return jsonify(job)


def _apply_journal_scores_to_papers(db):
    """
    Refreshes every paper's Impact Factor / Quartile / NAAS Score / ISSN
    from journal_scores, matching by ISSN first (most reliable), falling
    back to normalized journal name.
    """
    scores = db.execute("SELECT journal_name, issn, impact_factor, naas_score, quartile FROM journal_scores").fetchall()
    by_issn = {r["issn"]: r for r in scores if r["issn"]}
    by_name = {_norm_journal(r["journal_name"]): r for r in scores}

    papers = db.execute("SELECT publication_id, journal, issn FROM papers").fetchall()
    updated = 0
    for p in papers:
        match = by_issn.get(_norm_issn(p["issn"])) if p["issn"] else None
        if not match:
            match = by_name.get(_norm_journal(p["journal"]))
        if not match:
            continue

        new_if = match["impact_factor"]
        new_naas = match["naas_score"]
        new_quartile = match["quartile"] or ("NAAS" if new_naas and not new_if else "")
        new_issn = match["issn"]

        if new_if or new_naas or new_quartile or new_issn:
            db.execute(
                "UPDATE papers SET "
                "impact_factor = COALESCE(NULLIF(?, ''), impact_factor), "
                "naas_score = COALESCE(NULLIF(?, ''), naas_score), "
                "quartile = COALESCE(NULLIF(?, ''), quartile), "
                "issn = COALESCE(NULLIF(issn, ''), NULLIF(?, '')) "
                "WHERE publication_id = ?",
                (new_if, new_naas, new_quartile, new_issn, p["publication_id"]),
            )
            updated += 1
    db.commit()
    return updated


@app.route("/api/database/export-backup", methods=["GET"])
@require_auth
def export_database_backup():
    """
    Downloads a complete, self-contained copy of the live database — every
    publication, award, project, book chapter, software entry, hidden flag,
    and journal score, exactly as it currently stands. Save this as
    backend/research_backup.db and commit it to your repo: on the next
    deploy (a fresh, empty disk), the server automatically restores from
    this file instead of reseeding from scratch, so nothing is lost — not
    just NAAS/JCR data, but any admin edit at all. This is the more
    complete alternative to the journal-scores-only snapshot.
    """
    db = get_db()
    _require_super_admin()
    # Merge the WAL file into the main database file so the exported copy
    # is complete and self-contained — without this, recent writes could
    # still be sitting only in research.db-wal and get left out.
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db.commit()

    from flask import send_file
    return send_file(
        DB_PATH, mimetype="application/octet-stream", as_attachment=True,
        download_name="research_backup.db",
    )


@app.route("/api/journal-scores/export-snapshot", methods=["GET"])
@require_auth
def export_journal_scores_snapshot():
    """
    Downloads the currently-loaded journal scores plus every paper's
    resulting Impact Factor / Quartile / NAAS Score / ISSN as one JSON file.
    Save this as backend/journal_scores_snapshot.json and commit it to your
    repo — the server automatically reloads it on every startup (see
    init_db), so your NAAS/JCR data survives future deploys on Render's free
    tier instead of resetting each time. Re-export and re-commit whenever
    you upload updated NAAS/JCR files (e.g. once a year).
    """
    db = get_db()
    _require_super_admin()
    scores = db.execute("SELECT journal_name, issn, jid, impact_factor, naas_score, quartile FROM journal_scores").fetchall()
    papers = db.execute(
        "SELECT title, impact_factor, quartile, naas_score, issn FROM papers "
        "WHERE impact_factor != '' OR quartile != '' OR naas_score != '' OR issn != ''"
    ).fetchall()

    snapshot = {
        "journal_scores": [dict(r) for r in scores],
        "paper_overrides": [dict(r) for r in papers],
    }

    from flask import Response
    return Response(
        json.dumps(snapshot, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=journal_scores_snapshot.json"},
    )


def _load_journal_scores_snapshot(conn):
    """
    If backend/journal_scores_snapshot.json exists (committed to the repo
    via the export-snapshot endpoint), reload it into journal_scores and
    re-apply it to papers. Runs on every startup — this is what makes
    uploaded NAAS/JCR data survive a fresh Render deploy, since the repo
    (unlike the runtime disk) isn't wiped between deploys.
    """
    snapshot_path = os.path.join(BASE_DIR, "journal_scores_snapshot.json")
    if not os.path.exists(snapshot_path):
        return

    with open(snapshot_path, encoding="utf-8") as f:
        snapshot = json.load(f)

    for r in snapshot.get("journal_scores", []):
        _upsert_journal_score(
            conn, r.get("journal_name", ""), issn=r.get("issn", ""), jid=r.get("jid", ""),
            impact_factor=r.get("impact_factor", ""), naas_score=r.get("naas_score", ""),
            quartile=r.get("quartile", ""),
        )
    conn.commit()

    by_title = {r["title"].strip().lower(): r for r in snapshot.get("paper_overrides", [])}
    papers = conn.execute("SELECT publication_id, title FROM papers").fetchall()
    for p in papers:
        override = by_title.get((p["title"] or "").strip().lower())
        if not override:
            continue
        conn.execute(
            "UPDATE papers SET "
            "impact_factor = COALESCE(NULLIF(?, ''), impact_factor), "
            "quartile = COALESCE(NULLIF(?, ''), quartile), "
            "naas_score = COALESCE(NULLIF(?, ''), naas_score), "
            "issn = COALESCE(NULLIF(issn, ''), NULLIF(?, '')) "
            "WHERE publication_id = ?",
            (override.get("impact_factor", ""), override.get("quartile", ""),
             override.get("naas_score", ""), override.get("issn", ""), p["publication_id"]),
        )
    conn.commit()


@app.route("/api/journal-scores/apply", methods=["POST"])
@require_auth
def apply_journal_scores():
    """Re-applies the currently-loaded journal_scores table to all papers (no new upload)."""
    db = get_db()
    updated = _apply_journal_scores_to_papers(db)
    return jsonify({"message": f"Refreshed Impact Factor/Quartile/NAAS on {updated} paper(s) from the journal scores table.", "papers_updated": updated})


@app.route("/api/journal-scores/reset", methods=["POST"])
@require_auth
def reset_journal_scores():
    """
    Restores every paper's Impact Factor / Quartile back to the original
    values from your CV (papers_seed.json), clears NAAS Score, and wipes
    the journal_scores lookup table entirely. Use this before re-doing a
    clean NAAS + JCR upload — without it, repeated uploads (especially ones
    that were interrupted mid-way during earlier debugging) can leave a mix
    of values from different runs instead of one clean, trustworthy set.
    """
    db = get_db()
    _require_super_admin()

    with open(SEED_PATH, encoding="utf-8") as f:
        seed_records = json.load(f)
    by_title = {r["title"].strip().lower(): r for r in seed_records}

    papers = db.execute("SELECT publication_id, title FROM papers").fetchall()
    reset_count = 0
    for p in papers:
        seed = by_title.get((p["title"] or "").strip().lower())
        if not seed:
            continue
        db.execute(
            "UPDATE papers SET impact_factor = ?, quartile = ?, naas_score = '' WHERE publication_id = ?",
            (seed.get("impact_factor", ""), seed.get("quartile", ""), p["publication_id"]),
        )
        reset_count += 1

    db.execute("DELETE FROM journal_scores")
    db.commit()

    return jsonify({
        "message": f"Reset {reset_count} paper(s) to their original CV values and cleared the journal scores table. Now re-upload NAAS, then JCR, for a clean result.",
        "reset_count": reset_count,
    })


# ---------------------------------------------------------------------------
# CV download — admin picks which sections to include (Publications,
# Awards, Projects, Book Chapters, Software) and gets back a generated,
# styled PDF. Uses reportlab (pure Python, no system graphics libraries
# required) so it works the same locally and on minimal hosts like Render.
# ---------------------------------------------------------------------------
def _build_cv_pdf(scientist_id=1):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, HRFlowable
    )
    import io
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # Some content (Popular Articles, Manuals) may be in Hindi/Devanagari
    # script. ReportLab's built-in fonts (Times/Helvetica) have no glyphs for
    # this — without a Unicode font registered, that text silently renders as
    # garbled placeholder characters instead of failing loudly, so this is
    # easy to miss. Noto Sans Devanagari also covers Latin script, so it's
    # safe to use for any section that might mix English and Hindi entries.
    _unicode_font_path = os.path.join(BASE_DIR, "NotoSansDevanagari.ttf")
    _unicode_font_name = "Helvetica"  # fallback if the font file is missing
    if os.path.exists(_unicode_font_path):
        try:
            pdfmetrics.registerFont(TTFont("NotoDevanagari", _unicode_font_path))
            _unicode_font_name = "NotoDevanagari"
        except Exception:
            pass

    def esc(s):
        """Escapes text for ReportLab's Paragraph markup parser — without this,
        a literal '&' (e.g. 'Journal of X & Y') or '<'/'>' anywhere in real
        bibliographic data breaks the parser with 'unclosed tags'."""
        if s is None:
            return ""
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    ink = colors.HexColor("#1C2B39")
    olive = colors.HexColor("#454F32")
    slate = colors.HexColor("#6B7280")
    line = colors.HexColor("#DCD5C4")

    name_style = ParagraphStyle("name", fontName="Times-Bold", fontSize=22, textColor=ink, leading=26)
    role_style = ParagraphStyle("role", fontName="Helvetica-Bold", fontSize=11, textColor=olive, spaceAfter=2)
    small_style = ParagraphStyle("small", fontName="Helvetica", fontSize=8.5, textColor=slate, leading=12)
    h2_style = ParagraphStyle("h2", fontName="Times-Bold", fontSize=14, textColor=ink, spaceBefore=14, spaceAfter=6)
    body_style = ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, textColor=colors.HexColor("#1C2B39"), leading=13.5)
    meta_style = ParagraphStyle("meta", fontName="Helvetica-Oblique", fontSize=8.5, textColor=slate, leading=12, spaceAfter=8)
    entry_title_style = ParagraphStyle("entry_title", fontName="Helvetica-Bold", fontSize=9.5, textColor=ink, leading=13, spaceBefore=6)
    unicode_body_style = ParagraphStyle("unicode_body", fontName=_unicode_font_name, fontSize=9.5, textColor=colors.HexColor("#1C2B39"), leading=15)

    db = get_db()

    sci_row = db.execute("SELECT * FROM scientists WHERE scientist_id = ?", (scientist_id,)).fetchone()
    if not sci_row:
        raise ValueError(f"No scientist with id {scientist_id}")
    p = dict(sci_row)
    for key in ("mobile", "email", "education", "accolades", "employment", "other_records", "current_work"):
        p[key] = json.loads(p[key]) if p[key] else []
    try:
        p["research_interest"] = json.loads(p["research_interest"]) if p["research_interest"] else []
    except (json.JSONDecodeError, TypeError):
        p["research_interest"] = [p["research_interest"]] if p["research_interest"] else []

    # ---- Read the saved Home-tab tick state (profile_layout.config) ----
    layout_row = db.execute("SELECT config FROM profile_layout WHERE scientist_id = ?", (scientist_id,)).fetchone()
    layout = json.loads(layout_row["config"]) if layout_row else {}
    cv_blocks = layout.get("cv_blocks")  # None = not yet configured -> include everything
    cv_items = layout.get("cv_items", {})

    def block_included(block_id):
        return True if cv_blocks is None else (block_id in cv_blocks)

    def item_included(block_key, idx):
        cfg = cv_items.get(block_key)
        return True if cfg is None else (idx in cfg)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=18 * mm, bottomMargin=18 * mm, leftMargin=18 * mm, rightMargin=18 * mm,
    )
    story = []

    # ---- Header block (photo + name/role/address) ----
    if block_included("header"):
        photo_path = os.path.join(FRONTEND_DIR, p.get("photo_filename") or "yeasin-photo.png")
        header_cells = []
        if os.path.exists(photo_path):
            try:
                header_cells.append(Image(photo_path, width=30 * mm, height=30 * mm))
            except Exception:
                header_cells.append("")
        else:
            header_cells.append("")

        info_flow = [
            Paragraph(esc(p["name"]), name_style),
            Paragraph(f"{esc(p['designation'])} &middot; {esc(p['institute'])}", role_style),
            Paragraph(esc(p.get("address", "")), small_style),
        ]
        header_cells.append(info_flow)

        header_table = Table([header_cells], colWidths=[35 * mm, None])
        header_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (0, 0), 0),
            ("LEFTPADDING", (1, 0), (1, 0), 12),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 10))
        story.append(HRFlowable(width="100%", color=line, thickness=0.75))
        story.append(Spacer(1, 8))

    # ---- Contact block ----
    if block_included("contact"):
        contact_bits = []
        if p.get("dob"):
            contact_bits.append(f"DOB: {esc(p['dob'])}")
        if p.get("mobile"):
            contact_bits.append("Mobile: " + esc(" / ".join(p["mobile"])))
        if p.get("email"):
            contact_bits.append("Email: " + esc(", ".join(p["email"])))
        if contact_bits:
            story.append(Paragraph(" &nbsp;|&nbsp; ".join(contact_bits), small_style))
            story.append(Spacer(1, 6))

    # ---- Research interest, education, accolades, employment, other records (all bulleted, per-item ticks) ----
    # ---- Education / Accolades / Employment / Other Records (per-item ticks) ----
    def list_block(block_id, title, data_items, render_fn):
        if not block_included(block_id) or not data_items:
            return
        included = [(i, item) for i, item in enumerate(data_items) if item_included(block_id, i)]
        if not included:
            return
        story.append(Paragraph(title, h2_style))
        for i, item in included:
            story.append(Paragraph(render_fn(item), body_style))

    list_block("research_interest", "Research Interest", p.get("research_interest", []),
               lambda r: esc(r))
    list_block("current_work", "Current Work", p.get("current_work", []),
               lambda r: esc(r))
    list_block("education", "Education", p.get("education", []),
               lambda e: f"<b>{esc(e['degree'])}</b> ({esc(e['year'])}) &middot; {esc(e['institution'])}")
    list_block("accolades", "Academic Accolades", p.get("accolades", []),
               lambda a: esc(a))
    list_block("employment", "Employment", p.get("employment", []),
               lambda e: f"<b>{esc(e['period'])}</b> &middot; {esc(e['role'])}, {esc(e['institution'])}")
    list_block("other_records", "Other Records", p.get("other_records", []),
               lambda r: esc(r))

    def section_header(title):
        story.append(Paragraph(title, h2_style))

    # ---- Publications ----
    rows = db.execute("SELECT * FROM papers WHERE scientist_id = ? AND cv_included = 1 ORDER BY year DESC", (scientist_id,)).fetchall()
    if rows:
        section_header(f"Publications ({len(rows)})")
        for i, r in enumerate(rows, 1):
            story.append(Paragraph(f"{i}. {esc(r['complete_reference'] or r['title'])}", body_style))
            tag_bits = []
            if r["quartile"]:
                tag_bits.append(esc(r["quartile"]))
            if r["impact_factor"]:
                tag_bits.append(f"IF {esc(r['impact_factor'])}")
            if r["naas_score"]:
                tag_bits.append(f"NAAS {esc(r['naas_score'])}")
            if tag_bits:
                story.append(Paragraph(" &middot; ".join(tag_bits), meta_style))

    # ---- Awards ----
    rows = db.execute("SELECT * FROM awards WHERE scientist_id = ? AND cv_included = 1 ORDER BY year DESC", (scientist_id,)).fetchall()
    if rows:
        section_header(f"Awards ({len(rows)})")
        for r in rows:
            story.append(Paragraph(esc(r["title"]), entry_title_style))
            story.append(Paragraph(f"{esc(r['awarding_body'])} &middot; {esc(r['year'])}", meta_style))

    # ---- Projects ----
    rows = db.execute("SELECT * FROM projects WHERE scientist_id = ? AND cv_included = 1 ORDER BY date_start DESC", (scientist_id,)).fetchall()
    if rows:
        section_header(f"Projects ({len(rows)})")
        for r in rows:
            story.append(Paragraph(esc(r["project_title"]), entry_title_style))
            date_bit = f"Started {esc(r['date_start'])}" + (f" &middot; Ended {esc(r['date_end'])}" if r["date_end"] else "")
            story.append(Paragraph(f"{esc(r['funding_agency'])} &middot; {date_bit} &middot; {esc(r['status'])}", meta_style))

    # ---- Book Chapters ----
    rows = db.execute("SELECT * FROM book_chapters WHERE scientist_id = ? AND cv_included = 1 ORDER BY year DESC", (scientist_id,)).fetchall()
    if rows:
        section_header(f"Book Chapters ({len(rows)})")
        for r in rows:
            story.append(Paragraph(esc(r["title"]), entry_title_style))
            author_bit = esc(r["authors"]) + (f" &middot; Editor: {esc(r['editor'])}" if r["editor"] else "")
            story.append(Paragraph(author_bit, body_style))
            story.append(Paragraph(f"{esc(r['book_title'])} &middot; {esc(r['publisher'])} &middot; {esc(r['year'])}", meta_style))

    # ---- Software / Packages ----
    rows = db.execute("SELECT * FROM software WHERE scientist_id = ? AND cv_included = 1 ORDER BY year DESC", (scientist_id,)).fetchall()
    if rows:
        section_header(f"Software / Packages ({len(rows)})")
        for r in rows:
            story.append(Paragraph(esc(r["package_name"]), entry_title_style))
            story.append(Paragraph(esc(r["reference"]), meta_style))

    # ---- Courses Taught ----
    rows = db.execute("SELECT * FROM courses_taught WHERE scientist_id = ? AND cv_included = 1 ORDER BY course_id ASC", (scientist_id,)).fetchall()
    if rows:
        section_header(f"Courses Taught ({len(rows)})")
        for r in rows:
            story.append(Paragraph(esc(r["course_name"]), body_style))

    # ---- Students Guided ----
    rows = db.execute("SELECT * FROM students_guided WHERE scientist_id = ? AND cv_included = 1 ORDER BY start_date DESC", (scientist_id,)).fetchall()
    if rows:
        section_header(f"Students Guided ({len(rows)})")
        for r in rows:
            story.append(Paragraph(esc(r["name"]), entry_title_style))
            date_bit = esc(r["start_date"]) + (f" &ndash; {esc(r['end_date'])}" if r["end_date"] else "")
            story.append(Paragraph(date_bit, meta_style))
            if r["description"]:
                story.append(Paragraph(esc(r["description"]), body_style))

    # ---- Technology / Patents ----
    rows = db.execute("SELECT * FROM technology WHERE scientist_id = ? AND cv_included = 1 ORDER BY tech_id ASC", (scientist_id,)).fetchall()
    if rows:
        section_header(f"Technology / Patents / Copyright ({len(rows)})")
        for r in rows:
            story.append(Paragraph(f"{esc(r['authors'])} ({esc(r['year'])}). {esc(r['title'])}. [{esc(r['category'])} No. {esc(r['id_number'])}]", body_style))

    # ---- Popular Articles ----
    rows = db.execute("SELECT * FROM popular_articles WHERE scientist_id = ? AND cv_included = 1 ORDER BY article_id ASC", (scientist_id,)).fetchall()
    if rows:
        section_header(f"Popular Articles ({len(rows)})")
        for r in rows:
            bits = f"{esc(r['authors'])} ({esc(r['year'])}). {esc(r['title'])}. {esc(r['publication'])}"
            if r["details"]:
                bits += f", {esc(r['details'])}"
            story.append(Paragraph(bits, unicode_body_style))

    # ---- Policy Papers ----
    rows = db.execute("SELECT * FROM policy_papers WHERE scientist_id = ? AND cv_included = 1 ORDER BY paper_id ASC", (scientist_id,)).fetchall()
    if rows:
        section_header(f"Policy Papers ({len(rows)})")
        for r in rows:
            bits = f"{esc(r['authors'])} ({esc(r['year'])}). {esc(r['title'])}."
            if r["publisher"]:
                bits += f" {esc(r['publisher'])}."
            if r["id_number"]:
                bits += f" [{esc(r['id_number'])}]"
            story.append(Paragraph(bits, body_style))

    # ---- Manuals ----
    rows = db.execute("SELECT * FROM manuals WHERE scientist_id = ? AND cv_included = 1 ORDER BY manual_id ASC", (scientist_id,)).fetchall()
    if rows:
        section_header(f"Manuals ({len(rows)})")
        for r in rows:
            bits = f"{esc(r['authors'])} ({esc(r['year'])}). {esc(r['title'])}."
            if r["publisher"]:
                bits += f" {esc(r['publisher'])}."
            story.append(Paragraph(bits, unicode_body_style))

    doc.build(story)
    buf.seek(0)
    return buf


@app.route("/api/cv/download", methods=["GET", "POST"])
@require_auth
def download_cv():
    """
    Generates the CV from whatever is currently ticked for CV inclusion
    across the whole site — no selection payload needed. Every record type
    (papers, awards, projects, book chapters, software, courses taught,
    students guided) has its own cv_included flag toggled directly on its
    card; the Home profile blocks/items use the same tick mechanism, saved
    in profile_layout.
    """
    scientist_id = _get_scientist_id()
    try:
        pdf_buf = _build_cv_pdf(scientist_id)
    except Exception as e:
        return jsonify({"error": f"Could not generate the CV: {e}"}), 500

    db = get_db()
    sci = db.execute("SELECT name FROM scientists WHERE scientist_id = ?", (scientist_id,)).fetchone()
    filename = (sci["name"].replace(" ", "_").replace(".", "") if sci else "CV") + "_CV.pdf"

    from flask import send_file
    return send_file(
        pdf_buf, mimetype="application/pdf", as_attachment=True,
        download_name=filename,
    )


# Runs on import (not just "python app.py" directly) — this matters for
# production servers like gunicorn, which import this module and call the
# `app` object without ever executing `if __name__ == "__main__":`.
init_db()

if __name__ == "__main__":
    app.run(debug=True, port=5000, threaded=True)
