@echo off
REM Запуск воркера Celery для обработки фото/PDF и отправки расшифровки в Telegram.
REM Без запущенного воркера пользователи не получают результат распознавания.
cd /d "%~dp0.."
if exist "venv\Scripts\activate.bat" call venv\Scripts\activate.bat
celery -A celery_app worker -l info -P solo
