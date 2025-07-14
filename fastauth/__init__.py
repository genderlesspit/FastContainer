from .server import AuthServer
from .oauth_token_manager import ManagedOAuthClient, MultiTenantTokenManager, TokenStorage, GraphAPI, AccessToken, PKCEChallenge

auto_launch = True
auth_server = AuthServer()
auth_server.thread.start()