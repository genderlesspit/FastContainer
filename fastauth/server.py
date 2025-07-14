import secrets
import threading
import time
from datetime import datetime, timedelta
from functools import cached_property
from pathlib import Path
from typing import Dict, Optional

import uvicorn
from async_property import async_cached_property
from fastapi import FastAPI, Request
from fastapi import HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from loguru import logger as log
from pydantic import BaseModel
from pyzurecli import AzureCLI, AzureCLIAppRegistration
from singleton_decorator import singleton

from thread_manager import ManagedThread

DEBUG = True

from .oauth_token_manager import (
    AccessToken,
    PKCEChallenge, MultiTenantTokenManager, TokenStorage, GraphAPI, ManagedOAuthClient
)


# noinspection PyDeprecation
class UserCache:
    """In-memory user cache - super lightweight"""

    def __init__(self):
        self._users: Dict[str, dict] = {}

    def get_user(self, user_id: str) -> Optional[dict]:
        """Get cached user object"""
        user = self._users.get(user_id)
        if user and datetime.fromisoformat(user["expires_at"]) > datetime.utcnow():
            return user

    def store_user(self, user_id: str, user_data: dict, microsoft_token: AccessToken):
        """Cache user object with Microsoft data"""
        self._users[user_id] = {
            "id": user_id,
            "email": user_data.get("mail") or user_data.get("userPrincipalName", ""),
            "name": user_data.get("displayName", "Unknown User"),
            "profile": user_data,
            "authenticated": True,
            "authenticated_at": datetime.utcnow().isoformat(),
            "expires_at": (datetime.utcnow() + timedelta(hours=8)).isoformat(),
            "microsoft_token_expires": microsoft_token.expires_in,
            # Cache Microsoft data to avoid API calls
            "cached_profile": user_data,
            "has_mail_access": "Mail.Read" in microsoft_token.scope,
            "has_files_access": "Files.Read" in microsoft_token.scope
        }

    def remove_user(self, user_id: str):
        """Remove user from cache"""
        self._users.pop(user_id, None)


# Global user cache
user_cache = UserCache()


# Pydantic models
class SessionExchange(BaseModel):
    session_token: str


class CachedUser(BaseModel):
    id: str
    email: str
    name: str
    profile: dict
    authenticated: bool
    authenticated_at: str
    expires_at: str
    has_mail_access: bool
    has_files_access: bool


templates = Jinja2Templates(directory="templates")


class AuthUrlBuilder:
    """Builds multi-tenant OAuth URLs"""

    def __init__(self, client_id: str, redirect_uri: str = None, verbose: bool = False):
        self.verbose = verbose
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        if self.redirect_uri is None: raise RuntimeError
        if DEBUG or self.verbose: log.success(
            f"{self}: Successfully initialized:\nverbose={self.verbose}\nclient_id={self.client_id}\nredirect={self.redirect_uri}")

    def build_auth_url(self, scopes: str, pkce_challenge: PKCEChallenge, state: str) -> str:
        """Build multi-tenant OAuth URL"""
        endpoint = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"

        params = {
            'client_id': self.client_id,
            'response_type': 'code',
            'redirect_uri': self.redirect_uri,
            'scope': scopes,
            'response_mode': 'query',
            'code_challenge': pkce_challenge.code_challenge,
            'code_challenge_method': pkce_challenge.code_challenge_method,
            'state': state
        }

        query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
        return f"{endpoint}?{query_string}"


# noinspection PyProtectedMember,PyShadowingNames,PyUnusedLocal,PyBroadException,PyMethodMayBeStatic
@singleton
class AuthServer(FastAPI):
    """FastAPI server for multi-tenant OAuth callbacks"""
    verbose = True
    _oauth_client = None
    return_url: str = None

    @cached_property
    def uvicorn_cfg(self) -> uvicorn.Config:
        return uvicorn.Config(
            app=self,
            host=self.host,
            port=self.port,
            # reload=True,
            # log_config=,
        )

    @cached_property
    def thread(self) -> threading.Thread:  # type: ignore
        def proc(self):
            if self.verbose: log.info(f"[{self}]: Launching OAuth Server on {self.host}:{self.port}")
            server = uvicorn.Server(config=self.uvicorn_cfg)
            server.run()

        return ManagedThread(proc, self)

    @cached_property
    def path(self):
        return Path.cwd()

    @cached_property
    def url(self):
        return f"http://{self.host}:{self.port}"

    @cached_property
    def callback_url(self):
        return f"http://{self.host}:{self.port}/callback"

    @async_cached_property
    async def azure_cli(self) -> AzureCLI:
        return await AzureCLI.__async_init__(self.path)

    @async_cached_property
    async def app_registration(self) -> AzureCLIAppRegistration:
        azure_cli = await self.azure_cli
        return await azure_cli.app_registration

    @async_cached_property
    async def client_id(self) -> str:
        app_registration = await self.app_registration
        return await app_registration.client_id

    @async_cached_property
    async def oauth_client(self) -> ManagedOAuthClient:
        """Create multi-tenant OAuth client - shared instance"""
        if not self._oauth_client:
            client_id = await self.client_id
            # azure_cli = await self.azure_cli

            token_manager = MultiTenantTokenManager(client_id, self.callback_url)
            token_storage = TokenStorage()
            graph_api = GraphAPI()

            self._oauth_client = ManagedOAuthClient(token_manager, token_storage, graph_api)
            log.debug(f"[{self}]: ✅ Created OAuth client instance")

        return self._oauth_client

    @async_cached_property
    async def auth_url_builder(self) -> AuthUrlBuilder:
        client_id = await self.client_id
        return AuthUrlBuilder(client_id, self.callback_url)

    def __init__(self, return_url: str = None):
        super().__init__()
        self.host = "localhost"
        self.port = 3000
        self.return_url = return_url

        @self.get("/")
        async def start_auth(request: Request):
            """Start multi-tenant OAuth flow"""
            try:
                state = secrets.token_urlsafe(32)
                oauth_client: ManagedOAuthClient = await self.oauth_client
                pkce_challenge = oauth_client.token_manager.create_pkce_challenge(state)

                auth_url_builder = await self.auth_url_builder
                auth_url = auth_url_builder.build_auth_url(
                    scopes="User.Read Mail.Read Files.Read offline_access",
                    pkce_challenge=pkce_challenge,
                    state=state
                )

                log.debug(f"[{self}]: 🔐 Starting OAuth flow with state: {state[:8]}...")
                log.debug(f"[{self}]: 🔗 Auth URL: {auth_url}")
                return RedirectResponse(auth_url)

            except Exception as e:
                # log.debug(f"[{self}]: ❌ Error starting auth: {e}")
                raise RuntimeError(e)
                # return HTMLResponse(f"<h1>Error starting auth: {str(e)}</h1>", status_code=500)

        @self.get("/callback")
        async def callback(request: Request):
            """Handle OAuth callback"""
            query_params = dict(request.query_params)
            auth_code = query_params.get('code')
            state = query_params.get('state')
            error = query_params.get('error')

            log.debug(f"[{self}]: 🔄 Callback received - State: {state[:8] if state else 'None'}...")
            log.debug(f"[{self}]: 🔑 Auth code: {auth_code[:20] if auth_code else 'None'}...")

            if error:
                return self._error_response(request, error, query_params.get('error_description'))

            if not auth_code:
                return self._error_response(request, "No authorization code received")

            if not state:
                return self._error_response(request, "No state parameter received")

            try:
                oauth_client = await self.oauth_client

                # Debug: Check if PKCE challenge exists
                pkce_challenge = oauth_client.token_manager.consume_pkce_challenge(state)
                log.debug(f"[{self}]: 🔍 PKCE challenge found: {pkce_challenge is not None}")

                if not pkce_challenge:
                    # Debug: Show available states
                    available_states = list(oauth_client.token_manager._pkce_challenges.keys())
                    log.debug(f"[{self}]: 🔍 Available states: {[s[:8] for s in available_states]}")
                    return self._error_response(request, f"Invalid state parameter", "Received: {state[:8]}...")

                token = await oauth_client.authenticate_with_code(
                    auth_code,
                    scopes="User.Read Mail.Read Files.Read offline_access",
                    pkce_verifier=pkce_challenge.code_verifier
                )

                # Get user info via CLI
                user_data = await oauth_client.get_user_data("profile")
                user_display = user_data.get('displayName', 'User')
                user_email = user_data.get('mail') or user_data.get('userPrincipalName', 'No email')

                try:
                    if self.return_url is not None:
                        log.debug(f"{self}: Found return url! Redirecting to {return_url}!")
                        return RedirectResponse(return_url)
                except Exception:
                    pass

                return self._success_response(request, token, user_display, user_email)

            except Exception as e:
                log.debug(f"[{self}]: ❌ Callback error: {e}")
                return self._error_response(request, f"Authentication failed: {str(e)}")

        @self.get("/debug")
        async def debug(request: Request):
            """Debug endpoint to check PKCE challenges"""
            try:
                oauth_client = await self.oauth_client
                challenges = oauth_client.token_manager._pkce_challenges

                debug_info = {
                    "stored_challenges": len(challenges),
                    "challenge_states": [state[:8] + "..." for state in challenges.keys()]
                }

                return debug_info
            except Exception as e:
                return {"error": str(e)}

        @self.get("/profile")
        async def get_profile():
            """Get user profile via Azure CLI"""
            return await self._get_user_data("profile")

        @self.get("/emails")
        async def get_emails():
            """Get user emails via Azure CLI"""
            return await self._get_user_data("emails")

        @self.get("/files")
        async def get_files():
            """Get user files via Azure CLI"""
            return await self._get_user_data("files")

        @self.get("/dashboard")
        async def dashboard(request: Request):
            """User dashboard with all data"""
            try:
                oauth_client = await self.oauth_client

                profile = await oauth_client.get_user_data("profile")
                emails = await oauth_client.get_user_data("emails")
                files = await oauth_client.get_user_data("files")

                return templates.TemplateResponse("dashboard.html", {
                    "request": request,
                    "user_display_name": "null",
                    "user_email": "null",
                    "profile_json": profile,
                    "emails_json": emails,
                    "files_json": files
                })

            except Exception as e:
                return HTMLResponse(f"<h1>Error: {str(e)}</h1>", status_code=500)

        @self.get("/logout")
        async def logout(request):
            """Logout and clear tokens"""
            oauth_client = await self.oauth_client
            await oauth_client.logout()

            return HTMLResponse("""
            <html>
            <body style="font-family: Arial; margin: 40px;">
                <h1>✅ Logged Out Successfully!</h1>
                <p>Your tokens have been cleared.</p>
                <a href="/">Login Again</a>
            </body>
            </html>
            """)

        @self.get("/admin-consent")
        async def admin_consent(request: Request):
            """Show admin consent URL"""
            app_registration = await self.app_registration
            consent_url = await app_registration.generate_admin_consent_url()

            return templates.TemplateResponse("admin-consent.html", {
                "request": request,
                "admin_consent_url": consent_url,
            })

        @self.post("/api/exchange", response_model=CachedUser)
        async def exchange_session_for_user(request: SessionExchange):
            """
            SUPER LIGHTWEIGHT: FastAPI session -> cached user object
            If not authenticated, returns redirect to OAuth flow
            """
            try:
                # Extract user ID from session token (simplified - adjust for your session format)
                # For demo: assume session_token contains user identifier
                user_id = self._extract_user_id_from_session(request.session_token)

                # Check if user is cached and valid
                cached_user = user_cache.get_user(user_id)
                if cached_user:
                    log.debug(f"✅ Returning cached user: {user_id}")
                    return CachedUser(**cached_user)

                # User not cached or expired - check if OAuth is available
                oauth_client = await self.oauth_client
                microsoft_token = await oauth_client.get_valid_token()

                if not microsoft_token:
                    # No OAuth token - trigger OAuth flow
                    log.debug(f"🔐 No OAuth token for {user_id}, triggering OAuth flow")
                    raise HTTPException(
                        status_code=302,
                        detail="OAuth required",
                        headers={"Location": "/"}  # Redirect to OAuth flow
                    )

                # Fetch user data and cache it
                log.debug(f"📥 Fetching and caching user data for: {user_id}")
                user_data = await oauth_client.get_user_data("profile")

                # Cache the user
                actual_user_id = user_data.get("userPrincipalName") or user_data.get("mail") or user_id
                user_cache.store_user(actual_user_id, user_data, microsoft_token)

                # Return cached user
                cached_user = user_cache.get_user(actual_user_id)
                return CachedUser(**cached_user)

            except HTTPException:
                raise  # Re-raise HTTP exceptions (like redirects)
            except Exception as e:
                log.error(f"❌ Exchange error: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"User exchange failed: {str(e)}"
                )

        @self.get("/api/user/{user_id}", response_model=CachedUser)
        async def get_cached_user(user_id: str):
            """Get cached user by ID - no external API calls"""
            cached_user = user_cache.get_user(user_id)
            if not cached_user:
                raise HTTPException(status_code=404, detail="User not found or expired")

            return CachedUser(**cached_user)

        @self.delete("/api/user/{user_id}")
        async def logout_user(user_id: str):
            """Remove user from cache (logout)"""
            user_cache.remove_user(user_id)
            return {"status": "logged_out", "user_id": user_id}

        @self.get("/api/users")
        async def list_cached_users():
            """List all cached users (admin endpoint)"""
            return {
                "cached_users": len(user_cache._users),
                "users": [
                    {
                        "id": user["id"],
                        "name": user["name"],
                        "email": user["email"],
                        "authenticated_at": user["authenticated_at"],
                        "expires_at": user["expires_at"]
                    }
                    for user in user_cache._users.values()
                ]
            }

    async def _get_user_data(self, data_type: str):
        """Get user data and return as JSON"""
        try:
            oauth_client = await self.oauth_client
            data = await oauth_client.get_user_data(data_type)
            return data
        except Exception as e:
            return {"error": str(e)}

    def _error_response(self, request: Request, error: str, description: str = None):
        """Generate error response"""
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error_message": error,
            "error_description": description
        })

    def _success_response(self, request: Request, token: AccessToken, user_display: str, user_email: str):
        """Generate success response"""

        return templates.TemplateResponse("success.html", {
            "request": request,
            "user_display_name": user_display,
            "user_email": user_email,
            "token.expires_in": token.expires_in,
            "token.scope": token.scope,
            "refresh_token": token.refresh_token
        })

    def _dashboard_html(self, request: Request, profile: dict, emails: dict, files: dict):
        """Generate dashboard HTML"""
        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "user_display_name": "null",
            "user_email": "null",
            "profile_json": profile,
            "emails_json": emails,
            "files_json": files
        })

    def _extract_user_id_from_session(self, session_token: str) -> str:
        """Extract user ID from session token - implement based on your session format"""
        try:
            import jwt
            payload = jwt.decode(session_token, options={"verify_signature": False}) #type: ignore
            return payload.get("user_id") or payload.get("sub") or payload.get("email")
        except:
            # Fallback: treat as direct user identifier
            return session_token