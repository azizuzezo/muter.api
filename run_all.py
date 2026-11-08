#!/usr/bin/env python3
"""
SairiHost Unified Service Runner
Menjalankan DuaCincin Gemini Web2API (Port 2014) dan BalikLayar Discord Core Bot berdampingan dalam satu container SairiHost.
"""
import subprocess
import sys
import time
import os
import signal

def main():
    print("==================================================")
    print("🚀 [SairiHost] Memulai Layanan Terpadu BalikLayar AI")
    print("==================================================")

    # Pastikan direktori kerja benar
    cwd = os.path.dirname(os.path.abspath(__file__))

    # 1. Menjalankan DuaCincin Gemini API
    print("📡 [1/2] Menyalakan DuaCincin Gemini API (Port 2014)...")
    api_cmd = [sys.executable, "duacincin.py"]
    api_proc = subprocess.Popen(api_cmd, cwd=cwd)

    # Tunggu 3 detik agar socket port 2014 siap menerima request
    time.sleep(3)

    # 2. Menjalankan BalikLayar Discord Bot
    print("🤖 [2/2] Menyalakan BalikLayar Discord Core Bot...")
    bot_cmd = [sys.executable, "bot.py"]
    bot_proc = subprocess.Popen(bot_cmd, cwd=cwd)

    def handle_exit(signum, frame):
        nonlocal api_proc
        print("\n🛑 [SairiHost] Menerima sinyal stop, mematikan semua proses...")
        try:
            bot_proc.terminate()
            api_proc.terminate()
        except:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    # Pantau kedua proses. API mati -> hidupkan lagi (bot tetap jalan). Bot mati -> keluar (host akan restart).
    try:
        while bot_proc.poll() is None:
            if api_proc.poll() is not None:
                print(f"♻️ [SairiHost] DuaCincin API mati (kode {api_proc.returncode}), menyalakan ulang...", flush=True)
                time.sleep(2)
                api_proc = subprocess.Popen(api_cmd, cwd=cwd)
            time.sleep(5)
        print(f"🛑 [SairiHost] Bot berhenti (kode {bot_proc.returncode}).", flush=True)
    except KeyboardInterrupt:
        handle_exit(None, None)
    finally:
        api_proc.terminate()


if __name__ == "__main__":
    main()
