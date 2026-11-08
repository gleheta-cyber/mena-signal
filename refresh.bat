@echo off
rem Fetch the latest news and open the site
cd /d "%~dp0"
python build.py
start "" "%~dp0site\index.html"
