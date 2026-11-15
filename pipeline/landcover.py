"""
pipeline/landcover.py  —  Land-cover labels for the web (module ui/landcover.js)
Team 268LTK · NASA Space Apps 2026

Inputs (exported from Google Earth Engine on the same 0.01° grid, lon 102–110, lat 8–23.5):
  --esa    landcover_vn_001.tif  : ESA WorldCover v200 (2021, 10 m) → 3 bands: class, forest_pct, crop_pct
  --modis  mcd12q1_vn_001.tif    : NASA MODIS MCD12Q1 C6.1 (IGBP) per year → band y2001…y20xx
                                   (1 = forest: IGBP 1–5 and 8 · 2 = cropland: 12 · 3 = mosaic: 14 · 0 = other)
Reads from the web data (no need to re-run harmonize.py):
  site/data/cells/<year>.json, site/data/provinces.geojson

Combining rule:
  1. Base = ESA (10 m, more detailed).
  2. Uncertain: ESA and MODIS 2021 disagree (forest ↔ cropland) and ESA itself is not very sure
     (dominant share < 70%) → class 3 "mixed / uncertain".
  3. Land converted: in fire year Y, MODIS (3-year smoothed) says forest/cropland but differs from
     MODIS 2021 → use MODIS year Y (e.g. it was forest in 2008, cropland by 2021).

Outputs → site/data/landcover/
  lc_grid.bin.gz            4 × H × W uint8: final class (2021), forest_pct, crop_pct, flag (2 = uncertain)
  lc_meta.json              grid description + label names
  lc_override.json          per year: cells whose label differs from the grid because the land changed
                            {"2008":[lat_idx, lon_idx, label, ...]}
  province_monthly_lc.json  forest / cropland share by province × month: {"<province_id>":{"YYYY-MM":[f,a]}}, plus "VN"

Run:  python landcover.py --esa landcover_vn_001.tif --modis mcd12q1_vn_001.tif --site ../site
Needs: numpy, tifffile, matplotlib (imagecodecs is optional; without it the built-in LZW decoder is used)
"""
import argparse, glob, gzip, json, os, re
import numpy as np
import tifffile
from matplotlib.path import Path

FOREST, CROP, MIXED, OTHER = 1, 2, 3, 0
REF_YEAR = 2021          # year of ESA WorldCover v200


# ---------------------------------------------------------------- read GeoTIFF
def lzw_decode(data):
    """TIFF LZW decoder (MSB-first, early change) — used when imagecodecs is not installed."""
    data = bytes(data) + b'\x00\x00\x00'
    out, nbits, pos, end = bytearray(), 9, 0, len(data) * 8 - 24
    table, prev = [bytes([i]) for i in range(256)] + [b'', b''], b''
    while pos + nbits <= end + 24:
        b = pos >> 3
        code = ((data[b] << 16 | data[b + 1] << 8 | data[b + 2]) >> (24 - (pos & 7) - nbits)) & ((1 << nbits) - 1)
        pos += nbits
        if code == 257:
            break
        if code == 256:
            table, nbits, prev = table[:258], 9, b''
            continue
        if code < len(table):
            entry = table[code]
            if prev:
                table.append(prev + entry[:1])
        else:
            entry = prev + prev[:1]
            table.append(entry)
        out += entry
        prev = entry
        if len(table) >= (1 << nbits) - 1 and nbits < 12:
            nbits += 1
    return bytes(out)


def read_tif(path):
    """→ (array[bands, H, W] uint8, (x0, y0, d), band_names)"""
    with tifffile.TiffFile(path) as t:
        p = t.pages[0]
        d = p.tags[33550].value[0]
        tp = p.tags[33922].value
        names = re.findall(r'role="description">([^<]+)<', str(p.tags[42112].value)) if 42112 in p.tags else []
        try:
            a = p.asarray()
        except ValueError:                       # LZW without imagecodecs
            H, W, C = p.shape if p.ndim == 3 else (*p.shape, 1)
            th, tw = p.tilelength, p.tilewidth
            a = np.zeros((H, W, C), np.uint8)
            fh, k = t.filehandle, 0
            for ty in range(0, H, th):
                for tx in range(0, W, tw):
                    fh.seek(p.dataoffsets[k]); raw = fh.read(p.databytecounts[k]); k += 1
                    tile = np.frombuffer(lzw_decode(raw), np.uint8)
                    tile = np.pad(tile, (0, max(0, th * tw * C - tile.size)))[:th * tw * C].reshape(th, tw, C)
                    h, w = min(th, H - ty), min(tw, W - tx)
                    a[ty:ty + h, tx:tx + w] = tile[:h, :w]
        if a.ndim == 2:
            a = a[..., None]
        return np.ascontiguousarray(np.moveaxis(a, -1, 0)), (tp[3], tp[4], d), names


# ---------------------------------------------------------------- provinces (point-in-polygon)
def load_provinces(path):
    g = json.load(open(path, encoding='utf-8'))
    out = []
    for f in g['features']:
        geom = f['geometry']
        polys = geom['coordinates'] if geom['type'] == 'MultiPolygon' else [geom['coordinates']]
        parts = []
        for poly in polys:
            rings = [np.asarray(r)[:, :2] for r in poly]
            parts.append((Path(rings[0]), [Path(r) for r in rings[1:]]))
        allxy = np.vstack([np.asarray(p[0].vertices) for p in parts])
        out.append((str(f['properties']['province_id']), allxy.min(0), allxy.max(0), parts))
    return out


def assign_province(lon, lat, provs):
    pid = np.full(lon.shape, '', dtype=object)
    pts = np.column_stack([lon, lat])
    for p_id, mn, mx, parts in provs:
        cand = np.where((lon >= mn[0]) & (lon <= mx[0]) & (lat >= mn[1]) & (lat <= mx[1]) & (pid == ''))[0]
        if not len(cand):
            continue
        inside = np.zeros(len(cand), bool)
        for outer, holes in parts:
            m = outer.contains_points(pts[cand])
            for h in holes:
                m &= ~h.contains_points(pts[cand])
            inside |= m
        pid[cand[inside]] = p_id
    return pid


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--esa', required=True)
    ap.add_argument('--modis', required=True)
    ap.add_argument('--site', default='../site')
    ap.add_argument('--uncertain', type=float, default=70, help='ESA dominant share (%%) below which an ESA–MODIS conflict counts as uncertain')
    a = ap.parse_args()
    out = os.path.join(a.site, 'data', 'landcover')
    os.makedirs(out, exist_ok=True)

    esa, (x0, y0, d), _ = read_tif(a.esa)
    mod, geo_m, names = read_tif(a.modis)
    assert np.allclose(geo_m, (x0, y0, d)) and mod.shape[1:] == esa.shape[1:], 'ESA and MODIS grids do not match'
    years = [int(re.search(r'(\d{4})', n).group(1)) for n in names] if names else list(range(2001, 2001 + mod.shape[0]))
    H, W = esa.shape[1:]
    print(f'Grid {W}×{H}, d={d}° · MODIS {years[0]}–{years[-1]}')

    # MODIS smoothed (3-year mode) to avoid year-to-year flicker
    ms = mod.copy()
    for k in range(len(years)):
        win = mod[max(0, k - 1):k + 2]
        cnt = np.stack([(win == c).sum(0) for c in range(4)])
        best = cnt.argmax(0).astype(np.uint8)
        ms[k] = np.where(cnt.max(0) >= 2, best, mod[k])
    yi = {y: k for k, y in enumerate(years)}
    ref = ms[yi[min(REF_YEAR, years[-1])]]

    # (1) static grid: ESA + uncertain where it conflicts with MODIS 2021
    cls = esa[0].copy()
    dom = np.maximum(esa[1], esa[2])
    conflict = ((cls == FOREST) & (ref == CROP)) | ((cls == CROP) & (ref == FOREST))
    unc = conflict & (dom < a.uncertain)
    cls[unc] = MIXED
    flag = np.where(unc, 2, 0).astype(np.uint8)
    grid = np.stack([cls, esa[1], esa[2], flag]).astype(np.uint8)
    with gzip.open(os.path.join(out, 'lc_grid.bin.gz'), 'wb', compresslevel=9) as f:
        f.write(grid.tobytes())
    json.dump({'x0': x0, 'y0': y0, 'd': d, 'w': W, 'h': H, 'bands': ['class', 'forest_pct', 'crop_pct', 'flag'],
               'classes': {'0': 'other', '1': 'forest', '2': 'cropland', '3': 'mixed/uncertain'},
               'flags': {'2': 'ESA and MODIS 2021 disagree'}, 'ref_year': REF_YEAR,
               'modis_years': [years[0], years[-1]],
               'sources': ['ESA WorldCover v200 (2021), 10 m', 'NASA MODIS MCD12Q1 C6.1 (IGBP), 500 m, yearly']},
              open(os.path.join(out, 'lc_meta.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'Uncertain cells: {int(unc.sum()):,} / conflict {int(conflict.sum()):,}')

    # (2) fire cells per year + year-specific label
    recs = []
    for fp in sorted(glob.glob(os.path.join(a.site, 'data', 'cells', '*.json'))):
        y = int(os.path.basename(fp)[:4])
        for mm, rows in json.load(open(fp))['m'].items():
            if rows:
                r = np.asarray(rows, float)
                recs.append((y, int(mm), r[:, 0].astype(np.int64), r[:, 1].astype(np.int64), r[:, 2]))
    yy = np.concatenate([np.full(len(r[2]), r[0]) for r in recs]); mm = np.concatenate([np.full(len(r[2]), r[1]) for r in recs])
    ai = np.concatenate([r[2] for r in recs]); oi = np.concatenate([r[3] for r in recs]); vv = np.concatenate([r[4] for r in recs])
    lat, lon = (ai + .5) * .01, (oi + .5) * .01
    row = np.clip(np.floor((y0 - lat) / d).astype(int), 0, H - 1)
    col = np.clip(np.floor((lon - x0) / d).astype(int), 0, W - 1)
    lab = cls[row, col].copy()

    override = {}
    for y in sorted(set(yy.tolist())):
        k = yi.get(min(max(y, years[0]), years[-1]))
        sel = yy == y
        my, rf, base = ms[k][row[sel], col[sel]], ref[row[sel], col[sel]], lab[sel]
        chg = np.isin(my, [FOREST, CROP]) & np.isin(rf, [FOREST, CROP]) & (my != rf) & (my != base)
        new = base.copy(); new[chg] = my[chg]; lab[sel] = new
        cells = np.unique(np.column_stack([ai[sel][chg], oi[sel][chg], my[chg]]), axis=0)
        if len(cells):
            override[str(y)] = cells.astype(int).ravel().tolist()
    json.dump(override, open(os.path.join(out, 'lc_override.json'), 'w'), separators=(',', ':'))
    print('Override cells per year:', {y: len(v) // 3 for y, v in override.items()})

    # (3) shares by province × month
    uk, inv = np.unique(np.column_stack([ai, oi]), axis=0, return_inverse=True)
    pid = assign_province((uk[:, 1] + .5) * .01, (uk[:, 0] + .5) * .01, load_provinces(os.path.join(a.site, 'data', 'provinces.geojson')))[inv.ravel()]
    ym = np.char.add(np.char.add(yy.astype(str), '-'), np.char.zfill(mm.astype(str), 2))
    res = {}
    for key, mask in [('VN', np.ones(len(vv), bool))] + [(p, pid == p) for p in sorted(set(pid.tolist()) - {''})]:
        tot, f_, a_ = {}, {}, {}
        for m_, v_, l_ in zip(ym[mask], vv[mask], lab[mask]):
            tot[m_] = tot.get(m_, 0) + v_
            if l_ == FOREST: f_[m_] = f_.get(m_, 0) + v_
            elif l_ == CROP: a_[m_] = a_.get(m_, 0) + v_
        res[key] = {m_: [round(f_.get(m_, 0) / t, 3), round(a_.get(m_, 0) / t, 3)] for m_, t in sorted(tot.items()) if t > 0}
    json.dump(res, open(os.path.join(out, 'province_monthly_lc.json'), 'w'), separators=(',', ':'))
    vn = res['VN']; tot_f = np.mean([v[0] for v in vn.values()]); tot_a = np.mean([v[1] for v in vn.values()])
    print(f'Mean monthly share (VN): forest {tot_f:.0%} · cropland {tot_a:.0%} · mixed/other {1 - tot_f - tot_a:.0%}')
    print('Done →', out)


if __name__ == '__main__':
    main()
