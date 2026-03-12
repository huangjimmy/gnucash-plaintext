@echo off
REM Run tests in GnuCash development container
REM
REM Usage:
REM   scripts\test.bat              - Run all tests with latest image
REM   scripts\test.bat debian12     - Run with specific tag
REM   scripts\test.bat latest tests/unit - Run specific tests

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

REM Get remaining arguments (test paths)
shift
set TEST_PATH=%1
:loop
shift
if "%1"=="" goto :endloop
set TEST_PATH=%TEST_PATH% %1
goto :loop
:endloop

if "%TEST_PATH%"=="" set TEST_PATH=tests/

echo Running tests in %IMAGE_NAME%...
docker run --rm -v "%CD%:/workspace" %IMAGE_NAME% /workspace/scripts/test-in-docker.sh %TEST_PATH%
