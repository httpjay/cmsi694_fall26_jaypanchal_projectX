"""
Project X - watchlist service

Serving layer. Reads the scored watchlist and the contract data from Postgres
and exposes them to the interface.

Run:  uvicorn api.main:app --reload
Then open http://127.0.0.1:8000
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import create_engine, text
import csv
import os

DB_URL = os.environ.get(
    "PROJECTX_DB",
    "postgresql+psycopg2://jaypanchal@localhost:5432/projectx",
)

engine = create_engine(DB_URL)
app = FastAPI(title="Project X watchlist")

HERE = os.path.dirname(__file__)


def rows(sql, **params):
    with engine.connect() as conn:
        result = conn.execute(text(sql), params)
        return [dict(r._mapping) for r in result]


# ------------------------------------------------------------------
# How much the headline number moves between training runs
# ------------------------------------------------------------------
#
# Training is not repeatable: XGBoost splits work across threads and the
# order they finish in is not fixed, so the same code on the same data gives
# slightly different trees. The top 200 is decided by a handful of enormous
# contracts, so that small difference moves the total by millions.
#
# train_model.py measures this across five seeds and writes the results to
# scrum27_seeds.csv. The page reads the range from here so it can say that
# the figure on screen is one run, not the answer.

SEEDS_CSV = os.path.join(HERE, "..", "scrum27_seeds.csv")


def seed_range():
    """Lowest and highest top-200 capture for the watchlist model, or None."""
    try:
        with open(SEEDS_CSV, newline="") as f:
            rows_ = list(csv.DictReader(f))
        col = next(c for c in rows_[0] if c.startswith("Model C"))
        values = [float(r[col]) for r in rows_]
        if len(values) < 2:
            return None
        return {"low": min(values), "high": max(values), "runs": len(values)}
    except Exception:
        # The page works without it; it just says less.
        return None


# ------------------------------------------------------------------
# Summary - the headline numbers
# ------------------------------------------------------------------

@app.get("/api/summary")
def summary(top_k: int = 200):
    test_totals = rows("""
        SELECT COUNT(*) AS contracts,
               SUM(target_dollars) AS total_growth
        FROM model_final WHERE split = 'test'
    """)[0]

    captured = rows("""
        SELECT SUM(target_dollars) AS actual,
               SUM(predicted_dollars) AS predicted,
               COUNT(*) FILTER (WHERE target_grew = 1) AS grew
        FROM watchlist WHERE "rank" <= :k
    """, k=top_k)[0]

    baseline = rows("""
        SELECT SUM(target_dollars) AS actual
        FROM (SELECT target_dollars FROM model_final
              WHERE split = 'test'
              ORDER BY original_award DESC LIMIT :k) t
    """, k=top_k)[0]

    ceiling = rows("""
        SELECT SUM(target_dollars) AS actual
        FROM (SELECT target_dollars FROM model_final
              WHERE split = 'test'
              ORDER BY target_dollars DESC LIMIT :k) t
    """, k=top_k)[0]

    return {
        "top_k": top_k,
        "seed_range": seed_range(),
        "test_contracts": int(test_totals["contracts"] or 0),
        "test_total_growth": float(test_totals["total_growth"] or 0),
        "watchlist_captured": float(captured["actual"] or 0),
        "watchlist_predicted": float(captured["predicted"] or 0),
        "watchlist_grew": int(captured["grew"] or 0),
        "baseline_captured": float(baseline["actual"] or 0),
        "ceiling": float(ceiling["actual"] or 0),
    }


# ------------------------------------------------------------------
# The ranked watchlist
# ------------------------------------------------------------------

@app.get("/api/watchlist")
def watchlist(
    limit: int = Query(50, le=500),
    offset: int = 0,
    min_award: float = 0,
    competed: str | None = None,
    search: str | None = None,
):
    clauses = ['"rank" IS NOT NULL', "original_award >= :min_award"]
    params = {"min_award": min_award, "limit": limit, "offset": offset}

    if competed:
        clauses.append("extent_competed = :competed")
        params["competed"] = competed
    if search:
        # a reviewer searches by company name far more often than by
        # contract number, so both are matched
        clauses.append("(contract_award_unique_key ILIKE :search"
                       " OR recipient_name ILIKE :search)")
        params["search"] = f"%{search}%"

    where = " AND ".join(clauses)

    # running_total is the money a reviewer would have found by reading the
    # list from the top down to this row. It is computed over the whole
    # watchlist in rank order BEFORE any filter is applied, because it
    # describes the real review order, not the filtered view.
    data = rows(f"""
        WITH ranked AS (
            SELECT "rank", contract_award_unique_key, recipient_name,
                   award_date, original_award,
                   predicted_dollars, predicted_chance, naics_code,
                   product_service_code, extent_competed, contract_pricing_type,
                   planned_duration_days, under_umbrella,
                   target_dollars, target_grew,
                   SUM(target_dollars) OVER (ORDER BY "rank") AS running_total
            FROM watchlist
        )
        SELECT * FROM ranked
        WHERE {where}
        ORDER BY "rank"
        LIMIT :limit OFFSET :offset
    """, **params)

    total = rows(f"SELECT COUNT(*) AS n FROM watchlist WHERE {where}",
                 **{k: v for k, v in params.items() if k not in ("limit", "offset")})[0]["n"]

    return {"total": int(total), "rows": data}


# ------------------------------------------------------------------
# The capture curve - money found against how far down the list you read
# ------------------------------------------------------------------

@app.get("/api/curve")
def curve(n: int = Query(1000, le=5000)):
    """Three cumulative curves over the test year.

    For each position k, how many dollars of real growth a reviewer would
    have found by reading the first k contracts of that ordering.

    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW matters here. The
    default window frame is RANGE, which lumps tied values into one step -
    and target_dollars is zero for 96% of contracts, so RANGE would collapse
    them all into a single point.
    """
    model = rows("""
        SELECT "rank" AS k,
               SUM(target_dollars) OVER (
                   ORDER BY "rank"
                   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cum
        FROM watchlist
        WHERE "rank" <= :n
        ORDER BY "rank"
    """, n=n)

    def ordered_curve(order_by):
        return rows(f"""
            SELECT k, cum FROM (
                SELECT ROW_NUMBER() OVER (ORDER BY {order_by} DESC) AS k,
                       SUM(target_dollars) OVER (
                           ORDER BY {order_by} DESC
                           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cum
                FROM model_final WHERE split = 'test'
            ) t WHERE k <= :n ORDER BY k
        """, n=n)

    return {
        "n": n,
        "model":    [[int(r["k"]), float(r["cum"] or 0)] for r in model],
        "baseline": [[int(r["k"]), float(r["cum"] or 0)]
                     for r in ordered_curve("original_award")],
        "ceiling":  [[int(r["k"]), float(r["cum"] or 0)]
                     for r in ordered_curve("target_dollars")],
    }


# ------------------------------------------------------------------
# One contract, with comparable contracts for context
# ------------------------------------------------------------------

@app.get("/api/contract/{key}")
def contract(key: str):
    found = rows("""
        SELECT * FROM watchlist WHERE contract_award_unique_key = :key
    """, key=key)
    if not found:
        raise HTTPException(status_code=404, detail="Contract not in the watchlist")
    c = found[0]

    # How contracts of this shape behaved in the training year
    peers = rows("""
        SELECT COUNT(*) AS contracts,
               ROUND(100.0 * COUNT(*) FILTER (WHERE target_grew = 1)
                     / NULLIF(COUNT(*), 0), 1) AS pct_grew,
               ROUND(AVG(target_dollars)::numeric, 0) AS avg_growth
        FROM model_final
        WHERE split = 'train'
          AND naics_code = :naics
          AND extent_competed = :competed
    """, naics=c["naics_code"], competed=c["extent_competed"])[0]

    duration_peers = rows("""
        SELECT COUNT(*) AS contracts,
               ROUND(100.0 * COUNT(*) FILTER (WHERE target_grew = 1)
                     / NULLIF(COUNT(*), 0), 1) AS pct_grew
        FROM model_final
        WHERE split = 'train'
          AND planned_duration_days BETWEEN :lo AND :hi
    """, lo=max(0, (c["planned_duration_days"] or 0) - 90),
         hi=(c["planned_duration_days"] or 0) + 90)[0]

    return {"contract": c, "similar_by_industry": peers,
            "similar_by_duration": duration_peers}


# ------------------------------------------------------------------
# Filter options for the interface
# ------------------------------------------------------------------

@app.get("/api/filters")
def filters():
    return {
        "extent_competed": [
            r["extent_competed"] for r in rows("""
                SELECT DISTINCT extent_competed FROM watchlist
                WHERE extent_competed IS NOT NULL ORDER BY 1
            """)
        ]
    }


# ------------------------------------------------------------------
# Serve the interface
# ------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))
