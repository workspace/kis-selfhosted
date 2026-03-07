"""Generate kis_devlp.yaml from environment variables into the shared config volume."""

import os
import pathlib

cfg_dir = os.environ.get("KIS_CONFIG_DIR", "/app/kis-config")
pathlib.Path(cfg_dir).mkdir(parents=True, exist_ok=True)

entries = [
    ("my_app", os.environ.get("KIS_APP_KEY", "")),
    ("my_sec", os.environ.get("KIS_APP_SECRET", "")),
    ("paper_app", os.environ.get("KIS_PAPER_APP_KEY", "")),
    ("paper_sec", os.environ.get("KIS_PAPER_APP_SECRET", "")),
    ("my_htsid", os.environ.get("KIS_HTS_ID", "")),
    ("my_acct_stock", os.environ.get("KIS_ACCT_STOCK", "")),
    ("my_acct_future", os.environ.get("KIS_ACCT_FUTURE", "")),
    ("my_paper_stock", os.environ.get("KIS_PAPER_STOCK", "")),
    ("my_paper_future", os.environ.get("KIS_PAPER_FUTURE", "")),
    ("my_prod", os.environ.get("KIS_PROD_TYPE", "01")),
    ("my_token", ""),
    ("my_agent", os.environ.get("KIS_USER_AGENT", "Mozilla/5.0")),
    ("prod", "https://openapi.koreainvestment.com:9443"),
    ("ops", "ws://ops.koreainvestment.com:21000"),
    ("vps", "https://openapivts.koreainvestment.com:29443"),
    ("vops", "ws://ops.koreainvestment.com:31000"),
]

cfg_path = os.path.join(cfg_dir, "kis_devlp.yaml")
with open(cfg_path, "w", encoding="UTF-8") as f:
    for key, val in entries:
        f.write(f'{key}: "{val}"\n')

print(f"[init] kis_devlp.yaml -> {cfg_path}")
