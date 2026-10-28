"""Configuration for optional live integration fixtures."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

# These defaults match the maintainer's fictional demo workspace. Other users
# can point the live scripts at equivalent records in their own Linear workspace.
LINEAR_DEMO_ISSUE_TITLE = os.getenv(
    "LINEAR_DEMO_ISSUE_TITLE",
    "Electronics Pricing Optimization",
)
LINEAR_DEFAULT_TEAM = os.getenv("LINEAR_DEFAULT_TEAM", "Business Operations")

# This product is portable because scripts/seed_database.py creates it locally.
DEMO_PRODUCT_NAME = os.getenv("DEMO_PRODUCT_NAME", "Headphones")
