@echo off
REM Build Docker image for GnuCash development
REM
REM Usage:
REM   scripts\build.bat              - Build default (debian:13)
REM   scripts\build.bat debian:12    - Build specific distribution
REM   scripts\build.bat ubuntu:20.04 - Build Ubuntu 20.04

setlocal enabledelayedexpansion

set BASE_IMAGE=%1
if "%BASE_IMAGE%"=="" set BASE_IMAGE=debian:13

set IMAGE_NAME=gnucash-dev

REM Map base image to tag name
if "%BASE_IMAGE%"=="debian:13" (
    set TAG=latest
    set GNUCASH_VERSION=5.10
) else if "%BASE_IMAGE%"=="debian:12" (
    set TAG=debian12
    set GNUCASH_VERSION=4.13
) else if "%BASE_IMAGE%"=="debian:11" (
    set TAG=debian11
    set GNUCASH_VERSION=4.4
) else if "%BASE_IMAGE%"=="ubuntu:20.04" (
    set TAG=ubuntu20
    set GNUCASH_VERSION=3.8
) else (
    echo Unknown distribution: %BASE_IMAGE%
    echo Supported: debian:13, debian:12, debian:11, ubuntu:20.04
    exit /b 1
)

echo Building %IMAGE_NAME%:%TAG% (GnuCash %GNUCASH_VERSION%)...
docker build --build-arg BASE_IMAGE=%BASE_IMAGE% -t %IMAGE_NAME%:%TAG% .

echo.
echo Build complete: %IMAGE_NAME%:%TAG%
echo.
echo Run interactive shell:
echo   scripts\shell.bat %TAG%
