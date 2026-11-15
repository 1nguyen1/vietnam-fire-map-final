# -*- coding: utf-8 -*-
# AI use: Written with assistance from Claude (Anthropic); reviewed and tested by team 268LTK.
"""
export_web.py - Chuyen ket qua cua harmonize.py thanh cac file NHO cho web, theo 34 tinh thanh moi.

Chay SAU harmonize.py:
    pip install geopandas shapely
    python export_web.py --out "D:/NASA/output" --boundaries "D:/NASA/boundaries/vn_34_provinces.geojson"

Ket qua: <out>/web_data/
    index.json                      danh sach tinh, ngay du lieu, thang chua du
    provinces.geojson               ranh gioi 34 tinh (da don gian hoa cho web)
    method.json                     phuong phap + kiem chung (ca nuoc + tung tinh)
    series/vietnam.json             chuoi thang ca nuoc: harmonized, khoang tin cay, median lich su, bat thuong
    series/<tinh>.json              chuoi thang tung tinh (cung cau truc)
    cells/<tinh>.csv                ban do o 0,01 do (~1 km) theo thang: lat_idx, lon_idx, ym, v
    points/<tinh>/<nam>.csv         diem chay sach de nguoi dung tai ve
"""
import argparse
import json
import os
import time
import unicodedata
import warnings

import numpy as np
import pandas as pd
import geopandas as gpd
import shapely
from shapely import STRtree

import harmonize as H

warnings.filterwarnings("ignore")

CELL_RES = 0.01            # luoi HIEN THI tren ban do (~1 km), trung luoi L3/B3 cua nhom
SIMPLIFY_ASSIGN = 0.0005   # ~50 m: don gian hoa ranh gioi khi gan tinh (sai lech o bien <= ~50 m)
SIMPLIFY_WEB = 0.003       # ~300 m: ranh gioi ve tren web (file nhe)
NEAREST_MAX = 0.05         # diem nam ngoai moi da giac (ranh gioi FIRMS lech ranh gioi tinh, chu yeu <2 km o bien gioi)
                           # -> gan tinh gan nhat trong ~5 km
BASE_YEARS = (2003, 2025)  # ky co so tinh median lich su

# Loi du lieu nguon (nguyenduy1133/Free-GIS-Data): doi tuong Ma=31 nam o DBSCL nhung bi ghi ten "Lang Son"
FIXES = {"31": {"TinhThanh": "Đồng Tháp", "SapNhap": "Đồng Tháp, Tiền Giang"}}


def slug(s):
    s = unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D"))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    return "-".join("".join(c if c.isalnum() else " " for c in s).split())


# -----------------------------------------------------------------------------
# [1] Ranh gioi 34 tinh
# -----------------------------------------------------------------------------
def load_provinces(path):
    g = gpd.read_file(path).to_crs(4326)
    g["Ma"] = g["Ma"].astype(str)
    for ma, fix in FIXES.items():
        m = g["Ma"] == ma
        if m.any() and (g["TinhThanh"] == g.loc[m, "TinhThanh"].iloc[0]).sum() > 1:   # chi sua khi ten bi trung
            for k, v in fix.items():
                g.loc[m, k] = v
            H.log(f"  sua loi du lieu: Ma={ma} -> {fix['TinhThanh']}")
    if g["TinhThanh"].duplicated().any():
        raise ValueError(f"Ten tinh bi trung: {g['TinhThanh'][g['TinhThanh'].duplicated()].tolist()}")
    g["province_id"] = g["TinhThanh"].map(slug)
    g = g.rename(columns={"TinhThanh": "province_name", "SapNhap": "merged_from"})
    return g[["province_id", "province_name", "merged_from", "Ma", "geometry"]].reset_index(drop=True)


def assign_provinces(lat, lon, prov):
    """Gan tinh cho tung diem (point-in-polygon). Diem ven bien nam ngoai -> tinh gan nhat (<= ~5 km)."""
    geoms = shapely.simplify(prov.geometry.values, SIMPLIFY_ASSIGN, preserve_topology=True)
    idx = np.full(len(lat), -1, dtype=np.int16)
    for k, geom in enumerate(geoms):
        shapely.prepare(geom)
        x0, y0, x1, y1 = geom.bounds
        cand = np.where((idx < 0) & (lon >= x0) & (lon <= x1) & (lat >= y0) & (lat <= y1))[0]
        if len(cand):
            idx[cand[shapely.contains_xy(geom, lon[cand], lat[cand])]] = k
    miss = np.where(idx < 0)[0]
    n_near = 0
    if len(miss):
        res = STRtree(geoms).query_nearest(shapely.points(lon[miss], lat[miss]),
                                           max_distance=NEAREST_MAX, all_matches=False)
        idx[miss[res[0]]] = res[1]
        n_near = len(res[0])
    return idx, n_near


# -----------------------------------------------------------------------------
# [2] Phan bo so harmonized cua o 0,25 do ve tung tinh
#     = trong so cac diem tham chieu (dung vi tri that)
#     + phan con lai (chay nho du doan o o MODIS thay 0) chia theo ty le chay VIIRS lich su cua o trong tung tinh
# -----------------------------------------------------------------------------
def cell_province_shares(pts, rng):
    s = pts[(pts["sat"] == "SNPP") & H.in_range(pts["ym"], rng)]
    a = s.groupby(["grid_id", "province_id"], observed=True).size()
    allp = pts.groupby(["grid_id", "province_id"], observed=True).size()
    have = a.index.get_level_values(0).unique()
    a = pd.concat([a, allp[~allp.index.get_level_values(0).isin(have)]])
    return (a / a.groupby(level=0).transform("sum")).rename("share").reset_index()


def allocate(cell_month, pts_w, shares):
    """cell_month: grid_id, ym, total | pts_w: grid_id, ym, province_id, w -> Series (province_id, ym)."""
    W = pts_w.groupby(["grid_id", "ym", "province_id"], observed=True)["w"].sum().reset_index()
    wc = W.groupby(["grid_id", "ym"])["w"].sum().rename("w_cell")
    cm = cell_month.set_index(["grid_id", "ym"]).join(wc).fillna({"w_cell": 0.0})
    cm["resid"] = (cm["total"] - cm["w_cell"]).clip(lower=0)
    r = cm[cm["resid"] > 0].reset_index()[["grid_id", "ym", "resid"]].merge(shares, on="grid_id", how="inner")
    r["w"] = r["resid"] * r["share"]
    out = pd.concat([W[["province_id", "ym", "w"]], r[["province_id", "ym", "w"]]])
    return out.groupby(["province_id", "ym"])["w"].sum()


# -----------------------------------------------------------------------------
# [3] Kiem chung cap TINH (dung mo hinh hoc tren VAL_TRAIN, cham tren VAL_TEST)
# -----------------------------------------------------------------------------
def province_validation(grid, pts, model_name):
    ok = grid.groupby("ym")["M"].transform("sum") > 0
    tr = grid[H.in_range(grid["ym"], H.VAL_TRAIN) & ok]
    te = grid[H.in_range(grid["ym"], H.VAL_TEST) & ok].copy()
    m = H.make_model(model_name).fit(tr)
    te["total"] = m.predict(te)
    aq = pts[(pts["sat"] == "Aqua") & H.in_range(pts["ym"], H.VAL_TEST)][["grid_id", "ym", "province_id"]].copy()
    ratio = te.set_index(["grid_id", "ym"]).eval("total / M").replace(np.inf, 0)
    aq["w"] = ratio.reindex(pd.MultiIndex.from_frame(aq[["grid_id", "ym"]])).fillna(0).values
    pred = allocate(te[["grid_id", "ym", "total"]], aq, cell_province_shares(pts, H.VAL_TRAIN))
    obs = pts[(pts["sat"] == "SNPP") & H.in_range(pts["ym"], H.VAL_TEST)].groupby(
        ["province_id", "ym"], observed=True).size()
    months = sorted(te["ym"].unique())
    idx = pd.MultiIndex.from_product([sorted(set(pts["province_id"]) - {"outside"}), months])
    d = pd.DataFrame({"V": obs.reindex(idx).fillna(0), "p": pred.reindex(idx).fillna(0)})
    rows = []
    for pid, g in d.groupby(level=0):
        g = g.droplevel(0)
        lr = np.log((g["V"] + 1) / (g["p"] + 1)).values        # sai so rieng cua tinh -> khoang tin cay rieng
        big = g[g["V"] >= 20]
        yr = [x["V"].corr(x["p"], method="spearman") for _, x in g.groupby(g.index.str[:4]) if x["V"].sum() > 0]
        rows.append({"province_id": pid, "V_test": int(g["V"].sum()),
                     "r": float(g["V"].corr(g["p"])) if g["V"].std() > 0 else np.nan,
                     "bias_pct": float((g["p"].sum() - g["V"].sum()) / max(g["V"].sum(), 1) * 100),
                     "mape_pct_V20": float((abs(big["p"] - big["V"]) / big["V"]).mean() * 100) if len(big) else np.nan,
                     "spearman_lich": float(np.nanmean(yr)) if yr else np.nan,
                     "ci_q05": float(np.quantile(lr, 0.05)), "ci_q95": float(np.quantile(lr, 0.95))})
    return pd.DataFrame(rows)


# -----------------------------------------------------------------------------
# [4] Median lich su, bat thuong, xep hang
# -----------------------------------------------------------------------------
def add_climatology(s):
    s = s.copy()
    base = s[(s["year"].between(*BASE_YEARS)) & (~s["is_partial_month"])]
    q = base.groupby("month")["v"].quantile([0.25, 0.5, 0.75]).unstack()
    s["p25"] = s["month"].map(q[0.25]); s["med"] = s["month"].map(q[0.5]); s["p75"] = s["month"].map(q[0.75])
    s["anom_pct"] = np.where(s["med"] > 0, (s["v"] - s["med"]) / s["med"] * 100, np.nan)
    vals = {mo: g["v"].values for mo, g in base.groupby("month")}
    s["pct_rank"] = [float(((vals[mo] < v).sum() + 0.5 * (vals[mo] == v).sum()) / len(vals[mo]) * 100)
                     for mo, v in zip(s["month"], s["v"])]
    s.loc[s["is_partial_month"], ["anom_pct", "pct_rank"]] = np.nan   # thang chua du: khong so sanh
    return s


def series_json(s, path):
    cols = {"ym": "ym", "v": "v", "ci_low": "lo", "ci_high": "hi", "src": "src", "is_partial_month": "partial",
            "med": "med", "p25": "p25", "p75": "p75", "anom_pct": "anom", "pct_rank": "rank"}
    o = s[list(cols)].rename(columns=cols)
    for c in ["v", "lo", "hi", "med", "p25", "p75", "anom", "rank"]:
        o[c] = o[c].astype(float).round(1)
    recs = json.loads(o.to_json(orient="records"))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(recs, f, ensure_ascii=False, separators=(",", ":"))


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="D:/NASA/output")
    ap.add_argument("--boundaries", default="D:/NASA/boundaries/vn_34_provinces.geojson")
    a = ap.parse_args()
    web = os.path.join(a.out, "web_data")
    for sub in ["series", "cells", "points"]:
        os.makedirs(os.path.join(web, sub), exist_ok=True)
    meta = json.load(open(os.path.join(a.out, "harmonization_metadata.json"), encoding="utf-8"))
    model_name = meta["chosen_model"]

    H.log("[1] Doc ranh gioi 34 tinh + gan tinh cho tung diem")
    prov = load_provinces(a.boundaries)
    pts = pd.read_parquet(os.path.join(a.out, "hotspots_clean.parquet"))
    for c in ["ym", "sat", "sensor", "conf_level", "daynight", "grid_id"]:
        pts[c] = pts[c].astype(str)
    pidx, n_near = assign_provinces(pts["latitude"].values, pts["longitude"].values, prov)
    pts["province_id"] = np.where(pidx >= 0, prov["province_id"].values[np.clip(pidx, 0, None)], "outside")
    n_out = int((pidx < 0).sum())
    H.log(f"  {len(pts):,} diem | gan theo tinh gan nhat (lech ranh gioi <= ~5 km): {n_near:,} | ngoai lanh tho: {n_out:,}")

    H.log("[2] Phan bo harmonized ve 34 tinh")
    grid = pd.read_parquet(os.path.join(a.out, "grid_monthly.parquet"))
    nat = pd.read_csv(os.path.join(a.out, "national_monthly.csv"))
    pts_w = pts.loc[pts["weight"] > 0, ["grid_id", "ym", "province_id"]].assign(w=pts.loc[pts["weight"] > 0, "weight"].values)
    prov_month = allocate(grid[["grid_id", "ym", "harmonized"]].rename(columns={"harmonized": "total"}),
                          pts_w, cell_province_shares(pts, H.FINAL_FIT))
    closure = float(prov_month.sum() / grid["harmonized"].sum())
    H.log(f"  tong cac tinh / tong ca nuoc = {closure:.4f}")

    H.log("[3] Kiem chung cap tinh (train 2012-2017, test 2018-2021)")
    prov_val = province_validation(grid, pts, model_name)
    prov_val = prov_val.merge(prov[["province_id", "province_name"]], on="province_id", how="left")
    prov_val.to_csv(os.path.join(a.out, "validation_by_province.csv"), index=False)
    H.log(f"  median r = {prov_val['r'].median():.3f} | median |bias| = {prov_val['bias_pct'].abs().median():.1f}% | "
          f"so tinh dat r>=0.8 & |bias|<=15%: {int(((prov_val['r'] >= 0.8) & (prov_val['bias_pct'].abs() <= 15)).sum())}/{len(prov_val)}")

    H.log("[4] Chuoi thang + median lich su + bat thuong")
    src_map = {"modeled_from_modis_aqua": "modeled", "observed_viirs_snpp": "observed",
               "observed_viirs_noaa20_cal": "observed_n20"}
    base = nat[["ym", "year", "month", "source_flag", "is_partial_month"]].copy()
    base["src"] = base["source_flag"].map(src_map)
    modeled = base["src"].eq("modeled").values
    s_vn = add_climatology(base.assign(v=nat["harmonized"], ci_low=nat["ci_low"], ci_high=nat["ci_high"]))
    series_json(s_vn, os.path.join(web, "series", "vietnam.json"))
    pm = prov_month.unstack(0).reindex(base["ym"]).fillna(0)
    long_rows = []
    for pid in prov["province_id"]:
        v = pm[pid].values if pid in pm.columns else np.zeros(len(base))
        q = prov_val.loc[prov_val["province_id"] == pid, ["ci_q05", "ci_q95"]].values[0]
        lo, hi, _ = H.apply_ci(v, modeled, q)
        s = add_climatology(base.assign(v=v, ci_low=lo, ci_high=hi))
        series_json(s, os.path.join(web, "series", f"{pid}.json"))
        long_rows.append(s.assign(province_id=pid)[["province_id", "ym", "v", "ci_low", "ci_high", "src",
                                                    "is_partial_month", "med", "anom_pct", "pct_rank"]])
    pd.concat(long_rows).rename(columns={"v": "harmonized"}).to_csv(
        os.path.join(a.out, "province_monthly.csv"), index=False)

    H.log("[5] Ban do o 0,01 do theo thang")
    cw = pts.loc[pts["weight"] > 0].copy()
    cw["lat_idx"] = np.floor(cw["latitude"] / CELL_RES).astype(int)
    cw["lon_idx"] = np.floor(cw["longitude"] / CELL_RES).astype(int)
    cells = cw.groupby(["province_id", "ym", "lat_idx", "lon_idx"])["weight"].sum().round(3).rename("v").reset_index()
    for pid, g in cells.groupby("province_id"):
        if pid != "outside":
            g[["lat_idx", "lon_idx", "ym", "v"]].to_csv(os.path.join(web, "cells", f"{pid}.csv"), index=False)

    H.log("[6] Diem chay sach theo tinh x nam (de tai CSV)")
    keep = ["latitude", "longitude", "datetime_local", "sat", "sensor", "conf_level", "frp", "daynight", "weight"]
    pts["datetime_local"] = pd.to_datetime(pts["datetime_local"]).dt.strftime("%Y-%m-%d %H:%M")
    n_files = 0
    for (pid, yr), g in pts[pts["province_id"] != "outside"].groupby(["province_id", "year"]):
        d = os.path.join(web, "points", pid); os.makedirs(d, exist_ok=True)
        g[keep].to_csv(os.path.join(d, f"{yr}.csv"), index=False); n_files += 1

    H.log("[7] Ranh gioi cho web + index + method")
    pw = prov.copy()
    pw["geometry"] = shapely.set_precision(
        shapely.simplify(pw.geometry.values, SIMPLIFY_WEB, preserve_topology=True), 0.0001)
    pw.drop(columns=["Ma"]).to_file(os.path.join(web, "provinces.geojson"), driver="GeoJSON")
    years = {pid: sorted(int(y) for y in g["year"].unique()) for pid, g in pts.groupby("province_id")}
    # do tin cay giai doan 2003-2011 (modeled) theo nguong cua nhom: r >= 0,8 va |bias| <= 15% tren tap test
    rel = {r.province_id: ("high" if (r.r >= 0.8 and abs(r.bias_pct) <= 15) else "low") for r in prov_val.itertuples()}
    index = {
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "data_last_local_date": meta["data_last_local_date"], "partial_month": meta.get("partial_month"),
        "scale": meta["target_scale"], "cell_res_deg": CELL_RES,
        "provinces": [{"id": r.province_id, "name": r.province_name, "merged_from": r.merged_from,
                       "bbox": [round(x, 4) for x in r.geometry.bounds], "point_years": years.get(r.province_id, []),
                       "modeled_reliability": rel.get(r.province_id, "low")}
                      for r in prov.itertuples()],
        "files": {"series": "series/<id>.json (id = vietnam | province id)", "cells": "cells/<id>.csv",
                  "points": "points/<id>/<year>.csv", "boundaries": "provinces.geojson"},
    }
    json.dump(index, open(os.path.join(web, "index.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    method = {
        "harmonization": meta,
        "validation_models": pd.read_csv(os.path.join(a.out, "validation_report.csv")).round(4).to_dict("records"),
        "validation_by_province": prov_val.round(4).to_dict("records"),
        "province_ci_note": "Khoang 90% tung tinh = phan vi 5-95% cua log(V/du doan) tren 48 thang test cua chinh tinh do.",
        "province_allocation": ("So harmonized moi o 0,25 do duoc chia ve tinh: phan gan duoc diem dung vi tri that "
                                "cua diem; phan chay nho du doan o o MODIS thay 0 chia theo ty le chay VIIRS S-NPP "
                                "2012-2021 cua o trong tung tinh."),
        "province_closure": closure,
        "points_assigned_nearest": int(n_near), "points_outside_vn": n_out,
        "map_cells_note": ("Ban do o 0,01 do: tu 2012 la diem VIIRS that; 2003-2011 la vi tri diem MODIS-Aqua nhan he so "
                           f"quy doi (phu ~{meta['point_weight_coverage_modeled_period']*100:.0f}% tong so, phan con lai la "
                           "chay nho khong co vi tri cu the -> chi co trong tong theo tinh/ca nuoc)."),
        "boundaries_source": "github.com/nguyenduy1133/Free-GIS-Data (34 tinh thanh tu 01/07/2025); da sua Ma=31 -> Dong Thap",
    }
    json.dump(method, open(os.path.join(web, "method.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(web) for f in fs) / 1e6
    H.log(f"XONG: {web} | {n_files} file diem | tong {size:.0f} MB")


if __name__ == "__main__":
    main()
