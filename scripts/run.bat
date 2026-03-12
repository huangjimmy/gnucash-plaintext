@echo off
REM Run arbitrary command in GnuCash development container
REM
REM Usage:
REM   scripts\run.bat python3 --version
REM   scripts\run.bat debian12 python3 script.py
REM   scripts\run.bat latest gnucash-plaintext --help

setlocal

REM Check if first arg looks like a tag
set FIRST_ARG=%1
set TAG=latest

if "%FIRST_ARG%"=="latest" set TAG=latest& shift
if "%FIRST_ARG%"=="debian12" set TAG=debian12& shift
if "%FIRST_ARG%"=="debian11" set TAG=debian11& shift
if "%FIRST_ARG%"=="ubuntu20" set TAG=ubuntu20& shift

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

REM Collect remaining arguments
set ARGS=%1
:loop
shift
if "%1"=="" goto :endloop
set ARGS=%ARGS% %1
goto :loop
:endloop

docker run --rm -v "%CD%:/workspace" %IMAGE_NAME% %ARGS%
