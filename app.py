"""Flask app - Chat Realtime + Sanity Backup/Restore"""
import os
import sys
from flask import Flask, jsonify, send_from_directory, request
from config import Config
from models import db
from middleware import add_cors_headers

# Use temp directory for instance path on Vercel (read-only filesystem)
if os.environ.get('VERCEL') or os.environ.get('VERCEL_ENV'):
    import tempfile
    instance_path = tempfile.gettempdir()
else:
    instance_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')

app = Flask(__name__, instance_path=instance_path, instance_relative_config=False)
app.config.from_object(Config)
db.init_app(app)

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

# Lazy DB init on first request
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
        if 'theme_preference' not in cols:
            db.session.execute(db.text('ALTER TABLE users ADD COLUMN theme_preference VARCHAR(20) DEFAULT NULL'))
            db.session.commit()
            print("[MIGRATION] Added theme_preference")
    except:
        pass


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=Config.PORT)