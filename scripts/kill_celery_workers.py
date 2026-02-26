"""Останавливает все процессы Celery worker (celery -A celery_app ...), чтобы перезапустить воркер с новым кодом."""
import subprocess
import sys

if sys.platform != "win32":
    sys.exit(0)

# Ищем python.exe и celery.exe, в командной строке — celery_app (наша очередь)
try:
    out = subprocess.run(
        ["wmic", "process", "get", "processid,commandline"],
        capture_output=True,
        text=True,
        timeout=15,
    )
except Exception as e:
    print("wmic error:", e)
    sys.exit(0)

killed = 0
for line in out.stdout.splitlines():
    line_lower = line.lower()
    if "celery_app" not in line_lower or "worker" not in line_lower:
        continue
    if "celery" not in line_lower:
        continue
    parts = line.strip().split()
    for i, p in enumerate(parts):
        if p.isdigit() and i > 0:
            pid = int(p)
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=5)
                print("Killed Celery worker PID:", pid)
                killed += 1
            except Exception:
                pass
            break
if not killed:
    print("No Celery worker processes found.")
else:
    print("Done.")
