"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

All API configuration in one place.

Precedence (highest wins):
  1. a real environment variable
  2. a line in api/.env
  3. the default written here
"""

import os
from dotenv import load_dotenv

# Reads api/.env if it exists; harmless if it doesn't
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# database (should be the same as what parser uses) 
DB_URI = os.getenv("DB_URI",
    "mongodb+srv://test:test@banglacluster.ntnbhcq.mongodb.net/?appName=BanglaCluster")
DB_NAME = os.getenv("DB_NAME", "RiverGuard")

# redis (the live stream's backend)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# where to host the api (this machine's port 8000)
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))

# SSE keepalive: browsers and proxies drop connections that stay
# silent too long. Every N seconds of silence we send an SSE comment
# line (": keepalive") - browsers ignore it, but it resets those timers. ---
KEEPALIVE_SECONDS = int(os.getenv("KEEPALIVE_SECONDS", "15"))

# where the website files live (../web, relative to this file)
WEB_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web"))

# CORS: the website may be served from elsewhere (e.g. Vercel)
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")