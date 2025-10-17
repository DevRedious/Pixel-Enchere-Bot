# ===== GESTIONNAIRE DE BASE DE DONNÉES OPTIMISÉ =====
import asyncpg
import logging
from typing import Optional, Any, List, Dict
from contextlib import asynccontextmanager

logger = logging.getLogger('DatabaseManager')

class DatabaseManager:
    """Gestionnaire optimisé pour les connexions de base de données"""
    
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
        self._database_url: Optional[str] = None
    
    async def initialize(self, database_url: str, min_size: int = 5, max_size: int = 20):
        """Initialise le pool de connexions"""
        self._database_url = database_url
        try:
            self.pool = await asyncpg.create_pool(
                database_url,
                min_size=min_size,
                max_size=max_size,
                command_timeout=30.0
            )
            logger.info(f"📦 Pool DB initialisé ({min_size}-{max_size} connexions)")
        except Exception as e:
            logger.error(f"❌ Erreur initialisation pool DB: {e}")
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
    
    async def execute(self, query: str, *args) -> str:
        """Exécute une requête"""
        async with self.get_connection() as conn:
            return await conn.execute(query, *args)
    
    async def fetchrow(self, query: str, *args) -> Optional[Dict]:
        """Récupère une seule ligne"""
        async with self.get_connection() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None
    
    async def fetch(self, query: str, *args) -> List[Dict]:
        """Récupère plusieurs lignes"""
        async with self.get_connection() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]
    
    async def fetchval(self, query: str, *args) -> Any:
        """Récupère une seule valeur"""
        async with self.get_connection() as conn:
            return await conn.fetchval(query, *args)
    
    @asynccontextmanager
    async def transaction(self):
        """Context manager pour les transactions"""
        async with self.get_connection() as conn:
            async with conn.transaction():
                yield conn

# Instance globale
db = DatabaseManager()