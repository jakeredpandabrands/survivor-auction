"""Gunicorn config for Render deployment."""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '10000')}"
workers = 1  # Required: in-memory game state is per-worker; only 1 worker shares state
timeout = 120
