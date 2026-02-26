"""Останавливает все процессы python, запустившие bot.main (чтобы не было конфликта getUpdates)."""
import subprocess
import sys

if sys.platform != "win32":
    sys.exit(0)

try:
    out = subprocess.run(
        ["wmic", "process", "where", "name='python.exe'", "get", "processid,commandline"],
        capture_output=True,
        text=True,
        timeout=10,
    )
except Exception as e:
    print("wmic error:", e)
    sys.exit(0)

for line in out.stdout.splitlines():
    if "bot.main" not in line:
        continue
    parts = line.strip().split()
    for i, p in enumerate(parts):
        if p.isdigit() and i > 0:
            pid = int(p)
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=5)
                print("Killed bot PID:", pid)
            except Exception:
                pass
            break
print("Done")
