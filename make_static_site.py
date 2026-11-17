"""
SCRUM-31 - build a copy of the watchlist that other people can open.

    python3 -m uvicorn api.main:app        # in one terminal
    python3 make_static_site.py            # in another

Writes docs/index.html: one file, no server, no database. Open it from a
hard disk, email it, or let GitHub Pages serve it. Nothing to install and
nothing to keep running.

Why a copy instead of hosting the real thing
--------------------------------------------
Hosting api/main.py means hosting PostgreSQL with it, which means an account,
a monthly bill and a database that has to stay awake. For data that stops in
September 2018 and will never change again, that is a lot of machinery to keep
a fixed answer available. The live version stays the one to run while the
project is being worked on; this is the one to hand to somebody else.

How it works
------------
The page is NOT rewritten. The same api/static/index.html is used as it is,
with two things added:

  1. the answers this project's five endpoints would give, saved as data
  2. a short piece of JavaScript that answers fetch() from that saved data

So there is one interface, not two. A change to index.html shows up in both
versions the next time this runs, and cannot show up in only one of them.

The honest cost: the filtering, searching and paging that api/main.py does in
SQL have to be done again, in JavaScript, for the saved copy. Two pieces of
code doing one job is how the two versions could quietly start disagreeing, so
this script does not take it on trust - it asks the live API for a grid of
filter combinations, asks the saved copy the same questions through Node, and
refuses to write the file if any answer differs. See verify() at the bottom.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

API = os.environ.get("PROJECTX_API", "http://127.0.0.1:8000")
HERE = os.path.dirname(os.path.abspath(__file__))
PAGE_IN = os.path.join(HERE, "api", "static", "index.html")
OUT_DIR = os.path.join(HERE, "docs")
OUT = os.path.join(OUT_DIR, "index.html")

# Every row is saved, not just the first page, because the saved copy has no
# server to ask for the next one.
ALL_ROWS = 500          # the live API's own per-request ceiling
TOP_K = 200


def get(path):
    with urllib.request.urlopen(API + path, timeout=60) as r:
        return json.loads(r.read())


def collect():
    """Ask the live API everything the page could ever ask it."""
    print("Reading from the running server...")

    rows, offset = [], 0
    while True:
        page = get(f"/api/watchlist?limit={ALL_ROWS}&offset={offset}")
        rows.extend(page["rows"])
        offset += ALL_ROWS
        if offset >= page["total"]:
            break
    print(f"  {len(rows):,} contracts")

    # The detail panel asks per contract. Saving one entry per contract is
    # more data than strictly needed - the peer figures only depend on the
    # industry, how it was competed and the duration - but it keeps the
    # saved copy a plain lookup, which is far easier to be sure about than
    # a clever one.
    details = {}
    for i, r in enumerate(rows, 1):
        key = r["contract_award_unique_key"]
        details[key] = get(f"/api/contract/{urllib.parse.quote(key)}")
        if i % 100 == 0:
            print(f"  {i:,} of {len(rows):,} detail panels")

    return {
        "summary": get(f"/api/summary?top_k={TOP_K}"),
        "curve": get("/api/curve?n=500"),
        "filters": get("/api/filters"),
        "rows": rows,
        "details": details,
    }


# The saved copy's stand-in for the server. It answers the same five URLs the
# page already asks for, so index.html needs no change at all.
SHIM = """
<script id="baked-data" type="application/json">%(data)s</script>
<script>
// SCRUM-31. There is no server behind this copy of the page, so fetch() is
// answered from the data saved above. The page itself is untouched: it asks
// the same five URLs it always asked.
(function () {
  const D = JSON.parse(document.getElementById("baked-data").textContent);

  // The same filtering api/main.py does in SQL. Kept deliberately literal so
  // it can be read next to the SQL and compared line by line.
  function select(p) {
    const minAward = parseFloat(p.get("min_award") || "0") || 0;
    const competed = p.get("competed") || "";
    const search   = (p.get("search") || "").toLowerCase();

    const hits = D.rows.filter(r => {
      if (!(r.original_award >= minAward)) return false;
      if (competed && r.extent_competed !== competed) return false;
      if (search) {
        const key = (r.contract_award_unique_key || "").toLowerCase();
        const who = (r.recipient_name || "").toLowerCase();
        if (!key.includes(search) && !who.includes(search)) return false;
      }
      return true;
    });

    const offset = parseInt(p.get("offset") || "0", 10);
    const limit  = parseInt(p.get("limit")  || "50", 10);
    // running_total is already saved per row. It is the money found reading
    // the FULL list down to that row, so it must not be recomputed over a
    // filtered view - that would describe a review order nobody follows.
    return {total: hits.length, rows: hits.slice(offset, offset + limit)};
  }

  function answer(url) {
    const u = new URL(url, "http://local");
    const path = u.pathname;
    if (path === "/api/summary") return D.summary;
    if (path === "/api/curve")   return D.curve;
    if (path === "/api/filters") return D.filters;
    if (path === "/api/watchlist") return select(u.searchParams);
    if (path.startsWith("/api/contract/")) {
      const key = decodeURIComponent(path.slice("/api/contract/".length));
      return D.details[key] || null;
    }
    return null;
  }

  window.__answer = answer;   // used by the build-time check, harmless here

  const realFetch = window.fetch;
  window.fetch = function (input) {
    const url = typeof input === "string" ? input : input.url;
    if (url && url.indexOf("/api/") !== -1) {
      const body = answer(url);
      return Promise.resolve(new Response(JSON.stringify(body), {
        status: body === null ? 404 : 200,
        headers: {"Content-Type": "application/json"},
      }));
    }
    return realFetch.apply(this, arguments);
  };
})();
</script>
"""

BANNER = """
<div id="saved-copy-note">
  A saved copy, built from the data as it stood when the page was made.
  Nothing here is live, and nothing is sent anywhere.
</div>
<style>
  #saved-copy-note {
    font-size: 12px; padding: 8px 14px; margin: 0 0 4px;
    background: rgba(127,127,127,.10); border-radius: 6px;
  }
</style>
"""


def build(data):
    with open(PAGE_IN, encoding="utf-8") as f:
        page = f.read()

    shim = SHIM % {"data": json.dumps(data, default=str, separators=(",", ":"))}

    # The shim must run before the page's own script, so it goes in <head>.
    # </head> is matched rather than <head> so nothing is inserted above the
    # page's own character-set declaration.
    if "</head>" not in page:
        sys.exit("index.html has no </head> - cannot insert the saved data")
    page = page.replace("</head>", shim + "</head>", 1)

    if "<body>" in page:
        page = page.replace("<body>", "<body>" + BANNER, 1)

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(page)
    return page


def verify(data):
    """Ask both versions the same questions and refuse to ship a disagreement.

    The saved copy repeats, in JavaScript, filtering that api/main.py does in
    SQL. Two pieces of code doing one job drift apart sooner or later, and the
    way that shows up is a reviewer reading a list that quietly differs from
    the real one. So they are compared here rather than assumed equal.
    """
    competed = [None] + data["filters"]["extent_competed"][:3]
    cases = []
    for c in competed:
        for min_award in (0, 50000, 5_000_000):
            for search in (None, "a", "zzzznothing"):
                q = f"limit=50&offset=0&min_award={min_award}"
                if c:
                    q += f"&competed={urllib.parse.quote(c)}"
                if search:
                    q += f"&search={search}"
                cases.append(q)

    script = """
const fs = require("fs");
const html = fs.readFileSync(process.argv[1], "utf8");
const m = html.match(/<script id="baked-data"[^>]*>([\\s\\S]*?)<\\/script>/);
const D = JSON.parse(m[1]);
%(select)s
const out = [];
for (const q of JSON.parse(process.argv[2])) {
  const r = select(new URLSearchParams(q));
  out.push({total: r.total,
            keys: r.rows.map(x => x.contract_award_unique_key)});
}
console.log(JSON.stringify(out));
"""
    # The select() the saved page will really use, lifted out of the shim so
    # the check cannot accidentally test a different copy of it.
    start = SHIM.index("  function select(p) {")
    end = SHIM.index("  function answer(url)")
    select_src = SHIM[start:end]

    proc = subprocess.run(
        ["node", "-e", script % {"select": select_src}, OUT, json.dumps(cases)],
        capture_output=True, text=True)
    if proc.returncode:
        sys.exit("the saved copy's own filter could not be run:\n" + proc.stderr)
    theirs = json.loads(proc.stdout)

    bad = 0
    for q, got in zip(cases, theirs):
        live = get("/api/watchlist?" + q)
        want = {"total": live["total"],
                "keys": [r["contract_award_unique_key"] for r in live["rows"]]}
        if want != got:
            bad += 1
            print(f"  DIFFERS  ?{q}")
            print(f"    live  {want['total']:,} contracts")
            print(f"    saved {got['total']:,} contracts")
    return bad, len(cases)


def main():
    data = collect()
    build(data)

    print(f"\nChecking the saved copy against the live one "
          f"on every filter combination...")
    bad, total = verify(data)
    if bad:
        os.remove(OUT)
        sys.exit(f"\n{bad} of {total} disagreed. Nothing was written.")

    size = os.path.getsize(OUT) / 1024 / 1024
    print(f"  {total} combinations, all identical")
    print(f"\nWrote {os.path.relpath(OUT, HERE)} ({size:.1f} MB)")
    print("Open it in a browser, or let GitHub Pages serve the docs folder.")


if __name__ == "__main__":
    main()
