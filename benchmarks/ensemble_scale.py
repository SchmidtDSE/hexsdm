"""Raw-score vs rank-scaled ensembles (#35) on the seven CDFW species.

Fits each species twice with the default rf + glm ensemble, once with
ensemble_scale "raw" and once with "rank", over California at H3 res 8, and
reports the ensemble's spatial-CV AUC, Boyce and TSS, the suitable area, and
the AUC of the suitability surface against the SGCN expert range (the
docs/benchmarks.md query).

    SDM_OUTPUT_DIR=/tmp/sdm python benchmarks/ensemble_scale.py > ensemble_scale.csv
"""
import sys

import duckdb
import pandas as pd

from hexsdm import data, outputs, pipeline

SPECIES = ["Actinemys marmorata", "Ambystoma californiense", "Dipodomys ingens", "Gambelia sila",
           "Phrynosoma blainvillii", "Spea hammondii", "Thamnophis gigas"]
SGCN = "s3://public-swap/california/swap-2025/sgcn-ranges/hex/h0=*/data_0.parquet"


def range_auc(con, pred: pd.DataFrame, species: str) -> float:
    """Mann-Whitney AUC of suitability with SGCN range membership as the label (average ranks for ties)."""
    con.register("p", pred[["h8", "suitability"]].rename(columns={"suitability": "s"}))
    return con.sql(f"""
      WITH g AS (SELECT DISTINCT h8 FROM read_parquet('{SGCN}', hive_partitioning = true)
                 WHERE h0 IN (SELECT DISTINCT h3_cell_to_parent(h8, 0)::BIGINT FROM p)
                   AND SWAP_Scientific LIKE '{species}%'),
      j AS (SELECT p.s, g.h8 IS NOT NULL AS y FROM p LEFT JOIN g USING (h8)),
      r AS (SELECT y, rank() OVER (ORDER BY s) + (count(*) OVER (PARTITION BY s) - 1) / 2.0 AS rk FROM j)
      SELECT (sum(rk) FILTER (y) - count(*) FILTER (y) * (count(*) FILTER (y) + 1) / 2.0)
             / (count(*) FILTER (y) * count(*) FILTER (NOT y)) FROM r""").fetchone()[0]


def main():
    con = data.connect()
    rows = []
    for sp in SPECIES:
        for scale in ("raw", "rank"):
            s = pipeline.run({"occurrences": {"gbif": {"species": sp}},
                              "domain": {"type": "region", "region": "US-CA"}, "resolution": 8,
                              "ensemble_scale": scale}, log=lambda m: None)
            pred = pd.read_parquet(outputs.OUTPUT_DIR / s["run_id"] / "predictions.parquet")
            cv = s["cv_metrics"]["ensemble"]
            rows.append({"species": sp, "scale": scale, "run_id": s["run_id"],
                         "presence_cells": s["occurrences"]["presence_cells_at_res"],
                         "cv_auc": cv["auc"], "cv_boyce": cv.get("boyce"), "cv_tss": cv.get("tss"),
                         "suitable_km2": s["suitable_area_km2"], "threshold": s["threshold"]["value"],
                         "weights": s["ensemble_weights"], "sgcn_auc": round(range_auc(con, pred, sp), 4),
                         "seconds": s.get("elapsed_s")})
            print(rows[-1], file=sys.stderr, flush=True)
    pd.DataFrame(rows).to_csv(sys.stdout, index=False)


if __name__ == "__main__":
    main()
