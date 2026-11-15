# -*- coding: utf-8 -*-
# AI use: Written with assistance from Claude (Anthropic); reviewed and tested by team 268LTK.
"""Kiem tra nhanh thu muc deploy sau khi chay. Dung: python kiem_tra_deploy.py <out> <deploy>"""
import sys, os, json, gzip, struct
import pandas as pd
out, dep = sys.argv[1], sys.argv[2]
ok = True
def check(name, cond, info=""):
    global ok
    print(("  [OK]  " if cond else "  [LOI] ") + name + (f"  ({info})" if info else ""))
    ok &= bool(cond)

print("== Chuoi ca nuoc (uploads/national_monthly.csv)")
nm = pd.read_csv(os.path.join(dep, "uploads", "national_monthly.csv")).set_index("ym")
g = lambda ym: float(nm.loc[ym, "harmonized"])
check("2/2024 khong co su co -> giu nguyen 9199", abs(g("2024-02") - 9199) < 1, f"{g('2024-02'):.0f}")
check("3/2026 da bu (~8800-8900)", 8700 < g("2026-03") < 9000, f"{g('2026-03'):.0f}")
check("7/2024 da bu (~650-800)", 600 < g("2024-07") < 850, f"{g('2024-07'):.0f}")
check("7/2022 da bu (~1000-1250)", 950 < g("2022-07") < 1300, f"{g('2022-07'):.0f}")
meta = json.load(open(os.path.join(dep, "uploads", "harmonization_metadata.json"), encoding="utf-8"))
f = meta.get("noaa20_to_snpp_factor")
check("He so NOAA-20 -> S-NPP gan 1", f and 0.97 < f < 1.03, f"{f:.4f}" if f else "khong co")
check("Metadata co muc snpp_gap_fill", "snpp_gap_fill" in meta, str(meta.get("snpp_gap_fill", {}).get("passes")) + " luot bay")

print("== Che do Ngay (data/days/2026.bin.gz)")
b = gzip.open(os.path.join(dep, "data", "days", "2026.bin.gz")).read()
n = struct.unpack("<I", b[:4])[0]
t = struct.unpack(f"<{n}I", b[4:4 + 4 * n])
sc = b[4 + 11 * n: 4 + 12 * n]
for d in (10, 11, 12):
    doy = (pd.Timestamp(2026, 3, d) - pd.Timestamp(2026, 1, 1)).days
    c = sum(1 for i in range(n) if doy * 1440 <= t[i] < (doy + 1) * 1440 and sc[i] & 128)
    check(f"{d}/3/2026 khong con 0 diem", c > 50, f"{c} diem")
dq = json.load(open(os.path.join(dep, "data", "daily_quality.json")))
check("daily_quality.json sinh tu snpp_gaps.csv", len(dq) > 0 and "2026-03-11" in dq, f"{len(dq)} ngay")

print("== Tong tinh = tong ca nuoc (data/province_monthly.json)")
pm = json.load(open(os.path.join(dep, "data", "province_monthly.json"), encoding="utf-8"))
i = pm["months"].index("2026-03"); s = sum(pm["v"][i])
check("Tong 34 tinh thang 3/2026 ~ ca nuoc", abs(s - g("2026-03")) / g("2026-03") < 0.02, f"{s:.0f} vs {g('2026-03'):.0f}")

print("== Thu muc deploy")
need = ["index.html", "lib/d3.min.js", "data/tong_hop_34tinh.csv", "data/evidence.json", "data/method.json",
        "data/provinces.geojson", "data/patrol_cells/new_13.csv", "data/cells_meta.json", "data/days_meta.json"]
for p in need:
    check("co " + p, os.path.exists(os.path.join(dep, p)))
sizes = [(os.path.getsize(os.path.join(r, x)), os.path.join(r, x)) for r, _, fs in os.walk(dep) for x in fs]
big = max(sizes)
check("Khong file nao > 100 MB (gioi han Vercel)", big[0] < 100e6, f"lon nhat {big[0]/1e6:.1f} MB")
print(f"   {len(sizes)} file, tong {sum(s for s, _ in sizes)/1e6:.1f} MB")
print("\nKET QUA:", "DAT - san sang keo vao vercel.com/drop" if ok else "CO LOI - xem dong [LOI] o tren")
