# Academic Research Information Management System

A publication-records system for Dr. Md Yeasin (Scientist, ICAR-IASRI): a SQL-backed
database of research papers with filterable browsing, automatic research-domain
tagging, and an OTP-protected admin panel for adding new records (including
BibTeX import).

This matches the sketch you shared: minimal input → filtered/NLP-tagged output →
selection → BibTeX-based admin entry, OTP-protected.

## Restoring your existing research.db (with saved abstracts)

If you already have a `research.db` from an earlier version of this app (e.g.
one where you'd already run Crossref enrichment and edited some records),
just drop it into `backend/` **before** starting the server, replacing the
one in this zip. The app automatically:
- adds the new `field` and `hidden` columns to your existing papers
- backfills a sensible `Field` value for every paper from its current domain
- seeds Awards / Projects / Book Chapters / Software (since those tables
  didn't exist in older databases) without touching your existing papers

Nothing you'd already edited or enriched gets lost or overwritten.

## Profile photo

Your photo is at `frontend/yeasin-photo.png`. To swap it for a different one
later, just replace that file with another image of the same name (any
format works if you also update the `src="yeasin-photo.png"` line in
`frontend/index.html` to match the new extension).

- **Hide/Show everywhere**: Awards, Projects, Book Chapters, and Software now all support the same Hide/Show pattern as Publications — admin-only, with a "Hidden" badge and correct exclusion from the public view.
- **Publication stats now match what's actually shown**: the "69/68 Publications" counter at the top now correctly excludes hidden papers for public visitors (it previously always counted every paper regardless of hidden status or who was viewing).

## What's new in this version

- **Personal Details** section (below the header) with your full bio, education, accolades — pulled from `/api/scientist`.
- **Navigation tabs**: Publications / Awards / Projects / Book Chapters / Software-Packages. Awards, Projects, and Software are pre-seeded with real data extracted from your CV (6 projects, 45 R/CRAN packages, 6 accolades-as-awards). Book Chapters starts empty — add via the admin panel whenever you have them.
- **Multi-domain tagging**: each paper can now carry up to 4 domain tags (e.g. a paper can be both "Machine Learning & Deep Learning" *and* "Climate, Weather & Hydrology"), instead of being forced into one.
- **Field filter**: every paper is also tagged "Statistical" or "Interdisciplinary" (auto-classified from its domains, editable per-paper in the Edit panel).
- **Year range filter**: two number inputs (From/To) instead of a single dropdown.
- **Domain filter**: checkbox multi-select — pick several domains at once, shown if a paper matches *any* of them.
- **Hide/Show**: admins can hide a paper from public visitors without deleting it (a "Hidden" badge shows it to you, but it's invisible to everyone else). Toggle via the "Hide"/"Show" button on each paper.
- **Journal Scores (Excel-linked IF/NAAS/JID)**: as admin, click **"Upload Journal Scores"**, upload an `.xlsx` with columns `Journal Name, JID, Impact Factor, NAAS Score, Quartile, Year` — every paper's Impact Factor/Quartile is matched and refreshed by journal name automatically. Re-upload next year and everything updates in one shot.

## What's included

```
academic-ims/
├── backend/
│   ├── app.py              Flask API + SQLite database + domain classifier
│   ├── papers_seed.json    Your 69 publications, parsed from the CV
│   ├── awards_seed.json    Awards, from your Academic Accolades
│   ├── projects_seed.json  Projects, from your CV's project table
│   ├── software_seed.json  45 R/CRAN packages, from your CV's software table
│   ├── book_chapters_seed.json  Empty — add via admin panel
│   ├── parse_papers.py     The script that parsed the CV table (re-run only if you re-extract)
│   └── requirements.txt
└── frontend/
    ├── index.html
    ├── style.css
    └── script.js           talks to the API at /api/...
```

## Running it

Everything runs from **one server, one port, one terminal** — Flask serves the
API *and* the web app together.

```bash
cd backend
pip install -r requirements.txt
python app.py
```

Then open **http://localhost:5000** in your browser. That's it — no second
terminal, no second server.

This creates `research.db` (SQLite) on first run and seeds it with the 69
papers extracted from your CV.

> If you ever want the frontend files served separately (e.g. deploying them
> to a static host like Netlify while the API lives elsewhere), you still can
> — just run `python -m http.server 8080` inside `frontend/` in a second
> terminal, exactly like before. The frontend calls the API using a relative
> path (`/api/...`), so if you do split them onto different hosts/ports,
> change `API_BASE` at the top of `frontend/script.js` back to the full
> backend URL (e.g. `http://localhost:5000/api`).

## The "Papers" table

Matches the field list you sent:

| Field | Notes |
|---|---|
| Publication ID | auto-increment |
| Complete Reference | full citation text |
| Title, Authors, Year, Journal | parsed from your CV automatically |
| Author Position | Yeasin's position in the author list (auto-detected; `*` = corresponding author) |
| Publisher, ISSN | left blank for the seeded records — editable in the admin panel |
| DOI | extracted automatically |
| Article Type | defaults to "Research Article"; editable |
| Impact Factor, Quartile | from your CV table |
| Domain (NLP) | auto-classified from the title, see below |

A second table (e.g. **Awards**, as in your sketch) can be added the same way —
just say the word and I'll build it with the same pattern (its own SQL table,
filters, and admin form).

## The "NLP" domain tagging

`classify_domain(title, abstract, keywords)` in `app.py` scores weighted
keyword matches across three inputs: the **title** (highest weight — the
most deliberately-chosen text), the **abstract** (supporting evidence), and
**keywords** — which for this system means Crossref's own subject
categories (e.g. "Statistics and Probability", "Artificial Intelligence"),
mapped onto the same domain labels and weighted the strongest of the three,
since Crossref's categorization is more reliable than free-text keyword
guessing.

Every paper starts with title-only classification (that's all the raw CV
data has). To get title+abstract+keywords classification for real, see
**Crossref enrichment** below.

### Crossref enrichment (real abstracts + subjects, zero manual typing)

Every paper with a DOI can be enriched automatically:

- **Per paper:** open the paper in the admin **Edit** panel and click
  **"Fetch abstract from Crossref (via DOI)"**. This calls the free public
  Crossref REST API (`api.crossref.org`, no key needed), pulls the
  abstract and subject categories for that DOI, fills them in, and
  reclassifies the domain — right there, before you even save.
- **All at once:** as admin, click **"Enrich All (Crossref)"** in the top
  bar. This loops through every paper that has a DOI but no abstract yet,
  fetches each one (with a small delay between calls to stay within
  Crossref's public rate limit), and reclassifies domains as it goes. For
  69 papers this takes roughly a minute.

Not every DOI has an abstract on Crossref (older papers and some
publishers don't submit one) — those are simply skipped, and the response
tells you how many were updated vs. skipped.

> **Note on testing:** I built and unit-tested this against Crossref's
> response format, and confirmed the failure path is handled gracefully
> (no crash, clear message) when the network is unavailable — but my
> sandbox's network allowlist doesn't include `api.crossref.org`, so I
> couldn't verify a live, successful fetch end-to-end before handing this
> to you. Try it on your machine; if a specific DOI doesn't behave as
> expected, send me the error and I'll fix it.

## Admin login (OTP-protected)

Test credentials (as you requested):
- Email: `borapushkar1999@gmail.com`
- Password: `Pushkar@123`

Flow: **Admin → email/password → OTP → BibTeX or manual entry form.**

⚠️ **Important:** my sandbox can't send real emails, so right now the OTP is
only printed to the backend console (and shown in the login modal as a "dev
mode" hint so you can test end-to-end without real email). To send real OTP
emails, set these environment variables before running `app.py`:

```bash
export SMTP_HOST=smtp.gmail.com
export SMTP_PORT=587
export SMTP_USER=your-email@gmail.com
export SMTP_PASSWORD=your-app-password   # Gmail App Password, not your login password
```

Once set, `send_otp_email()` sends a real email and the "dev mode" hint
disappears automatically.

For production, I'd also recommend: hashing the admin password instead of
storing it in plain text, and moving the OTP/session stores from memory to
Redis or the database so logins survive a server restart.

## Design notes

The visual identity: a bibliography/ledger look (serif titles, mono for
DOIs and years, a small numbered index per entry) rather than a generic SaaS
dashboard — since the whole point is *reading and filtering a publication
record*, like a CV made interactive.

## Extending it

- **Table 2 (Awards)**: same backend pattern — a `awards` table, its own
  filters (by year, by awarding body), same admin add/edit/delete flow.
- **Deployment**: for a real public site, swap SQLite → Postgres, run Flask
  behind gunicorn, and host the frontend as static files (Netlify/Vercel) or
  serve it from Flask directly.
