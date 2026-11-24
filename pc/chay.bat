@echo off
chcp 65001 >nul
python -c "import PIL" 2>nul || pip install pillow
python "%~dp0server.py"
pause
