# Bản đồ cháy Việt Nam – NASA Space Apps 2026

Lịch cháy hài hoà MODIS + VIIRS (thang VIIRS S-NPP) 2003–nay cho 34 tỉnh, bản đồ ô 1 km,
chế độ xem theo ngày và bản đồ ưu tiên tuần tra.

## Cấu trúc
| Thư mục | Nội dung |
|---|---|
| `site/` | Web tĩnh được deploy lên Vercel (`index.html`, `lib/`, `uploads/`, `data/`) |
| `pipeline/` | Code tạo dữ liệu: `harmonize.py` → `export_web.py` → `build_vercel.py`, kiểm tra `kiem_tra_deploy.py` |
| `.github/workflows/` | GitHub Actions: tự chạy kiểm tra dữ liệu mỗi lần push / pull request |

## Cập nhật web
- **Sửa giao diện:** sửa `site/index.html` → commit → push. Vercel tự deploy (~1 phút).
- **Cập nhật dữ liệu** (cần dữ liệu FIRMS gốc trên máy, không lưu trong repo):
  ```bash
  pip install -r pipeline/requirements.txt
  cd pipeline
  python harmonize.py    --data <thu_muc_FIRMS> --out ../output
  python export_web.py   --out ../output --boundaries vn_34_provinces.geojson
  python build_vercel.py --out ../output --deploy ../site
  python kiem_tra_deploy.py ../output ../site
  ```
  rồi commit thư mục `site/` và push.

## Cấu hình Vercel
Root Directory: `site` · Framework Preset: Other · Build Command / Output Directory: để trống.
