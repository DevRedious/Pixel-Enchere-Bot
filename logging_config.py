"""
Configuration avancée du logging pour Atlant'ARK Bot
"""
import logging
import logging.handlers
import os
from datetime import datetime

def setup_logging():
    """Configure le système de logging avancé"""
    
    # Créer le dossier de logs s'il n'existe pas
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
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
    file_handler = logging.handlers.RotatingFileHandler(
        filename=f"{log_dir}/atlantark_bot.log",
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(log_format)
    
    # Handler pour les erreurs uniquement
    error_handler = logging.handlers.RotatingFileHandler(
        filename=f"{log_dir}/atlantark_errors.log",
        maxBytes=5*1024*1024,   # 5MB
        backupCount=3,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(log_format)
    
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
    root_logger.addHandler(file_handler)
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
    
    return {
        'bot': logging.getLogger('AtlantArkBot'),
        'api': logging.getLogger('AtlantArkAPI'),
        'commands': commands_logger,
        'discord': discord_logger
    }

def log_command_usage(user_id: int, command_name: str, success: bool = True, error: str = None):
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

def log_auction_event(event_type: str, user_id: int, details: str = ""):
    """Log les événements d'enchères"""
    auction_logger = logging.getLogger('auctions')
    auction_logger.info(f"{event_type} | User: {user_id} | {details}")

def log_economy_transaction(from_user: int, to_user: int, amount: int, transaction_type: str):
    """Log les transactions économiques"""
    economy_logger = logging.getLogger('economy')
    economy_logger.info(f"TRANSACTION | From: {from_user} | To: {to_user} | Amount: {amount} | Type: {transaction_type}")