"""
Configuration avancée du logging pour Atlant'ARK Bot
"""
import logging
import logging.handlers
import os
from datetime import datetime
from typing import Dict, Optional

def setup_logging() -> Dict[str, logging.Logger]:
    """Configure le système de logging avancé"""
    
    # Créer le dossier de logs s'il n'existe pas
    log_dir = "logs"
    try:
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
    except OSError as e:
        print(f"⚠️ Impossible de créer le dossier logs: {e}")
        log_dir = "."  # Fallback vers le répertoire courant
    
    # Configuration du format des logs
    log_format = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)-15s | %(funcName)-20s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Logger principal
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Handler pour la console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(log_format)
    
    # Handler pour le fichier principal (avec rotation)
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            filename=f"{log_dir}/atlantark_bot.log",
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(log_format)
    except (OSError, PermissionError) as e:
        print(f"⚠️ Impossible de créer le fichier de log principal: {e}")
        file_handler = None
    
    # Handler pour les erreurs uniquement
    try:
        error_handler = logging.handlers.RotatingFileHandler(
            filename=f"{log_dir}/atlantark_errors.log",
            maxBytes=5*1024*1024,   # 5MB
            backupCount=3,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(log_format)
    except (OSError, PermissionError) as e:
        print(f"⚠️ Impossible de créer le fichier de log d'erreurs: {e}")
        error_handler = None
    
    # Handler pour les événements Discord (debug)
    discord_handler = logging.handlers.RotatingFileHandler(
        filename=f"{log_dir}/discord_events.log",
        maxBytes=10*1024*1024,  # 10MB
        backupCount=3,
        encoding='utf-8'
    )
    discord_handler.setLevel(logging.DEBUG)
    discord_handler.setFormatter(log_format)
    
    # Ajouter les handlers
    root_logger.addHandler(console_handler)
    if file_handler:
        root_logger.addHandler(file_handler)
    if error_handler:
        root_logger.addHandler(error_handler)
    
    # Logger spécifique pour Discord
    discord_logger = logging.getLogger('discord')
    discord_logger.addHandler(discord_handler)
    discord_logger.setLevel(logging.WARNING)  # Réduire le bruit de discord.py
    
    # Logger pour les commandes
    commands_logger = logging.getLogger('commands')
    commands_handler = logging.handlers.RotatingFileHandler(
        filename=f"{log_dir}/commands.log",
        maxBytes=5*1024*1024,
        backupCount=2,
        encoding='utf-8'
    )
    commands_handler.setFormatter(log_format)
    commands_logger.addHandler(commands_handler)
    
    # Logger pour les enchères
    auctions_logger = logging.getLogger('auctions')
    auctions_handler = logging.handlers.RotatingFileHandler(
        filename=f"{log_dir}/auctions.log",
        maxBytes=5*1024*1024,
        backupCount=2,
        encoding='utf-8'
    )
    auctions_handler.setFormatter(log_format)
    auctions_logger.addHandler(auctions_handler)
    
    # Logger pour l'économie
    economy_logger = logging.getLogger('economy')
    economy_handler = logging.handlers.RotatingFileHandler(
        filename=f"{log_dir}/economy.log",
        maxBytes=5*1024*1024,
        backupCount=2,
        encoding='utf-8'
    )
    economy_handler.setFormatter(log_format)
    economy_logger.addHandler(economy_handler)
    
    return {
        'bot': logging.getLogger('AtlantArkBot'),
        'api': logging.getLogger('AtlantArkAPI'),
        'commands': commands_logger,
        'discord': discord_logger,
        'auctions': auctions_logger,
        'economy': economy_logger
    }

def log_command_usage(user_id: int, command_name: str, success: bool = True, error: Optional[str] = None) -> None:
    """Log l'utilisation d'une commande"""
    commands_logger = logging.getLogger('commands')
    
    status = "SUCCESS" if success else "ERROR"
    message = f"User {user_id} | Command: {command_name} | Status: {status}"
    
    if error:
        message += f" | Error: {error}"
    
    if success:
        commands_logger.info(message)
    else:
        commands_logger.error(message)

def log_auction_event(event_type: str, user_id: int, details: str = "") -> None:
    """Log les événements d'enchères"""
    auction_logger = logging.getLogger('auctions')
    auction_logger.info(f"{event_type} | User: {user_id} | {details}")

def log_economy_transaction(from_user: int, to_user: int, amount: int, transaction_type: str) -> None:
    """Log les transactions économiques"""
    economy_logger = logging.getLogger('economy')
    economy_logger.info(f"TRANSACTION | From: {from_user} | To: {to_user} | Amount: {amount} | Type: {transaction_type}")

def validate_logging_config() -> bool:
    """Valide que la configuration de logging fonctionne correctement"""
    try:
        loggers = setup_logging()
        
        # Test basique de chaque logger
        for name, logger in loggers.items():
            logger.info(f"Logger {name} initialisé avec succès")
        
        return True
    except Exception as e:
        print(f"❌ Erreur lors de la validation du logging: {e}")
        return False