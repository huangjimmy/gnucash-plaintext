@echo off
REM Stop the development environment
REM
REM Usage:
REM   scripts\dev-stop.bat

echo Stopping GnuCash Plaintext development environment...
docker compose down
echo Stopped.
