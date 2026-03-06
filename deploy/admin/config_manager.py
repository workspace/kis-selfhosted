"""KIS config (kis_devlp.yaml) initializer from Docker environment variables."""

from __future__ import annotations

import os
import pathlib

import yaml

KIS_CONFIG_DIR = os.environ.get("KIS_CONFIG_DIR", "/app/kis-config")
CONFIG_FILE = os.path.join(KIS_CONFIG_DIR, "kis_devlp.yaml")


def init_config_from_env() -> None:
    """Write kis_devlp.yaml from environment variables on startup."""
    pathlib.Path(KIS_CONFIG_DIR).mkdir(parents=True, exist_ok=True)

    env_map = {
        "my_app": "KIS_APP_KEY",
        "my_sec": "KIS_APP_SECRET",
        "paper_app": "KIS_PAPER_APP_KEY",
        "paper_sec": "KIS_PAPER_APP_SECRET",
        "my_htsid": "KIS_HTS_ID",
        "my_acct_stock": "KIS_ACCT_STOCK",
        "my_acct_future": "KIS_ACCT_FUTURE",
        "my_paper_stock": "KIS_PAPER_STOCK",
        "my_paper_future": "KIS_PAPER_FUTURE",
        "my_prod": "KIS_PROD_TYPE",
    }

    cfg = {}
    for yaml_key, env_key in env_map.items():
        val = os.environ.get(env_key, "")
        if val:
            cfg[yaml_key] = val

    if cfg:
        with open(CONFIG_FILE, "w", encoding="UTF-8") as f:
            yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
