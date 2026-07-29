import requests as http_requests
from google.oauth2 import id_token
from google.auth.transport import requests
from config import Config

class GoogleService:
    @staticmethod
    def verify_id_token(id_token_str: str) -> dict:
        """Verify Google id_token (from One Tap)."""
        # Sandbox / Mock Token for testing & local development
        if getattr(Config, 'ENV', 'production') in ("development", "test") and id_token_str.startswith("mock_google_token_"):
            mock_sub = id_token_str.replace("mock_google_token_", "")
            return {
                "sub": f"google_sub_{mock_sub}",
                "email": f"{mock_sub}@gmail.com",
                "display_name": f"Mock User {mock_sub}",
                "avatar_url": f"https://avatar.vercel.sh/{mock_sub}"
            }

        if not Config.GOOGLE_CLIENT_ID:
            raise ValueError("Google OAuth Client ID is not configured.")

        try:
            # Verify the token signature, audience, and issuer
            idinfo = id_token.verify_oauth2_token(
                id_token_str, 
                requests.Request(), 
                Config.GOOGLE_CLIENT_ID
            )

            if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
                raise ValueError("Wrong Google OAuth token issuer.")

            email = idinfo.get('email')
            if not email:
                raise ValueError("Google OAuth token did not contain email.")

            return {
                "sub": idinfo['sub'],
                "email": email,
                "display_name": idinfo.get('name'),
                "avatar_url": idinfo.get('picture')
            }
        except Exception as e:
            raise ValueError(f"Google authentication failed: {str(e)}")

    @staticmethod
    def verify_access_token(access_token: str) -> dict:
        """Verify Google access_token (from Token Client popup).
        Uses Google OAuth2 API to get user info from access_token.
        """
        if not Config.GOOGLE_CLIENT_ID:
            raise ValueError("Google OAuth Client ID is not configured.")

        try:
            # Use Google OAuth2 API to verify access_token and get user info
            resp = http_requests.get(
                'https://www.googleapis.com/oauth2/v3/userinfo',
                headers={'Authorization': f'Bearer {access_token}'},
                timeout=10
            )
            if resp.status_code != 200:
                raise ValueError(f"Google API returned {resp.status_code}: {resp.text}")

            userinfo = resp.json()
            email = userinfo.get('email')
            if not email:
                raise ValueError("Google token did not contain email.")

            return {
                "sub": userinfo.get('sub', ''),
                "email": email,
                "display_name": userinfo.get('name'),
                "avatar_url": userinfo.get('picture')
            }
        except Exception as e:
            raise ValueError(f"Google authentication failed: {str(e)}")

class GoogleUserInfo:
    def __init__(self, sub: str, email: str, display_name: str = None, avatar_url: str = None):
        self.sub = sub
        self.email = email
        self.display_name = display_name
        self.avatar_url = avatar_url