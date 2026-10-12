"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

All configuration in one place.
Defaults assume localhosted service and port.

Precedence (highest wins):
  1. a real environment variable
  2. a line in parser/.env
  3. the default written here
"""

import os
from dotenv import load_dotenv

# Reads .env if it exists; harmless if it doesn't
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=False)

# database 
DB_URI = os.getenv("DB_URI","mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "RiverGuard")

# mqtt
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

# redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")