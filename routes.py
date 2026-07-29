import re
import uuid
import hashlib
import secrets
import threading
from datetime import datetime
from flask import Blueprint, request, jsonify, g
from models import db, User as UserModel
from services.user_service import UserService
from services.token_service import TokenService
from services.email_service import EmailService
from services.google_service import GoogleService
from middleware import require_auth, rate_limit, log_audit_event, build_success_response, build_error_response

auth_bp = Blueprint('auth', __name__)

# Password helpers (thay thế bcrypt - không cần C extension)
def hash_password(password: str) -> str:
    """Hash password with salt using SHA-256."""
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
    return f"{salt}${pwd_hash}"

def verify_password(password: str, stored: str) -> bool:
    """Verify password against stored salt$hash format."""
    try:
        salt, pwd_hash = stored.split('$', 1)
        check = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
        return check == pwd_hash
    except (ValueError, AttributeError):
        return False

# Input validation helpers
def validate_username(username):
    if not username or len(username) < 3 or len(username) > 20:
        return "Username must be between 3 and 20 characters."
    if not re.match(r"^[a-zA-Z0-9_]+$", username):
        return "Username can only contain letters, numbers, and underscores."
    return None

def validate_email(email):
    if not email:
        return "Email is required."
    email_clean = email.strip().lower()
    if not email_clean.endswith("@gmail.com"):
        return "Only Gmail addresses (@gmail.com) are allowed."
    if not re.match(r"^[a-z0-9._%+-]+@gmail\.com$", email_clean):
        return "Invalid email format."
    return None

def validate_password(password):
    if not password or len(password) < 8:
        return "Password must be at least 8 characters."
    return None

# Cookie Helpers
def set_refresh_token_cookie(response, token):
    response.set_cookie(
        'refresh_token', token,
        httponly=True, secure=request.is_secure,
        samesite='Strict', max_age=7 * 24 * 60 * 60
    )

def clear_refresh_token_cookie(response):
    response.delete_cookie('refresh_token', httponly=True, samesite='Strict')

# 1. REGISTER
@auth_bp.route('/register', methods=['POST'])
@rate_limit('auth')
def register():
    data = request.get_json() or {}
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')

    err = validate_username(username) or validate_email(email) or validate_password(password)
    if err:
        return jsonify(build_error_response("VALIDATION_ERROR", err)), 400

    try:
        if UserService.check_username_exists(username):
            return jsonify(build_error_response("USERNAME_EXISTS", "Username already exists.")), 400

        if UserService.check_email_exists(email):
            return jsonify(build_error_response("EMAIL_EXISTS", "Email already exists.")), 400

        password_hash = hash_password(password)

        user = UserService.create_user(
            username=username,
            email=email,
            password_hash=password_hash,
            package='free'
        )

        session = TokenService.create_session(user.id, request.headers.get("User-Agent"), request.remote_addr)
        access_token = TokenService.generate_access_token(user)

        response = jsonify(build_success_response(
            message="Registration successful.",
            accessToken=access_token,
            refreshToken=session.token,
            user=user.to_dict()
        ))
        set_refresh_token_cookie(response, session.token)

        try:
            EmailService.send_welcome_email(
                email=user.email, username=user.username,
                created_at=user.created_at, ip_address=request.remote_addr,
                user_agent=request.headers.get("User-Agent")
            )
        except Exception:
            pass

        return response, 201
    except Exception as e:
        return jsonify(build_error_response("REGISTRATION_FAILED", str(e))), 500

# 2. LOGIN
@auth_bp.route('/login', methods=['POST'])
@rate_limit('auth')
def login():
    data = request.get_json() or {}
    username_or_email = data.get('usernameOrEmail')
    password = data.get('password')

    if not username_or_email or not password:
        return jsonify(build_error_response("VALIDATION_ERROR", "Username/Email and password are required.")), 400

    try:
        user = None
        if "@" in username_or_email:
            try:
                user = UserService.find_by_email(username_or_email)
            except ValueError:
                user = None
        else:
            user = UserService.find_by_username(username_or_email)

        if not user or not user.password_hash:
            return jsonify(build_error_response("INVALID_CREDENTIALS", "Invalid username/email or password.")), 401

        if not verify_password(password, user.password_hash):
            return jsonify(build_error_response("INVALID_CREDENTIALS", "Invalid username/email or password.")), 401

        session = TokenService.create_session(user.id, request.headers.get("User-Agent"), request.remote_addr)
        access_token = TokenService.generate_access_token(user)

        response = jsonify(build_success_response(
            message="Login successful.",
            accessToken=access_token,
            refreshToken=session.token,
            user=user.to_dict()
        ))
        set_refresh_token_cookie(response, session.token)

        return response, 200
    except Exception as e:
        return jsonify(build_error_response("LOGIN_FAILED", str(e))), 500

# 3. GOOGLE OAUTH
@auth_bp.route('/google', methods=['POST'])
@rate_limit('auth')
def login_google():
    data = request.get_json() or {}
    
    # Accept multiple key formats for flexibility
    id_token_str = data.get('idToken') or data.get('id_token') or data.get('credential')
    access_token_str = data.get('accessToken') or data.get('access_token')
    
    print(f"[GOOGLE AUTH] Received keys: {list(data.keys())}")
    print(f"[GOOGLE AUTH] id_token_str: {'present' if id_token_str else 'none'}, access_token_str: {'present' if access_token_str else 'none'}")

    if not id_token_str and not access_token_str:
        return jsonify(build_error_response("VALIDATION_ERROR", "Google ID token or access token is required.")), 400

    try:
        if id_token_str:
            print("[GOOGLE AUTH] Verifying id_token...")
            google_info = GoogleService.verify_id_token(id_token_str)
        else:
            print("[GOOGLE AUTH] Verifying access_token...")
            google_info = GoogleService.verify_access_token(access_token_str)
        
        print(f"[GOOGLE AUTH] User info: sub={google_info.get('sub')}, email={google_info.get('email')}")
        user = UserService.find_by_google_sub(google_info['sub'])

        is_new_user = False
        if not user:
            existing_email_user = UserService.find_by_email(google_info['email'])
            if existing_email_user:
                user = UserService.link_google_account(existing_email_user.id, google_info['sub'])
                if not user.avatar_url or not user.display_name:
                    UserService.update_user_profile(
                        user.id,
                        avatar_url=user.avatar_url or google_info['avatar_url'],
                        display_name=user.display_name or google_info['display_name']
                    )
            else:
                is_new_user = True
                email_prefix = re.sub(r'[^a-zA-Z0-9_]', '', google_info['email'].split('@')[0])
                username_base = email_prefix or 'user'
                final_username = username_base
                suffix = 1
                while UserService.check_username_exists(final_username):
                    final_username = f"{username_base}_{suffix}"
                    suffix += 1

                user = UserService.create_user(
                    username=final_username,
                    email=google_info['email'],
                    google_sub=google_info['sub'],
                    display_name=google_info['display_name'],
                    avatar_url=google_info['avatar_url'],
                    package='free'
                )

        if google_info['email'].lower() == 'soladzpro@gmail.com' and user.role != 'admin':
            user.role = 'admin'
            db.session.commit()

        session = TokenService.create_session(user.id, request.headers.get("User-Agent"), request.remote_addr)
        access_token = TokenService.generate_access_token(user)

        response = jsonify(build_success_response(
            message="Google authentication successful.",
            accessToken=access_token,
            refreshToken=session.token,
            user=user.to_dict()
        ))
        set_refresh_token_cookie(response, session.token)

        if is_new_user:
            try:
                EmailService.send_welcome_email(
                    email=user.email, username=user.username,
                    created_at=user.created_at, ip_address=request.remote_addr,
                    user_agent=request.headers.get("User-Agent")
                )
            except Exception:
                pass

        return response, 200
    except Exception as e:
        return jsonify(build_error_response("GOOGLE_AUTH_FAILED", str(e))), 400

# 4. LOGOUT
@auth_bp.route('/logout', methods=['POST'])
def logout():
    refresh_token = request.cookies.get('refresh_token') or (request.get_json() or {}).get('refreshToken')
    
    if not refresh_token:
        return jsonify(build_error_response("MISSING_TOKEN", "Refresh token is required.")), 400

    try:
        TokenService.revoke_session(refresh_token)
        response = jsonify(build_success_response(message="Logged out successfully."))
        clear_refresh_token_cookie(response)
        return response, 200
    except Exception as e:
        return jsonify({"success": False, "code": "LOGOUT_FAILED", "message": str(e)}), 500

# 5. LOGOUT ALL DEVICES
@auth_bp.route('/logout-all', methods=['POST'])
@require_auth
def logout_all():
    user_id = g.user.get('userId')
    try:
        TokenService.revoke_all_sessions(user_id)
        response = jsonify(build_success_response(message="Logged out from all devices."))
        clear_refresh_token_cookie(response)
        return response, 200
    except Exception as e:
        return jsonify({"success": False, "code": "LOGOUT_FAILED", "message": str(e)}), 500

# 6. REFRESH TOKEN
@auth_bp.route('/refresh', methods=['POST'])
def refresh():
    refresh_token = request.cookies.get('refresh_token') or (request.get_json() or {}).get('refreshToken')

    if not refresh_token:
        return jsonify(build_error_response("MISSING_TOKEN", "Refresh token is required.")), 400

    try:
        access_token, new_refresh_token, _ = TokenService.rotate_session(
            refresh_token,
            request.headers.get("User-Agent"),
            request.remote_addr
        )

        response = jsonify(build_success_response(
            message="Token refreshed successfully.",
            accessToken=access_token,
            refreshToken=new_refresh_token
        ))
        set_refresh_token_cookie(response, new_refresh_token)
        return response, 200
    except Exception as e:
        response = jsonify(build_error_response("SESSION_EXPIRED", str(e)))
        clear_refresh_token_cookie(response)
        return response, 401

# 7. ME
@auth_bp.route('/me', methods=['GET'])
@require_auth
def me():
    user_id = g.user.get('userId')
    user = UserService.find_by_id(user_id)
    if not user:
        return jsonify(build_error_response("USER_NOT_FOUND", "User not found.")), 404
    
    if user.email and user.email.lower() == 'soladzpro@gmail.com' and user.role != 'admin':
        user.role = 'admin'
        db.session.commit()

    return jsonify(build_success_response(message="User profile loaded.", user=user.to_dict())), 200

# 8. VERIFY SESSION
@auth_bp.route('/verify', methods=['POST'])
def verify_session():
    data = request.get_json() or {}
    refresh_token = request.cookies.get('refresh_token') or data.get('refreshToken')
    auth_header = request.headers.get('Authorization', '')

    if auth_header.startswith('Bearer '):
        token = auth_header.split(' ', 1)[1]
        try:
            payload = TokenService.verify_access_token(token)
            user = UserService.find_by_id(payload.get('userId'))
            if not user:
                raise ValueError('User not found.')

            expires_at = payload.get('exp')
            if isinstance(expires_at, (int, float)):
                expires_at = datetime.fromtimestamp(expires_at).isoformat()

            return jsonify(build_success_response(
                message="Access token is valid.", valid=True,
                tokenType="access", expiresAt=expires_at, user=user.to_dict()
            )), 200
        except Exception as e:
            return jsonify(build_error_response("TOKEN_INVALID", str(e), valid=False)), 401

    if not refresh_token:
        return jsonify(build_error_response("MISSING_TOKEN", "Session token is required.", valid=False)), 400

    try:
        session = TokenService.validate_session(refresh_token)
        return jsonify(build_success_response(
            message="Session is valid.", valid=True,
            tokenType="refresh", expiresAt=session.expires_at.isoformat(),
            user=session.user.to_dict()
        )), 200
    except Exception as e:
        return jsonify(build_error_response("SESSION_INVALID", str(e), valid=False)), 401

# 9. CHECK USERNAME
@auth_bp.route('/check-username', methods=['POST'])
def check_username():
    data = request.get_json() or {}
    username = data.get('username')
    if not username:
        return jsonify(build_error_response("VALIDATION_ERROR", "Username is required.")), 400
    exists = UserService.check_username_exists(username)
    return jsonify(build_success_response(message="Username availability checked.", available=not exists)), 200

# 12. CHECK EMAIL
@auth_bp.route('/check-email', methods=['POST'])
def check_email():
    data = request.get_json() or {}
    email = data.get('email')
    if not email:
        return jsonify(build_error_response("VALIDATION_ERROR", "Email is required.")), 400
    try:
        exists = UserService.check_email_exists(email)
        return jsonify(build_success_response(message="Email availability checked.", available=not exists)), 200
    except Exception as e:
        return jsonify(build_error_response("INVALID_EMAIL", str(e))), 400

# 13. UPDATE PROFILE
@auth_bp.route('/me', methods=['PUT'])
@require_auth
def update_profile():
    user_id = g.user.get('userId')
    data = request.get_json() or {}
    username = data.get('username')
    display_name = data.get('display_name')
    avatar_url = data.get('avatar_url')

    try:
        if username:
            err = validate_username(username)
            if err:
                return jsonify(build_error_response("VALIDATION_ERROR", err)), 400
        user = UserService.update_user_profile(user_id, username=username, display_name=display_name, avatar_url=avatar_url)
        return jsonify(build_success_response(message="Profile updated successfully.", user=user.to_dict())), 200
    except Exception as e:
        return jsonify(build_error_response("UPDATE_FAILED", str(e))), 400

# 14. CHANGE PASSWORD
@auth_bp.route('/change-password', methods=['POST'])
@require_auth
def change_password():
    user_id = g.user.get('userId')
    data = request.get_json() or {}
    current_password = data.get('currentPassword')
    new_password = data.get('newPassword')

    if not current_password or not new_password:
        return jsonify(build_error_response("VALIDATION_ERROR", "Current password and new password are required.")), 400

    err = validate_password(new_password)
    if err:
        return jsonify(build_error_response("VALIDATION_ERROR", err)), 400

    try:
        user = UserService.find_by_id(user_id)
        if not user or not user.password_hash:
            return jsonify(build_error_response("INVALID_CREDENTIALS", "Password change not available for this account.")), 400

        if not verify_password(current_password, user.password_hash):
            return jsonify(build_error_response("WRONG_PASSWORD", "Current password is incorrect.")), 401

        user.password_hash = hash_password(new_password)
        db.session.commit()

        TokenService.revoke_all_sessions(user_id)
        session = TokenService.create_session(user_id, request.headers.get("User-Agent"), request.remote_addr)
        access_token = TokenService.generate_access_token(user)

        response = jsonify(build_success_response(
            message="Password changed successfully. Please sign in again.",
            accessToken=access_token, refreshToken=session.token
        ))
        set_refresh_token_cookie(response, session.token)
        return response, 200
    except Exception as e:
        return jsonify(build_error_response("CHANGE_PASSWORD_FAILED", str(e))), 500

# 15. Theme Preference
@auth_bp.route('/theme', methods=['GET', 'PUT'])
@require_auth
def handle_theme():
    user_id = g.user.get('userId')
    user = UserService.find_by_id(user_id)
    if not user:
        return jsonify(build_error_response("USER_NOT_FOUND", "User not found.")), 404

    if request.method == 'GET':
        return jsonify(build_success_response(
            message="Theme preference loaded.",
            theme=user.theme_preference or 'white'
        )), 200

    if request.method == 'PUT':
        data = request.get_json() or {}
        theme = data.get('theme', '').strip()
        valid_themes = ['blue', 'darkgreen', 'yellowgreen', 'lightgreen', 'olive', 'black', 'white', 'skyblue', 'rose', 'blush', 'beige', 'steelblue', 'lavender', 'coral']
        if theme not in valid_themes:
            return jsonify(build_error_response("INVALID_THEME", f"Invalid theme. Valid: {', '.join(valid_themes)}")), 400

        user.theme_preference = theme
        db.session.commit()
        
        return jsonify(build_success_response(
            message="Theme preference saved.",
            theme=theme
        )), 200