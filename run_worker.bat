@echo off
REM На Windows Celery с prefork падает с PermissionError. Запуск с --pool=solo обязателен.
cd /d "%~dp0"
if exist venv\Scripts\activate.bat call venv\Scripts\activate.bat
celery -A celery_app worker --loglevel=info --pool=solo
