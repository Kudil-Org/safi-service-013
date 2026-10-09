@echo off
rem SAFI Service 013 - Root Service Expert (default port 8013)
python -m uvicorn safi.main:app --host 127.0.0.1 --port 8013
