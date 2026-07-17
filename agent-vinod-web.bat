@echo off
title Agent Vinod - Web App Launcher
echo.
echo  ==========================================
echo   Agent Vinod - Web App (FastAPI + React)
echo  ==========================================
echo.
cd /d "%~dp0"

echo Starting backend (FastAPI) on http://localhost:8000 ...
start "Agent Vinod - Backend" cmd /k "call env\Scripts\activate && uvicorn backend.app:app --reload --reload-dir backend --reload-dir steps --port 8000"

echo Starting frontend (Vite) on http://localhost:5173 ...
start "Agent Vinod - Frontend" cmd /k "cd frontend && npm run dev"

echo.
echo Both servers are starting in separate windows.
echo Open http://localhost:5173 in your browser once they're ready.
pause
