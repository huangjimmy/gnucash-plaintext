@echo off
REM Start the development environment with VS Code Server
REM
REM Usage:
REM   scripts\dev-start.bat

echo Starting GnuCash Plaintext development environment...
echo.

REM Check if base image exists
docker image inspect gnucash-dev:latest >nul 2>&1
if errorlevel 1 (
    echo Base image gnucash-dev:latest not found. Building...
    call scripts\build.bat
    echo.
)

REM Check if dev image exists
docker image inspect gnucash-dev-vscode:latest >nul 2>&1
if errorlevel 1 (
    echo Dev image not found. Docker compose will build it ^(this may take a few minutes^)...
    echo.
)

echo Starting docker compose...
docker compose up --build
