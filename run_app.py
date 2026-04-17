import os
import sys
import webbrowser
import threading
import time
import shutil
from pathlib import Path
from waitress import serve

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
from core.wsgi import application

def open_browser():
    # Wait for the server to start
    time.sleep(2)
    webbrowser.open("http://127.0.0.1:8000")

def initialize_app():
    if getattr(sys, 'frozen', False):
        # Paths when running as EXE
        bundle_dir = Path(sys._MEIPASS)
        exe_dir = Path(sys.executable).parent
        
        db_source = bundle_dir / "db.sqlite3"
        db_dest = exe_dir / "db.sqlite3"
        
        # Copy database if it doesn't exist in the EXE folder
        if not db_dest.exists() and db_source.exists():
            print(f"Initializing database at {db_dest}")
            shutil.copy2(db_source, db_dest)

if __name__ == "__main__":
    initialize_app()
    
    print("Starting FanJet BMS...")
    print("Server running at http://127.0.0.1:8000")
    print("Close this window to stop the application.")
    
    # Open browser in a separate thread
    threading.Thread(target=open_browser, daemon=True).start()
    
    # Run server
    serve(application, host="127.0.0.1", port=8000)