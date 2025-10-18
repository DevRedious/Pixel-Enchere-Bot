import os
import aiomysql
import httpx
import secrets
import logging
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, Dict, Any
import jwt
from urllib.parse import urlencode

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s'
)
logger = logging.getLogger('AtlantArkAPI')

app = FastAPI(title="Atlant-Ark API", version="2.1.0")

# Configuration Discord OAuth2 - GARDÉE IDENTIQUE
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "https://atlantark-token.up.railway.app/auth/callback")  # MÊME URL
JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_urlsafe(32))
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://devredious.github.io/atlant-ark-site/")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID", "1339531996422078526")

# CORS - GARDÉ IDENTIQUE
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://devredious.github.io",
        "https://devredious.github.io/",
        "https://devredious.github.io/atlant-ark-site",
        "https://devredious.github.io/atlant-ark-site/",
        "http://localhost:3000",
        "http://127.0.0.1:3000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================
# AMÉLIORATIONS - Pool de connexions DB
# =============================================

class DatabasePool:
    def __init__(self):
        self.pool = None
    
    async def initialize(self):
        DATABASE_URL = os.getenv("DATABASE_URL")
        if not DATABASE_URL:
            raise HTTPException(status_code=500, detail="Database URL not configured")
        
        # Parse MySQL URL
        from urllib.parse import urlparse
        parsed = urlparse(DATABASE_URL)
        
        self.pool = await aiomysql.create_pool(
            host=parsed.hostname,
            port=parsed.port or 3306,
            user=parsed.username,
            password=parsed.password,
            db=parsed.path[1:],  # Remove leading slash
            minsize=5,
            maxsize=20,
            autocommit=True
        )
        logger.info("MySQL pool initialized")
    
    async def get_connection(self):
        if not self.pool:
            await self.initialize()
        return self.pool.acquire()

# Instance globale du pool
db_pool = DatabasePool()

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Démarrage de l'API Atlant-Ark")
    await db_pool.initialize()

@app.on_event("shutdown")
async def shutdown_event():
    if db_pool.pool:
        await db_pool.pool.close()
        logger.info("Database pool fermé")

# =============================================
# EXCEPTIONS AMÉLIORÉES
# =============================================

class AuthenticationError(HTTPException):
    def __init__(self, detail: str = "Authentication failed"):
        super().__init__(status_code=401, detail=detail)

class ValidationError(HTTPException):
    def __init__(self, detail: str = "Validation failed"):
        super().__init__(status_code=400, detail=detail)

# =============================================
# MIDDLEWARE DE SÉCURITÉ AMÉLIORÉ
# =============================================

from starlette.middleware.base import BaseHTTPMiddleware
import time

class ImprovedSecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.rate_limit_storage = {}
        
    async def dispatch(self, request: Request, call_next):
        # Rate limiting amélioré
        client_ip = request.client.host
        current_time = time.time()
        
        if client_ip not in self.rate_limit_storage:
            self.rate_limit_storage[client_ip] = []
        
        # Nettoyer les anciennes requêtes
        self.rate_limit_storage[client_ip] = [
            timestamp for timestamp in self.rate_limit_storage[client_ip]
            if current_time - timestamp < 60
        ]
        
        if len(self.rate_limit_storage[client_ip]) >= 120:  # Plus permissif
            return JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded", "retry_after": 60},
                headers={"Retry-After": "60"}
            )
        
        self.rate_limit_storage[client_ip].append(current_time)
        
        # Headers de sécurité
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        return response

app.add_middleware(ImprovedSecurityMiddleware)

# =============================================
# HELPERS DE BASE DE DONNÉES AMÉLIORÉS
# =============================================

async def execute_db_query(query: str, *args):
    """Execute database query with pool"""
    async with await db_pool.get_connection() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(query, args)
            return cursor.rowcount

async def fetch_db_row(query: str, *args):
    """Fetch single row with pool"""
    async with await db_pool.get_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(query, args)
            return await cursor.fetchone()

async def fetch_db_all(query: str, *args):
    """Fetch all rows with pool"""
    async with await db_pool.get_connection() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(query, args)
            return await cursor.fetchall()

async def fetch_db_val(query: str, *args):
    """Fetch single value with pool"""
    async with await db_pool.get_connection() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(query, args)
            row = await cursor.fetchone()
            return row[0] if row else None

# =============================================
# VARIABLES GLOBALES - GARDÉES IDENTIQUES
# =============================================

bot_instance = None
auctions_data = {
    "active": False,
    "count": 0,
    "total_players": 0,
    "server_uptime": "100%"
}

def set_bot_instance(bot):
    global bot_instance
    bot_instance = bot

def update_auctions_state(active: bool, count: int = 0):
    global auctions_data
    auctions_data["active"] = active
    auctions_data["count"] = count

# =============================================
# GESTIONNAIRE DE TOKENS AMÉLIORÉ
# =============================================

class TokenManager:
    @staticmethod
    def create_access_token(user_data: dict) -> str:
        payload = {
            "discord_id": str(user_data["id"]),
            "username": user_data["username"],
            "avatar": user_data.get("avatar"),
            "type": "access",
            "exp": datetime.utcnow() + timedelta(hours=1),
            "iat": datetime.utcnow()
        }
        return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    @staticmethod
    def create_refresh_token() -> str:
        return secrets.token_urlsafe(32)

    @staticmethod
    def verify_access_token(token: str) -> Optional[dict]:
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            if payload.get("type") != "access":
                return None
            return payload
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            return None

    @staticmethod
    async def save_refresh_token(discord_id: str, refresh_token: str) -> None:
        await execute_db_query("DELETE FROM refresh_tokens WHERE discord_id = %s", int(discord_id))
        await execute_db_query(
            """INSERT INTO refresh_tokens (discord_id, token, expires_at) 
               VALUES (%s, %s, %s)""",
            int(discord_id), refresh_token, datetime.utcnow() + timedelta(days=30)
        )

    @staticmethod
    async def verify_refresh_token(refresh_token: str) -> Optional[str]:
        result = await fetch_db_row(
            """SELECT discord_id FROM refresh_tokens 
               WHERE token = %s AND expires_at > %s""",
            refresh_token, datetime.utcnow()
        )
        return str(result["discord_id"]) if result else None

    @staticmethod
    async def revoke_refresh_token(refresh_token: str) -> None:
        await execute_db_query("DELETE FROM refresh_tokens WHERE token = %s", refresh_token)

# =============================================
# AUTHENTICATION HELPERS - GARDÉS IDENTIQUES
# =============================================

security = HTTPBearer(auto_error=False)

def validate_csrf_token(request: Request) -> bool:
    csrf_cookie = request.cookies.get("csrf_token")
    csrf_header = request.headers.get("X-CSRF-Token")
    return csrf_cookie and csrf_header and csrf_cookie == csrf_header

async def get_current_user(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)) -> Optional[dict]:
    token = None
    
    if "access_token" in request.cookies:
        token = request.cookies.get("access_token")
    elif credentials and credentials.credentials:
        token = credentials.credentials
    
    if not token:
        return None
    
    user_data = TokenManager.verify_access_token(token)
    if not user_data:
        return None
    
    # Enrichir avec les données DB
    try:
        db_user = await fetch_db_row(
            "SELECT ark_name, balance FROM players WHERE discord_id = %s", 
            int(user_data["discord_id"])
        )
        if db_user:
            user_data.update({
                "ark_name": db_user["ark_name"],
                "balance": db_user["balance"]
            })
    except Exception as e:
        logger.error(f"Error enriching user data: {e}")
    
    return user_data

# =============================================
# ROUTES AUTH - URLS GARDÉES IDENTIQUES
# =============================================

@app.get("/auth/discord")  # MÊME URL QUE AVANT
async def discord_auth():
    if not DISCORD_CLIENT_ID:
        raise HTTPException(status_code=500, detail="Discord OAuth2 not configured")
    
    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify email guilds"
    }
    
    discord_url = f"https://discord.com/api/oauth2/authorize?{urlencode(params)}"
    return RedirectResponse(discord_url)

@app.get("/auth/callback")  # MÊME URL QUE AVANT
async def discord_callback(code: str, error: Optional[str] = None):
    if error:
        return RedirectResponse(f"{FRONTEND_URL}?error={error}")
    
    if not code:
        return RedirectResponse(f"{FRONTEND_URL}?error=no_code")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Exchange code for access token
            token_response = await client.post(
                "https://discord.com/api/oauth2/token",
                data={
                    "client_id": DISCORD_CLIENT_ID,
                    "client_secret": DISCORD_CLIENT_SECRET,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": DISCORD_REDIRECT_URI,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            
            if token_response.status_code != 200:
                logger.error(f"Token exchange failed: {token_response.status_code}")
                return RedirectResponse(f"{FRONTEND_URL}?error=token_exchange_failed")
            
            token_data = token_response.json()
            discord_token = token_data["access_token"]
            
            # Get user info
            user_response = await client.get(
                "https://discord.com/api/users/@me",
                headers={"Authorization": f"Bearer {discord_token}"}
            )
            
            if user_response.status_code != 200:
                return RedirectResponse(f"{FRONTEND_URL}?error=user_fetch_failed")
            
            user_data = user_response.json()
            
            # Verify guild membership
            guilds_response = await client.get(
                "https://discord.com/api/users/@me/guilds",
                headers={"Authorization": f"Bearer {discord_token}"}
            )
            
            if guilds_response.status_code == 200:
                guilds = guilds_response.json()
                guild_ids = [g["id"] for g in guilds]
                
                if DISCORD_GUILD_ID not in guild_ids:
                    return RedirectResponse(f"{FRONTEND_URL}?error=not_in_guild")
            
            # Create or update user
            await execute_db_query("""
                INSERT INTO players (discord_id, username, ark_name, balance)
                VALUES (%s, %s, %s, 0)
                ON DUPLICATE KEY UPDATE username = VALUES(username), updated_at = NOW()
            """, int(user_data["id"]), user_data["username"], user_data["username"])
            
            # Create tokens
            access_token = TokenManager.create_access_token(user_data)
            refresh_token = TokenManager.create_refresh_token()
            
            await TokenManager.save_refresh_token(str(user_data["id"]), refresh_token)
            
            # Create response with secure cookies
            response = RedirectResponse(f"{FRONTEND_URL}?auth=success")
            
            response.set_cookie(
                "access_token",
                access_token,
                max_age=3600,
                httponly=True,
                secure=True,
                samesite="strict",
                path="/"
            )
            
            response.set_cookie(
                "refresh_token",
                refresh_token,
                max_age=30*24*3600,
                httponly=True,
                secure=True,
                samesite="strict",
                path="/"
            )
            
            csrf_token = secrets.token_urlsafe(32)
            response.set_cookie(
                "csrf_token",
                csrf_token,
                max_age=30*24*3600,
                httponly=False,
                secure=True,
                samesite="strict"
            )
            
            # GitHub Pages fallback
            if "github.io" in FRONTEND_URL:
                fallback_url = f"{FRONTEND_URL}?access_token={access_token}&refresh_token={refresh_token}"
                return RedirectResponse(fallback_url)
            
            return response
            
    except Exception as e:
        logger.error(f"Auth callback error: {e}")
        return RedirectResponse(f"{FRONTEND_URL}?error=auth_failed")

@app.post("/auth/verify")  # MÊME URL QUE AVANT
async def verify_token(request: Request):
    try:
        body = await request.json()
        token = body.get("access_token") or body.get("token")
        
        if not token:
            raise ValidationError("Access token required")
        
        user_data = TokenManager.verify_access_token(token)
        if not user_data:
            raise AuthenticationError("Invalid or expired token")
        
        return {"valid": True, "user": user_data}
    except Exception as e:
        raise AuthenticationError("Token invalid")

@app.post("/auth/refresh")  # MÊME URL QUE AVANT
async def refresh_access_token(request: Request):
    if not validate_csrf_token(request):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        try:
            body = await request.json()
            refresh_token = body.get("refresh_token")
        except:
            pass
    
    if not refresh_token:
        raise ValidationError("Refresh token required")
    
    discord_id = await TokenManager.verify_refresh_token(refresh_token)
    if not discord_id:
        raise AuthenticationError("Invalid or expired refresh token")
    
    # Get user data
    user_data = await fetch_db_row(
        "SELECT discord_id, username FROM players WHERE discord_id = %s",
        int(discord_id)
    )
    
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Create new tokens
    new_access_token = TokenManager.create_access_token({
        "id": str(user_data["discord_id"]),
        "username": user_data["username"],
        "avatar": None
    })
    new_refresh_token = TokenManager.create_refresh_token()
    
    await TokenManager.revoke_refresh_token(refresh_token)
    await TokenManager.save_refresh_token(discord_id, new_refresh_token)
    
    response = JSONResponse({
        "success": True,
        "message": "Tokens refreshed successfully"
    })
    
    response.set_cookie(
        "access_token",
        new_access_token,
        max_age=3600,
        httponly=True,
        secure=True,
        samesite="strict"
    )
    
    response.set_cookie(
        "refresh_token",
        new_refresh_token,
        max_age=30*24*3600,
        httponly=True,
        secure=True,
        samesite="strict"
    )
    
    return response

@app.post("/auth/logout")  # MÊME URL QUE AVANT
async def logout(request: Request):
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        try:
            body = await request.json()
            refresh_token = body.get("refresh_token")
        except:
            pass
    
    if refresh_token:
        await TokenManager.revoke_refresh_token(refresh_token)
    
    response = JSONResponse({"message": "Logged out successfully"})
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    response.delete_cookie("csrf_token", path="/")
    
    return response

# =============================================
# ROUTES UTILISATEUR - URLS GARDÉES IDENTIQUES
# =============================================

@app.get("/user/profile")  # MÊME URL QUE AVANT
async def get_user_profile(current_user: dict = Depends(get_current_user)):
    if not current_user:
        raise AuthenticationError("Not authenticated")
    
    try:
        discord_id = int(current_user["discord_id"])
        
        user_stats = await fetch_db_row("""
            SELECT ark_name, balance,
                   (SELECT COUNT(*) FROM auction_history WHERE user_id = %s AND won = true) as wins,
                   (SELECT COUNT(*) FROM auction_history WHERE user_id = %s) as total_auctions
            FROM players WHERE discord_id = %s
        """, discord_id)
        
        if not user_stats:
            # Create user if doesn't exist
            await execute_db_query("""
                INSERT IGNORE INTO players (discord_id, username, balance) VALUES (%s, %s, 0)
            """, discord_id, current_user["username"])
            
            user_stats = {"ark_name": None, "balance": 0, "wins": 0, "total_auctions": 0}
        
        # Get rank
        rank = await fetch_db_val("""
            SELECT COUNT(*) + 1 FROM players 
            WHERE balance > %s AND balance > 0
        """, user_stats["balance"])
        
        avatar_url = None
        if current_user.get("avatar"):
            avatar_url = f"https://cdn.discordapp.com/avatars/{discord_id}/{current_user['avatar']}.png"
        
        return {
            "discord_id": current_user["discord_id"],
            "username": current_user["username"],
            "avatar_url": avatar_url,
            "ark_name": user_stats["ark_name"],
            "balance": user_stats["balance"] or 0,
            "auction_wins": user_stats["wins"] or 0,
            "total_auctions": user_stats["total_auctions"] or 0,
            "rank": rank if user_stats["balance"] > 0 else "Non classé"
        }
    except Exception as e:
        logger.error(f"Error getting user profile: {e}")
        raise HTTPException(status_code=500, detail=f"Profile error: {str(e)}")

@app.get("/user/history")  # MÊME URL QUE AVANT
async def get_user_auction_history(current_user: dict = Depends(get_current_user)):
    if not current_user:
        raise AuthenticationError("Not authenticated")
    
    try:
        history = await fetch_db_all("""
            SELECT dino_name, final_price, won, created_at
            FROM auction_history 
            WHERE user_id = %s 
            ORDER BY created_at DESC 
            LIMIT 20
        """, int(current_user["discord_id"]))
        
        return [dict(record) for record in history]
    except Exception as e:
        logger.error(f"Error getting user history: {e}")
        raise HTTPException(status_code=500, detail=f"History error: {str(e)}")

@app.put("/user/ark-name")  # MÊME URL QUE AVANT
async def update_ark_name(request: Request, current_user: dict = Depends(get_current_user)):
    if not current_user:
        raise AuthenticationError("Not authenticated")
    
    try:
        body = await request.json()
        ark_name = body.get("ark_name", "").strip()
        
        if not ark_name or len(ark_name) < 3:
            raise ValidationError("ARK name invalid (min 3 characters)")
        
        await execute_db_query("""
            UPDATE players SET ark_name = %s, updated_at = NOW() 
            WHERE discord_id = %s
        """, ark_name, int(current_user["discord_id"]))
        
        return {"message": "ARK name updated", "ark_name": ark_name}
    except ValidationError:
        raise
    except Exception as e:
        logger.error(f"Error updating ARK name: {e}")
        raise HTTPException(status_code=500, detail=f"Update error: {str(e)}")

# =============================================
# ROUTES AQUALIS - URLS GARDÉES IDENTIQUES
# =============================================

@app.get("/api/user/aqualis")  # MÊME URL QUE AVANT
async def get_user_aqualis(current_user: dict = Depends(get_current_user)):
    try:
        discord_id = current_user["discord_id"]
        
        player_data = await fetch_db_row("""
            SELECT balance, ark_name, username
            FROM players 
            WHERE discord_id = %s
        """, int(discord_id))
        
        if not player_data:
            await execute_db_query("""
                INSERT IGNORE INTO players (discord_id, username, balance)
                VALUES (%s, %s, 0)
            """, int(discord_id), current_user.get("username", "User"))
            
            balance = 0
        else:
            balance = player_data["balance"] or 0
        
        return {
            "balance": balance
        }
        
    except Exception as e:
        logger.error(f"Error getting user aqualis: {e}")
        raise HTTPException(status_code=500, detail="Server error")

# TOUS LES AUTRES ENDPOINTS MANQUANTS

@app.get("/mods")  # GARDÉ IDENTIQUE
def get_mods():
    return [
        "🐉 Primal Fear - Créatures légendaires",
        "✨ Shiny Dinos - Variants colorés rares", 
        "🏗️ Structures Plus - Constructions avancées",
        "🎯 Awesome SpyGlass - Informations détaillées",
        "🔧 Super Structures - Éléments de construction",
        "🌈 Dino Colours - Nouvelles couleurs",
        "📦 Resource Stacks - Empilage amélioré",
        "⚡ Utilities Plus - Outils pratiques"
    ]

@app.get("/api/user/aqualis/test")  # GARDÉ IDENTIQUE
async def get_user_aqualis_test(user_id: str):
    try:
        discord_id = str(user_id)
        
        player_data = await fetch_db_row(
            "SELECT balance FROM players WHERE discord_id = %s",
            int(discord_id)
        )
        
        if not player_data:
            balance = 0
        else:
            balance = player_data["balance"] or 0
        
        return {
            "balance": balance,
            "total_aqualis": balance,
            "test_mode": True
        }
        
    except Exception as e:
        logger.error(f"Error in aqualis test for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Test error: {str(e)}")

@app.get("/api/aqualis/leaderboard")  # GARDÉ IDENTIQUE
async def get_aqualis_leaderboard(limit: int = 10):
    try:
        leaderboard = await fetch_db_all("""
            SELECT 
                ark_name,
                username,
                balance
            FROM players
            WHERE balance > 0
            ORDER BY balance DESC
            LIMIT %s
        """, limit)
        
        result = []
        for i, row in enumerate(leaderboard):
            result.append({
                "rank": i + 1,
                "name": row['ark_name'] or f"Player #{i+1}",
                "aqualis": row['balance'],
                "legacy_balance": row['balance'] or 0
            })
        
        return {
            "leaderboard": result,
            "total_players": len(result)
        }
        
    except Exception as e:
        logger.error(f"Error getting aqualis leaderboard: {e}")
        raise HTTPException(status_code=500, detail="Server error")

@app.get("/api/aqualis/stats")  # GARDÉ IDENTIQUE
async def get_aqualis_stats():
    try:
        discord_stats = await fetch_db_row("""
            SELECT 
                COUNT(*) as total_users,
                SUM(balance) as total_aqualis,
                AVG(balance) as avg_aqualis,
                MAX(balance) as max_aqualis
            FROM players
            WHERE balance > 0
        """)
        
        return {
            "discord": {
                "total_users": discord_stats['total_users'] or 0,
                "total_aqualis": discord_stats['total_aqualis'] or 0,
                "average_aqualis": float(discord_stats['avg_aqualis'] or 0),
                "max_aqualis": discord_stats['max_aqualis'] or 0
            },
            "transfers": {
                "total_transfers": 0,
                "total_amount_transferred": 0,
                "active_users": 0
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting aqualis stats: {e}")
        raise HTTPException(status_code=500, detail="Server error")

# =============================================
# ROUTES PUBLIQUES - GARDÉES IDENTIQUES
# =============================================

@app.get("/")  # GARDÉ IDENTIQUE
def root():
    return {
        "name": "Atlant-Ark API",
        "version": "2.1.0",
        "description": "API pour le serveur ARK Atlant-Ark avec authentification Discord",
        "auth": "Discord OAuth2",
        "endpoints": ["/stats", "/mods", "/auctions", "/players", "/leaderboard", "/auth/discord"]
    }

@app.get("/stats")  # MÊME URL QUE AVANT
async def get_stats():
    try:
        player_count = await fetch_db_val("SELECT COUNT(*) FROM players")
        
        active_auctions = 0
        if bot_instance:
            guild = bot_instance.guilds[0] if bot_instance.guilds else None
            if guild:
                category = guild.get_channel(1414725581773340734)
                if category:
                    active_auctions = len([ch for ch in category.text_channels if "🦖" in ch.name])
        
        return {
            "players_online": f"{active_auctions * 2}",
            "uptime": "99.9%",
            "active_auctions": active_auctions,
            "registered_players": player_count,
            "server_status": "🟢 En ligne",
            "last_update": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail=f"Stats error: {str(e)}")

@app.get("/leaderboard")  # MÊME URL QUE AVANT
async def get_leaderboard():
    try:
        rows = await fetch_db_all("""
            SELECT ark_name, username, balance 
            FROM players 
            WHERE ark_name IS NOT NULL AND balance > 0 
            ORDER BY balance DESC 
            LIMIT 10
        """)
        
        leaderboard = []
        for i, row in enumerate(rows, 1):
            leaderboard.append({
                "rank": i,
                "name": row['ark_name'],
                "balance": row['balance'],
                "medal": "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"#{i}"
            })
            
        return {
            "total": len(leaderboard),
            "leaderboard": leaderboard
        }
    except Exception as e:
        logger.error(f"Error getting leaderboard: {e}")
        raise HTTPException(status_code=500, detail=f"Leaderboard error: {str(e)}")

@app.get("/health")  # MÊME URL QUE AVANT
def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "bot_connected": bot_instance is not None,
        "auth": "Discord OAuth2"
    }

# =============================================
# ERROR HANDLERS AMÉLIORÉS
# =============================================

@app.exception_handler(ValidationError)
async def validation_error_handler(request: Request, exc: ValidationError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "Validation Error", "detail": exc.detail}
    )

@app.exception_handler(AuthenticationError)
async def auth_error_handler(request: Request, exc: AuthenticationError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "Authentication Error", "detail": exc.detail}
    )

@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    logger.error(f"Internal server error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal Server Error", "detail": "Something went wrong"}
    )