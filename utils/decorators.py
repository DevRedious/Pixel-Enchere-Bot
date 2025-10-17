# ===== DÉCORATEURS POUR SIMPLIFIER LE CODE =====
import functools
import logging
import discord
from typing import Callable, Any

logger = logging.getLogger('Decorators')

def handle_db_errors(func: Callable) -> Callable:
    """Décorateur pour gérer les erreurs de base de données"""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logger.error(f"❌ Erreur DB dans {func.__name__}: {e}")
            # Si c'est une interaction Discord, répondre à l'utilisateur
            if args and hasattr(args[0], 'response'):
                interaction = args[0]
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ Erreur de base de données. Réessayez plus tard.", 
                        ephemeral=True
                    )
            raise
    return wrapper

def require_role(role_name: str):
    """Décorateur pour vérifier qu'un utilisateur a un rôle spécifique"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(interaction: discord.Interaction, *args, **kwargs):
            # Vérifier le rôle
            role = discord.utils.get(interaction.guild.roles, name=role_name)
            if role and role not in interaction.user.roles:
                await interaction.response.send_message(
                    f"❌ Vous devez avoir le rôle {role.mention} pour cette action.",
                    ephemeral=True
                )
                return
            return await func(interaction, *args, **kwargs)
        return wrapper
    return decorator

def admin_only(func: Callable) -> Callable:
    """Décorateur pour les commandes admin uniquement"""
    @functools.wraps(func)
    async def wrapper(interaction: discord.Interaction, *args, **kwargs):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Cette commande est réservée aux administrateurs.",
                ephemeral=True
            )
            return
        return await func(interaction, *args, **kwargs)
    return wrapper

def auctions_open_required(func: Callable) -> Callable:
    """Décorateur pour vérifier que les enchères sont ouvertes"""
    @functools.wraps(func)
    async def wrapper(interaction: discord.Interaction, *args, **kwargs):
        from bot import auctions_open  # Import local pour éviter les dépendances circulaires
        if not auctions_open:
            await interaction.response.send_message(
                "❌ Les enchères sont actuellement fermées.",
                ephemeral=True
            )
            return
        return await func(interaction, *args, **kwargs)
    return wrapper

def log_performance(func: Callable) -> Callable:
    """Décorateur pour mesurer les performances des fonctions"""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        import time
        start_time = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            end_time = time.perf_counter()
            logger.info(f"⚡ {func.__name__} exécuté en {end_time - start_time:.3f}s")
            return result
        except Exception as e:
            end_time = time.perf_counter()
            logger.error(f"❌ {func.__name__} échoué après {end_time - start_time:.3f}s: {e}")
            raise
    return wrapper

def validate_input(**validators):
    """Décorateur pour valider les entrées utilisateur"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            for param_name, validator in validators.items():
                if param_name in kwargs:
                    value = kwargs[param_name]
                    is_valid, error_msg = validator(value)
                    if not is_valid:
                        if args and hasattr(args[0], 'response'):
                            await args[0].response.send_message(f"❌ {error_msg}", ephemeral=True)
                            return
                        else:
                            raise ValueError(error_msg)
            return await func(*args, **kwargs)
        return wrapper
    return decorator

def retry_on_failure(max_retries: int = 3, delay: float = 1.0):
    """Décorateur pour réessayer automatiquement en cas d'échec"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            import asyncio
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(f"⚠️ {func.__name__} échec (tentative {attempt + 1}/{max_retries + 1}): {e}")
                        await asyncio.sleep(delay * (attempt + 1))  # Backoff exponentiel
                    else:
                        logger.error(f"❌ {func.__name__} échec définitif après {max_retries + 1} tentatives")
            
            raise last_exception
        return wrapper
    return decorator