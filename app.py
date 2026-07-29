"""Flask app - Clerk Auth + Chat Realtime + Sanity Backup/Restore"""
import os
import threading
import time
from flask import Flask, jsonify, send_from_directory, request
from config import Config
from models import db
from middleware import add_cors_headers
from services.database_backup import DatabaseBackupService

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

# SocketIO (chỉ dùng cho local dev, không dùng trên Vercel)
IS_VERCEL = bool(os.environ.get('VERCEL') or os.environ.get('VERCEL_ENV'))
socketio = None
if not IS_VERCEL:
    try:
        from flask_socketio import SocketIO
        socketio = SocketIO(cors_allowed_origins="*", async_mode='threading')
        socketio.init_app(app)
        from socketio_events import register_socketio_events
        register_socketio_events(socketio)
        print("[APP] SocketIO initialized")
    except Exception as e:
        print(f"[APP] SocketIO init skipped: {e}")

# Register blueprints
from routes import auth_bp
from routes_payment import payment_bp
from routes_social import social_bp
app.register_blueprint(auth_bp, url_prefix='/api/auth')
app.register_blueprint(payment_bp, url_prefix='/api')
app.register_blueprint(social_bp, url_prefix='/api')

# CORS
@app.after_request
def after_request(resp):
    return add_cors_headers(resp)

# Frontend
frontend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'frontend')

@app.route('/')
def serve_index():
    return send_from_directory(frontend_dir, 'index.html')

@app.route('/<path:path>')
def serve_frontend(path):
    fp = os.path.join(frontend_dir, path)
    if os.path.isfile(fp):
        return send_from_directory(frontend_dir, path)
    if path in ['login', 'register', 'dashboard', 'docs', 'admin', 'social']:
        return send_from_directory(frontend_dir, f'{path}.html')
    return send_from_directory(frontend_dir, 'index.html')

# Health
@app.route('/health')
def health():
    try:
        with db.engine.connect() as c:
            c.execute(db.text("SELECT 1"))
        return jsonify({"status": "ok", "database": "connected"}), 200
    except:
        return jsonify({"status": "ok", "database": "initializing"}), 200

# Error handler
@app.errorhandler(500)
def handle_error(error):
    return jsonify({"success": False, "code": "INTERNAL_ERROR", "message": "Server error"}), 500

# Lazy DB init + Sanity backup restore on first request
_initialized = False

@app.before_request
def init_db():
    global _initialized
    if _initialized:
        return
    _initialized = True
    
    try:
        db.create_all()
        print("[INIT] Database tables created")
    except Exception as e:
        print(f"[INIT] create_all: {e}")
        return
    
    # Migrations
    try:
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        cols = [c['name'] for c in inspector.get_columns('users')]
        if 'clerk_id' not in cols:
            db.session.execute(db.text('ALTER TABLE users ADD COLUMN clerk_id VARCHAR(255) DEFAULT NULL'))
            db.session.commit()
            print("[MIGRATION] Added clerk_id")
        if 'theme_preference' not in cols:
            db.session.execute(db.text('ALTER TABLE users ADD COLUMN theme_preference VARCHAR(20) DEFAULT NULL'))
            db.session.commit()
            print("[MIGRATION] Added theme_preference")
    except:
        pass
    
    # Restore full database from Sanity backup (project 10)
    try:
        from models import User as U
        if U.query.count() == 0:
            print("[INIT] DB empty, restoring from Sanity backup...")
            restored = DatabaseBackupService.restore_from_backup()
            if restored:
                print("[INIT] Database restored from Sanity backup!")
            else:
                print("[INIT] No backup found, starting fresh")
    except Exception as e:
        print(f"[INIT] Restore skipped: {e}")
    
    # Start periodic backup thread (only non-Vercel)
    if not IS_VERCEL:
        def periodic_backup():
            while True:
                time.sleep(300)
                try:
                    DatabaseBackupService.backup_to_sanity()
                    print("[BACKUP] Periodic backup completed")
                except Exception as e:
                    print(f"[BACKUP] Error: {e}")
        
        t = threading.Thread(target=periodic_backup, daemon=True)
        t.start()
        print("[INIT] Periodic backup thread started (every 5 min)")


if __name__ == '__main__':
    if socketio is not None:
        socketio.run(app, host='0.0.0.0', port=Config.PORT, allow_unsafe_werkzeug=True)
    else:
        app.run(host='0.0.0.0', port=Config.PORT)