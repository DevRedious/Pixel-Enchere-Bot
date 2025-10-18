# ===== GESTIONNAIRE DE BASE DE DONNÉES OPTIMISÉ =====
import aiomysql
import logging
from typing import Optional, Any, List, Dict
from contextlib import asynccontextmanager
from urllib.parse import urlparse

logger = logging.getLogger('DatabaseManager')

class DatabaseManager:
    """Gestionnaire optimisé pour les connexions de base de données"""
    
    def __init__(self):
        self.pool: Optional[aiomysql.Pool] = None
        self._database_url: Optional[str] = None
    
    async def initialize(self, database_url: str, min_size: int = 5, max_size: int = 20):
        """Initialise le pool de connexions"""
        self._database_url = database_url
        try:
            # Parse MySQL URL: mysql://user:password@host:port/database
            parsed = urlparse(database_url)
            self.pool = await aiomysql.create_pool(
                host=parsed.hostname,
                port=parsed.port or 3306,
                user=parsed.username,
                password=parsed.password,
                db=parsed.path[1:],  # Remove leading slash
                minsize=min_size,
                maxsize=max_size,
                autocommit=True
            )
            logger.info(f"📦 Pool MySQL initialisé ({min_size}-{max_size} connexions)")
        except Exception as e:
            logger.error(f"❌ Erreur initialisation pool MySQL: {e}")
            raise
    
    async def close(self):
        """Ferme le pool de connexions"""
        if self.pool:
            await self.pool.close()
            logger.info("🔒 Pool DB fermé")
    
    @asynccontextmanager
    async def get_connection(self):
        """Context manager pour obtenir une connexion"""
        if not self.pool:
            logger.warning("⚠️ Pool non initialisé, tentative de reconnexion...")
            if self._database_url:
                try:
                    await self.initialize(self._database_url)
                except Exception as e:
                    logger.error(f"❌ Échec reconnexion pool : {e}")
                    raise RuntimeError("Pool de base de données non disponible")
            else:
                raise RuntimeError("Pool de base de données non initialisé")
        
        async with self.pool.acquire() as conn:
            yield conn
    
    async def execute(self, query: str, *args) -> int:
        """Exécute une requête"""
        async with self.get_connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, args)
                return cursor.rowcount
    
    async def fetchrow(self, query: str, *args) -> Optional[Dict]:
        """Récupère une seule ligne"""
        async with self.get_connection() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(query, args)
                return await cursor.fetchone()
    
    async def fetch(self, query: str, *args) -> List[Dict]:
        """Récupère plusieurs lignes"""
        async with self.get_connection() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(query, args)
                return await cursor.fetchall()
    
    async def fetchval(self, query: str, *args) -> Any:
        """Récupère une seule valeur"""
        async with self.get_connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, args)
                row = await cursor.fetchone()
                return row[0] if row else None
    
    @asynccontextmanager
    async def transaction(self):
        """Context manager pour les transactions"""
        async with self.get_connection() as conn:
            try:
                await conn.begin()
                yield conn
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

# Instance globale
db = DatabaseManager()