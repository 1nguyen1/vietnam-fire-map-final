# -*- coding: utf-8 -*-
# AI use: Written with assistance from Claude (Anthropic); reviewed and tested by team 268LTK.
"""
harmonize.py - Dong bo (harmonize) hotspot MODIS & VIIRS cho Viet Nam
NASA Space Apps 2026 - "Harmonization of MODIS and VIIRS Hot Spots"

Muc tieu: tao 1 chuoi thoi gian so hotspot NHAT QUAN 2003 -> nay, tren thang
"VIIRS-tuong-duong" (vi tuong lai chi con VIIRS), de lam lich chay.

Cach chay:
    pip install pandas numpy scikit-learn scipy pyarrow matplotlib
    python harmonize.py --data "D:/NASA" --out "D:/NASA/output"
"""
import argparse
import glob
import json
import os
import time
import warnings

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.linear_model import PoissonRegressor
from sklearn.metrics import mean_poisson_deviance
from sklearn.preprocessing import OneHotEncoder

# =============================================================================
# [0] CAU HINH - moi lua chon phuong phap deu nam o day de de giai thich/doi
# =============================================================================
GRID_RES = 0.25            # o luoi tong hop (do) ~ 27 km
STATIC_FINE_RES = 0.001    # o mat na nha may ~100 m (ve theo hinh dang nha may)
STATIC_FINE_DILATE = 2     # no 2 o moi phia -> khoi 5x5 ~500 m (do lech vi tri VIIRS ~260 m)
STATIC_T2_SHARE = 0.5      # o co >= 50% diem type=2 -> o nha may (nhan NASA)
PERSIST_RES = 0.01         # o 1 km cho quy tac hanh vi cua nhom
PERSIST_MONTHS = 8         # chay LIEN TUC >= 8 thang trong 1 nam
PERSIST_YEARS = 3          # ... lap lai >= 3 nam
TZ_OFFSET_H = 7            # gio Viet Nam = UTC+7
START_YEAR = 2003          # nam day du dau tien cua MODIS-Aqua
DROP_LOW_CONF = True       # bo diem do tin cay thap o CA HAI cam bien

VIIRS_FIRST_FULL_MONTH = "2012-02"   # S-NPP bat dau 20/01/2012 -> thang 1 thieu
SNPP_LAST_MONTH = "2026-10"          # FIRMS ngung S-NPP ngay 02/11/2026

# --- BU NGAY S-NPP MAT DU LIEU (moi) ---------------------------------------------
# Don vi xet = 1 "luot bay" = (ngay gio VN, ngay/dem). Moi ve tinh VIIRS bay qua VN ~2 lan/ngay
# (~13:30 va ~01:30 gio VN); NOAA-20 cung quy dao, cach S-NPP ~50 phut -> la ban thay the gan nhat.
GAP_MIN_REF = 5            # S-NPP = 0 ma ve tinh tham chieu thay >= 5 diem -> luot bay bi mat
GAP_PARTIAL_MIN = 10 ** 9  # TAT quy tac "thieu mot phan": kiem tra cho thay no bat nham ~90 luot bay/2018-2026
                           # (S-NPP va NOAA-20 nhin VN o goc quet khac nhau -> lech so diem tu nhien, khong phai mat
                           # du lieu). Bien cua cac dot mat that da nam trong SNPP_OUTAGES_UTC. Muon bat lai: dat = 30.
GAP_PARTIAL_RATIO = 0.3
# Cac dot mat du lieu da duoc NOAA/NASA cong bo (gio UTC). Luot bay nao roi vao day thi bu chac chan,
# ke ca ngay mua mua it chay ma quy tac tu dong o tren khong bat duoc.
SNPP_OUTAGES_UTC = [
    ("2022-07-26 16:09", "2022-08-11 00:00"),   # safe mode
    ("2024-07-09 21:42", "2024-07-16 17:42"),   # GPS, du lieu bi an
    ("2024-07-24 05:28", "2024-08-01 07:00"),
    ("2024-09-26 00:00", "2024-09-27 17:30"),
    ("2026-03-09 18:00", "2026-03-13 08:12"),
    ("2026-04-28 00:33", "2026-04-30 13:33"),
    ("2026-07-10 14:50", "2026-07-16 19:48"),
]

# Chia thoi gian de VALIDATE (deu truoc khi Aqua troi quy dao ~2022)
VAL_TRAIN = ("2012-02", "2017-12")
VAL_TEST = ("2018-01", "2021-12")
# Fit cuoi cung: 2012-2021 (Aqua con dung gio bay ~13:30 nhu giai doan 2003-2011)
FINAL_FIT = ("2012-02", "2021-12")
# Kiem tra rieng anh huong troi quy dao cua Aqua
DRIFT_CHECK = ("2022-01", SNPP_LAST_MONTH)

SHRINK_LAMBDA = 20.0       # pseudo-count cho ty le co "co ve" (model B)
GLM_ALPHAS = [1e-4, 1e-3]
MIN_FIRES_CELL_SPEARMAN = 50

SOURCES = {                # ten nguon -> mau ten file FIRMS
    "MODIS": "*M-C61*.csv",
    "SNPP": "*SV-C2*.csv",
    "NOAA20": "*J1V-C2*.csv",
    "NOAA21": "*J2V-C2*.csv",
}
USECOLS = ["latitude", "longitude", "acq_date", "acq_time", "satellite",
           "confidence", "frp", "daynight", "type", "scan", "track"]


warnings.filterwarnings("ignore", message=".*constant.*")
warnings.filterwarnings("ignore", category=FutureWarning)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def in_range(ym, rng):
    return (ym >= rng[0]) & (ym <= rng[1])


# =============================================================================
# [1] DOC DU LIEU: noi archive + NRT cua tung cam bien
# =============================================================================
def load_source(data_dir, name, pattern):
    files = sorted(glob.glob(os.path.join(data_dir, "**", pattern), recursive=True))
    files = [f for f in files if os.path.basename(f).startswith("fire_")]
    if not files:
        raise FileNotFoundError(f"Khong tim thay file {pattern} trong {data_dir}")
    parts = []
    for f in files:   # 'fire_archive' dung truoc 'fire_nrt' khi sort
        d = pd.read_csv(f, usecols=lambda c: c in USECOLS,
                        dtype={"acq_time": str, "confidence": str, "satellite": str})
        d["is_nrt"] = os.path.basename(f).startswith("fire_nrt")
        if "type" not in d.columns:
            d["type"] = np.nan          # NRT khong co cot type
        parts.append(d)
        log(f"  {name}: {os.path.basename(f)} -> {len(d):,} dong")
    d = pd.concat(parts, ignore_index=True)
    d["source"] = name
    d["sensor"] = "MODIS" if name == "MODIS" else "VIIRS"
    return d


# =============================================================================
# [2] CHUAN HOA SCHEMA: ve tinh, gio dia phuong, muc tin cay chung
# =============================================================================
def standardize(df):
    # 2a. Ten ve tinh thong nhat
    sat_map = {"Terra": "Terra", "T": "Terra", "Aqua": "Aqua", "A": "Aqua"}
    df["sat"] = np.where(df["sensor"] == "MODIS",
                         df["satellite"].map(sat_map).fillna(df["satellite"]),
                         df["source"])
    # 2b. UTC -> gio Viet Nam (luot bay dem ~01:30 VN = 18:30 UTC ngay HOM TRUOC)
    t = df["acq_time"].str.zfill(4)
    df["datetime_utc"] = pd.to_datetime(df["acq_date"] + " " + t.str[:2] + ":" + t.str[2:],
                                        format="%Y-%m-%d %H:%M")
    df["datetime_local"] = df["datetime_utc"] + pd.Timedelta(hours=TZ_OFFSET_H)
    df["date_local"] = df["datetime_local"].dt.normalize()
    df["year"] = df["datetime_local"].dt.year.astype("int16")
    df["month"] = df["datetime_local"].dt.month.astype("int8")
    df["ym"] = df["datetime_local"].dt.strftime("%Y-%m")
    # 2c. Confidence: MODIS so 0-100, VIIRS chu l/n/h -> 3 muc chung (nguong FIRMS)
    num = pd.to_numeric(df["confidence"], errors="coerce")
    modis_lvl = np.select([num < 30, num < 80, num >= 80], ["low", "nominal", "high"], default="unknown")
    viirs_lvl = df["confidence"].str.lower().map({"l": "low", "n": "nominal", "h": "high"}).fillna("unknown")
    df["conf_level"] = np.where(df["sensor"] == "MODIS", modis_lvl, viirs_lvl)
    df = df.drop(columns=["acq_date", "acq_time", "satellite", "confidence"])
    for c in ["source", "sensor", "sat", "conf_level", "daynight", "ym"]:
        df[c] = df[c].astype("category")
    return df


def dedupe_points(df):
    """Bo diem trung: cung ve tinh + cung phut chup + toa do lech < ~10 m.
    Bat 2 truong hop: (1) archive va NRT chong lan ngay -> giu ban archive (chat luong chuan);
    (2) VIIRS ghi 1 dam chay 2 lan do 2 dai quet lien ke chong mep (pixel 375 m, 2 diem
    cach nhau ~10 m cung phut thi chac chan la 1 dam chay).
    Chay SAU standardize() de dung ten ve tinh da thong nhat (sat)."""
    n0 = len(df)
    key = pd.DataFrame({"sat": df["sat"].astype(str), "t": df["datetime_utc"],
                        "la": df["latitude"].round(4), "lo": df["longitude"].round(4)})
    order = np.argsort(df["is_nrt"].values, kind="stable")      # archive (False) dung truoc
    dup = key.iloc[order].duplicated(keep="first")
    keep_idx = df.index[order][~dup.values]
    df = df.loc[np.sort(keep_idx)].reset_index(drop=True)
    return df, n0 - len(df)


# =============================================================================
# [3] LOC: chi giu chay thuc vat (rung + nong nghiep), bo nguon nhiet tinh
#     Gop 2 cach, ap CUNG 1 quy tac cho archive va NRT:
#     (A) Nhan NASA: o 100 m co >= 50% diem type=2, no ra khoi 5x5 (~500 m)
#     (B) Hanh vi (quy tac nhom): o 1 km chay lien tuc >= 8 thang/nam, >= 3 nam
# =============================================================================
OFF = 10 ** 6


def cell_key(lat, lon, res):
    return ((np.floor(np.asarray(lat) / res).astype(np.int64) + 50000) * OFF
            + (np.floor(np.asarray(lon) / res).astype(np.int64) + 50000))


def dilate(keys, n):
    a, b = keys // OFF, keys % OFF
    return np.unique(np.concatenate([(a + di) * OFF + (b + dj)
                                     for di in range(-n, n + 1) for dj in range(-n, n + 1)]))


def static_by_label(df):
    """(A) O 100 m ma da so diem duoc NASA gan type=2 -> no 5x5."""
    arc = df[~df["is_nrt"] & df["type"].isin([0, 2])]
    k = cell_key(arc["latitude"].values, arc["longitude"].values, STATIC_FINE_RES)
    share = pd.Series(arc["type"].values == 2).groupby(k).mean()
    cells = share[share >= STATIC_T2_SHARE].index.values.astype(np.int64)
    return dilate(cells, STATIC_FINE_DILATE), len(cells)


def static_by_persistence(df):
    """(B) O 1 km co chuoi thang LIEN TUC >= 8 trong cung 1 nam, lap lai >= 3 nam.
    Chay thuc vat o VN khong bao gio lien tuc >= 6 thang (da kiem tren du lieu) -> an toan."""
    k = cell_key(df["latitude"].values, df["longitude"].values, PERSIST_RES)
    u = (pd.DataFrame({"k": k, "y": df["year"].values, "m": df["month"].values})
         .drop_duplicates().sort_values(["k", "y", "m"]))
    brk = u["k"].ne(u["k"].shift()) | u["y"].ne(u["y"].shift()) | (u["m"] - u["m"].shift()).ne(1)
    run = u.groupby(brk.cumsum()).agg(k=("k", "first"), y=("y", "first"), n=("m", "size"))
    ny = run[run["n"] >= PERSIST_MONTHS].groupby("k")["y"].nunique()
    return ny[ny >= PERSIST_YEARS].index.values.astype(np.int64)


def filter_fires(df):
    stats = {"tong_ban_dau": len(df)}
    # buoc 1: bo tung diem NASA da gan nhan khong phai chay thuc vat (archive)
    bad_type = df["type"].isin([1, 2, 3]).values
    stats["bo_type_1_2_3"] = int(bad_type.sum())
    # buoc 2: mat na nguon tinh, ap cho MOI diem (archive + NRT)
    mask_a, n_a = static_by_label(df)
    cells_b = static_by_persistence(df)
    in_a = np.isin(cell_key(df["latitude"].values, df["longitude"].values, STATIC_FINE_RES), mask_a)
    in_b = np.isin(cell_key(df["latitude"].values, df["longitude"].values, PERSIST_RES), cells_b)
    df["is_static"] = bad_type | in_a | in_b
    stats["o_100m_nha_may_nhan_NASA"] = int(n_a)
    stats["o_1km_quy_tac_lien_tuc"] = int(len(cells_b))
    stats["bo_them_do_mat_na_nhan_NASA"] = int((in_a & ~bad_type).sum())
    stats["bo_them_do_quy_tac_lien_tuc"] = int((in_b & ~in_a & ~bad_type).sum())
    stats["trong_do_NRT_bi_loai"] = int((df["is_static"] & df["is_nrt"]).sum())
    df = df[~df["is_static"]]
    if DROP_LOW_CONF:
        low = df["conf_level"] == "low"
        stats["bo_do_tin_cay_thap"] = int(low.sum())
        df = df[~low]
    stats["con_lai"] = len(df)
    return df.drop(columns=["is_static"]).reset_index(drop=True), stats


# =============================================================================
# [4] GAN LUOI + CHON CHUOI THAM CHIEU, dung bang panel o-luoi x thang
# =============================================================================
def add_grid(df):
    gi = np.floor(df["latitude"].values / GRID_RES).astype(int)
    gj = np.floor(df["longitude"].values / GRID_RES).astype(int)
    df["grid_id"] = pd.Categorical([f"{a}_{b}" for a, b in zip(gi, gj)])
    return df


def snpp_gap_fill(df):
    """Tim cac luot bay S-NPP bi mat va tinh trong so 'tuong duong S-NPP' w_v cho tung diem.
    - Luot binh thuong : diem S-NPP w=1, ve tinh khac w=0 (nhu cu).
    - Luot bi mat     : diem S-NPP (neu con sot) w=0; diem NOAA-20 w=c_n20; neu NOAA-20 cung trong thi
                        NOAA-21 w=c_n21; truoc 2018 (chua co NOAA-20) dung Aqua w=k_aqua cua thang do.
    He so c_n20/c_n21/k_aqua hoc tren cac luot KHONG bi mat (sua loi he so bi keo thap boi thang co ngay mat)."""
    ym = df["ym"].astype(str)
    era = ((ym >= VIIRS_FIRST_FULL_MONTH) & (ym <= SNPP_LAST_MONTH)).values
    sat = df["sat"].astype(str).values
    slot = pd.MultiIndex.from_arrays([df["date_local"].values, df["daynight"].astype(str).values],
                                     names=["date_local", "daynight"])
    d = pd.DataFrame({"sat": sat[era]}, index=slot[era])
    cnt = d.groupby(level=[0, 1])["sat"].value_counts().unstack(fill_value=0)
    for c in ["Aqua", "SNPP", "NOAA20", "NOAA21"]:
        if c not in cnt.columns:
            cnt[c] = 0
    ref = cnt["NOAA20"] + cnt["NOAA21"]
    no_viirs_ref = ref == 0
    zero = (cnt["SNPP"] == 0) & ((ref >= GAP_MIN_REF) | (no_viirs_ref & (cnt["Aqua"] >= GAP_MIN_REF)))
    partial = (cnt["NOAA20"] >= GAP_PARTIAL_MIN) & (cnt["SNPP"] < GAP_PARTIAL_RATIO * cnt["NOAA20"])
    # luot bay nam trong dot mat du lieu da cong bo
    t = df["datetime_utc"].values[era]
    in_out = np.zeros(era.sum(), bool)
    for a, b in SNPP_OUTAGES_UTC:
        in_out |= (t >= np.datetime64(a)) & (t < np.datetime64(b))
    official = pd.Series(in_out, index=slot[era]).groupby(level=[0, 1]).any().reindex(cnt.index, fill_value=False)
    gap = zero | partial | official
    reason = np.select([official, zero, partial], ["official", "A_EMPTY", "B_PARTIAL"], default="")

    # he so quy doi hoc tren luot KHONG mat
    ok = cnt[~gap]
    okm = ok.assign(ym=pd.to_datetime(ok.index.get_level_values(0)).strftime("%Y-%m"))
    def factor(col, start):
        o = okm[(okm["ym"] >= start) & (okm[col] > 0)]
        return float(o["SNPP"].sum() / o[col].sum()) if o[col].sum() else np.nan
    c_n20 = factor("NOAA20", "2018-04")
    c_n21 = factor("NOAA21", "2023-03")
    k_aqua = okm.groupby("ym")[["SNPP", "Aqua"]].sum()
    k_aqua = (k_aqua["SNPP"] / k_aqua["Aqua"].replace(0, np.nan)).fillna(float(ok["SNPP"].sum() / max(ok["Aqua"].sum(), 1)))

    # trong so tung diem
    g = gap.reindex(slot, fill_value=False).values & era
    gi = pd.DataFrame({"n20": cnt["NOAA20"], "n21": cnt["NOAA21"]}).reindex(slot, fill_value=0)
    use_n20 = g & (gi["n20"].values > 0)
    use_n21 = g & (gi["n20"].values == 0) & (gi["n21"].values > 0)
    use_aq = g & (gi["n20"].values == 0) & (gi["n21"].values == 0)
    w = np.zeros(len(df), dtype="float32")
    w[era & ~g & (sat == "SNPP")] = 1.0
    w[use_n20 & (sat == "NOAA20")] = c_n20
    w[use_n21 & (sat == "NOAA21")] = c_n21
    idx = np.where(use_aq & (sat == "Aqua"))[0]
    w[idx] = k_aqua.reindex(ym.values[idx]).fillna(0).values
    df["w_v"] = w
    df["snpp_gap"] = g

    gaps = cnt[gap].assign(reason=reason[gap.values]).reset_index()
    filled = pd.Series(w[g], index=slot[g]).groupby(level=[0, 1]).sum()
    gaps["filled_pts"] = filled.reindex(pd.MultiIndex.from_frame(gaps[["date_local", "daynight"]])).fillna(0).round(1).values
    log(f"  S-NPP mat du lieu: {len(gaps)} luot bay ({(gaps['reason'] == 'official').sum()} theo thong bao chinh thuc) | "
        f"bu {gaps['filled_pts'].sum():,.0f} diem | c_n20={c_n20:.4f} c_n21={c_n21:.4f}")
    return df, gaps, c_n20, c_n21


def build_panel(df, last_ym):
    months = pd.period_range(f"{START_YEAR}-01", last_ym, freq="M").strftime("%Y-%m")
    cnt = (df[df["sat"].isin(["Aqua", "Terra", "SNPP", "NOAA20", "NOAA21"])]
           .groupby(["grid_id", "ym", "sat"], observed=True).size()
           .unstack("sat", fill_value=0))
    for c in ["Aqua", "Terra", "SNPP", "NOAA20", "NOAA21"]:
        if c not in cnt.columns:
            cnt[c] = 0
    cnt["V_fill"] = df.groupby(["grid_id", "ym"], observed=True)["w_v"].sum()   # S-NPP da bu
    grids = cnt.index.get_level_values("grid_id").unique()
    full = pd.MultiIndex.from_product([grids, months], names=["grid_id", "ym"])
    p = cnt.reindex(full, fill_value=0).reset_index()   # dien 0 -> Poisson can so 0
    p = p.rename(columns={"Aqua": "M", "Terra": "M_terra", "SNPP": "V_raw",
                          "NOAA20": "V_n20", "NOAA21": "V_n21"})
    # V = chuoi muc tieu tuong duong S-NPP: dung ban DA BU trong giai doan S-NPP (nhan sach hon cho mo hinh)
    snpp = in_range(p["ym"], (VIIRS_FIRST_FULL_MONTH, SNPP_LAST_MONTH))
    p["V"] = np.where(snpp, p["V_fill"].fillna(0), p["V_raw"]).astype(float)
    p = p.drop(columns=["V_fill"])
    p["grid_id"] = p["grid_id"].astype(str)
    return add_neighbor_feature(p)


def add_neighbor_feature(p):
    """M_nb = tong so diem MODIS-Aqua o 8 o lan can, CUNG thang.
    Cho mo hinh biet 'mua chay dang dien ra quanh day' tu du lieu THAT cua thang do,
    KHONG dung bien 'thang trong nam' vi no lam mo hinh hoc thuoc khi hau trung binh
    va keo nam bat thuong ve muc trung binh."""
    ij = p["grid_id"].str.split("_", expand=True).astype(int)
    key = pd.Series(p["M"].values, index=pd.MultiIndex.from_arrays([ij[0].values, ij[1].values, p["ym"].values]))
    nb = np.zeros(len(p))
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            if di == 0 and dj == 0:
                continue
            k = pd.MultiIndex.from_arrays([ij[0].values + di, ij[1].values + dj, p["ym"].values])
            nb += key.reindex(k).fillna(0).values
    p["M_nb"] = nb
    return p


def n20_to_snpp_factor(p):
    """NOAA-20 -> thang S-NPP, hoc tren giai doan ca 2 cung chay (2018-04 -> 2026-10)."""
    o = p[in_range(p["ym"], ("2018-04", SNPP_LAST_MONTH))].groupby("ym")[["V", "V_n20"]].sum()
    o = o[(o["V"] > 0) & (o["V_n20"] > 0)]          # bo thang 1 trong 2 ve tinh mat du lieu
    return float(o["V"].sum() / o["V_n20"].sum()), int(len(o))


# =============================================================================
# [5] MO HINH QUY DOI MODIS-Aqua -> VIIRS(S-NPP) + VALIDATION
# =============================================================================
class GlobalRatio:                     # A (= M1 cua nhom): 1 he so cho ca nuoc - duong co so
    name = "A_ty_le_toan_quoc"
    def fit(self, d):
        self.k = d["V"].sum() / d["M"].sum(); return self
    def predict(self, d):
        return self.k * d["M"].values


class ShrunkCellRatio:                 # B: he so rieng tung o, co ve ve toan quoc - duong co so
    name = "B_ty_le_theo_o_co_ve"
    def fit(self, d):
        kg = d["V"].sum() / d["M"].sum()
        g = d.groupby("grid_id")[["V", "M"]].sum()
        self.k = ((g["V"] + SHRINK_LAMBDA * kg) / (g["M"] + SHRINK_LAMBDA)).to_dict()
        self.kg = kg; return self
    def predict(self, d):
        return d["grid_id"].map(self.k).fillna(self.kg).values * d["M"].values


class PoissonGLM:                      # D: MO HINH DUOC CHON
    """log E[V] = a + b1*log(M+1) + b2*[M>0] + b3*log(M_nb+1) + hieu ung o luoi
    - log(M+1): quan he khong tuyen tinh MODIS -> VIIRS (khong can doi nguoc tu log)
    - [M>0]   : nhay muc khi MODIS thay it nhat 1 diem
    - M_nb    : chay nho VIIRS thay ma MODIS bo sot (M=0) van du doan duoc
    - o luoi  : moi vung co ty le rieng (loai chay, dia hinh, may)"""
    def __init__(self, alpha):
        self.alpha = alpha
        self.name = f"D_glm_lan_can_alpha{alpha:g}"
    def _X(self, d):
        f = np.column_stack([np.log1p(d["M"].values.astype(float)),
                             (d["M"].values > 0).astype(float),
                             np.log1p(d["M_nb"].values)])
        return sparse.hstack([sparse.csr_matrix(f), self.enc.transform(d[["grid_id"]])]).tocsr()
    def fit(self, d):
        self.enc = OneHotEncoder(handle_unknown="ignore").fit(d[["grid_id"]])
        self.m = PoissonRegressor(alpha=self.alpha, max_iter=3000).fit(self._X(d), d["V"].values)
        self.coef = [float(c) for c in self.m.coef_[:3]]
        return self
    def predict(self, d):
        return self.m.predict(self._X(d))


def evaluate(d, pred, label):
    d = d.assign(p=np.clip(pred, 1e-6, None))
    out = {"model": label,
           "o_MAE": float(np.abs(d["V"] - d["p"]).mean()),
           "o_poisson_deviance": float(mean_poisson_deviance(d["V"], d["p"])),
           "o_R2_log1p": float(np.corrcoef(np.log1p(d["V"]), np.log1p(d["p"]))[0, 1] ** 2)}
    nat = d.groupby("ym")[["V", "p"]].sum()
    out["qg_bias_%"] = float((nat["p"].sum() - nat["V"].sum()) / nat["V"].sum() * 100)
    out["qg_R2"] = float(np.corrcoef(nat["V"], nat["p"])[0, 1] ** 2)
    out["qg_MAPE_%"] = float((np.abs(nat["p"] - nat["V"]) / nat["V"].clip(lower=1)).mean() * 100)
    nat["y"] = nat.index.str[:4]
    sp = [g["V"].corr(g["p"], method="spearman") for _, g in nat.groupby("y") if len(g) >= 12]
    out["lich_spearman_thang_tb"] = float(np.nanmean(sp))
    big = d.groupby("grid_id")["V"].sum()
    big = big[big >= MIN_FIRES_CELL_SPEARMAN].index
    cs = [g["V"].corr(g["p"], method="spearman") for _, g in d[d["grid_id"].isin(big)].groupby("grid_id")]
    out["o_spearman_median"] = float(np.nanmedian(cs))
    return out


def validate(train, test):
    models = [GlobalRatio(), ShrunkCellRatio()] + [PoissonGLM(a) for a in GLM_ALPHAS]
    rows = []
    for m in models:
        m.fit(train)
        rows.append(evaluate(test, m.predict(test), m.name))
        log(f"  {m.name}: deviance={rows[-1]['o_poisson_deviance']:.3f} "
            f"bias={rows[-1]['qg_bias_%']:+.1f}% spearman_lich={rows[-1]['lich_spearman_thang_tb']:.3f}")
    rep = pd.DataFrame(rows)
    best = rep.loc[rep["o_poisson_deviance"].idxmin(), "model"]
    return rep, best, {m.name: m for m in models}


def make_model(name):
    if name.startswith("A_"): return GlobalRatio()
    if name.startswith("B_"): return ShrunkCellRatio()
    return PoissonGLM(float(name.split("alpha")[1]))


def loyo_national_residuals(panel_fit, model_name):
    """Sai so toan quoc bang leave-one-year-out tren giai doan FINAL_FIT:
    moi lan bo 1 nam, hoc tren cac nam con lai, du doan nam bi bo.
    Tra ve log(V/du doan) theo THANG va theo NAM -> CI thang va CI nam tinh RIENG,
    khong cong don CI thang (cong don gia dinh sai so 12 thang tuong quan 100%)."""
    years = sorted(panel_fit["ym"].str[:4].unique())
    m_res, y_res = [], []
    for y in years:
        hold = panel_fit["ym"].str[:4] == y
        if hold.sum() == 0 or (~hold).sum() == 0:
            continue
        m = make_model(model_name).fit(panel_fit[~hold])
        h = panel_fit[hold].assign(p=m.predict(panel_fit[hold]))
        nm = h.groupby("ym")[["V", "p"]].sum()
        m_res += list(np.log((nm["V"] + 1) / (nm["p"] + 1)))
        if len(nm) == 12:
            y_res.append(float(np.log((nm["V"].sum() + 1) / (nm["p"].sum() + 1))))
    return np.array(m_res), np.array(y_res)


def apply_ci(values, is_modeled, res):
    q05, q95 = np.quantile(res, [0.05, 0.95])
    lo = np.where(is_modeled, np.clip((values + 1) * np.exp(q05) - 1, 0, None), values)
    hi = np.where(is_modeled, (values + 1) * np.exp(q95) - 1, values)
    return lo, hi, [float(q05), float(q95)]


# =============================================================================
# [6] GHEP CHUOI HARMONIZED: modeled (MODIS) -> observed (S-NPP) -> NOAA-20
# =============================================================================
def build_harmonized(p, model, c_n20, test_resid):
    p = p.copy()
    p["pred_from_modis"] = model.predict(p)
    modeled = p["ym"] < VIIRS_FIRST_FULL_MONTH
    snpp = in_range(p["ym"], (VIIRS_FIRST_FULL_MONTH, SNPP_LAST_MONTH))
    p["harmonized"] = np.select([modeled, snpp], [p["pred_from_modis"], p["V"]], default=p["V_n20"] * c_n20)
    p["source_flag"] = np.select([modeled, snpp], ["modeled_from_modis_aqua", "observed_viirs_snpp"],
                                 default="observed_viirs_noaa20_cal")
    q05, q95 = np.quantile(test_resid, [0.05, 0.95])   # khoang bat dinh tu sai so tap test
    p["ci_low"] = np.where(modeled, np.clip((p["harmonized"] + 1) * np.exp(q05) - 1, 0, None), p["harmonized"])
    p["ci_high"] = np.where(modeled, (p["harmonized"] + 1) * np.exp(q95) - 1, p["harmonized"])
    return p


# =============================================================================
# [7] TRONG SO TUNG DIEM: de vung nguoi dung tu ve van ra so harmonized
# =============================================================================
def point_weights(df, panel, c_n20):
    w = np.zeros(len(df), dtype="float32")
    ym = df["ym"].astype(str).values
    sat = df["sat"].astype(str).values
    modeled = ym < VIIRS_FIRST_FULL_MONTH
    pm = panel[(panel["ym"] < VIIRS_FIRST_FULL_MONTH) & (panel["M"] > 0)]
    ratio = pd.Series((pm["pred_from_modis"] / pm["M"]).values,
                      index=pd.MultiIndex.from_arrays([pm["grid_id"], pm["ym"]]))
    idx = np.where(modeled & (sat == "Aqua"))[0]
    key = pd.MultiIndex.from_arrays([df["grid_id"].astype(str).values[idx], ym[idx]])
    w[idx] = ratio.reindex(key).fillna(0).values
    era = (ym >= VIIRS_FIRST_FULL_MONTH) & (ym <= SNPP_LAST_MONTH)
    w[era] = df["w_v"].values[era]          # S-NPP = 1, luot bi mat: NOAA-20/NOAA-21/Aqua da quy doi
    w[(ym > SNPP_LAST_MONTH) & (sat == "NOAA20")] = c_n20
    df["is_reference"] = w > 0
    df["weight"] = w
    return df


# =============================================================================
# [8] XUAT KET QUA + BIEU DO KIEM CHUNG
# =============================================================================
def save_table(df, path_noext):
    try:
        df.to_parquet(path_noext + ".parquet", index=False); return path_noext + ".parquet"
    except Exception:
        df.to_csv(path_noext + ".csv.gz", index=False); return path_noext + ".csv.gz"


def make_plots(nat, yr, val_test, best_model, out):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        log("  (khong co matplotlib -> bo qua bieu do)"); return
    full = yr[~yr["is_partial_year"]]; part = yr[yr["is_partial_year"]]
    fig, ax = plt.subplots(1, 2, figsize=(14, 4.5))
    raw = np.where(full.index < 2012, full["raw_modis_aqua"], full["harmonized"])
    ax[0].plot(full.index, raw, "o-", color="#999", label="Ghep tho (MODIS -> VIIRS)")
    ax[0].axvline(2012, ls="--", color="k", lw=0.8)
    ax[0].set_title("TRUOC: buoc nhay gia nam 2012 do doi cam bien")
    ax[0].legend(); ax[0].set_ylabel("So hotspot / nam")
    ax[1].plot(full.index, full["raw_modis_aqua"], "o-", color="#e08214", label="MODIS-Aqua tho")
    ax[1].plot(full.index, full["harmonized"], "o-", color="#2166ac", label="Harmonized (thang VIIRS)")
    m = full.index < 2012
    ax[1].fill_between(full.index[m], full["ci_low"][m], full["ci_high"][m], color="#2166ac", alpha=0.15,
                       label="Khoang 90% cap NAM (leave-one-year-out)")
    if len(part):
        lab = f"{part.index[0]} chua du nam (den {part['last_date'].iloc[0]})"
        ax[1].plot([full.index[-1], part.index[0]], [full["harmonized"].iloc[-1], part["harmonized"].iloc[0]],
                   ls=":", color="#2166ac")
        ax[1].plot(part.index, part["harmonized"], "o", mfc="white", mec="#2166ac", label=lab)
    ax[1].axvline(2012, ls="--", color="k", lw=0.8)
    ax[1].set_title("SAU: chuoi nhat quan 2003 -> nay"); ax[1].legend(fontsize=8)
    fig.tight_layout(); fig.savefig(os.path.join(out, "fig1_truoc_sau_harmonize.png"), dpi=150); plt.close(fig)

    t = val_test.assign(p=best_model.predict(val_test)).groupby("ym")[["V", "p"]].sum()
    fig, ax = plt.subplots(figsize=(14, 4))
    ax.plot(pd.to_datetime(t.index), t["V"], label="VIIRS S-NPP quan sat")
    ax.plot(pd.to_datetime(t.index), t["p"], "--", label="Du doan tu MODIS-Aqua")
    ax.set_title(f"Validation tren tap TEST {VAL_TEST[0]} -> {VAL_TEST[1]} (mo hinh chua tung thay)")
    ax.legend(); fig.tight_layout(); fig.savefig(os.path.join(out, "fig2_validation_test.png"), dpi=150); plt.close(fig)

    cal = nat.pivot(index="year", columns="month", values="harmonized")
    partial = nat[nat["is_partial_month"]]
    fig, ax = plt.subplots(figsize=(9, 9))
    shown = cal.values.copy()
    for _, r in partial.iterrows():                       # thang chua du: khong to mau
        shown[cal.index.get_loc(r["year"]), r["month"] - 1] = np.nan
    im = ax.imshow(shown, aspect="auto", cmap="YlOrRd")
    for _, r in partial.iterrows():
        i, j = cal.index.get_loc(r["year"]), r["month"] - 1
        ax.add_patch(plt.Rectangle((j - .5, i - .5), 1, 1, fill=False, hatch="///", ec="#666", lw=0))
        ax.text(j, i, "chua\ndu", ha="center", va="center", fontsize=6, color="#333")
    ax.set_xticks(range(12)); ax.set_xticklabels(range(1, 13))
    ax.set_yticks(range(len(cal))); ax.set_yticklabels(cal.index)
    ax.set_xlabel("Thang"); ax.set_title("Lich chay Viet Nam (harmonized, thang VIIRS)\no gach cheo = thang chua du du lieu")
    fig.colorbar(im, ax=ax, label="So hotspot"); fig.tight_layout()
    fig.savefig(os.path.join(out, "fig3_lich_chay_vietnam.png"), dpi=150); plt.close(fig)


# =============================================================================
# MAIN
# =============================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="D:/NASA")
    ap.add_argument("--out", default="D:/NASA/output")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    log("[1] Doc du lieu")
    df = pd.concat([load_source(a.data, n, pat) for n, pat in SOURCES.items()], ignore_index=True)
    log("[2] Chuan hoa schema")
    df = standardize(df)
    df, n_dup = dedupe_points(df)
    log(f"  bo {n_dup:,} diem trung (archive/NRT hoac quet chong mep)")
    log("[3] Loc chay thuc vat")
    df, fstats = filter_fires(df)          # dung du lieu tu 2000 de nhan dien nha may tot hon
    fstats["bo_diem_trung"] = int(n_dup)
    n_before = len(df)
    df = df[df["year"] >= START_YEAR].reset_index(drop=True)   # lich chay bat dau tu START_YEAR
    fstats["bo_truoc_START_YEAR"] = int(n_before - len(df))
    fstats["con_lai"] = len(df)
    log(f"  {fstats}")
    log("[4] Gan luoi + panel o x thang")
    df = add_grid(df)
    last_ym = df["ym"].astype(str).max()
    df, gaps, c_n20, c_n21 = snpp_gap_fill(df)          # MOI: bu luot bay S-NPP bi mat
    gaps.to_csv(os.path.join(a.out, "snpp_gaps.csv"), index=False)
    panel = build_panel(df, last_ym)
    _, n20_months = n20_to_snpp_factor(panel)           # chi giu so thang de ghi metadata
    log(f"  panel: {panel['grid_id'].nunique()} o x {panel['ym'].nunique()} thang; he so NOAA20->SNPP = {c_n20:.3f}")

    log("[5] Validation cac mo hinh quy doi")
    ok_month = panel.groupby("ym")["M"].transform("sum") > 0      # bo thang Aqua mat du lieu
    tr = panel[in_range(panel["ym"], VAL_TRAIN) & ok_month]
    te = panel[in_range(panel["ym"], VAL_TEST) & ok_month]
    rep, best, fitted = validate(tr, te)
    log(f"  -> chon mo hinh: {best}")
    final = make_model(best).fit(panel[in_range(panel["ym"], FINAL_FIT) & ok_month])
    dr = panel[in_range(panel["ym"], DRIFT_CHECK) & ok_month]
    drift = evaluate(dr, final.predict(dr), best + "_DRIFT_CHECK_2022+")
    rep = pd.concat([rep, pd.DataFrame([drift])], ignore_index=True)
    log(f"  drift check 2022+: bias={drift['qg_bias_%']:+.1f}% (Aqua troi quy dao)")
    bm = fitted[best]
    resid = np.log((te["V"].values + 1) / (np.clip(bm.predict(te), 0, None) + 1))   # CI cap o
    log("  leave-one-year-out cho khoang tin cay toan quoc (thang + nam)")
    m_res, y_res = loyo_national_residuals(panel[in_range(panel["ym"], FINAL_FIT) & ok_month], best)

    log("[6] Ghep chuoi harmonized")
    panel = build_harmonized(panel, final, c_n20, resid)

    log("[7] Trong so tung diem")
    df = point_weights(df, panel, c_n20)

    log("[8] Xuat ket qua")
    nat = panel.groupby("ym").agg(raw_modis_aqua=("M", "sum"), raw_modis_terra=("M_terra", "sum"),
                                  raw_viirs_snpp=("V_raw", "sum"), raw_viirs_noaa20=("V_n20", "sum"),
                                  raw_viirs_noaa21=("V_n21", "sum"), harmonized=("harmonized", "sum"),
                                  source_flag=("source_flag", "first")).reset_index()
    gm = gaps.assign(ym=pd.to_datetime(gaps["date_local"]).dt.strftime("%Y-%m")).groupby("ym")
    nat["snpp_gap_passes"] = nat["ym"].map(gm.size()).fillna(0).astype(int)
    nat["snpp_gap_filled_pts"] = nat["ym"].map(gm["filled_pts"].sum()).fillna(0).round(1)
    nat.loc[(nat["snpp_gap_passes"] > 0) & (nat["source_flag"] == "observed_viirs_snpp"),
            "source_flag"] = "observed_viirs_snpp_gapfilled"
    mod = nat["source_flag"].str.startswith("modeled").values
    nat["ci_low"], nat["ci_high"], ci_month = apply_ci(nat["harmonized"].values, mod, m_res)
    nat["year"] = nat["ym"].str[:4].astype(int); nat["month"] = nat["ym"].str[5:].astype(int)
    last_day = df["date_local"].max()
    days_in_last = pd.Period(last_ym).days_in_month
    nat["is_partial_month"] = (nat["ym"] == last_ym) & (last_day.day < days_in_last)
    # bang NAM: CI tinh rieng tu sai so cap nam (khong cong don CI thang)
    yr = nat.groupby("year").agg(raw_modis_aqua=("raw_modis_aqua", "sum"), raw_viirs_snpp=("raw_viirs_snpp", "sum"),
                                 harmonized=("harmonized", "sum"), n_months=("month", "count"),
                                 n_modeled=("source_flag", lambda x: x.str.startswith("modeled").sum()))
    has_partial = nat.groupby("year")["is_partial_month"].any()
    yr["is_partial_year"] = (yr["n_months"] < 12) | has_partial
    yr["last_date"] = np.where(yr["is_partial_year"], str(last_day.date()), "")
    yr["ci_low"], yr["ci_high"], ci_year = apply_ci(yr["harmonized"].values, (yr["n_modeled"] == 12).values, y_res)
    wsum = df[df["ym"].astype(str) < VIIRS_FIRST_FULL_MONTH]["weight"].sum()
    cov = float(wsum / panel.loc[panel["ym"] < VIIRS_FIRST_FULL_MONTH, "harmonized"].sum())

    keep = ["latitude", "longitude", "datetime_utc", "datetime_local", "date_local", "year", "month", "ym",
            "source", "sensor", "sat", "conf_level", "frp", "daynight", "scan", "track", "is_nrt",
            "grid_id", "is_reference", "weight"]
    files = {
        "hotspots": save_table(df[keep], os.path.join(a.out, "hotspots_clean")),
        "grid_monthly": save_table(panel, os.path.join(a.out, "grid_monthly")),
    }
    
    snpp_aqua_path = os.path.join(a.out, "hotspots_snpp_aqua_2012_2025.csv.gz")
    out_cols = ["latitude", "longitude", "date_local", "year", "month", "sat", "daynight"]
    (df.loc[df["sat"].isin(["SNPP", "Aqua"]) & df["year"].between(2012, 2025), out_cols]
       .to_csv(snpp_aqua_path, index=False))
    files["snpp_aqua_2012_2025"] = snpp_aqua_path
    
    nat.to_csv(os.path.join(a.out, "national_monthly.csv"), index=False)
    yr.reset_index().to_csv(os.path.join(a.out, "national_yearly.csv"), index=False)
    nat.pivot(index="year", columns="month", values="harmonized").round(0).to_csv(
        os.path.join(a.out, "calendar_vietnam_year_x_month.csv"))
    rep.to_csv(os.path.join(a.out, "validation_report.csv"), index=False)
    meta = {
        "ai_assistance": AI_NOTE,
        "created": time.strftime("%Y-%m-%d %H:%M"), "data_last_local_date": str(last_day.date()),
        "target_scale": "VIIRS S-NPP 375 m equivalent (single satellite)",
        "grid_res_deg": GRID_RES, "start_year": START_YEAR, "drop_low_conf": DROP_LOW_CONF,
        "filter_stats": fstats, "noaa20_to_snpp_factor": c_n20, "noaa20_factor_months_used": n20_months,
        "noaa21_to_snpp_factor": c_n21,
        "snpp_gap_fill": {"passes": int(len(gaps)), "filled_points": float(gaps["filled_pts"].sum()),
                          "by_reason": gaps["reason"].value_counts().to_dict(),
                          "rule": (f"luot bay (ngay VN x ngay/dem): S-NPP=0 va tham chieu >= {GAP_MIN_REF}, hoac "
                                   f"S-NPP < {GAP_PARTIAL_RATIO:.0%} NOAA-20 (NOAA-20 >= {GAP_PARTIAL_MIN}), hoac nam "
                                   "trong dot mat du lieu NOAA/NASA cong bo; bu bang NOAA-20 x c_n20 "
                                   "(NOAA-21 x c_n21, truoc 2018 Aqua x ty le thang)")},
        "chosen_model": best, "final_fit_period": FINAL_FIT,
        "glm_coef_logM_indM_logMnb": getattr(final, "coef", None),
        "ci90_log_ratio_monthly_loyo": ci_month, "ci90_log_ratio_yearly_loyo": ci_year,
        "n_loyo_years": int(len(y_res)),
        "partial_month": last_ym if nat["is_partial_month"].any() else None,
        "point_weight_coverage_modeled_period": cov,
        "note_point_weights": ("Vung tu ve: harmonized = sum(weight) cac diem trong vung. Giai doan 2003-01/2012 "
                               f"chi phu ~{cov*100:.0f}% vi phan du doan o cac o M=0 (nhung M_nb>0) khong co diem "
                               "Aqua nao de gan trong so. So theo o/tinh/toan quoc dung grid_monthly (day du)."),
        "outputs": files,
    }
    with open(os.path.join(a.out, "harmonization_metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    make_plots(nat, yr, te, bm, a.out)
    print("\n" + rep.round(3).to_string(index=False))
    log(f"XONG. Ket qua o: {a.out}")


AI_NOTE = ("Code written with assistance from Claude (Anthropic); reviewed and tested by team 268LTK. "
           "All values are computed from NASA FIRMS data, not generated by AI.")

if __name__ == "__main__":
    main()
