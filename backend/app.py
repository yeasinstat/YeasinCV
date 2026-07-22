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
import re
import json
import sqlite3
import random
import string
import time
from functools import wraps

from flask import Flask, request, jsonify, g, send_from_directory
from flask_cors import CORS

try:
    import bibtexparser
except ImportError:
    bibtexparser = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "research.db")
SEED_PATH = os.path.join(BASE_DIR, "papers_seed.json")
FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
CORS(app)


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
OTP_STORE = {}       # email -> {"otp": str, "expires": ts}
SESSION_STORE = {}    # token -> {"email": str, "expires": ts}
OTP_TTL_SECONDS = 300      # 5 minutes
SESSION_TTL_SECONDS = 3600  # 1 hour


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_db(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    publication_id      INTEGER PRIMARY KEY AUTOINCREMENT,
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
    quartile             TEXT,
    domain               TEXT,
    field                TEXT DEFAULT '',
    hidden               INTEGER DEFAULT 0,
    abstract             TEXT DEFAULT '',
    keywords             TEXT DEFAULT '',
    created_at           TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS awards (
    award_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT,
    awarding_body TEXT,
    year          TEXT,
    description   TEXT DEFAULT '',
    hidden        INTEGER DEFAULT 0,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS projects (
    project_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    sl_no           TEXT,
    investigators   TEXT,
    project_title   TEXT,
    funding_agency  TEXT,
    date_start      TEXT,
    status          TEXT,
    hidden          INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS book_chapters (
    book_chapter_id INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT,
    authors         TEXT,
    book_title      TEXT,
    publisher       TEXT,
    year            TEXT,
    pages           TEXT,
    isbn            TEXT,
    doi             TEXT DEFAULT '',
    hidden          INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS software (
    software_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    package_name TEXT,
    reference    TEXT,
    year         TEXT,
    downloads    TEXT DEFAULT '',
    cran_url     TEXT DEFAULT '',
    hidden       INTEGER DEFAULT 0,
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS journal_scores (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    journal_name   TEXT UNIQUE,
    jid            TEXT DEFAULT '',
    impact_factor  TEXT DEFAULT '',
    naas_score     TEXT DEFAULT '',
    quartile       TEXT DEFAULT '',
    year_updated   TEXT DEFAULT '',
    updated_at     TEXT DEFAULT (datetime('now'))
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


PROJECTS_SEED_PATH = os.path.join(BASE_DIR, "projects_seed.json")
SOFTWARE_SEED_PATH = os.path.join(BASE_DIR, "software_seed.json")
AWARDS_SEED_PATH = os.path.join(BASE_DIR, "awards_seed.json")
BOOK_CHAPTERS_SEED_PATH = os.path.join(BASE_DIR, "book_chapters_seed.json")


def init_db(force_reseed=False):
    fresh = not os.path.exists(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    migrate_db(conn)  # safe no-op if columns already exist

    if fresh or force_reseed:
        if force_reseed:
            conn.execute("DELETE FROM papers")

        with open(SEED_PATH, encoding="utf-8") as f:
            records = json.load(f)
        for r in records:
            domains = classify_domains(r["title"])
            domain = ", ".join(domains)
            field = classify_field(domains)
            conn.execute(
                """INSERT INTO papers
                (complete_reference, title, authors, author_position, year,
                 journal, publisher, issn, doi, article_type, impact_factor,
                 quartile, domain, field, hidden)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
                (
                    r["complete_reference"], r["title"], r["authors"],
                    r["author_position"], r["year"], r["journal"],
                    r.get("publisher", ""), r.get("issn", ""), r["doi"],
                    r["article_type"], r["impact_factor"], r["quartile"],
                    domain, field,
                ),
            )
        conn.commit()

    # Seed Awards / Projects / Book Chapters / Software independently of the
    # papers table's freshness — this matters when someone drops in an
    # older research.db (with papers already populated) that predates these
    # four tables: each one still gets seeded here as long as it's empty,
    # rather than silently staying blank forever.
    for path, table, cols in [
        (AWARDS_SEED_PATH, "awards", ["title", "awarding_body", "year", "description"]),
        (PROJECTS_SEED_PATH, "projects", ["sl_no", "investigators", "project_title", "funding_agency", "date_start", "status"]),
        (BOOK_CHAPTERS_SEED_PATH, "book_chapters", ["title", "authors", "book_title", "publisher", "year", "pages", "isbn", "doi"]),
        (SOFTWARE_SEED_PATH, "software", ["package_name", "reference", "year", "downloads", "cran_url"]),
    ]:
        if not os.path.exists(path):
            continue
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if count > 0 and not force_reseed:
            continue
        if force_reseed:
            conn.execute(f"DELETE FROM {table}")
        with open(path, encoding="utf-8") as f:
            items = json.load(f)
        placeholders = ",".join(["?"] * len(cols))
        for item in items:
            conn.execute(
                f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})",
                tuple(item.get(c, "") for c in cols),
            )
    conn.commit()
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
        session = SESSION_STORE.get(token)
        if not session or session["expires"] < time.time():
            return jsonify({"error": "Unauthorized. Please log in again."}), 401
        return f(*args, **kwargs)
    return wrapper


def send_otp_email(email: str, otp: str):
    """
    Sends the OTP by email. Configure SMTP credentials via environment
    variables (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD) to enable
    real delivery. Without them, the OTP is only logged to the server
    console so you can still test the flow locally.
    """
    smtp_host = os.environ.get("SMTP_HOST")
    if not smtp_host:
        print(f"[DEV MODE] OTP for {email}: {otp}  (configure SMTP_* env vars to send real emails)")
        return False
    import smtplib
    from email.mime.text import MIMEText
    msg = MIMEText(f"Your OTP for the Academic Research Information Management System is: {otp}\nIt expires in 5 minutes.")
    msg["Subject"] = "Your Admin Login OTP"
    msg["From"] = os.environ.get("SMTP_USER")
    msg["To"] = email
    with smtplib.SMTP(smtp_host, int(os.environ.get("SMTP_PORT", 587))) as server:
        server.starttls()
        server.login(os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD"))
        server.send_message(msg)
    return True


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------
@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if email != ADMIN_EMAIL.lower() or password != ADMIN_PASSWORD:
        return jsonify({"error": "Invalid email or password"}), 401

    otp = generate_otp()
    OTP_STORE[email] = {"otp": otp, "expires": time.time() + OTP_TTL_SECONDS}
    try:
        delivered = send_otp_email(email, otp)
    except Exception as e:
        print(f"[SMTP ERROR] Failed to send OTP email: {e}")
        delivered = False

    resp = {"message": "OTP sent to your registered email."}
    if not delivered:
        resp["dev_otp"] = otp
    return jsonify(resp)


@app.route("/api/verify-otp", methods=["POST"])
def verify_otp():
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    otp = (data.get("otp") or "").strip()

    record = OTP_STORE.get(email)
    if not record or record["expires"] < time.time():
        return jsonify({"error": "OTP expired. Please log in again."}), 400
    if record["otp"] != otp:
        return jsonify({"error": "Incorrect OTP."}), 400

    del OTP_STORE[email]
    token = generate_token()
    SESSION_STORE[token] = {"email": email, "expires": time.time() + SESSION_TTL_SECONDS}
    return jsonify({"token": token, "message": "Login successful."})


def is_admin_request():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    session = SESSION_STORE.get(token)
    return bool(session and session["expires"] >= time.time())


# ---------------------------------------------------------------------------
# Paper (research article table) routes
# ---------------------------------------------------------------------------
@app.route("/api/papers", methods=["GET"])
def get_papers():
    db = get_db()
    query = "SELECT * FROM papers WHERE 1=1"
    params = []

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
    hidden_clause = "" if admin else "AND hidden = 0"

    years = [r[0] for r in db.execute(f"SELECT DISTINCT year FROM papers WHERE year != '' {hidden_clause} ORDER BY year DESC")]
    journals = [r[0] for r in db.execute(f"SELECT DISTINCT journal FROM papers WHERE journal != '' {hidden_clause} ORDER BY journal")]
    quartiles = [r[0] for r in db.execute(f"SELECT DISTINCT quartile FROM papers WHERE quartile != '' {hidden_clause} ORDER BY quartile")]
    fields = [r[0] for r in db.execute(f"SELECT DISTINCT field FROM papers WHERE field != '' {hidden_clause} ORDER BY field")]

    domain_rows = db.execute(f"SELECT domain FROM papers WHERE domain != '' {hidden_clause}")
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
    hidden_clause = "" if is_admin_request() else "WHERE hidden = 0"
    year_clause = "year != ''" if is_admin_request() else "year != '' AND hidden = 0"
    quartile_clause = "quartile != ''" if is_admin_request() else "quartile != '' AND hidden = 0"
    domain_clause = "1=1" if is_admin_request() else "hidden = 0"

    total = db.execute(f"SELECT COUNT(*) FROM papers {hidden_clause}").fetchone()[0]
    by_year = db.execute(f"SELECT year, COUNT(*) c FROM papers WHERE {year_clause} GROUP BY year ORDER BY year").fetchall()
    by_quartile = db.execute(f"SELECT quartile, COUNT(*) c FROM papers WHERE {quartile_clause} GROUP BY quartile").fetchall()
    by_domain = db.execute(f"SELECT domain, COUNT(*) c FROM papers WHERE {domain_clause} GROUP BY domain ORDER BY c DESC").fetchall()
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

    if "bibtex" in data:
        if bibtexparser is None:
            return jsonify({"error": "bibtexparser not installed on server"}), 500
        bib_db = bibtexparser.loads(data["bibtex"])
        if not bib_db.entries:
            return jsonify({"error": "Could not parse any entries from the BibTeX provided."}), 400
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
                (complete_reference, title, authors, author_position, year,
                 journal, publisher, issn, doi, article_type, impact_factor,
                 quartile, domain, field, hidden, abstract, keywords)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)""",
                (
                    f"{authors} ({year}). {title}. {journal}.",
                    title, authors, "", year, journal, publisher, issn, doi,
                    entry.get("ENTRYTYPE", "article"), "", "", domain, field, "", "",
                ),
            )
            added.append(cur.lastrowid)
        db.commit()
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
        (complete_reference, title, authors, author_position, year, journal,
         publisher, issn, doi, article_type, impact_factor, quartile, domain,
         field, hidden, abstract, keywords)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)""",
        (
            data.get("complete_reference", ""), data.get("title", ""),
            data.get("authors", ""), data.get("author_position", ""),
            data.get("year", ""), data.get("journal", ""),
            data.get("publisher", ""), data.get("issn", ""),
            data.get("doi", ""), data.get("article_type", "Research Article"),
            data.get("impact_factor", ""), data.get("quartile", ""), domain,
            field, data.get("abstract", ""), data.get("keywords", ""),
        ),
    )
    db.commit()
    return jsonify({"message": "Paper added.", "id": cur.lastrowid}), 201


@app.route("/api/papers/<int:pub_id>", methods=["PUT"])
@require_auth
def update_paper(pub_id):
    data = request.get_json(force=True)
    db = get_db()
    fields = [
        "complete_reference", "title", "authors", "author_position", "year",
        "journal", "publisher", "issn", "doi", "article_type",
        "impact_factor", "quartile", "abstract", "keywords", "field", "domain",
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
    row = db.execute("SELECT hidden FROM papers WHERE publication_id = ?", (pub_id,)).fetchone()
    if not row:
        return jsonify({"error": "Paper not found."}), 404
    new_val = 0 if row["hidden"] else 1
    db.execute("UPDATE papers SET hidden = ? WHERE publication_id = ?", (new_val, pub_id))
    db.commit()
    return jsonify({"message": "Paper hidden." if new_val else "Paper visible again.", "hidden": bool(new_val)})


@app.route("/api/papers/<int:pub_id>/enrich", methods=["POST"])
@require_auth
def enrich_paper(pub_id):
    """Fetches abstract + subject keywords from Crossref for one paper (by its DOI) and reclassifies its domain."""
    db = get_db()
    row = db.execute("SELECT title, doi FROM papers WHERE publication_id = ?", (pub_id,)).fetchone()
    if not row:
        return jsonify({"error": "Paper not found."}), 404
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
    db = get_db()

    if force:
        rows = db.execute("SELECT publication_id, title, doi FROM papers WHERE doi != ''").fetchall()
    else:
        rows = db.execute(
            "SELECT publication_id, title, doi FROM papers WHERE doi != '' AND (abstract IS NULL OR abstract = '')"
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
    db.execute("DELETE FROM papers WHERE publication_id = ?", (pub_id,))
    db.commit()
    return jsonify({"message": "Paper deleted."})


@app.route("/api/scientist", methods=["GET"])
def scientist_info():
    return jsonify(SCIENTIST_PROFILE)


SCIENTIST_PROFILE = {
    "name": "Dr. Md Yeasin",
    "designation": "Scientist",
    "institute": "ICAR-Indian Agricultural Statistics Research Institute (IASRI)",
    "address": "304, TAC Building, ICAR-IASRI, Library Avenue, New Delhi-110012",
    "location": "New Delhi - 110012",
    "dob": "27th January 1994",
    "mobile": ["8926261427", "9136309898"],
    "email": ["yeasin.iasri@gmail.com", "mdyeasin.iasri@icar.org.in"],
    "research_interest": (
        "I am a statistician, specialize in time series and machine learning "
        "models for agriculture and allied sciences. My current research "
        "focuses on modelling and forecasting temporal behaviour of the "
        "environmental parameters and quantifying its effect on agricultural "
        "productivity and sustainability."
    ),
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
}


# ---------------------------------------------------------------------------
# Simple CRUD for the other CV sections: Awards, Projects, Book Chapters,
# Software/Packages. Same pattern as Papers (public GET, admin-only
# add/edit/delete) but without domain/hide logic, since those are specific
# to the Papers table.
# ---------------------------------------------------------------------------
SIMPLE_TABLES = {
    "awards": {
        "id_col": "award_id",
        "columns": ["title", "awarding_body", "year", "description"],
        "order_by": "year DESC",
    },
    "projects": {
        "id_col": "project_id",
        "columns": ["sl_no", "investigators", "project_title", "funding_agency", "date_start", "status"],
        "order_by": "date_start DESC",
    },
    "book-chapters": {
        "table": "book_chapters",
        "id_col": "book_chapter_id",
        "columns": ["title", "authors", "book_title", "publisher", "year", "pages", "isbn", "doi"],
        "order_by": "year DESC",
    },
    "software": {
        "id_col": "software_id",
        "columns": ["package_name", "reference", "year", "downloads", "cran_url"],
        "order_by": "year DESC",
    },
}


def _register_simple_crud(endpoint_name, config):
    table = config.get("table", endpoint_name.replace("-", "_"))
    id_col = config["id_col"]
    columns = config["columns"]
    order_by = config["order_by"]

    def list_items():
        db = get_db()
        hidden_clause = "" if is_admin_request() else "WHERE hidden = 0"
        rows = db.execute(f"SELECT * FROM {table} {hidden_clause} ORDER BY {order_by}").fetchall()
        return jsonify([dict(r) for r in rows])

    def add_item():
        data = request.get_json(force=True)
        db = get_db()
        vals = [data.get(c, "") for c in columns]
        placeholders = ",".join(["?"] * len(columns))
        cur = db.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})", vals)
        db.commit()
        return jsonify({"message": "Added.", "id": cur.lastrowid}), 201

    def update_item(item_id):
        data = request.get_json(force=True)
        db = get_db()
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
        db.execute(f"DELETE FROM {table} WHERE {id_col} = ?", (item_id,))
        db.commit()
        return jsonify({"message": "Deleted."})

    def toggle_hidden(item_id):
        db = get_db()
        row = db.execute(f"SELECT hidden FROM {table} WHERE {id_col} = ?", (item_id,)).fetchone()
        if not row:
            return jsonify({"error": "Not found."}), 404
        new_val = 0 if row["hidden"] else 1
        db.execute(f"UPDATE {table} SET hidden = ? WHERE {id_col} = ?", (new_val, item_id))
        db.commit()
        return jsonify({"message": "Hidden." if new_val else "Visible again.", "hidden": bool(new_val)})

    app.add_url_rule(f"/api/{endpoint_name}", f"list_{table}", list_items, methods=["GET"])
    app.add_url_rule(f"/api/{endpoint_name}", f"add_{table}", require_auth(add_item), methods=["POST"])
    app.add_url_rule(f"/api/{endpoint_name}/<int:item_id>", f"update_{table}", require_auth(update_item), methods=["PUT"])
    app.add_url_rule(f"/api/{endpoint_name}/<int:item_id>", f"delete_{table}", require_auth(delete_item), methods=["DELETE"])
    app.add_url_rule(f"/api/{endpoint_name}/<int:item_id>/toggle-hidden", f"toggle_{table}", require_auth(toggle_hidden), methods=["POST"])


for _endpoint, _config in SIMPLE_TABLES.items():
    _register_simple_crud(_endpoint, _config)


# ---------------------------------------------------------------------------
# Journal scores (Impact Factor / NAAS score / JID) — Excel-linked lookup
# table. Upload a spreadsheet once a year and every paper's displayed
# Impact Factor / Quartile is refreshed from it via journal-name matching.
# ---------------------------------------------------------------------------
def _norm_journal(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


@app.route("/api/journal-scores", methods=["GET"])
def list_journal_scores():
    db = get_db()
    rows = db.execute("SELECT * FROM journal_scores ORDER BY journal_name").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/journal-scores/upload", methods=["POST"])
@require_auth
def upload_journal_scores():
    """
    Accepts a multipart/form-data upload with field name 'file', an .xlsx
    spreadsheet. Expected columns (case-insensitive, order doesn't matter):
    Journal Name, JID, Impact Factor, NAAS Score, Quartile, Year.
    After loading, every paper's impact_factor/quartile is refreshed by
    matching its journal name against this table (case/punctuation-insensitive).
    """
    try:
        import openpyxl
    except ImportError:
        return jsonify({"error": "openpyxl is not installed on the server. Run: pip install openpyxl"}), 500

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded (expected form field 'file')."}), 400
    file = request.files["file"]

    try:
        wb = openpyxl.load_workbook(file, data_only=True)
    except Exception as e:
        return jsonify({"error": f"Could not read the Excel file: {e}"}), 400

    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return jsonify({"error": "The spreadsheet appears to be empty."}), 400

    header = [str(h or "").strip().lower() for h in rows[0]]

    def find_col(*names):
        for name in names:
            if name in header:
                return header.index(name)
        return None

    col_journal = find_col("journal name", "journal", "journal_name")
    col_jid = find_col("jid", "journal id")
    col_if = find_col("impact factor", "if", "impact_factor")
    col_naas = find_col("naas score", "naas", "naas_score")
    col_quartile = find_col("quartile")
    col_year = find_col("year", "year updated")

    if col_journal is None:
        return jsonify({"error": "Couldn't find a 'Journal Name' column in the spreadsheet header."}), 400

    db = get_db()
    loaded = 0
    for row in rows[1:]:
        if col_journal >= len(row) or not row[col_journal]:
            continue
        journal_name = str(row[col_journal]).strip()
        jid = str(row[col_jid]).strip() if col_jid is not None and col_jid < len(row) and row[col_jid] else ""
        impact_factor = str(row[col_if]).strip() if col_if is not None and col_if < len(row) and row[col_if] is not None else ""
        naas_score = str(row[col_naas]).strip() if col_naas is not None and col_naas < len(row) and row[col_naas] is not None else ""
        quartile = str(row[col_quartile]).strip() if col_quartile is not None and col_quartile < len(row) and row[col_quartile] else ""
        year_updated = str(row[col_year]).strip() if col_year is not None and col_year < len(row) and row[col_year] else ""

        db.execute(
            """INSERT INTO journal_scores (journal_name, jid, impact_factor, naas_score, quartile, year_updated, updated_at)
               VALUES (?,?,?,?,?,?, datetime('now'))
               ON CONFLICT(journal_name) DO UPDATE SET
                 jid=excluded.jid, impact_factor=excluded.impact_factor,
                 naas_score=excluded.naas_score, quartile=excluded.quartile,
                 year_updated=excluded.year_updated, updated_at=datetime('now')""",
            (journal_name, jid, impact_factor, naas_score, quartile, year_updated),
        )
        loaded += 1
    db.commit()

    updated_papers = _apply_journal_scores_to_papers(db)

    return jsonify({
        "message": f"Loaded {loaded} journal(s) from the spreadsheet. Updated Impact Factor/Quartile on {updated_papers} paper(s).",
        "loaded": loaded,
        "papers_updated": updated_papers,
    })


def _apply_journal_scores_to_papers(db):
    scores = db.execute("SELECT journal_name, impact_factor, naas_score, quartile FROM journal_scores").fetchall()
    score_map = {_norm_journal(r["journal_name"]): r for r in scores}

    papers = db.execute("SELECT publication_id, journal FROM papers").fetchall()
    updated = 0
    for p in papers:
        match = score_map.get(_norm_journal(p["journal"]))
        if not match:
            continue
        new_if = match["impact_factor"] or match["naas_score"]
        new_quartile = match["quartile"] or ("NAAS" if match["naas_score"] and not match["impact_factor"] else "")
        if new_if or new_quartile:
            db.execute(
                "UPDATE papers SET impact_factor = COALESCE(NULLIF(?, ''), impact_factor), "
                "quartile = COALESCE(NULLIF(?, ''), quartile) WHERE publication_id = ?",
                (new_if, new_quartile, p["publication_id"]),
            )
            updated += 1
    db.commit()
    return updated


@app.route("/api/journal-scores/apply", methods=["POST"])
@require_auth
def apply_journal_scores():
    """Re-applies the currently-loaded journal_scores table to all papers (no new upload)."""
    db = get_db()
    updated = _apply_journal_scores_to_papers(db)
    return jsonify({"message": f"Refreshed Impact Factor/Quartile on {updated} paper(s) from the journal scores table.", "papers_updated": updated})


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", debug=True, port=5000, threaded=True)
