@echo off
cd /d "%~dp0"
py -m pip install -q -r requirements.txt
start "" http://127.0.0.1:5000
py app.py
pause
