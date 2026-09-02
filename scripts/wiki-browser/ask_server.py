#!/usr/bin/env python3
"""
Local "Ask the Wiki" server for the Influential Brands knowledge vault.

- Reads OPENAI_API_KEY from influential-brands/.env.local (stays server-side).
- Parses the vault entity notes into an in-memory graph at startup.
- On POST /ask, retrieves the records relevant to the question and asks
  OpenAI (gpt-4o-mini) to answer using ONLY those records (strict grounding).
- Serves the self-contained wiki-browser.html on GET /.

Run:  python3 ask_server.py       (or double-click "Ask the Wiki.command")
Stdlib only — no pip installs.
"""
import os, re, sys, json, threading, subprocess, webbrowser, urllib.request, urllib.error
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(SCRIPT_DIR)                        # .../scripts
VAULT = os.path.abspath(os.environ.get("IB_VAULT_ROOT") or os.path.join(SCRIPT_DIR, "..", ".."))  # influential-brands/
ENT = os.path.join(VAULT, "entities")
HTML_PATH = os.path.join(VAULT, "Apps", "wiki-browser.html")
DATA_PATH = os.path.join(VAULT, "Apps", "wiki-data.js")
PORT = int(os.environ.get("IB_WIKI_PORT", "8765"))

# ToEnhance writer — lets the person-screen checkbox persist to the vault
sys.path.insert(0, SCRIPTS_DIR)
from mark_to_enhance import read_to_enhance, set_to_enhance  # noqa: E402
MODEL = "gpt-4o-mini"
GROUNDING = "strict"   # "strict" = vault-only; "open" = vault + general knowledge

# ── env ───────────────────────────────────────────────────────
def load_env():
    env = {}
    p = os.path.join(VAULT, ".env.local")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env
API_KEY = load_env().get("OPENAI_API_KEY", "").strip()

# ── vault parsing (mirrors build_wiki.py) ─────────────────────
TYPES = [
    ("people","People"),("organisations","Organisations"),("appointments","Appointments"),
    ("brands","Brands"),("industries","Industries"),("locations","Locations"),
    ("organisational-functions","Functions"),("marketing-campaigns","Campaigns"),
    ("marketing-segments","Segments"),("products-services","Products"),
    ("projects-initiatives","Projects"),("sales-opportunities","Sales Opps"),
    ("topics","Topics"),("meetings-events","Meetings"),("email-messages","Emails"),
    ("sources","Sources"),("decisions","Decisions"),("search","Searches"),
]
TYPE_LABEL = {k: l for k, l in TYPES}
ID_FIELD = {
    "people":"personId","organisations":"organisationId","appointments":"appointmentId",
    "brands":"brandId","industries":"industryId","locations":"locationId",
    "organisational-functions":"functionId","marketing-campaigns":"campaignId",
    "marketing-segments":"marketingSegmentId","products-services":"productServiceId",
    "projects-initiatives":"projectInitiativeId","sales-opportunities":"opportunityId",
    "topics":"topicId","meetings-events":"meetingEventId","email-messages":"emailMessageId",
    "sources":"sourceId","decisions":"decisionId","search":"queryId",
}
ID_SKIP = {"messageId","bodyHash","evidenceHash","threadIndex","queryId"}
FIELD_SKIP = {"entityType","sourceRefs","aliases","tags","extraction","relationships",
    "participants","titleObservations","bodyHash","threadIndex","inputLocator","attachments",
    "messageId","evidenceHash","outcomes","domains","procedureVersion","parserVersion",
    "hashAlgorithm","fileHash","rawPath","originalPath","membershipRule","affects"}

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

def humanize(key):
    k = key[:-3] if key.endswith("Ids") else (key[:-2] if key.endswith("Id") else key)
    out = ""
    for i, c in enumerate(k):
        if c.isupper() and i > 0 and not k[i-1].isupper():
            out += " "
        out += c
    return (out[:1].upper() + out[1:]) if out else key

NODES = {}   # id -> {t,name,fields,links:[(rel,tid)],text}
NAME = {}
INBOUND = {}

def build_graph():
    records = {}
    for tk, _ in TYPES:
        d = os.path.join(ENT, tk)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".md") or fn in ("catalog.md","index.md","log.md"):
                continue
            fm = parse_fm(os.path.join(d, fn))
            if not fm:
                continue
            idf = ID_FIELD.get(tk)
            nid = fm.get(idf) or fn[:-3]
            records[nid] = (tk, fm, idf)
            nm = (fm.get("displayName") or fm.get("name") or fm.get("title")
                  or fm.get("subject") or fm.get("query") or fm.get("primaryEmail") or nid)
            NAME[nid] = clean_name(nm) if isinstance(nm, str) else nid
    # composed names
    for nid, (tk, fm, idf) in records.items():
        if tk == "appointments":
            title = clean_name(fm.get("title") or "Appointment")
            org = NAME.get(fm.get("organisationId"))
            NAME[nid] = f"{title} · {org}" if org else title
        elif tk == "email-messages":
            NAME[nid] = clean_name(fm.get("subject") or "(no subject)") or "(no subject)"
    # nodes + links
    for nid, (tk, fm, idf) in records.items():
        links = []
        def add(rel, tid):
            if tid and tid in records and tid != nid:
                links.append((rel, tid))
        for k, v in fm.items():
            if k == idf or k in ID_SKIP:
                continue
            if isinstance(v, str) and k.endswith("Id"):
                add(humanize(k), v)
            elif isinstance(v, list) and k.endswith("Ids"):
                for it in v:
                    if isinstance(it, str):
                        add(humanize(k), it)
        for p in (fm.get("participants") or []):
            if isinstance(p, dict):
                if p.get("personId"): add("Participant", p["personId"])
                if p.get("organisationId"): add("Organisation", p["organisationId"])
        fields = {}
        for k, v in fm.items():
            if k in FIELD_SKIP or k == idf or k.endswith("Id") or k.endswith("Ids"):
                continue
            if isinstance(v, (str, int, float, bool)) and v not in (None, ""):
                fields[k] = v
        # dedup links
        seen = set(); ul = []
        for rel, tid in links:
            if (rel, tid) not in seen:
                seen.add((rel, tid)); ul.append((rel, tid))
        text = " ".join([NAME.get(nid, nid)] + [str(x) for x in fields.values()]
                        + [clean_name(a) for a in (fm.get("aliases") or []) if isinstance(a, str)]
                        + [d for d in (fm.get("domains") or []) if isinstance(d, str)]).lower()
        NODES[nid] = {"t": tk, "name": NAME.get(nid, nid), "fields": fields, "links": ul, "text": text}
    for nid, n in NODES.items():
        for rel, tid in n["links"]:
            INBOUND.setdefault(tid, []).append((rel, nid))

# ── retrieval ─────────────────────────────────────────────────
STOP = set("tell me what we have has had do did done with over the a an of to on in it that this you your my i can could would please about show give our us is are was were who whom when where how and for history timeline summary list all any recent latest everything anything know years year been their they them he she his her get got find regarding re vs into around related relationship relationships work works working done".split())

def sig_tokens(q):
    return [w for w in re.findall(r"[a-z0-9][a-z0-9.\-&]*", q.lower()) if len(w) >= 3 and w not in STOP]

def retrieve(question, max_nodes=45):
    toks = sig_tokens(question)
    if not toks:
        return [], []
    scored = []
    best = 0
    for nid, n in NODES.items():
        c = sum(1 for t in toks if t in n["text"])
        if c:
            scored.append((nid, c)); best = max(best, c)
    seeds = [nid for nid, c in scored if c == best]
    if len(seeds) > 60:  # broad → prefer name matches
        name_hits = [nid for nid in seeds if any(t in NODES[nid]["name"].lower() for t in toks)]
        seeds = name_hits or seeds
        seeds = seeds[:60]
    # 1-hop neighborhood
    hood = list(seeds)
    seen = set(seeds)
    for nid in seeds:
        for rel, tid in NODES[nid]["links"]:
            if tid not in seen and tid in NODES:
                seen.add(tid); hood.append(tid)
        for rel, sid in INBOUND.get(nid, []):
            if sid not in seen and sid in NODES:
                seen.add(sid); hood.append(sid)
    # order: seeds first, then by a light type priority
    prio = {"people":0,"appointments":1,"organisations":2,"brands":3,"industries":4,
            "marketing-segments":5,"marketing-campaigns":6,"projects-initiatives":7,
            "email-messages":8,"meetings-events":9}
    seed_set = set(seeds)
    hood.sort(key=lambda i: (i not in seed_set, prio.get(NODES[i]["t"], 20), NODES[i]["name"].lower()))
    hood = hood[:max_nodes]
    return seeds, hood

def record_line(nid):
    n = NODES[nid]
    parts = [f"[{TYPE_LABEL.get(n['t'], n['t'])}] {n['name']}"]
    for k, v in n["fields"].items():
        if k in ("status","confidence"):
            continue
        parts.append(f"{k}={v}")
    rels = []
    for rel, tid in n["links"]:
        if tid in NODES:
            rels.append(f"{rel}: {NODES[tid]['name']}")
    if rels:
        parts.append("linked → " + "; ".join(rels[:12]))
    return " | ".join(parts)

def build_context(hood):
    return "\n".join("- " + record_line(nid) for nid in hood)

# ── OpenAI ────────────────────────────────────────────────────
def ask_openai(question, context):
    if not API_KEY:
        return "No OPENAI_API_KEY is set in .env.local, so I can't run the AI answer. Add your key and restart the server."
    if GROUNDING == "strict":
        sys = ("You are a knowledge assistant for the 'Influential Brands' relationship & communications vault. "
               "Answer using ONLY the CONTEXT records provided below — do NOT use outside or general knowledge, and never invent facts. "
               "Always be USEFUL: if the exact thing asked (e.g. an activity history) is not in the context but related records ARE, "
               "first summarise everything the vault DOES hold about the subject — the people and their roles, the organisation, brand, "
               "industry, segment, location and any dates — and THEN note what is missing (e.g. 'no dated interactions or campaigns are "
               "recorded'). Only reply that the vault has nothing if the context is genuinely empty of relevant records. "
               "Be concise and executive in tone; cite the specific names, roles and organisations that appear in the context.")
    else:
        sys = ("You are a knowledge assistant for the 'Influential Brands' vault. Prefer the CONTEXT records; you may add "
               "widely-known general facts, but clearly separate vault facts from general knowledge. Be concise and executive.")
    payload = {
        "model": MODEL,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": sys},
            {"role": "user", "content": f"CONTEXT (vault records):\n{context}\n\nQUESTION: {question}"},
        ],
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        return f"OpenAI API error ({e.code}). {body[:300]}"
    except Exception as e:
        return f"Could not reach OpenAI: {e}"

def answer(question):
    seeds, hood = retrieve(question)
    if not hood:
        return {"answer": "I couldn't find anything in the vault matching that. Try a company, person, or brand name.",
                "sources": []}
    context = build_context(hood)
    text = ask_openai(question, context)
    sources = [{"id": nid, "name": NODES[nid]["name"], "type": NODES[nid]["t"]} for nid in seeds[:20]]
    return {"answer": text, "sources": sources}

# ── HTTP ──────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def _send(self, code, body, ctype="application/json"):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)
    def do_GET(self):
        if self.path in ("/", "/index.html", "/wiki-browser.html"):
            try:
                with open(HTML_PATH, "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except FileNotFoundError:
                self._send(404, "wiki-browser.html not found — run build_wiki.py first.", "text/plain")
        elif self.path == "/wiki-data.js":
            data_path = os.path.join(os.path.dirname(HTML_PATH), "wiki-data.js")
            try:
                with open(data_path, "rb") as f:
                    self._send(200, f.read(), "application/javascript; charset=utf-8")
            except FileNotFoundError:
                self._send(404, "wiki-data.js not found — run build_wiki.py first.", "text/plain")
        elif self.path.startswith("/to-enhance-state"):
            from urllib.parse import urlparse, parse_qs
            pid = (parse_qs(urlparse(self.path).query).get("id") or [""])[0]
            try:
                self._send(200, json.dumps({"status": "ok", "id": pid, "value": read_to_enhance(pid, root=Path(VAULT))}))
            except Exception as e:
                self._send(404, json.dumps({"status": "failed", "error": f"{type(e).__name__}: {e}"}))
        else:
            self._send(404, "Not found", "text/plain")
    def do_POST(self):
        if self.path == "/rebuild":
            try:
                build = os.path.join(SCRIPT_DIR, "build_wiki.py")
                r = subprocess.run([sys.executable, build], capture_output=True, text=True, timeout=600)
                if r.returncode != 0:
                    raise RuntimeError((r.stderr or r.stdout or "build failed").strip()[:500])
                self._send(200, json.dumps({"status": "ok"}))
            except Exception as e:
                self._send(500, json.dumps({"status": "failed", "error": f"{type(e).__name__}: {e}"}))
            return
        if self.path == "/set-to-enhance":
            try:
                n = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(n) or b"{}")
                value = payload.get("value")
                if value not in (True, False, None):
                    raise ValueError("value must be true, false or null")
                result = set_to_enhance(payload.get("id"), value, root=Path(VAULT))
                self._send(200, json.dumps({"status": "ok", **result}))
            except Exception as e:
                self._send(400, json.dumps({"status": "failed", "error": f"{type(e).__name__}: {e}"}))
            return
        if self.path != "/ask":
            self._send(404, "Not found", "text/plain"); return
        try:
            n = int(self.headers.get("Content-Length", 0))
            q = json.loads(self.rfile.read(n) or b"{}").get("question", "")
        except Exception:
            self._send(400, json.dumps({"answer": "Bad request", "sources": []})); return
        try:
            self._send(200, json.dumps(answer(q)))
        except Exception as e:
            self._send(500, json.dumps({"answer": f"Server error: {e}", "sources": []}))

def main():
    print("Parsing the Influential Brands vault…")
    build_graph()
    print(f"  loaded {len(NODES)} records.")
    if not API_KEY:
        print("  ⚠  No OPENAI_API_KEY found in .env.local — the Ask chat will return a setup message.")
    url = f"http://localhost:{PORT}/"
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"\n  Ask-the-Wiki is running →  {url}\n  (Press Ctrl+C to stop.)\n")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")

if __name__ == "__main__":
    main()
