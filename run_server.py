"""Convenience runner script for PyCharm and local execution."""
import os
import sys
from pathlib import Path

# Ensure cryptotracker directory is the working directory and in sys.path
BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import uvicorn

if __name__ == "__main__":
    print("🚀 Starting Freshie CoinTracker on http://localhost:8000 ...")
    uvicorn.run("config.asgi:application", host="127.0.0.1", port=8000, reload=True)
