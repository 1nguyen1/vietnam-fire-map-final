# -*- coding: utf-8 -*-
# AI use: Written with assistance from Claude (Anthropic); reviewed and tested by team 268LTK.
"""
build_vercel.py - Dong goi du lieu cho web app tren Vercel (chay SAU harmonize.py va export_web.py).

    python build_vercel.py --out "D:/NASA/output" --deploy "D:/NASA/vercel-deploy"

Tao trong <deploy>/:
    uploads/national_monthly.csv, uploads/harmonization_metadata.json   chuoi ca nuoc
    data/provinces.geojson                                              ranh gioi 34 tinh
    data/province_monthly.json                                          so harmonized theo tinh x thang
    data/cells_meta.json + data/cells/<nam>.json                        ban do o 0,01 do (~1 km), tai theo nam
    data/points/<tinh>/<nam>.csv.gz                                     diem chay de tai CSV (nen gzip cho Vercel <100 MB)
    data/days_meta.json + data/days/<nam>.bin.gz                        diem chay that theo ngay/gio (che do Ngay, Gio)
"""
import argparse, glob, gzip, json, os, shutil
import numpy as np, pandas as pd


SAT_CODE = {"Terra": 0, "Aqua": 1, "SNPP": 2, "NOAA20": 3, "NOAA21": 4}


def build_days(web, data, ids):
    """Diem chay THAT theo ngay/gio cho che do Ngay va Gio tren web.
    data/days/<nam>.bin.gz, moi diem 12 byte, xep theo thoi gian (gio Viet Nam):
        [u32 n] [u32 phut-trong-nam x n] [u16 lat x n] [u16 lon x n] [u16 frp*10 x n] [u8 tinh x n] [u8 ve tinh x n]
        lat = (vi do - 8) * 4000, lon = (kinh do - 102) * 4000  -> buoc 0,00025 do (~28 m)
        tinh = vi tri trong province_monthly.json["ids"]; ve tinh: 3 bit thap = SAT_CODE, bit 7 = diem chuan (weight > 0,
        tuc dung bo diem tao nen lich harmonized: Aqua truoc 2012, S-NPP 2012 - 10/2026, NOAA-20 tu 11/2026)
    """
    cols = ["latitude", "longitude", "datetime_local", "sat", "frp", "weight"]
    pts = pd.concat([pd.read_csv(f, usecols=cols).assign(pid=os.path.basename(os.path.dirname(f)))
                     for f in glob.glob(os.path.join(web, "points", "*", "*.csv"))], ignore_index=True)
    t = pd.to_datetime(pts["datetime_local"])
    pts["yy"] = t.dt.year
    pts["mins"] = ((t - pd.to_datetime(pts["yy"].astype(str) + "-01-01")).dt.total_seconds() // 60).astype("uint32")
    pts["pi"] = pts["pid"].map({p: i for i, p in enumerate(ids)}).astype("uint8")
    pts["sc"] = pts["sat"].map(SAT_CODE).astype("uint8") | np.where(pts["weight"] > 0, 128, 0).astype("uint8")
    out = os.path.join(data, "days"); os.makedirs(out, exist_ok=True)
    for y, g in pts.sort_values("mins", kind="stable").groupby("yy"):
        buf = b"".join([np.uint32(len(g)).tobytes(), g["mins"].values.astype("<u4").tobytes(),
                        np.round((g["latitude"].values - 8) * 4000).astype("<u2").tobytes(),
                        np.round((g["longitude"].values - 102) * 4000).astype("<u2").tobytes(),
                        np.clip(np.round(g["frp"].fillna(0).values * 10), 0, 65535).astype("<u2").tobytes(),
                        g["pi"].values.astype("u1").tobytes(), g["sc"].values.astype("u1").tobytes()])
        with gzip.open(os.path.join(out, f"{y}.bin.gz"), "wb", compresslevel=9) as fo:
            fo.write(buf)
    # nguong thang mau cho che do Ngay/Gio (dem so diem that)
    pts["day"] = pts["mins"] // 1440; pts["hr"] = pts["mins"] // 60
    pts["ck"] = np.floor(pts["latitude"] / 0.01).astype(int) * 100000 + np.floor(pts["longitude"] / 0.01).astype(int)
    def mx(s):
        return {k: {"prov": float(np.quantile(s.groupby(["yy", c, "pi"]).size(), .97)),
                    "cell": float(np.quantile(s.groupby(["yy", c, "ck"]).size(), .99))} for k, c in [("day", "day"), ("hour", "hr")]}
    meta = {"sat": list(SAT_CODE), "n": int(len(pts)), "n_std": int((pts["weight"] > 0).sum()),
            "max": {"std": mx(pts[pts["weight"] > 0]), "all": mx(pts)}}
    json.dump(meta, open(os.path.join(data, "days_meta.json"), "w"))
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="D:/NASA/output")
    ap.add_argument("--deploy", default="D:/NASA/vercel-deploy")
    a = ap.parse_args()
    web = os.path.join(a.out, "web_data")
    data = os.path.join(a.deploy, "data")
    for d in ["uploads", "data/cells", "data/points"]:
        os.makedirs(os.path.join(a.deploy, d), exist_ok=True)

    # 1) chuoi ca nuoc + metadata + ranh gioi
    shutil.copy(os.path.join(a.out, "national_monthly.csv"), os.path.join(a.deploy, "uploads"))
    shutil.copy(os.path.join(a.out, "harmonization_metadata.json"), os.path.join(a.deploy, "uploads"))
    shutil.copy(os.path.join(web, "provinces.geojson"), data)
    shutil.copy(os.path.join(web, "method.json"), data)
    # 1b) MOI: daily_quality.json lay thang tu snpp_gaps.csv cua harmonize.py (cung 1 nguon voi so lieu da bu)
    gp = os.path.join(a.out, "snpp_gaps.csv")
    if os.path.exists(gp):
        g = pd.read_csv(gp)
        g["day"] = g["date_local"].astype(str).str[:10]
        d = g.groupby("day").agg(snpp=("SNPP", "sum"), filled=("filled_pts", "sum"))
        dq = {k: ["A_EMPTY" if r.snpp == 0 else "B_PARTIAL", round(float(r.filled), 1)] for k, r in d.iterrows()}
        json.dump(dq, open(os.path.join(data, "daily_quality.json"), "w"), separators=(",", ":"))
        print(f"daily_quality: {len(dq)} ngay co luot bay S-NPP da bu")

    # 2) tinh x thang
    pm = pd.read_csv(os.path.join(a.out, "province_monthly.csv"))
    idx = json.load(open(os.path.join(web, "index.json"), encoding="utf-8"))
    ids = [p["id"] for p in idx["provinces"]]
    piv = pm.pivot(index="ym", columns="province_id", values="harmonized").reindex(columns=ids).fillna(0).round(1)
    json.dump({"months": list(piv.index), "ids": ids,
               "names": {p["id"]: p["name"] for p in idx["provinces"]},
               "reliability": {p["id"]: p["modeled_reliability"] for p in idx["provinces"]},
               "v": piv.values.tolist()},
              open(os.path.join(data, "province_monthly.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))

    # 3) o 0,01 do theo nam (gop cac tinh: 1 o co the nam o 2 tinh)
    c = pd.concat([pd.read_csv(f) for f in glob.glob(os.path.join(web, "cells", "*.csv"))])
    c = c.groupby(["ym", "lat_idx", "lon_idx"], as_index=False)["v"].sum()
    c = c[c["v"] >= 0.005]
    c["y"] = c["ym"].str[:4].astype(int); c["m"] = c["ym"].str[5:7]; c["q"] = (c["m"].astype(int) - 1) // 3
    for y, g in c.groupby("y"):
        out = {m: gm[["lat_idx", "lon_idx", "v"]].round(2).values.tolist() for m, gm in g.groupby("m")}
        for m in out:
            out[m] = [[int(r[0]), int(r[1]), r[2]] for r in out[m]]
        json.dump({"m": out}, open(os.path.join(data, "cells", f"{y}.json"), "w"), separators=(",", ":"))
    q = lambda s: float(np.quantile(s, 0.99))
    meta = {"res": 0.01, "years": sorted(int(y) for y in c["y"].unique()),
            "max": {"month": q(c["v"]),
                    "quarter": q(c.groupby(["y", "q", "lat_idx", "lon_idx"])["v"].sum()),
                    "year": q(c.groupby(["y", "lat_idx", "lon_idx"])["v"].sum())}}
    json.dump(meta, open(os.path.join(data, "cells_meta.json"), "w"))

    # 4) diem chay theo tinh x nam, nen gzip
    n = 0
    for f in glob.glob(os.path.join(web, "points", "*", "*.csv")):
        pid, yr = os.path.basename(os.path.dirname(f)), os.path.basename(f)
        d = os.path.join(data, "points", pid); os.makedirs(d, exist_ok=True)
        with open(f, "rb") as src, gzip.open(os.path.join(d, yr + ".gz"), "wb", compresslevel=9) as dst:
            shutil.copyfileobj(src, dst)
        n += 1
    # 5) diem chay that theo ngay/gio
    dm = build_days(web, data, ids)
    print(f"days: {dm['n']} diem ({dm['n_std']} diem chuan), nguong {dm['max']}")
    size = sum(os.path.getsize(os.path.join(dp, x)) for dp, _, fs in os.walk(a.deploy) for x in fs) / 1e6
    nf = sum(len(fs) for _, _, fs in os.walk(a.deploy))
    print(f"XONG: {a.deploy} | {nf} file | {size:.1f} MB | cells max {meta['max']} | {n} file diem")


if __name__ == "__main__":
    main()
