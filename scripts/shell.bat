@echo off
REM Start interactive shell in GnuCash development container
REM
REM Usage:
REM   scripts\shell.bat         - Use latest image
REM   scripts\shell.bat debian12 - Use specific tag

setlocal

set TAG=%1
if "%TAG%"=="" set TAG=latest

set IMAGE_NAME=gnucash-dev:%TAG%

REM Check if image exists
docker image inspect %IMAGE_NAME% >nul 2>&1
if errorlevel 1 (
    echo Image %IMAGE_NAME% not found. Building...
    if "%TAG%"=="latest" (
        call scripts\build.bat debian:13
    ) else if "%TAG%"=="debian12" (
        call scripts\build.bat debian:12
    ) else if "%TAG%"=="debian11" (
        call scripts\build.bat debian:11
    ) else if "%TAG%"=="ubuntu20" (
        call scripts\build.bat ubuntu:20.04
    ) else (
        echo Unknown tag: %TAG%
        exit /b 1
    )
)

echo Starting interactive shell in %IMAGE_NAME%...
docker run -it --rm -v "%CD%:/workspace" %IMAGE_NAME% bash
