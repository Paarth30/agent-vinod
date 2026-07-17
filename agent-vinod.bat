@echo off
title Agent Vinod - Job Application Agent
echo.
echo  ==========================================
echo   Agent Vinod - Job Application Agent
echo  ==========================================
echo.
cd /d "%~dp0"
call env\Scripts\activate
python main.py
pause
