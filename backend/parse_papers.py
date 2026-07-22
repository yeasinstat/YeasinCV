import json, re

with open('raw_papers.json', encoding='utf-8') as f:
    rows = json.load(f)

def clean(s):
    return re.sub(r'\s+', ' ', s.replace('\xa0', ' ')).strip()

records = []
for row in rows:
    sl, ref, year, ifval, quartile = row
    ref_clean = clean(ref)

    # find year in parentheses e.g. (2023) or year at pos after authors like ", 2026."
    m = re.search(r'\((\d{4})\)\.?', ref_clean)
    if m:
        yr_found = m.group(1)
        authors = ref_clean[:m.start()].strip().rstrip(',').strip()
        rest = ref_clean[m.end():].strip()
    else:
        m2 = re.search(r',\s*(\d{4})\.', ref_clean)
        if m2:
            yr_found = m2.group(1)
            authors = ref_clean[:m2.start()].strip()
            rest = ref_clean[m2.end():].strip()
        else:
            yr_found = year
            authors = ref_clean
            rest = ''

    if not year:
        year = yr_found

    # Title = up to next sentence-ending period followed by a capital letter/space (heuristic: first ". " split)
    title = ''
    journal_part = rest
    # find DOI first and strip it off the end
    doi = ''
    doi_m = re.search(r'(https?://\S+|10\.\d{4,9}/\S+)', rest)
    if doi_m:
        doi = doi_m.group(1).rstrip('.')
        journal_part = rest[:doi_m.start()].strip()
    else:
        journal_part = rest

    # split title vs journal: title ends at first ". " where following text starts with capital
    parts = re.split(r'(?<=[.?!])\s+(?=[A-Z])', journal_part, maxsplit=1)
    if len(parts) == 2:
        title, journal_and_rest = parts
    else:
        title = journal_part
        journal_and_rest = ''

    # journal name = text up to first comma
    journal = ''
    if journal_and_rest:
        jparts = journal_and_rest.split(',')
        journal = jparts[0].strip()

    # author position of Yeasin
    author_list_raw = re.sub(r'\s*&\s*', ', ', authors)
    author_tokens = [a.strip() for a in author_list_raw.split(',') if a.strip()]
    # tokens look like "Yeasin, M." split by comma breaks names apart; instead split by pattern "Lastname, Initials."
    name_pattern = re.findall(r'[A-Z][A-Za-z\-]+,\s*(?:[A-Z]\.\s*)+\*?', authors + (' & ' if False else ''))
    # fallback simpler: split authors string by regex on ", " but merge "Lastname, Initials"
    tokens = re.split(r',\s*(?=[A-Z][a-zA-Z\-]+,\s*[A-Z]\.|[A-Z][a-zA-Z\-]+\s*&|$)', authors)
    # Simplify: use name_pattern which captures each "Lastname, Initials." unit
    names = name_pattern if name_pattern else tokens
    position = ''
    corresponding = '*' in authors
    for idx, n in enumerate(names, start=1):
        if 'Yeasin' in n:
            position = str(idx)
            break
    if not position:
        # fallback: locate 'Yeasin' word index among comma-split raw authors
        if 'Yeasin' in authors:
            position = '?'

    article_type = 'Research Article'
    if ifval and ifval.strip().upper() in ('NAAS',):
        pass
    impact_factor = ifval.strip()
    quartile_val = quartile.strip()

    title_clean = clean(title).rstrip('.').strip()

    records.append({
        'sl_no': sl,
        'complete_reference': ref_clean,
        'title': title_clean,
        'authors': clean(authors),
        'author_position': position,
        'corresponding_author': corresponding,
        'year': year.strip() if year else '',
        'journal': journal,
        'publisher': '',
        'issn': '',
        'doi': doi,
        'article_type': article_type,
        'impact_factor': impact_factor,
        'quartile': quartile_val,
    })

with open('papers_seed.json', 'w', encoding='utf-8') as f:
    json.dump(records, f, ensure_ascii=False, indent=2)

print(len(records), 'records parsed')
for r in records[:3]:
    print(json.dumps(r, ensure_ascii=False, indent=2))
