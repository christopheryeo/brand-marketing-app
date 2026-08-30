#!/usr/bin/env python3
"""Compile the influential-brands vault into a single self-contained wiki browser HTML."""
import json, os
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[2])
ENT = os.path.join(ROOT, "entities")
OUT = os.path.join(ROOT, "Apps", "wiki-browser.html")
HERE = os.path.dirname(os.path.abspath(__file__))

# type folder -> (label, icon, tooltip)
TYPES = [
    ("people", "People", "🧑", "Individuals — contacts, employees, prospects and stakeholders"),
    ("organisations", "Organisations", "🏢", "Companies and organisations"),
    ("appointments", "Appointments", "🪪", "Roles & job titles a person holds at an organisation"),
    ("brands", "Brands", "™️", "Brand names"),
    ("industries", "Industries", "🏭", "Industry sectors / brand categories"),
    ("locations", "Locations", "🌏", "Countries and places"),
    ("organisational-functions", "Functions", "🏛️", "Organisational functions / departments"),
    ("marketing-campaigns", "Campaigns", "📣", "Marketing campaigns"),
    ("marketing-segments", "Segments", "🎯", "Audience / market segments"),
    ("products-services", "Products", "📦", "Products and services"),
    ("projects-initiatives", "Projects", "🚀", "Projects and initiatives"),
    ("sales-opportunities", "Sales Opps", "🤝", "Sales opportunities / deals"),
    ("topics", "Topics", "🗂️", "Subjects and themes"),
    ("meetings-events", "Meetings", "📅", "Meetings and calendar events"),
    ("email-messages", "Emails", "✉️", "Email messages"),
    ("sources", "Sources", "🗄️", "Imported source documents"),
    ("decisions", "Decisions", "⚖️", "Governance decisions"),
    ("search", "Searches", "🔍", "Saved search queries"),
]

# Fields never shown as a plain field (handled elsewhere or noise)
FIELD_BLACKLIST = {
    "entityType", "sourceRefs", "aliases", "tags", "extraction", "relationships",
    "participants", "titleObservations", "bodyHash", "threadIndex", "inputLocator",
    "attachments", "messageId", "evidenceHash", "outcomes", "domains",
    "procedureVersion", "parserVersion", "hashAlgorithm", "fileHash", "rawPath",
    "originalPath", "membershipRule", "affects",
}
# ID-ish fields we do NOT turn into links (self ids / non-entity ids)
ID_SKIP = {"messageId", "bodyHash", "evidenceHash", "threadIndex", "queryId"}

def clean_name(s):
    s = (s or "").strip()
    while len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        s = s[1:-1].strip()
    return s

def parse_fm(path):
    try:
        t = open(path, encoding="utf-8").read()
    except Exception:
        return None
    if not t.startswith("---"):
        return None
    end = t.find("\n---", 3)
    if end == -1:
        return None
    try:
        return json.loads(t[3:end].strip())
    except Exception:
        return None

ID_FIELD = {
    "people":"personId", "organisations":"organisationId", "appointments":"appointmentId",
    "brands":"brandId", "industries":"industryId", "locations":"locationId",
    "organisational-functions":"functionId", "marketing-campaigns":"campaignId",
    "marketing-segments":"marketingSegmentId", "products-services":"productServiceId",
    "projects-initiatives":"projectInitiativeId", "sales-opportunities":"opportunityId",
    "topics":"topicId", "meetings-events":"meetingEventId", "email-messages":"emailMessageId",
    "sources":"sourceId", "decisions":"decisionId", "search":"queryId",
}
def id_field_for(type_key, fm):
    # the frontmatter key holding this note's own id (type-specific — never guess)
    return ID_FIELD.get(type_key)

def humanize(key):
    k = key[:-3] if key.endswith("Ids") else (key[:-2] if key.endswith("Id") else key)
    out = ""
    for i, c in enumerate(k):
        if c.isupper() and i > 0 and not k[i-1].isupper():
            out += " "
        out += c
    return (out[:1].upper() + out[1:]) if out else key

# ── Pass 1: load every note's frontmatter, establish id -> (type, name)
records = {}   # id -> (type_key, fm, own_id_field)
name_of = {}   # id -> display name

for type_key, label, icon, tip in TYPES:
    d = os.path.join(ENT, type_key)
    if not os.path.isdir(d):
        continue
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".md") or fn in ("catalog.md", "index.md", "log.md"):
            continue
        fm = parse_fm(os.path.join(d, fn))
        if not fm:
            continue
        idf = id_field_for(type_key, fm)
        nid = fm.get(idf) if idf else fn[:-3]
        if not nid:
            nid = fn[:-3]
        records[nid] = (type_key, fm, idf)
        # provisional name (refined in pass 2 for composed names)
        nm = (fm.get("displayName") or fm.get("name") or fm.get("title")
              or fm.get("subject") or fm.get("query") or fm.get("primaryEmail") or nid)
        name_of[nid] = clean_name(nm) if isinstance(nm, str) else nid

# Compose nicer names for appointments (title @ org) and emails
for nid, (tk, fm, idf) in records.items():
    if tk == "appointments":
        title = clean_name(fm.get("title") or "Appointment")
        org = name_of.get(fm.get("organisationId"))
        name_of[nid] = f"{title} · {org}" if org else title
    elif tk == "email-messages":
        subj = clean_name(fm.get("subject") or "(no subject)")
        name_of[nid] = subj or "(no subject)"

# ── Pass 2: build nodes with typed outbound links
nodes = {}
for nid, (tk, fm, idf) in records.items():
    links = []   # [rel_label, target_id]
    def add(rel, tid):
        if tid and tid in records and tid != nid:
            links.append([rel, tid])

    for k, v in fm.items():
        if k == idf:
            continue
        if k in ID_SKIP:
            continue
        if isinstance(v, str) and k.endswith("Id"):
            add(humanize(k), v)
        elif isinstance(v, list) and k.endswith("Ids"):
            for item in v:
                if isinstance(item, str):
                    add(humanize(k), item)
    # participants arrays (emails, meetings)
    for p in (fm.get("participants") or []):
        if isinstance(p, dict):
            if p.get("personId"):
                add("Participant", p["personId"])
            if p.get("organisationId"):
                add("Organisation", p["organisationId"])

    # plain display fields
    fields = {}
    for k, v in fm.items():
        if k in FIELD_BLACKLIST or k == idf:
            continue
        if k.endswith("Id") or k.endswith("Ids"):
            continue
        if isinstance(v, (str, int, float, bool)) and v not in (None, ""):
            fields[k] = v

    # de-dup links
    seen = set(); ul = []
    for rel, tid in links:
        key = (rel, tid)
        if key not in seen:
            seen.add(key); ul.append([rel, tid])

    nodes[nid] = {"t": tk, "n": name_of.get(nid, nid), "f": fields, "l": ul,
                  "al": [clean_name(a) for a in (fm.get("aliases") or []) if isinstance(a, str)],
                  "tg": [t for t in (fm.get("tags") or []) if isinstance(t, str)]}

types_meta = []
for type_key, label, icon, tip in TYPES:
    cnt = sum(1 for v in nodes.values() if v["t"] == type_key)
    if cnt:
        types_meta.append({"key": type_key, "label": label, "icon": icon, "tip": tip, "count": cnt})

payload = {"types": types_meta, "nodes": nodes}
data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

TEMPLATE = open(os.path.join(HERE, "template_wiki.html"), encoding="utf-8").read()
out = TEMPLATE.replace("/*__DATA__*/", data_json)
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(out)

total_links = sum(len(v["l"]) for v in nodes.values())
print(f"Wrote {OUT}")
print(f"Nodes: {len(nodes)}  across {len(types_meta)} types  |  Links: {total_links}")
print(f"Size: {os.path.getsize(OUT)/1024/1024:.2f} MB")
for t in types_meta:
    print(f"  {t['icon']} {t['label']:<22} {t['count']}")
