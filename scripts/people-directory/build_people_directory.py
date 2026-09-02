#!/usr/bin/env python3
"""Build a self-contained People Directory HTML from the influential-brands vault."""
import json, os, re, html, sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[2])
ENT = os.path.join(ROOT, "entities")
OUT = os.path.join(ROOT, "Apps", "people-directory.html")

def parse_catalog(path):
    """Parse a generated catalog.md markdown table into {id: name}."""
    m = {}
    if not os.path.exists(path):
        return m
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("| "):
                continue
            cols = [c.strip() for c in line.strip("|").split("|")]
            if len(cols) < 2:
                continue
            _id, name = cols[0], cols[1]
            if _id in ("ID", "---") or _id.startswith("---"):
                continue
            m[_id] = name.strip("'\"")
    return m

orgs = parse_catalog(os.path.join(ENT, "organisations", "catalog.md"))
locs = parse_catalog(os.path.join(ENT, "locations", "catalog.md"))
inds = parse_catalog(os.path.join(ENT, "industries", "catalog.md"))

def parse_frontmatter(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    block = text[3:end].strip()
    try:
        return json.loads(block)
    except Exception:
        return None

def clean_name(s):
    s = (s or "").strip()
    # strip one matched pair of surrounding quotes
    while len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        s = s[1:-1].strip()
    return s

people = []
pdir = os.path.join(ENT, "people")
for fn in sorted(os.listdir(pdir)):
    if not fn.startswith("person-") or not fn.endswith(".md"):
        continue
    fm = parse_frontmatter(os.path.join(pdir, fn))
    if not fm:
        continue
    src = (fm.get("sourceRefs") or [{}])[0]
    people.append({
        "id": fm.get("personId", fn[:-3]),
        "name": clean_name(fm.get("displayName")) or fm.get("primaryEmail") or fm.get("personId", ""),
        "email": fm.get("primaryEmail"),
        "linkedin": fm.get("linkedInUrl"),
        "org": orgs.get(fm.get("organisationId"), None),
        "country": locs.get(fm.get("countryId"), None),
        "industry": inds.get(fm.get("brandCategoryId"), None),
        "mentions": fm.get("mentionCount"),
        "status": fm.get("status"),
        "confidence": fm.get("confidence"),
        "created": fm.get("createdAt"),
        "updated": fm.get("updatedAt"),
        "clayEnhanced": fm.get("clayEnhanced"),
        "enrichmentProvider": fm.get("enrichmentProvider"),
        "enrichmentDate": fm.get("enrichmentDate"),
        "jobTitle": fm.get("jobTitle") or fm.get("currentRole"),
        "company": fm.get("company"),
        "location": fm.get("location"),
        "phone": fm.get("phone") or fm.get("mobilePhone"),
        "professionalHistory": [r for r in (fm.get("professionalHistory") or []) if isinstance(r, dict)],
        "ToEnhance": fm.get("ToEnhance"),
        "aliases": fm.get("aliases") or [],
        "tags": fm.get("tags") or [],
        "sourceLocator": src.get("locator"),
        "file": fn,
    })

# Sort by name, case-insensitive; blanks last
people.sort(key=lambda p: (p["name"] or "￿").lower())

data_json = json.dumps(people, ensure_ascii=False, separators=(",", ":"))

TEMPLATE = open(os.path.join(os.path.dirname(__file__), "template.html"), encoding="utf-8").read()
out = TEMPLATE.replace("/*__DATA__*/", data_json).replace("__COUNT__", str(len(people)))
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(out)

print(f"Wrote {OUT}")
print(f"People: {len(people)}  |  Orgs resolved: {len(orgs)}  Locations: {len(locs)}  Industries: {len(inds)}")
print(f"Size: {os.path.getsize(OUT)/1024:.0f} KB")
