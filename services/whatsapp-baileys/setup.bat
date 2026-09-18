@echo off
REM ================================================================
REM  SK AI Agent — Baileys WhatsApp Gateway Setup (Windows)
REM  Run this ONCE to install Node dependencies.
REM ================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
echo.
echo [1/2] Installing Baileys + Express + Multer (this takes ~1-3 min)...
call npm install --no-audit --no-fund
if errorlevel 1 (
    echo ERROR: npm install failed. Check Node.js version:
    node --version
    exit /b 1
)
echo.
echo [2/2] OK. Dependencies installed.
echo.
echo To start the gateway standalone (optional, SK starts it automatically):
echo     npm start
echo.
echo Credentials and session saved at: memory\baileys_auth\
echo (Never commit that folder — it's in .gitignore.)
echo.
pause
