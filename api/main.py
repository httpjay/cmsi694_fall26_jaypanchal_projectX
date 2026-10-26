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
        clauses.append("contract_award_unique_key ILIKE :search")
        params["search"] = f"%{search}%"

    where = " AND ".join(clauses)

    data = rows(f"""
        SELECT "rank", contract_award_unique_key, award_date, original_award,
               predicted_dollars, predicted_chance, naics_code,
               product_service_code, extent_competed, contract_pricing_type,
               planned_duration_days, under_umbrella,
               target_dollars, target_grew
        FROM watchlist
        WHERE {where}
        ORDER BY "rank"
        LIMIT :limit OFFSET :offset
    """, **params)

    total = rows(f"SELECT COUNT(*) AS n FROM watchlist WHERE {where}",
                 **{k: v for k, v in params.items() if k not in ("limit", "offset")})[0]["n"]

    return {"total": int(total), "rows": data}


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
