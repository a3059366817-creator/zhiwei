@echo off
rem ZhiWei local dev server (ASCII only on purpose)
cd /d "%~dp0"
if not exist .env (
  echo [ERROR] .env not found. Copy .env.example to .env first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8420 --reload
