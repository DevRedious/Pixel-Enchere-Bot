import os
import re
import json
import discord
import threading
import uvicorn
import asyncpg
import httpx
import logging
import hashlib
from api import app, set_bot_instance, update_auctions_state
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import asyncio
from datetime import datetime, timedelta

# Imports des nouveaux modules optimisés
from utils.database import DatabaseManager
from utils.decorators import handle_db_errors, require_role, auctions_open_required, log_performance
from utils.validators import validate_price, validate_level, validate_gender, validate_mutations, validate_dino_name, format_currency
from utils.embeds import EmbedBuilder, quick_success, quick_error, quick_info, quick_warning

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger('AtlantArkBot')

# ------------ CONFIG ------------
ANNOUNCE_CHANNEL_ID = 1339944248589553706     # Salon central
FORUM_CHANNEL_ID = 1428101487828930620         # Forum des enchères (remplace la catégorie)
FORUM_FALLBACK_NAME = "🦖・Enchères"            # Nom du forum si création nécessaire
TICKET_CATEGORY_NAME = "🎫・Tickets Enchères"   # Catégorie pour les tickets tribu
MIN_INCREMENT = 100                            # Pas minimum d'une surenchère
EMOJI_CURRENCY = "<:aqualis:1420798729027321927>"

# Liste des administrateurs du bot (Discord IDs)
BOT_ADMINS = [
    819182965598191637,  # Utilisateur ajouté
]
# --------------------------------

# Validation des variables d'environnement
load_dotenv()
required_env = ["DATABASE_URL", "DISCORD_TOKEN"]
missing_env = [var for var in required_env if not os.getenv(var)]
if missing_env:
    raise RuntimeError(f"❌ Variables d'environnement manquantes : {', '.join(missing_env)}")

DATABASE_URL = os.getenv("DATABASE_URL")
TOKEN = os.getenv("DISCORD_TOKEN")
API_URL = os.getenv("API_URL", "https://atlantark-token.up.railway.app")

# Instance globale du gestionnaire de base de données
db = DatabaseManager()

intents = discord.Intents.default()
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command("help")

auctions_open = False
auctions_message_id = None
tribe_required = True  # Contrôle si l'appartenance à une tribu est obligatoire

# État pour récupération après redémarrage
active_auctions_cache = {}  # {thread_id: auction_data}

# ---------- RÉCUPÉRATION APRÈS REDÉMARRAGE ----------
async def save_active_auction_state(thread_id: int, auction_data: dict):
    """Sauvegarde l'état d'une enchère active en BDD pour récupération"""
    try:
        async with db.get_connection() as conn:
            await conn.execute("""
                INSERT INTO active_auctions (thread_id, auction_data, created_at)
                VALUES ($1, $2, $3)
                ON CONFLICT (thread_id) 
                DO UPDATE SET 
                    auction_data = $2,
                    updated_at = $3
            """, thread_id, json.dumps(auction_data), datetime.utcnow())
            
        active_auctions_cache[thread_id] = auction_data
        logger.info(f"💾 État enchère sauvegardé pour thread {thread_id}")
    except Exception as e:
        logger.error(f"❌ Erreur sauvegarde état enchère {thread_id}: {e}")

async def load_active_auctions_state():
    """Charge toutes les enchères actives depuis la BDD"""
    try:
        async with db.get_connection() as conn:
            rows = await conn.fetch("SELECT thread_id, auction_data FROM active_auctions")
            
        loaded_count = 0
        for row in rows:
            thread_id = row['thread_id']
            auction_data = json.loads(row['auction_data'])
            active_auctions_cache[thread_id] = auction_data
            loaded_count += 1
            
        logger.info(f"📂 {loaded_count} enchères actives chargées depuis la BDD")
        return loaded_count
    except Exception as e:
        logger.error(f"❌ Erreur chargement enchères actives: {e}")
        return 0

async def remove_active_auction_state(thread_id: int):
    """Supprime l'état d'une enchère terminée"""
    try:
        async with db.get_connection() as conn:
            await conn.execute("DELETE FROM active_auctions WHERE thread_id = $1", thread_id)
            
        if thread_id in active_auctions_cache:
            del active_auctions_cache[thread_id]
            
        logger.info(f"🗑️ État enchère supprimé pour thread {thread_id}")
    except Exception as e:
        logger.error(f"❌ Erreur suppression état enchère {thread_id}: {e}")

async def restore_auction_views_on_startup():
    """Restaure les Views sur tous les threads d'enchères actifs après redémarrage"""
    if not FORUM_CHANNEL_ID:
        logger.warning("⚠️ FORUM_CHANNEL_ID non configuré, impossible de restaurer les Views")
        return 0
        
    try:
        forum = bot.get_channel(FORUM_CHANNEL_ID)
        if not forum:
            logger.error("❌ Forum d'enchères introuvable")
            return 0
            
        restored_count = 0
        
        # Parcourir tous les threads actifs du forum
        for thread in forum.threads:
            if not thread.archived and thread.id in active_auctions_cache:
                try:
                    # Récupérer le dernier message avec embed
                    last_message = await get_last_message_with_embed(thread)
                    
                    if last_message and last_message.embeds:
                        # Restaurer la View sur le message d'enchère
                        await last_message.edit(view=BidView())
                        restored_count += 1
                        logger.info(f"🔄 View restaurée sur thread {thread.id} ({thread.name})")
                        
                except Exception as e:
                    logger.error(f"❌ Erreur restauration View thread {thread.id}: {e}")
                    
        logger.info(f"✅ {restored_count} Views d'enchères restaurées après redémarrage")
        return restored_count
        
    except Exception as e:
        logger.error(f"❌ Erreur restauration générale des Views: {e}")
        return 0

# ---------- HELPERS ----------
def set_highest_bid_in_description(desc: str, amount: str, bidder_mention: str) -> str:
    """Met à jour la plus haute enchère dans la description avec identité visible"""
    if not desc:
        return f"🏆 **Plus haute enchère** : **{amount}** {EMOJI_CURRENCY} par {bidder_mention}"
    
    lines = desc.split("\n")
    for i, line in enumerate(lines):
        if "Plus haute enchère" in line or "🏆" in line:
            lines[i] = f"🏆 **Plus haute enchère** : **{amount}** {EMOJI_CURRENCY} par {bidder_mention}"
            break
    else:
        lines.append(f"🏆 **Plus haute enchère** : **{amount}** {EMOJI_CURRENCY} par {bidder_mention}")
    return "\n".join(lines)

def parse_highest_bid_from_description(desc: str):
    """
    Extrait (montant, mention) depuis la ligne 'Plus haute enchère'.
    Format avec mentions directes des participants.
    """
    if not desc:
        return None, None

    # Rechercher le format avec emoji et mention
    m = re.search(
        r"🏆.*?Plus haute enchère.*?:\s*\*\*(\d+)\*\*.*?\s+par\s+(<@!?[0-9]+>)",
        desc,
        flags=re.IGNORECASE
    )
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # Rechercher le format standard avec mention
    m = re.search(
        r"Plus haute enchère\s*:\s*\*\*(\d+)\*\*.*?\s+par\s+(<@!?[0-9]+>)",
        desc,
        flags=re.IGNORECASE
    )
    if m:
        return m.group(1).strip(), m.group(2).strip()
    
    return None, None

def extract_vendor_id_safely(footer_text: str) -> int:
    """Extrait l'ID du vendeur de manière sécurisée"""
    if not footer_text or "vendeur_id:" not in footer_text:
        return None
    
    try:
        parts = footer_text.split("vendeur_id:")
        if len(parts) > 1:
            vendor_part = parts[1].split("|")[0].strip()
            return int(vendor_part)
    except (ValueError, IndexError):
        pass
    return None

def extract_user_id_from_mention(mention: str) -> int:
    """Extrait l'ID utilisateur d'une mention Discord"""
    if not mention:
        return None
    
    match = re.search(r"<@!?(\d+)>", mention)
    return int(match.group(1)) if match else None

# ---------- GESTION DES PERMISSIONS ----------
def is_bot_admin(user_id: int) -> bool:
    """Vérifie si un utilisateur est administrateur du bot"""
    return user_id in BOT_ADMINS

def is_admin(interaction: discord.Interaction) -> bool:
    """Vérifie si un utilisateur est administrateur (bot ou Discord)"""
    # Vérifier admin bot
    if is_bot_admin(interaction.user.id):
        return True
    
    # Vérifier admin Discord
    if interaction.guild and hasattr(interaction.user, 'guild_permissions'):
        if interaction.user.guild_permissions.administrator:
            return True
    
    return False

async def check_admin_permissions(interaction: discord.Interaction) -> bool:
    """Vérifie les permissions administrateur et renvoie True/False"""
    if not is_admin(interaction):
        await interaction.response.send_message(
            "❌ Cette commande nécessite des permissions d'administrateur.", 
            ephemeral=True
        )
        return False
    return True

# Fonctions de rôle supprimées - Contrôle d'accès uniquement par tribus

async def get_last_message_with_embed(channel):
    """Récupère le dernier message avec un embed dans le canal (thread ou channel)"""
    try:
        async for msg in channel.history(limit=10):
            if msg.embeds:
                return msg
    except discord.Forbidden:
        pass
    return None

async def get_all_forum_threads(forum: discord.ForumChannel):
    """Récupère tous les threads d'un forum (actifs et archivés)"""
    all_threads = []
    
    # Threads actifs
    all_threads.extend(forum.threads)
    
    # Threads archivés
    try:
        async for thread in forum.archived_threads(limit=None):
            all_threads.append(thread)
    except discord.Forbidden:
        pass
    
    return all_threads

# ---------- GESTION DES TRIBUS ----------
async def get_user_tribe(user_id: int) -> dict:
    """Récupère la tribu d'un utilisateur"""
    try:
        async with db.get_connection() as conn:
            result = await conn.fetchrow("""
                SELECT t.id, t.name, t.leader_id, tm.role
                FROM tribes t
                JOIN tribe_members tm ON t.id = tm.tribe_id
                WHERE tm.user_id = $1
            """, user_id)
            
            if result:
                return {
                    'id': result['id'],
                    'name': result['name'],
                    'leader_id': result['leader_id'],
                    'role': result['role']
                }
    except Exception as e:
        logger.error(f"❌ Erreur récupération tribu utilisateur {user_id}: {e}")
    return None

async def can_user_act_for_user(acting_user_id: int, target_user_id: int) -> bool:
    """Vérifie si un utilisateur peut agir pour un autre (même tribu)"""
    if acting_user_id == target_user_id:
        return True
        
    try:
        async with db.get_connection() as conn:
            # Vérifier s'ils sont dans la même tribu
            result = await conn.fetchval("""
                SELECT COUNT(*)
                FROM tribe_members tm1
                JOIN tribe_members tm2 ON tm1.tribe_id = tm2.tribe_id
                WHERE tm1.user_id = $1 AND tm2.user_id = $2
            """, acting_user_id, target_user_id)
            
            return result > 0
    except Exception as e:
        logger.error(f"❌ Erreur vérification permission tribu: {e}")
        return False

async def get_tribe_members(tribe_id: int) -> list:
    """Récupère tous les membres d'une tribu"""
    try:
        async with db.get_connection() as conn:
            results = await conn.fetch("""
                SELECT tm.user_id, tm.role, tm.joined_at
                FROM tribe_members tm
                WHERE tm.tribe_id = $1
                ORDER BY tm.role DESC, tm.joined_at ASC
            """, tribe_id)
            
            return [dict(row) for row in results]
    except Exception as e:
        logger.error(f"❌ Erreur récupération membres tribu {tribe_id}: {e}")
        return []

async def get_forum_tags(forum: discord.ForumChannel):
    """Récupère les tags existants du forum (les tags sont pré-créés)"""
    required_tag_names = [
        '♂️ Male', '♀️ Femelle', '💑 Couple', 
        '🧬 Avec muta', '🔹 Sans muta'
    ]
    
    # Log des tags existants pour diagnostic
    logger.info(f"🏷️ Tags disponibles dans {forum.name}: {[tag.name for tag in forum.available_tags]}")
    
    existing_tags = {tag.name: tag for tag in forum.available_tags}
    existing_tags_lower = {tag.name.lower(): tag for tag in forum.available_tags}
    tags_to_use = []
    
    for tag_name in required_tag_names:
        if tag_name in existing_tags:
            tags_to_use.append(existing_tags[tag_name])
        elif tag_name.lower() in existing_tags_lower:
            # Tag existe avec une casse différente
            existing_tag = existing_tags_lower[tag_name.lower()]
            tags_to_use.append(existing_tag)
            logger.info(f"🏷️ Tag trouvé avec casse différente: {existing_tag.name}")
        else:
            logger.warning(f"⚠️ Tag requis '{tag_name}' non trouvé dans le forum")
    
    return {tag.name: tag for tag in tags_to_use}

def validate_price(price_str: str) -> tuple[bool, str, int]:
    """
    Valide un prix. 
    Retourne (is_valid, error_message, price_value)
    """
    try:
        price = int(price_str)
        if price <= 0:
            return False, "Le prix doit être positif.", 0
        if price % 100 != 0:
            return False, "Le prix doit être un multiple de 100 (ex: 1000, 1100, 1200...).", 0
        return True, "", price
    except ValueError:
        return False, "Prix invalide. Veuillez entrer un nombre.", 0
# ------------------------------

# ------------- TRANSACTION VIEW -------------
class TransactionView(discord.ui.View):
    def __init__(self, vendeur_id: int, acheteur_id: int):
        super().__init__(timeout=None)
        self.vendeur_id = vendeur_id
        self.acheteur_id = acheteur_id
        self.vendeur_ok = False
        self.acheteur_ok = False

    @discord.ui.button(label="✅ Paiement reçu", style=discord.ButtonStyle.success, custom_id="paiement_recu")
    async def paiement_recu(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Récupérer les IDs depuis le message embed si nécessaire (pour persistance)
        if not hasattr(self, 'vendeur_id') or not hasattr(self, 'acheteur_id'):
            try:
                embed = interaction.message.embeds[0] if interaction.message.embeds else None
                if embed and embed.footer and embed.footer.text:
                    # Format attendu : "Vendeur: <@123> | Acheteur: <@456>"
                    footer_text = embed.footer.text
                    import re
                    vendeur_match = re.search(r'Vendeur: <@(\d+)>', footer_text)
                    acheteur_match = re.search(r'Acheteur: <@(\d+)>', footer_text)
                    if vendeur_match and acheteur_match:
                        self.vendeur_id = int(vendeur_match.group(1))
                        self.acheteur_id = int(acheteur_match.group(1))
                        self.vendeur_ok = False
                        self.acheteur_ok = False
            except Exception:
                pass
        # Vérifier si l'utilisateur peut agir pour le vendeur (lui-même ou membre de sa tribu)
        can_act = await can_user_act_for_user(interaction.user.id, self.vendeur_id)
        if not can_act:
            await interaction.response.send_message("❌ Seul le vendeur ou un membre de sa tribu peut confirmer le paiement.", ephemeral=True)
            return
            
        self.vendeur_ok = True
        if interaction.user.id == self.vendeur_id:
            await interaction.response.send_message("✅ Paiement confirmé !", ephemeral=True)
        else:
            await interaction.response.send_message(f"✅ Paiement confirmé pour <@{self.vendeur_id}> !", ephemeral=True)
        await self.check_done(interaction)

    @discord.ui.button(label="✅ Dino reçu", style=discord.ButtonStyle.primary, custom_id="dino_recu")
    async def dino_recu(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Récupérer les IDs depuis le message embed si nécessaire (pour persistance)
        if not hasattr(self, 'vendeur_id') or not hasattr(self, 'acheteur_id'):
            try:
                embed = interaction.message.embeds[0] if interaction.message.embeds else None
                if embed and embed.footer and embed.footer.text:
                    # Format attendu : "Vendeur: <@123> | Acheteur: <@456>"
                    footer_text = embed.footer.text
                    import re
                    vendeur_match = re.search(r'Vendeur: <@(\d+)>', footer_text)
                    acheteur_match = re.search(r'Acheteur: <@(\d+)>', footer_text)
                    if vendeur_match and acheteur_match:
                        self.vendeur_id = int(vendeur_match.group(1))
                        self.acheteur_id = int(acheteur_match.group(1))
                        self.vendeur_ok = False
                        self.acheteur_ok = False
            except Exception:
                pass
        
        # Vérifier si l'utilisateur peut agir pour l'acheteur (lui-même ou membre de sa tribu)
        can_act = await can_user_act_for_user(interaction.user.id, self.acheteur_id)
        if not can_act:
            await interaction.response.send_message("❌ Seul l'acheteur ou un membre de sa tribu peut confirmer la réception.", ephemeral=True)
            return
            
        self.acheteur_ok = True
        if interaction.user.id == self.acheteur_id:
            await interaction.response.send_message("✅ Dino confirmé !", ephemeral=True)
        else:
            await interaction.response.send_message(f"✅ Dino confirmé pour <@{self.acheteur_id}> !", ephemeral=True)
        await self.check_done(interaction)

    async def check_done(self, interaction: discord.Interaction):
        if self.vendeur_ok and self.acheteur_ok:
            try:
                # Supprimer l'état de l'enchère active avant suppression
                if hasattr(interaction.channel, 'id'):
                    await remove_active_auction_state(interaction.channel.id)
                
                # Message de confirmation et suppression
                await interaction.channel.send("✅ Transaction validée ! Fermeture du salon dans 5 secondes...")
                await asyncio.sleep(5)
                await interaction.channel.delete()
                
                logger.info(f"�️ Thread {interaction.channel.id} supprimé après transaction complète")
                
            except discord.Forbidden:
                await interaction.channel.send("⚠️ Impossible de supprimer le salon automatiquement.")
            except Exception as e:
                logger.error(f"❌ Erreur lors de la suppression du thread : {e}")
# -------------------------------------------

# ------------- PERSISTENT TRANSACTION VIEW -------------
class PersistentTransactionView(discord.ui.View):
    """Version persistante de TransactionView qui récupère les IDs depuis l'embed"""
    def __init__(self):
        super().__init__(timeout=None)

    def _extract_ids_from_embed(self, interaction: discord.Interaction):
        """Extrait les IDs vendeur/acheteur depuis l'embed du message"""
        try:
            embed = interaction.message.embeds[0] if interaction.message.embeds else None
            if embed and embed.footer and embed.footer.text:
                # Format attendu dans le footer : "Vendeur: <@123> | Acheteur: <@456>"
                footer_text = embed.footer.text
                import re
                vendeur_match = re.search(r'Vendeur: <@(\d+)>', footer_text)
                acheteur_match = re.search(r'Acheteur: <@(\d+)>', footer_text)
                if vendeur_match and acheteur_match:
                    return int(vendeur_match.group(1)), int(acheteur_match.group(1))
        except Exception as e:
            logger.error(f"❌ Erreur extraction IDs embed : {e}")
        return None, None

    @discord.ui.button(label="✅ Paiement reçu", style=discord.ButtonStyle.success, custom_id="persistent_paiement_recu")
    async def paiement_recu(self, interaction: discord.Interaction, button: discord.ui.Button):
        vendeur_id, acheteur_id = self._extract_ids_from_embed(interaction)
        if not vendeur_id or not acheteur_id:
            await interaction.response.send_message("❌ Impossible de récupérer les informations de transaction.", ephemeral=True)
            return
        
        # Créer une TransactionView temporaire pour traiter l'action
        temp_view = TransactionView(vendeur_id, acheteur_id)
        await temp_view.paiement_recu.__func__(temp_view, interaction, button)

    @discord.ui.button(label="✅ Dino reçu", style=discord.ButtonStyle.primary, custom_id="persistent_dino_recu")
    async def dino_recu(self, interaction: discord.Interaction, button: discord.ui.Button):
        vendeur_id, acheteur_id = self._extract_ids_from_embed(interaction)
        if not vendeur_id or not acheteur_id:
            await interaction.response.send_message("❌ Impossible de récupérer les informations de transaction.", ephemeral=True)
            return
        
        # Créer une TransactionView temporaire pour traiter l'action
        temp_view = TransactionView(vendeur_id, acheteur_id)
        await temp_view.dino_recu.__func__(temp_view, interaction, button)

# ------------- TRIBE REQUEST VIEW -------------
class TribeRequestView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # Timeout None pour persistance
    
    @discord.ui.button(label="🏛️ Créer ou rejoindre une tribu", style=discord.ButtonStyle.primary, custom_id="tribe_request")
    async def request_tribe(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            guild = interaction.guild
            if not guild:
                await interaction.response.send_message("❌ Erreur : serveur introuvable.", ephemeral=True)
                return
            
            # Chercher ou créer la catégorie des tickets
            ticket_category = discord.utils.get(guild.categories, name=TICKET_CATEGORY_NAME)
            if not ticket_category:
                try:
                    ticket_category = await guild.create_category(
                        TICKET_CATEGORY_NAME,
                        reason="Catégorie créée automatiquement pour les demandes de tribu"
                    )
                    logger.info(f"📁 Catégorie '{TICKET_CATEGORY_NAME}' créée automatiquement")
                except discord.Forbidden:
                    await interaction.response.send_message("❌ Impossible de créer la catégorie de tickets. Contactez un administrateur.", ephemeral=True)
                    return
            
            # Créer le ticket privé
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
            
            # Ajouter les permissions pour les administrateurs
            for role in guild.roles:
                if role.permissions.administrator:
                    overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            
            # Créer le channel ticket
            ticket_name = f"tribu-{interaction.user.display_name.lower()[:10]}-{interaction.user.id % 1000}"
            ticket_channel = await guild.create_text_channel(
                ticket_name,
                category=ticket_category,
                overwrites=overwrites,
                reason=f"Demande de tribu par {interaction.user}"
            )
            
            # Message dans le ticket
            embed = discord.Embed(
                title="🏛️ Demande d'Accès aux Enchères",
                description=f"**Demandeur :** {interaction.user.mention}\n**ID :** `{interaction.user.id}`",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(
                name="📋 Situation",
                value="Ce joueur souhaite participer aux enchères mais n'est membre d'aucune tribu.",
                inline=False
            )
            
            embed.add_field(
                name="🎯 Actions Possibles",
                value="• Créer une nouvelle tribu pour ce joueur\n• L'ajouter à une tribu existante\n• Lui donner des informations sur les tribus disponibles",
                inline=False
            )
            
            embed.add_field(
                name="🛠️ Commandes Utiles",
                value="`/tribu-create` - Créer une tribu\n`/tribu-add` - Ajouter à une tribu\n`/tribu-list` - Voir les tribus existantes",
                inline=False
            )
            
            embed.set_footer(text="Ticket créé automatiquement")
            
            await ticket_channel.send(
                f"👋 Salut {interaction.user.mention} !\n🛡️ **Staff**, ce joueur souhaite accéder aux enchères.",
                embed=embed
            )
            
            # Réponse à l'utilisateur
            await interaction.response.send_message(
                f"✅ **Ticket créé !**\n"
                f"📝 Un ticket privé a été ouvert : {ticket_channel.mention}\n"
                f"🛡️ **Un administrateur va traiter votre demande** sous peu.\n\n"
                f"💡 **En attendant**, vous pouvez consulter `/tribu-list` pour voir les tribus existantes.",
                ephemeral=True
            )
            
            logger.info(f"🎫 Ticket tribu créé pour {interaction.user} dans {ticket_channel}")
            
        except Exception as e:
            logger.error(f"❌ Erreur création ticket tribu : {e}")
            await interaction.response.send_message("❌ Erreur lors de la création du ticket. Contactez un administrateur.", ephemeral=True)

# ------------- MODALS -------------
class CreateAuctionModal(discord.ui.Modal, title="Créer une annonce"):
    dino_name = discord.ui.TextInput(label="Nom du Dino", placeholder="Ex: T-Rex", max_length=100)
    dino_level = discord.ui.TextInput(label="Niveau (1-2000)", placeholder="Ex: 150", max_length=10)
    gender_mutations = discord.ui.TextInput(label="Sexe et Mutations", placeholder="Ex: Male Muta | Femelle Normal | Couple Oui", max_length=50)
    start_price = discord.ui.TextInput(label="Prix de départ", placeholder="Ex: 2000", max_length=10)
    dino_stats = discord.ui.TextInput(label="Stats / Infos supplémentaires", style=discord.TextStyle.paragraph, required=False, max_length=500)

    @log_performance
    async def on_submit(self, interaction: discord.Interaction):
        # Validation avec les nouvelles fonctions optimisées
        is_valid, error_msg, price_value = validate_price(self.start_price.value)
        if not is_valid:
            await interaction.response.send_message(f"❌ {error_msg}", ephemeral=True)
            return

        is_valid, error_msg, dino_name = validate_dino_name(self.dino_name.value)
        if not is_valid:
            await interaction.response.send_message(f"❌ {error_msg}", ephemeral=True)
            return

        is_valid, error_msg, level = validate_level(self.dino_level.value)
        if not is_valid:
            await interaction.response.send_message(f"❌ {error_msg}", ephemeral=True)
            return

        # Parser le champ combiné sexe et mutations
        gender_mutations_text = self.gender_mutations.value.strip()
        
        # Patterns acceptés: "Male Avec", "Femelle Sans", "Couple Avec", etc.
        parts = gender_mutations_text.split()
        if len(parts) < 2:
            await interaction.response.send_message(
                "❌ Format incorrect. Utilisez: `Male Avec`, `Femelle Sans`, `Couple Avec`, etc.", 
                ephemeral=True
            )
            return
        
        gender_part = parts[0]
        mutations_part = " ".join(parts[1:])  # Au cas où "Avec muta" ou "Sans muta"
        
        is_valid, error_msg, gender = validate_gender(gender_part)
        if not is_valid:
            await interaction.response.send_message(f"❌ Sexe invalide: {error_msg}", ephemeral=True)
            return

        is_valid, error_msg, mutations = validate_mutations(mutations_part)
        if not is_valid:
            await interaction.response.send_message(f"❌ Mutations invalides: {error_msg}", ephemeral=True)
            return

        guild = interaction.guild

        # Vérification des permissions
        if not guild.me.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ Le bot n'a pas les permissions pour créer des salons.", ephemeral=True)
            return

        # Recherche du forum
        forum = guild.get_channel(FORUM_CHANNEL_ID)
        if forum is None or forum.type is not discord.ChannelType.forum:
            # Essayer de trouver par nom
            forum = discord.utils.get(guild.channels, name=FORUM_FALLBACK_NAME, type=discord.ChannelType.forum)
            if forum is None:
                try:
                    forum = await guild.create_forum(FORUM_FALLBACK_NAME)
                except discord.Forbidden:
                    await interaction.response.send_message("❌ Impossible de créer le forum d'enchères.", ephemeral=True)
                    return

        # Création du titre du post avec nom réel
        safe_dino = re.sub(r'[^a-zA-Z0-9\-_\s]', '', dino_name).strip()[:20]
        post_title = f"🦖 {safe_dino} Niv.{level} - {interaction.user.display_name}"

        # Création de l'embed avec vendeur visible
        stats_text = self.dino_stats.value.strip() if self.dino_stats.value else "Aucune information supplémentaire"
        
        # Utiliser l'EmbedBuilder optimisé
        embed = EmbedBuilder.auction_created(
            dino_name=dino_name,
            level=level,
            gender=gender,
            mutations=mutations,
            price=price_value,
            seller=interaction.user.display_name,
            auction_id=interaction.user.id % 9999,
            seller_id=interaction.user.id
        )
        
        # Ajouter les informations détaillées
        if stats_text and stats_text != "Aucune information supplémentaire":
            embed.add_field(name="📋 Informations détaillées", value=stats_text, inline=False)
        
        # Définir la couleur selon les mutations
        embed_color = discord.Color.purple() if mutations == 'Avec muta' else discord.Color.green()
        
        # Déterminer les emojis
        gender_emoji = "♂️" if gender == "Male" else "♀️" if gender == "Femelle" else "💑"
        mutation_emoji = "🧬" if mutations == "Avec muta" else "🔹"
        
        embed.set_footer(text=f"vendeur_id:{interaction.user.id}|level:{level}|gender:{gender}|mutations:{mutations}")

        try:
            # Récupérer ou créer les tags nécessaires
            available_tags = await get_forum_tags(forum)
            
            # Sélectionner les tags appropriés
            selected_tags = []
            gender_tag_name = f"♂️ Male" if gender == "Male" else f"♀️ Femelle" if gender == "Femelle" else f"💑 Couple"
            mutation_tag_name = f"🧬 Avec muta" if mutations == "Avec muta" else f"🔹 Sans muta"
            
            if gender_tag_name in available_tags:
                selected_tags.append(available_tags[gender_tag_name])
            if mutation_tag_name in available_tags:
                selected_tags.append(available_tags[mutation_tag_name])
            
            # Créer le post dans le forum avec les tags
            thread, message = await forum.create_thread(
                name=post_title,
                embed=embed,
                view=BidView(),
                applied_tags=selected_tags[:5]  # Discord limite à 5 tags max
            )
            
            # Message d'instruction avec nom réel
            await thread.send(
                f"📸 **{interaction.user.display_name}**, merci d'envoyer une **image en pièce jointe** dans ce post.\n"
                f"La première image envoyée sera ajoutée à votre annonce.\n"
                f"ℹ️ *Seul le vendeur peut ajouter des images.*"
            )
            
            # Sauvegarder l'état de l'enchère pour récupération après redémarrage
            auction_state = {
                'dino_name': dino_name,
                'seller_id': interaction.user.id,
                'seller_name': interaction.user.display_name,
                'level': level,
                'gender': gender,
                'mutations': mutations,
                'starting_price': price_value,
                'current_price': price_value,
                'current_bidder_id': None,
                'current_bidder_name': None,
                'created_at': datetime.utcnow().isoformat(),
                'message_id': message.id
            }
            
            await save_active_auction_state(thread.id, auction_state)
            
            await interaction.response.send_message(f"✅ Ton annonce a été créée : {thread.mention}", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Impossible de créer le post d'enchère.", ephemeral=True)

class BidModal(discord.ui.Modal, title="Placer une enchère"):
    bid_amount = discord.ui.TextInput(label="Montant de l'enchère", placeholder="Ex: 2500", max_length=10)

    @log_performance
    async def on_submit(self, interaction: discord.Interaction):
        message = interaction.message
        if not message or not message.embeds:
            await interaction.response.send_message(
                embed=quick_error("Erreur", "Impossible de trouver l'annonce à mettre à jour."), 
                ephemeral=True
            )
            return

        embed = message.embeds[0]

        # Validation du prix avec les nouveaux validateurs
        is_valid, error_msg, bid_value = validate_price(self.bid_amount.value)
        if not is_valid:
            await interaction.response.send_message(embed=quick_error("Prix invalide", error_msg), ephemeral=True)
            return

        # Extraction du prix de départ (nouveau format avec emoji)
        start_price = None
        for line in (embed.description or "").split("\n"):
            if "Prix de départ" in line or "💰" in line:
                try:
                    match = re.search(r'\*\*(\d+)\*\*', line)
                    if match:
                        start_price = int(match.group(1))
                except (IndexError, ValueError):
                    pass
                break

        # Vérification du prix de départ
        if start_price and bid_value < start_price:
            await interaction.response.send_message(
                f"❌ Ton enchère doit être ≥ prix de départ ({start_price}{EMOJI_CURRENCY}).",
                ephemeral=True
            )
            return

        # Extraction de la dernière enchère (nouveau format avec emoji)
        last_bid_amount = None
        for line in (embed.description or "").split("\n"):
            if "Plus haute enchère" in line or "🏆" in line:
                try:
                    # Plus robust extraction
                    match = re.search(r'\*\*(\d+)\*\*', line)
                    if match:
                        last_bid_amount = int(match.group(1))
                except (IndexError, ValueError):
                    pass
                break

        # Vérification de l'incrément minimum
        if last_bid_amount is not None and bid_value < last_bid_amount + MIN_INCREMENT:
            await interaction.response.send_message(
                f"❌ Ta surenchère doit être d'au moins +{MIN_INCREMENT} (enchère actuelle {last_bid_amount}{EMOJI_CURRENCY}).",
                ephemeral=True
            )
            return

        # Vérification que l'utilisateur n'enchérit pas sur sa propre annonce
        vendor_id = extract_vendor_id_safely(embed.footer.text if embed.footer else "")
        if vendor_id and vendor_id == interaction.user.id:
            await interaction.response.send_message("❌ Action non autorisée pour cette annonce.", ephemeral=True)
            return

        # Mise à jour de l'embed avec identité visible
        embed.description = set_highest_bid_in_description(
            embed.description or "",
            str(bid_value),
            interaction.user.mention
        )

        # Mise à jour du footer
        footer_text = embed.footer.text or ""
        footer_text = re.sub(r"\s*\|\s*last_bidder_id:[0-9]+", "", footer_text)
        footer_text = re.sub(r"\s*\|\s*last_bid_amount:[^|]+", "", footer_text)
        if footer_text:
            footer_text += f" | last_bidder_id:{interaction.user.id} | last_bid_amount:{bid_value}"
        else:
            footer_text = f"last_bidder_id:{interaction.user.id} | last_bid_amount:{bid_value}"
        embed.set_footer(text=footer_text)

        try:
            # Mettre à jour l'état de l'enchère pour récupération
            if hasattr(interaction, 'channel') and interaction.channel:
                thread_id = interaction.channel.id
                if thread_id in active_auctions_cache:
                    auction_state = active_auctions_cache[thread_id].copy()
                    auction_state['current_price'] = bid_value
                    auction_state['current_bidder_id'] = interaction.user.id
                    auction_state['current_bidder_name'] = interaction.user.display_name
                    auction_state['last_bid_at'] = datetime.utcnow().isoformat()
                    
                    await save_active_auction_state(thread_id, auction_state)
            
            await message.edit(embed=embed, view=BidView())
            await interaction.response.send_message(f"✅ Enchère placée : {bid_value}{EMOJI_CURRENCY}", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Impossible de mettre à jour l'enchère.", ephemeral=True)
# -----------------------------------

# --------------- VIEWS ---------------
class AuctionHubView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        logger.debug("🔧 AuctionHubView initialisée")
                         
    @discord.ui.button(
        label="Créer une annonce", 
        style=discord.ButtonStyle.primary, 
        emoji="📣", 
        custom_id="auctionhub_create"
    )
    async def create_auction(self, interaction: discord.Interaction, button: discord.ui.Button):
        logger.info(f"🎯 Bouton 'Créer une annonce' utilisé par {interaction.user.display_name} ({interaction.user.id})")
        
        if not auctions_open:
            await interaction.response.send_message("❌ Les enchères sont actuellement fermées.", ephemeral=True)
            return
        
        # Vérifier si l'utilisateur est membre d'une tribu (si requis)
        if tribe_required:
            user_tribe = await get_user_tribe(interaction.user.id)
            if not user_tribe:
                embed = discord.Embed(
                    title="🏛️ Tribu Obligatoire",
                    description="**Tu dois être enregistré dans une tribu pour participer aux enchères.**",
                    color=discord.Color.orange()
                )
                embed.add_field(
                    name="🎯 Pourquoi ?",
                    value="• Sécurité des transactions\n• Validation délégué si absent\n• Organisation communautaire",
                    inline=False
                )
                embed.add_field(
                    name="📋 Que faire ?",
                    value="Clique sur le bouton ci-dessous pour créer un ticket privé.\nUn administrateur t'aidera à rejoindre ou créer une tribu.",
                    inline=False
                )
                
                await interaction.response.send_message(
                    embed=embed,
                    view=TribeRequestView(),
                    ephemeral=True
                )
                return
        
        try:
            await interaction.response.send_modal(CreateAuctionModal())
            logger.info(f"✅ Modal CreateAuctionModal ouvert pour {interaction.user.display_name}")
        except discord.InteractionResponded:
            logger.warning(f"⚠️ Interaction déjà répondue pour {interaction.user.display_name}")
        except Exception as e:
            logger.error(f"❌ Erreur ouverture modal : {e}")
            await interaction.response.send_message("❌ Erreur lors de l'ouverture du formulaire.", ephemeral=True)
    
    @discord.ui.button(
        label="ℹ️ Comment ça marche", 
        style=discord.ButtonStyle.secondary, 
        custom_id="auction_info"
    )
    async def auction_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🔨 Système d'Enchères",
            description="Système d'enchères avec identités visibles pour tous les participants.",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="👤 Identités visibles", 
            value="• Vendeurs et enchérisseurs sont identifiables\n• Visibilité complète des participants\n• Historique des enchères public", 
            inline=False
        )
        embed.add_field(
            name="🏆 Fonctionnement", 
            value="• Créez votre annonce avec vos vraies informations\n• Enchérissez de manière ouverte\n• Le gagnant et vendeur finalisent directement", 
            inline=False
        )
        embed.add_field(
            name="✅ Avantages", 
            value="• Visibilité maximale\n• Confiance dans le système\n• Relations directes entre joueurs", 
            inline=False
        )
        embed.add_field(
            name="📝 Format Sexe et Mutations", 
            value="**Sexe :** mâle/m, femelle/f, couple/c, garçon, fille, breeding...\n**Mutations :** avec/oui/muta, sans/non/normal, colored, wild...", 
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

class BidView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        logger.debug("🔧 BidView initialisée")
                         
    @discord.ui.button(
        label="Placer une enchère", 
        style=discord.ButtonStyle.success, 
        emoji="💸", 
        custom_id="bidview_place"
    )
    async def place_bid(self, interaction: discord.Interaction, button: discord.ui.Button):
        logger.info(f"💸 Bouton 'Placer une enchère' utilisé par {interaction.user.display_name} ({interaction.user.id})")
        
        if not auctions_open:
            await interaction.response.send_message("❌ Les enchères sont actuellement fermées.", ephemeral=True)
            return
        
        # Vérifier si l'utilisateur est membre d'une tribu (si requis)
        if tribe_required:
            user_tribe = await get_user_tribe(interaction.user.id)
            if not user_tribe:
                embed = discord.Embed(
                    title="🏛️ Tribu Obligatoire",
                    description="**Tu dois être enregistré dans une tribu pour participer aux enchères.**",
                    color=discord.Color.orange()
                )
                embed.add_field(
                    name="🎯 Pourquoi ?",
                    value="• Sécurité des transactions\n• Validation délégué si absent\n• Organisation communautaire",
                    inline=False
                )
                embed.add_field(
                    name="📋 Que faire ?",
                    value="Clique sur le bouton ci-dessous pour créer un ticket privé.\nUn administrateur t'aidera à rejoindre ou créer une tribu.",
                    inline=False
                )
                
                await interaction.response.send_message(
                    embed=embed,
                    view=TribeRequestView(),
                    ephemeral=True
                )
                return
        
        await interaction.response.send_modal(BidModal())
# ------------------------------------

# --------- SLASH COMMANDS ENCHÈRES ----------
@bot.tree.command(name="début", description="Démarrer une session d'enchères")
@handle_db_errors
@log_performance
async def auctions_start(interaction: discord.Interaction):
    if not await check_admin_permissions(interaction):
        return
    global auctions_open, auctions_message_id
    
    if auctions_open:
        await interaction.response.send_message("⚠️ Les enchères sont déjà ouvertes.", ephemeral=True)
        return
    
    auctions_open = True
    
    # Notifier l'API
    try:
        update_auctions_state(True, 0)
    except Exception as e:
        logger.error(f"Erreur API update: {e}")

    # Message privé pour l'admin (confirmation)
    await interaction.response.send_message("✅ Les enchères sont ouvertes et annoncées au public.", ephemeral=True)

    # Message public dans le salon central
    announce_channel = interaction.guild.get_channel(ANNOUNCE_CHANNEL_ID)
    if announce_channel and isinstance(announce_channel, discord.TextChannel):
        embed = EmbedBuilder.success(
            title="Les enchères sont ouvertes !",
            description="Cliquez sur le bouton ci-dessous pour créer votre annonce."
        )
        try:
            msg = await announce_channel.send("@everyone", embed=embed, view=AuctionHubView())
            auctions_message_id = msg.id
            logger.info(f"📌 Message d'ouverture enregistré avec ID: {auctions_message_id}")
        except discord.Forbidden:
            await interaction.followup.send("⚠️ Impossible d'envoyer le message public.", ephemeral=True)
    else:
        await interaction.followup.send("⚠️ Salon d'annonce introuvable.", ephemeral=True)

    # Mise à jour du statut du bot
    try:
        await bot.change_presence(
            status=discord.Status.online,
            activity=discord.Game("📢 Enchères en cours !")
        )
    except Exception as e:
        logger.error(f"Erreur changement de statut: {e}")





@bot.tree.command(name="fin", description="Clôturer la session d'enchères")
@app_commands.describe(
    lock_threads="Verrouiller les threads d'enchères (empêche les nouveaux messages)"
)
@handle_db_errors
@log_performance
async def auctions_stop(interaction: discord.Interaction, lock_threads: bool = False):
    if not await check_admin_permissions(interaction):
        return
    global auctions_open, auctions_message_id
    
    if not auctions_open:
        await interaction.response.send_message("⚠️ Les enchères sont déjà fermées.", ephemeral=True)
        return
    
    auctions_open = False
    
    # Notifier l'API
    try:
        update_auctions_state(False, 0)
    except Exception as e:
        logger.error(f"Erreur API update: {e}")

    await interaction.response.send_message("Fermeture des enchères en cours...", ephemeral=True)
    guild = interaction.guild

    # Supprimer le message d'ouverture si on a son ID
    if auctions_message_id:
        try:
            announce_channel = guild.get_channel(ANNOUNCE_CHANNEL_ID)
            if announce_channel:
                hub_msg = await announce_channel.fetch_message(auctions_message_id)
                await hub_msg.delete()
                logger.info(f"🗑️ Message d'ouverture {auctions_message_id} supprimé.")
        except Exception as e:
            logger.warning(f"⚠️ Impossible de supprimer le message d'ouverture : {e}")
        finally:
            auctions_message_id = None

    # Recherche du forum
    forum = guild.get_channel(FORUM_CHANNEL_ID)
    if forum is None or forum.type is not discord.ChannelType.forum:
        forum = discord.utils.get(guild.channels, name=FORUM_FALLBACK_NAME, type=discord.ChannelType.forum)
        if forum is None:
            await interaction.followup.send("Aucun forum d'enchères trouvé.", ephemeral=True)
            return

    recap_lines = []

    # Parcourir tous les threads du forum (actifs et archivés)
    all_threads = await get_all_forum_threads(forum)
    for thread in all_threads:
        try:
            msg = await get_last_message_with_embed(thread)
            if not msg or not msg.embeds:
                continue

            embed = msg.embeds[0]
            
            # Extraction sécurisée du vendeur (révélation de l'identité réelle)
            vendeur_id = extract_vendor_id_safely(embed.footer.text if embed.footer else "")
            vendeur_mention = f"<@{vendeur_id}>" if vendeur_id else "vendeur inconnu"

            # Extraction de l'enchère gagnante (peut être anonyme)
            montant, acheteur_info = parse_highest_bid_from_description(embed.description or "")
            
            # Extraction du nom du dino depuis la nouvelle structure
            dino_name = "Dino inconnu"
            for line in (embed.description or "").split("\n"):
                if "**" in line and "Niveau" in line:
                    try:
                        # Format : **T-Rex** - Niveau **150**
                        match = re.search(r'\*\*(.*?)\*\*.*?Niveau.*?\*\*(\d+)\*\*', line)
                        if match:
                            dino_name = f"{match.group(1)} Niv.{match.group(2)}"
                            break
                    except Exception:
                        pass
                elif line.startswith("**") and "Dino" not in line:
                    # Fallback pour extraire juste le nom
                    try:
                        match = re.search(r'\*\*(.*?)\*\*', line)
                        if match:
                            dino_name = match.group(1)
                            break
                    except Exception:
                        pass

            if montant and acheteur_info:
                # Récupérer la vraie identité depuis le footer pour le message final
                footer_text = embed.footer.text if embed.footer else ""
                acheteur_id = None
                acheteur_mention = None
                
                # Extraire l'ID du dernier enchérisseur depuis le footer
                match = re.search(r"last_bidder_id:(\d+)", footer_text)
                if match:
                    acheteur_id = int(match.group(1))
                    acheteur_mention = f"<@{acheteur_id}>"
                
                if acheteur_mention:
                    # Message récapitulatif avec vraie identité
                    recap_lines.append(f"🦖 {dino_name} de {vendeur_mention} → gagné par {acheteur_mention} pour {montant}{EMOJI_CURRENCY}")
                    
                    if acheteur_id and vendeur_id:
                        # Message final avec vraie identité pour la transaction
                        embed = discord.Embed(
                            title="🏆 Enchère Terminée !",
                            description=f"**{acheteur_mention}** a remporté l'enchère !\n\n"
                                      f"💰 **Montant :** {montant}{EMOJI_CURRENCY}\n"
                                      f"👑 **Gagnant :** {acheteur_mention}\n"
                                      f"🏪 **Vendeur :** {vendeur_mention}",
                            color=discord.Color.gold()
                        )
                        embed.set_footer(text=f"Vendeur: {vendeur_mention} | Acheteur: {acheteur_mention}")
                        
                        await thread.send(
                            content=f"{vendeur_mention}, confirme ton paiement.\n{acheteur_mention}, confirme la réception du dino.",
                            embed=embed,
                            view=PersistentTransactionView()
                        )
                    else:
                        await thread.send("⚠️ Erreur dans les données de l'enchère. Vérifiez manuellement.")
                else:
                    recap_lines.append(f"⚠️ {dino_name} de {vendeur_mention} → enchérisseur introuvable")
                    await thread.send("⚠️ Impossible de retrouver l'identité de l'enchérisseur gagnant.")
            else:
                recap_lines.append(f"⚠️ {dino_name} de {vendeur_mention} → aucune enchère valide")
                await thread.send("ℹ️ Aucune surenchère valable détectée sur cette annonce.")

            # Verrouillage optionnel des threads
            if lock_threads:
                try:
                    await thread.edit(locked=True)
                    logger.info(f"🔒 Thread {thread.name} verrouillé")
                except discord.Forbidden:
                    logger.warning(f"⚠️ Impossible de verrouiller {thread.name}")
            else:
                # Les utilisateurs peuvent continuer à discuter après l'enchère
                logger.info(f"💬 Thread {thread.name} laissé ouvert pour discussion")

        except Exception as e:
            logger.error(f"Erreur lors du traitement du thread {thread.name}: {e}")
            try:
                await thread.send(f"⚠️ Erreur lors de la clôture : {e}")
            except Exception:
                pass

    # Envoi du récapitulatif
    announce_channel = guild.get_channel(ANNOUNCE_CHANNEL_ID)
    if announce_channel:
        recap_text = "\n".join(recap_lines) if recap_lines else "Aucun résultat disponible."
        recap_embed = EmbedBuilder.info(
            title="Enchères terminées — Résultats",
            description=recap_text
        )
        recap_embed.color = 0xf1c40f  # Couleur dorée
        try:
            await announce_channel.send("@everyone", embed=recap_embed)
        except discord.Forbidden:
            pass

    lock_status = "🔒 verrouillés" if lock_threads else "💬 laissés ouverts pour discussion"
    await interaction.followup.send(f"✅ Session d'enchères clôturée.\n📝 Threads {lock_status}.", ephemeral=True)
    
    try:
        await bot.change_presence(status=discord.Status.idle, activity=discord.Game("⏳ En attente de la prochaine enchère"))
    except Exception as e:
        logger.error(f"Erreur changement de statut: {e}")

# --------- COMMANDES ÉCONOMIQUES ADMIN ----------
@bot.tree.command(name="eco-ajouter", description="[ADMIN] Ajouter de l'argent à un joueur")
@handle_db_errors
@log_performance
async def admin_add_money(interaction: discord.Interaction, joueur: discord.Member, montant: int, raison: str = "Ajout administrateur"):
    if not await check_admin_permissions(interaction):
        return
    """Ajoute de l'argent au compte d'un joueur"""
    if montant <= 0:
        await interaction.response.send_message("❌ Le montant doit être positif.", ephemeral=True)
        return
    
    async with db.get_connection() as conn:
        # Ajouter l'argent au joueur
        await conn.execute("""
            INSERT INTO players (discord_id, username, ark_name, balance) VALUES ($1, $2, $3, $4)
            ON CONFLICT (discord_id) DO UPDATE SET 
                balance = players.balance + $4,
                username = $2,
                updated_at = NOW()
        """, joueur.id, joueur.name, joueur.display_name, montant)
        
        # Enregistrer la transaction pour l'historique
        await conn.execute("""
            INSERT INTO transactions (to_user_id, amount, transaction_type, description, admin_id)
            VALUES ($1, $2, 'admin_add', $3, $4)
        """, joueur.id, montant, raison, interaction.user.id)
        
        # Récupérer le nouveau solde
        nouveau_solde = await conn.fetchval("SELECT balance FROM players WHERE discord_id = $1", joueur.id)
        
        # Utiliser l'embed optimisé
        embed = EmbedBuilder.admin_action(
            action="Ajout d'argent",
            target=joueur.display_name,
            amount=montant,
            reason=raison,
            admin=interaction.user.display_name
        )
        embed.add_field(name="Nouveau solde", value=format_currency(nouveau_solde), inline=True)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="eco-retirer", description="[ADMIN] Retirer de l'argent à un joueur")  
@handle_db_errors
@log_performance
async def admin_remove_money(interaction: discord.Interaction, joueur: discord.Member, montant: int, raison: str = "Retrait administrateur"):
    if not await check_admin_permissions(interaction):
        return
    """Retire de l'argent du compte d'un joueur"""
    if montant <= 0:
        await interaction.response.send_message("❌ Le montant doit être positif.", ephemeral=True)
        return
    
    async with db.get_connection() as conn:
        # Vérifier le solde actuel
        solde_actuel = await conn.fetchval("SELECT balance FROM players WHERE discord_id = $1", joueur.id)
        if not solde_actuel:
            await interaction.response.send_message(
                embed=quick_error("Compte introuvable", f"{joueur.mention} n'a pas de compte."), 
                ephemeral=True
            )
            return
        
        if solde_actuel < montant:
            await interaction.response.send_message(
                embed=quick_error("Solde insuffisant", 
                                f"{joueur.mention} n'a que {format_currency(solde_actuel)} (demandé: {format_currency(montant)})"), 
                ephemeral=True
            )
            return
        
        # Retirer l'argent
        await conn.execute("UPDATE players SET balance = balance - $1, updated_at = NOW() WHERE discord_id = $2", montant, joueur.id)
        
        # Enregistrer la transaction
        await conn.execute("""
            INSERT INTO transactions (from_user_id, amount, transaction_type, description, admin_id)
            VALUES ($1, $2, 'admin_remove', $3, $4)
        """, joueur.id, montant, raison, interaction.user.id)
        
        # Récupérer le nouveau solde
        nouveau_solde = await conn.fetchval("SELECT balance FROM players WHERE discord_id = $1", joueur.id)
        
        # Utiliser l'embed optimisé
        embed = EmbedBuilder.admin_action(
            action="Retrait d'argent",
            target=joueur.display_name,
            amount=montant,
            reason=raison,
            admin=interaction.user.display_name
        )
        embed.add_field(name="Nouveau solde", value=format_currency(nouveau_solde), inline=True)
        embed.color = 0xffa502  # Orange pour retrait
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="eco-définir", description="[ADMIN] Définir le solde d'un joueur")
async def admin_set_money(interaction: discord.Interaction, joueur: discord.Member, montant: int, raison: str = "Définition administrateur"):
    if not await check_admin_permissions(interaction):
        return
    """Définit le solde exact d'un joueur"""
    if montant < 0:
        await interaction.response.send_message("❌ Le montant ne peut pas être négatif.", ephemeral=True)
        return
    
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        # Récupérer le solde actuel
        ancien_solde = await conn.fetchval("SELECT balance FROM players WHERE discord_id = $1", joueur.id)
        if ancien_solde is None:
            ancien_solde = 0
        
        # Définir le nouveau solde
        await conn.execute("""
            INSERT INTO players (discord_id, username, ark_name, balance) VALUES ($1, $2, $3, $4)
            ON CONFLICT (discord_id) DO UPDATE SET 
                balance = $4,
                username = $2,
                updated_at = NOW()
        """, joueur.id, joueur.name, joueur.display_name, montant)
        
        # Enregistrer la transaction
        difference = montant - ancien_solde
        await conn.execute("""
            INSERT INTO transactions (to_user_id, amount, transaction_type, description, admin_id)
            VALUES ($1, $2, 'admin_set', $3, $4)
        """, joueur.id, difference, f"{raison} (ancien: {ancien_solde:,}, nouveau: {montant:,})", interaction.user.id)
        
        await conn.close()
        
        embed = discord.Embed(
            title="⚖️ Solde Défini",
            description=f"Solde de {joueur.mention} défini à **{montant:,}** Aqualis",
            color=discord.Color.blue()
        )
        embed.add_field(name="Ancien solde", value=f"{ancien_solde:,} Aqualis", inline=True)
        embed.add_field(name="Nouveau solde", value=f"{montant:,} Aqualis", inline=True)
        embed.add_field(name="Différence", value=f"{difference:+,} Aqualis", inline=True)
        embed.add_field(name="Raison", value=raison, inline=False)
        embed.add_field(name="Administrateur", value=interaction.user.mention, inline=True)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    except asyncpg.exceptions.PostgresError as e:
        await interaction.response.send_message(f"❌ Erreur base de données : {e}", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur inattendue : {e}", ephemeral=True)

@bot.tree.command(name="eco-infos", description="[ADMIN] Voir les infos économiques d'un joueur")
async def admin_eco_info(interaction: discord.Interaction, joueur: discord.Member):
    if not await check_admin_permissions(interaction):
        return
    """Affiche les informations économiques détaillées d'un joueur"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        # Récupérer les infos du joueur
        player_info = await conn.fetchrow("SELECT * FROM players WHERE discord_id = $1", joueur.id)
        
        if not player_info:
            await interaction.response.send_message(f"❌ {joueur.mention} n'a pas de compte.", ephemeral=True)
            await conn.close()
            return
        
        # Récupérer les dernières transactions
        recent_transactions = await conn.fetch("""
            SELECT amount, transaction_type, description, created_at, admin_id
            FROM transactions 
            WHERE to_user_id = $1 OR from_user_id = $1
            ORDER BY created_at DESC 
            LIMIT 5
        """, joueur.id)
        
        await conn.close()
        
        embed = discord.Embed(
            title=f"📊 Infos Économiques - {joueur.display_name}",
            color=discord.Color.green()
        )
        
        embed.add_field(name="💰 Solde actuel", value=f"{player_info['balance']:,} Aqualis", inline=True)
        embed.add_field(name="🏷️ Pseudo ARK", value=player_info['ark_name'] or "Non défini", inline=True)
        embed.add_field(name="🆔 Discord ID", value=str(joueur.id), inline=True)
        
        # Historique récent
        if recent_transactions:
            transactions_text = ""
            for tx in recent_transactions:
                date_str = tx['created_at'].strftime("%d/%m %H:%M")
                transactions_text += f"• {date_str} - {tx['transaction_type']} - {tx['amount']:+,} Aqualis\n"
            
            embed.add_field(name="📝 Dernières transactions", value=transactions_text[:1024], inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    except asyncpg.exceptions.PostgresError as e:
        await interaction.response.send_message(f"❌ Erreur base de données : {e}", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur inattendue : {e}", ephemeral=True)

# --------- COMMANDES JOUEURS ----------
@bot.tree.command(name="solde", description="Voir votre solde")
async def check_balance(interaction: discord.Interaction):
    """Affiche le solde du joueur"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        player_info = await conn.fetchrow("SELECT balance, ark_name FROM players WHERE discord_id = $1", interaction.user.id)
        
        await conn.close()
        
        if not player_info:
            embed = discord.Embed(
                title="💰 Votre Solde",
                description="Vous n'avez pas encore de compte.\nVotre solde est de **0** Aqualis.",
                color=discord.Color.blue()
            )
        else:
            embed = discord.Embed(
                title="💰 Votre Solde",
                description=f"Vous avez **{player_info['balance']:,}** Aqualis",
                color=discord.Color.green()
            )
            if player_info['ark_name']:
                embed.add_field(name="🏷️ Pseudo ARK", value=player_info['ark_name'], inline=True)
        
        embed.add_field(name="🌐 Site Web", value="Consultez votre [économie](https://devredious.github.io/atlant-ark-site/economie.html) pour plus de détails", inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    except asyncpg.exceptions.PostgresError as e:
        await interaction.response.send_message(f"❌ Erreur base de données : {e}", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur inattendue : {e}", ephemeral=True)

@bot.tree.command(name="inscription", description="Enregistrer ton pseudo ARK")
async def register(interaction: discord.Interaction, pseudo: str):
    if not pseudo.strip() or len(pseudo) > 50:
        await interaction.response.send_message("❌ Le pseudo doit faire entre 1 et 50 caractères.", ephemeral=True)
        return
    
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("""
            INSERT INTO players (discord_id, username, ark_name, balance)
            VALUES ($1, $2, $3, 0)
            ON CONFLICT (discord_id) DO UPDATE SET 
                ark_name = $3,
                username = $2,
                updated_at = NOW()
        """, interaction.user.id, interaction.user.name, pseudo.strip())
        await conn.close()

        await interaction.response.send_message(
            f"✅ Ton compte a été enregistré avec le pseudo **{pseudo.strip()}**.",
            ephemeral=True
        )
    except asyncpg.exceptions.PostgresError as e:
        await interaction.response.send_message(f"❌ Erreur base de données : {e}", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur inattendue : {e}", ephemeral=True)

# --------- COMMANDES API ----------
@bot.tree.command(name="stats-api", description="Voir les stats de l'API")
async def api_stats(interaction: discord.Interaction):
    if not await check_admin_permissions(interaction):
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{API_URL}/stats")
            response.raise_for_status()
            data = response.json()
            
        embed = discord.Embed(
            title="📊 Statistiques API", 
            color=discord.Color.blue()
        )
        embed.add_field(name="Joueurs en ligne", value=data.get("players_online", "N/A"), inline=True)
        embed.add_field(name="Enchères actives", value=data.get("active_auctions", "N/A"), inline=True)
        embed.add_field(name="Joueurs enregistrés", value=data.get("registered_players", "N/A"), inline=True)
        embed.add_field(name="Uptime", value=data.get("uptime", "N/A"), inline=True)
        embed.add_field(name="Statut", value=data.get("server_status", "N/A"), inline=True)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    except httpx.RequestError as e:
        await interaction.response.send_message(f"❌ Erreur de connexion API: {e}", ephemeral=True)
    except httpx.HTTPStatusError as e:
        await interaction.response.send_message(f"❌ Erreur HTTP API: {e.response.status_code}", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur inattendue API: {e}", ephemeral=True)

# --------- COMMANDES GESTION RÔLES SUPPRIMÉES ----------
# Contrôle d'accès géré uniquement par le système de tribus

@bot.tree.command(name="encheres-fermer", description="[ADMIN] Fermer définitivement une enchère")
@app_commands.describe(thread_id="ID du thread d'enchère à fermer")
async def admin_close_auction(interaction: discord.Interaction, thread_id: str):
    if not await check_admin_permissions(interaction):
        return
    
    try:
        thread_id_int = int(thread_id)
    except ValueError:
        await interaction.response.send_message("❌ ID de thread invalide.", ephemeral=True)
        return
    
    try:
        # Vérifier si l'enchère existe dans le cache
        if thread_id_int not in active_auctions_cache:
            await interaction.response.send_message("❌ Aucune enchère active trouvée avec cet ID.", ephemeral=True)
            return
        
        auction_data = active_auctions_cache[thread_id_int]
        
        # Essayer de récupérer le thread Discord
        try:
            thread = bot.get_channel(thread_id_int)
            if thread:
                # Désactiver les boutons sur le dernier message d'enchère
                last_message = await get_last_message_with_embed(thread)
                if last_message:
                    embed = last_message.embeds[0] if last_message.embeds else None
                    if embed:
                        embed.color = discord.Color.red()
                        embed.set_footer(text="🔒 Enchère fermée par un administrateur")
                        await last_message.edit(embed=embed, view=None)
                
                # Archiver le thread
                await thread.edit(archived=True, reason="Enchère fermée par admin")
        except Exception as e:
            logger.warning(f"⚠️ Impossible de modifier le thread {thread_id_int}: {e}")
        
        # Supprimer l'état de l'enchère
        await remove_active_auction_state(thread_id_int)
        
        embed = EmbedBuilder.success(
            title="Enchère fermée",
            description=f"L'enchère **{auction_data.get('dino_name', 'Inconnu')}** a été fermée définitivement."
        )
        embed.add_field(name="Thread ID", value=str(thread_id_int), inline=True)
        embed.add_field(name="Vendeur", value=auction_data.get('seller_name', 'Inconnu'), inline=True)
        embed.add_field(name="Prix final", value=f"{auction_data.get('current_price', 0):,} {EMOJI_CURRENCY}", inline=True)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    except Exception as e:
        logger.error(f"❌ Erreur fermeture enchère {thread_id}: {e}")
        await interaction.response.send_message("❌ Erreur lors de la fermeture de l'enchère.", ephemeral=True)

@bot.tree.command(name="classement", description="Voir le classement des joueurs")
async def leaderboard(interaction: discord.Interaction):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{API_URL}/leaderboard")
            response.raise_for_status()
            data = response.json()
            
        if not data.get("leaderboard"):
            await interaction.response.send_message("🏆 Aucun joueur dans le classement pour le moment.", ephemeral=True)
            return
            
        embed = discord.Embed(
            title="🏆 Classement des Joueurs", 
            description="Top 5 des joueurs les plus riches",
            color=discord.Color.gold()
        )
        
        for player in data["leaderboard"][:5]:  # Top 5 pour Discord
            embed.add_field(
                name=f"{player['medal']} {player['name']}", 
                value=f"{player['balance']} Aqualis", 
                inline=False
            )
            
        await interaction.response.send_message(embed=embed, ephemeral=True)
    except httpx.RequestError as e:
        await interaction.response.send_message(f"❌ Erreur de connexion : {e}", ephemeral=True)
    except httpx.HTTPStatusError as e:
        await interaction.response.send_message(f"❌ Erreur HTTP : {e.response.status_code}", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur inattendue : {e}", ephemeral=True)

# --------------- COMMANDES TRIBUS ---------------
@bot.tree.command(name="tribu-créer", description="[ADMIN] Créer une nouvelle tribu")
@app_commands.describe(
    name="Nom de la tribu",
    leader="Leader de la tribu",
    description="Description de la tribu (optionnel)"
)
async def create_tribe(interaction: discord.Interaction, name: str, leader: discord.Member, description: str = None):
    if not await check_admin_permissions(interaction):
        return
    try:
        async with db.get_connection() as conn:
            # Vérifier si la tribu existe déjà
            existing = await conn.fetchval("SELECT id FROM tribes WHERE name = $1", name)
            if existing:
                await interaction.response.send_message(f"❌ Une tribu nommée **{name}** existe déjà.", ephemeral=True)
                return
            
            # Vérifier si le leader est déjà dans une tribu
            existing_membership = await conn.fetchval("""
                SELECT t.name FROM tribes t
                JOIN tribe_members tm ON t.id = tm.tribe_id
                WHERE tm.user_id = $1
            """, leader.id)
            
            if existing_membership:
                await interaction.response.send_message(f"❌ {leader.mention} est déjà membre de la tribu **{existing_membership}**.", ephemeral=True)
                return
            
            # Créer la tribu
            tribe_id = await conn.fetchval("""
                INSERT INTO tribes (name, leader_id, description)
                VALUES ($1, $2, $3)
                RETURNING id
            """, name, leader.id, description)
            
            # Ajouter le leader comme membre
            await conn.execute("""
                INSERT INTO tribe_members (tribe_id, user_id, role)
                VALUES ($1, $2, 'leader')
            """, tribe_id, leader.id)
            
        embed = EmbedBuilder.success(
            title="Tribu Créée !",
            description=f"🏛️ **{name}** a été créée avec succès !"
        )
        embed.add_field(name="👑 Leader", value=leader.mention, inline=True)
        embed.add_field(name="🆔 ID", value=str(tribe_id), inline=True)
        if description:
            embed.add_field(name="📝 Description", value=description, inline=False)
            
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(f"🏛️ Tribu '{name}' créée par {interaction.user} avec leader {leader}")
        
    except Exception as e:
        logger.error(f"❌ Erreur création tribu: {e}")
        await interaction.response.send_message("❌ Erreur lors de la création de la tribu.", ephemeral=True)

@bot.tree.command(name="tribu-supprimer", description="[ADMIN] Supprimer une tribu")
@app_commands.describe(name="Nom de la tribu à supprimer")
async def delete_tribe(interaction: discord.Interaction, name: str):
    if not await check_admin_permissions(interaction):
        return
    try:
        async with db.get_connection() as conn:
            # Récupérer les infos de la tribu
            tribe = await conn.fetchrow("SELECT id, name, leader_id FROM tribes WHERE name = $1", name)
            if not tribe:
                await interaction.response.send_message(f"❌ Aucune tribu nommée **{name}** trouvée.", ephemeral=True)
                return
            
            # Compter les membres
            member_count = await conn.fetchval("SELECT COUNT(*) FROM tribe_members WHERE tribe_id = $1", tribe['id'])
            
            # Supprimer la tribu (cascade supprime les membres)
            await conn.execute("DELETE FROM tribes WHERE id = $1", tribe['id'])
            
        embed = EmbedBuilder.success(
            title="Tribu Supprimée !",
            description=f"🏛️ **{name}** a été supprimée avec succès."
        )
        embed.add_field(name="👑 Ex-Leader", value=f"<@{tribe['leader_id']}>", inline=True)
        embed.add_field(name="👥 Membres libérés", value=str(member_count), inline=True)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(f"🗑️ Tribu '{name}' supprimée par {interaction.user}")
        
    except Exception as e:
        logger.error(f"❌ Erreur suppression tribu: {e}")
        await interaction.response.send_message("❌ Erreur lors de la suppression de la tribu.", ephemeral=True)

@bot.tree.command(name="tribu-ajouter", description="[ADMIN] Ajouter un membre à une tribu")
@app_commands.describe(
    tribe_name="Nom de la tribu",
    member="Membre à ajouter"
)
async def add_tribe_member(interaction: discord.Interaction, tribe_name: str, member: discord.Member):
    if not await check_admin_permissions(interaction):
        return
    try:
        async with db.get_connection() as conn:
            # Vérifier si la tribu existe
            tribe = await conn.fetchrow("SELECT id, name FROM tribes WHERE name = $1", tribe_name)
            if not tribe:
                await interaction.response.send_message(f"❌ Aucune tribu nommée **{tribe_name}** trouvée.", ephemeral=True)
                return
            
            # Vérifier si le membre est déjà dans une tribu
            existing = await conn.fetchval("""
                SELECT t.name FROM tribes t
                JOIN tribe_members tm ON t.id = tm.tribe_id
                WHERE tm.user_id = $1
            """, member.id)
            
            if existing:
                await interaction.response.send_message(f"❌ {member.mention} est déjà membre de la tribu **{existing}**.", ephemeral=True)
                return
            
            # Ajouter le membre
            await conn.execute("""
                INSERT INTO tribe_members (tribe_id, user_id, role)
                VALUES ($1, $2, 'member')
            """, tribe['id'], member.id)
            
        embed = EmbedBuilder.success(
            title="Membre Ajouté !",
            description=f"👥 {member.mention} a rejoint la tribu **{tribe_name}** !"
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(f"👥 {member} ajouté à la tribu '{tribe_name}' par {interaction.user}")
        
    except Exception as e:
        logger.error(f"❌ Erreur ajout membre tribu: {e}")
        await interaction.response.send_message("❌ Erreur lors de l'ajout du membre.", ephemeral=True)

@bot.tree.command(name="tribu-retirer", description="[ADMIN] Retirer un membre d'une tribu")
@app_commands.describe(member="Membre à retirer de sa tribu")
async def remove_tribe_member(interaction: discord.Interaction, member: discord.Member):
    if not await check_admin_permissions(interaction):
        return
    try:
        async with db.get_connection() as conn:
            # Récupérer la tribu du membre
            tribe_info = await conn.fetchrow("""
                SELECT t.name, t.id, tm.role
                FROM tribes t
                JOIN tribe_members tm ON t.id = tm.tribe_id
                WHERE tm.user_id = $1
            """, member.id)
            
            if not tribe_info:
                await interaction.response.send_message(f"❌ {member.mention} n'est membre d'aucune tribu.", ephemeral=True)
                return
            
            # Vérifier si c'est le leader
            if tribe_info['role'] == 'leader':
                member_count = await conn.fetchval("SELECT COUNT(*) FROM tribe_members WHERE tribe_id = $1", tribe_info['id'])
                if member_count > 1:
                    await interaction.response.send_message(f"❌ Impossible de retirer le leader s'il y a d'autres membres. Supprimez la tribu ou transférez le leadership.", ephemeral=True)
                    return
            
            # Retirer le membre
            await conn.execute("DELETE FROM tribe_members WHERE user_id = $1", member.id)
            
        embed = EmbedBuilder.success(
            title="Membre Retiré !",
            description=f"👥 {member.mention} a quitté la tribu **{tribe_info['name']}** !"
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(f"👥 {member} retiré de la tribu '{tribe_info['name']}' par {interaction.user}")
        
    except Exception as e:
        logger.error(f"❌ Erreur retrait membre tribu: {e}")
        await interaction.response.send_message("❌ Erreur lors du retrait du membre.", ephemeral=True)

@bot.tree.command(name="tribu-liste", description="Voir la liste des tribus")
async def list_tribes(interaction: discord.Interaction):
    try:
        async with db.get_connection() as conn:
            tribes = await conn.fetch("""
                SELECT t.name, t.leader_id, t.description, t.created_at,
                       COUNT(tm.user_id) as member_count
                FROM tribes t
                LEFT JOIN tribe_members tm ON t.id = tm.tribe_id
                GROUP BY t.id, t.name, t.leader_id, t.description, t.created_at
                ORDER BY member_count DESC, t.created_at ASC
            """)
            
        if not tribes:
            await interaction.response.send_message("🏛️ Aucune tribu n'existe actuellement.", ephemeral=True)
            return
            
        embed = discord.Embed(
            title="🏛️ Liste des Tribus",
            color=discord.Color.gold()
        )
        
        for tribe in tribes[:10]:  # Top 10 tribus
            leader_mention = f"<@{tribe['leader_id']}>"
            description = tribe['description'] or "Aucune description"
            
            embed.add_field(
                name=f"**{tribe['name']}** ({tribe['member_count']} membres)",
                value=f"👑 {leader_mention}\n📝 {description}",
                inline=False
            )
            
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    except Exception as e:
        logger.error(f"❌ Erreur liste tribus: {e}")
        await interaction.response.send_message("❌ Erreur lors de la récupération des tribus.", ephemeral=True)

@bot.tree.command(name="tribu-infos", description="Voir les informations d'une tribu")
@app_commands.describe(name="Nom de la tribu (optionnel, sinon votre tribu)")
async def tribe_info(interaction: discord.Interaction, name: str = None):
    try:
        async with db.get_connection() as conn:
            if name:
                # Tribu spécifiée
                tribe = await conn.fetchrow("SELECT * FROM tribes WHERE name = $1", name)
                if not tribe:
                    await interaction.response.send_message(f"❌ Aucune tribu nommée **{name}** trouvée.", ephemeral=True)
                    return
                tribe_id = tribe['id']
            else:
                # Tribu de l'utilisateur
                user_tribe = await get_user_tribe(interaction.user.id)
                if not user_tribe:
                    await interaction.response.send_message("❌ Vous n'êtes membre d'aucune tribu.", ephemeral=True)
                    return
                tribe_id = user_tribe['id']
                tribe = await conn.fetchrow("SELECT * FROM tribes WHERE id = $1", tribe_id)
            
            # Récupérer les membres
            members = await get_tribe_members(tribe_id)
            
        embed = discord.Embed(
            title=f"🏛️ {tribe['name']}",
            description=tribe['description'] or "Aucune description",
            color=discord.Color.gold()
        )
        
        embed.add_field(name="👑 Leader", value=f"<@{tribe['leader_id']}>", inline=True)
        embed.add_field(name="👥 Membres", value=str(len(members)), inline=True)
        embed.add_field(name="📅 Créée le", value=tribe['created_at'].strftime("%d/%m/%Y"), inline=True)
        
        if members:
            member_list = []
            for member in members[:10]:  # Max 10 membres affichés
                role_emoji = "👑" if member['role'] == 'leader' else "👤"
                member_list.append(f"{role_emoji} <@{member['user_id']}>")
            
            embed.add_field(
                name="📋 Liste des Membres",
                value="\n".join(member_list),
                inline=False
            )
            
            if len(members) > 10:
                embed.add_field(name="Note", value=f"... et {len(members) - 10} autres membres", inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    except Exception as e:
        logger.error(f"❌ Erreur info tribu: {e}")
        await interaction.response.send_message("❌ Erreur lors de la récupération des informations.", ephemeral=True)

@bot.tree.command(name="tribu-basculer", description="[ADMIN] Activer/désactiver l'obligation d'être en tribu")
@app_commands.describe(enabled="True pour activer l'obligation de tribu, False pour la désactiver")
async def toggle_tribe_requirement(interaction: discord.Interaction, enabled: bool):
    if not await check_admin_permissions(interaction):
        return
    """Active ou désactive l'obligation d'appartenir à une tribu pour participer aux enchères"""
    global tribe_required
    
    try:
        old_status = tribe_required
        tribe_required = enabled
        
        status_text = "**activée**" if enabled else "**désactivée**"
        color = discord.Color.green() if enabled else discord.Color.orange()
        
        embed = discord.Embed(
            title="🏛️ Configuration Tribus Mise à Jour",
            description=f"L'obligation d'appartenir à une tribu est maintenant {status_text}",
            color=color
        )
        
        if enabled:
            embed.add_field(
                name="✅ Mode Sécurisé Activé",
                value="• Seuls les membres de tribus peuvent participer\n"
                      "• Système de délégation disponible\n"
                      "• Tickets automatiques pour les nouveaux",
                inline=False
            )
        else:
            embed.add_field(
                name="⚠️ Mode Libre Activé", 
                value="• Tous les utilisateurs peuvent participer\n"
                      "• Pas de restriction par tribu\n"
                      "• Le système de tribus reste disponible",
                inline=False
            )
        
        embed.add_field(
            name="📊 Statut",
            value=f"Ancien : {'Activé' if old_status else 'Désactivé'} → Nouveau : {'Activé' if enabled else 'Désactivé'}",
            inline=False
        )
        
        embed.set_footer(text=f"Modifié par {interaction.user.display_name}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(f"🔄 Obligation tribu {'activée' if enabled else 'désactivée'} par {interaction.user.display_name}")
        
    except Exception as e:
        logger.error(f"❌ Erreur toggle tribu: {e}")
        await interaction.response.send_message("❌ Erreur lors de la modification de la configuration.", ephemeral=True)

# --------------- COMMANDES ADMIN BOT ---------------
@bot.tree.command(name="admin-ajouter", description="[SUPER ADMIN] Ajouter un administrateur du bot")
async def add_bot_admin(interaction: discord.Interaction, utilisateur: discord.Member):
    """Ajoute un utilisateur à la liste des administrateurs du bot"""
    if not await check_admin_permissions(interaction):
        return
    
    global BOT_ADMINS
    
    if utilisateur.id in BOT_ADMINS:
        await interaction.response.send_message(f"❌ {utilisateur.mention} est déjà administrateur du bot.", ephemeral=True)
        return
    
    BOT_ADMINS.append(utilisateur.id)
    
    embed = discord.Embed(
        title="✅ Administrateur Ajouté !",
        description=f"🛡️ {utilisateur.mention} a été ajouté aux administrateurs du bot.",
        color=discord.Color.green()
    )
    embed.add_field(name="ID Discord", value=str(utilisateur.id), inline=True)
    embed.add_field(name="Total Admins", value=str(len(BOT_ADMINS)), inline=True)
    embed.set_footer(text=f"Ajouté par {interaction.user.display_name}")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)
    logger.info(f"🛡️ {utilisateur} ({utilisateur.id}) ajouté comme admin bot par {interaction.user}")

@bot.tree.command(name="admin-retirer", description="[SUPER ADMIN] Retirer un administrateur du bot")
async def remove_bot_admin(interaction: discord.Interaction, utilisateur: discord.Member):
    """Retire un utilisateur de la liste des administrateurs du bot"""
    if not await check_admin_permissions(interaction):
        return
    
    global BOT_ADMINS
    
    if utilisateur.id not in BOT_ADMINS:
        await interaction.response.send_message(f"❌ {utilisateur.mention} n'est pas administrateur du bot.", ephemeral=True)
        return
    
    BOT_ADMINS.remove(utilisateur.id)
    
    embed = discord.Embed(
        title="⚠️ Administrateur Retiré !",
        description=f"🛡️ {utilisateur.mention} a été retiré des administrateurs du bot.",
        color=discord.Color.orange()
    )
    embed.add_field(name="ID Discord", value=str(utilisateur.id), inline=True)
    embed.add_field(name="Total Admins", value=str(len(BOT_ADMINS)), inline=True)
    embed.set_footer(text=f"Retiré par {interaction.user.display_name}")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)
    logger.info(f"🛡️ {utilisateur} ({utilisateur.id}) retiré des admins bot par {interaction.user}")

@bot.tree.command(name="admin-liste", description="[ADMIN] Voir la liste des administrateurs du bot")
async def list_bot_admins(interaction: discord.Interaction):
    """Affiche la liste des administrateurs du bot"""
    if not await check_admin_permissions(interaction):
        return
    
    embed = discord.Embed(
        title="🛡️ Administrateurs du Bot",
        color=discord.Color.blue()
    )
    
    if not BOT_ADMINS:
        embed.description = "Aucun administrateur spécifique configuré.\nSeuls les administrateurs Discord peuvent gérer le bot."
    else:
        admin_list = []
        for admin_id in BOT_ADMINS:
            try:
                user = bot.get_user(admin_id) or await bot.fetch_user(admin_id)
                admin_list.append(f"• **{user.display_name}** (`{admin_id}`)")
            except:
                admin_list.append(f"• Utilisateur inconnu (`{admin_id}`)")
        
        embed.description = "\n".join(admin_list)
    
    embed.add_field(name="Total", value=str(len(BOT_ADMINS)), inline=True)
    embed.set_footer(text="Ces utilisateurs peuvent gérer le bot même sans permissions Discord Admin")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="admin-check", description="[ADMIN] Vérifier les permissions d'un utilisateur")
async def check_user_permissions(interaction: discord.Interaction, utilisateur: discord.Member = None):
    """Vérifie les permissions d'un utilisateur pour le bot"""
    if not await check_admin_permissions(interaction):
        return
    
    target_user = utilisateur or interaction.user
    
    embed = discord.Embed(
        title=f"🔍 Permissions - {target_user.display_name}",
        color=discord.Color.blue()
    )
    
    # Vérifications des permissions
    is_bot_admin_user = is_bot_admin(target_user.id)
    is_discord_admin_user = target_user.guild_permissions.administrator if hasattr(target_user, 'guild_permissions') else False
    can_use_admin_commands = is_bot_admin_user or is_discord_admin_user
    
    embed.add_field(
        name="🛡️ Admin Bot", 
        value="✅ Oui" if is_bot_admin_user else "❌ Non", 
        inline=True
    )
    embed.add_field(
        name="🔧 Admin Discord", 
        value="✅ Oui" if is_discord_admin_user else "❌ Non", 
        inline=True
    )
    embed.add_field(
        name="⚡ Accès Commandes Admin", 
        value="✅ Oui" if can_use_admin_commands else "❌ Non", 
        inline=True
    )
    
    embed.add_field(name="🆔 Discord ID", value=str(target_user.id), inline=False)
    
    if can_use_admin_commands:
        embed.add_field(
            name="📋 Commandes Disponibles",
            value="• Gestion enchères (`/début`, `/fin`)\n• Économie (`/eco-*`)\n• Tribus (`/tribu-*`)\n• Administration (`/admin-*`)",
            inline=False
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --------------- INITIALISATION DB ---------------
async def init_db():
    """Initialise la base de données avec le gestionnaire optimisé"""
    async with db.get_connection() as conn:
        # Table des joueurs (structure simplifiée)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS players (
                id SERIAL PRIMARY KEY,
                discord_id BIGINT UNIQUE NOT NULL,
                username TEXT,
                ark_name TEXT,
                balance BIGINT DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # Table des enchères
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS auctions (
                id SERIAL PRIMARY KEY,
                dino_name TEXT NOT NULL,
                vendeur_id BIGINT NOT NULL,
                acheteur_id BIGINT,
                price BIGINT,
                status TEXT DEFAULT 'open',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # Table de l'historique des enchères
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS auction_history (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                dino_name TEXT NOT NULL,
                final_price BIGINT NOT NULL,
                won BOOLEAN DEFAULT false,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # Table des transactions économiques
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                from_user_id BIGINT,
                to_user_id BIGINT,
                amount BIGINT NOT NULL,
                transaction_type TEXT NOT NULL,
                description TEXT,
                admin_id BIGINT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # Table des enchères actives pour récupération après redémarrage
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS active_auctions (
                thread_id BIGINT PRIMARY KEY,
                auction_data JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # Table des tribus
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tribes (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                leader_id BIGINT NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # Table des membres de tribus
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tribe_members (
                id SERIAL PRIMARY KEY,
                tribe_id INTEGER REFERENCES tribes(id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL,
                role TEXT DEFAULT 'member', -- 'leader', 'member'
                joined_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(tribe_id, user_id)
            )
        """)
        
        # Suppression des anciennes tables (migration vers players unifiée)
        await conn.execute("DROP TABLE IF EXISTS user_currency CASCADE")
        await conn.execute("DROP TABLE IF EXISTS user_profiles CASCADE")
        await conn.execute("DROP TABLE IF EXISTS aqualis_transactions CASCADE")
        
        # Vérifier que la table players a tous les champs nécessaires
        try:
            await conn.execute("""
                ALTER TABLE players 
                ADD COLUMN IF NOT EXISTS username TEXT,
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW(),
                ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()
            """)
        except asyncpg.exceptions.PostgresError:
            # Les colonnes existent déjà
            pass
        
        logger.info("✅ Base de données initialisée avec succès")

# Tâche de mise à jour des stats
async def update_stats_task():
    """Tâche qui met à jour les stats régulièrement"""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            if auctions_open:
                # Compter les enchères actives
                guild = bot.guilds[0] if bot.guilds else None
                if guild:
                    forum = guild.get_channel(FORUM_CHANNEL_ID)
                    if forum and forum.type == discord.ChannelType.forum:
                        auction_count = len([thread for thread in forum.threads if "🦖" in thread.name])
                        update_auctions_state(True, auction_count)
        except Exception as e:
            logger.error(f"Erreur update stats: {e}")
        
        await asyncio.sleep(300)  # 5 minutes

# --------------- EVENTS ---------------
@bot.event
async def on_ready():
    try:
        await bot.tree.sync()
        logger.info(f"✅ Connecté en tant que {bot.user}")

        # Initialiser le pool de connexions optimisé AVANT init_db
        try:
            await db.initialize(DATABASE_URL)
            logger.info("📦 Pool de connexions DB optimisé créé")
        except Exception as e:
            logger.error(f"❌ Erreur initialisation pool DB : {e}")
            logger.warning("⚠️ Continuons sans pool optimisé")
            # Continuer sans pool optimisé
        
        # Init DB (après initialisation du pool)
        try:
            await init_db()
            logger.info("✅ Base de données initialisée avec succès")
        except Exception as e:
            logger.error(f"❌ Erreur initialisation DB : {e}")
            logger.warning("⚠️ Certaines fonctionnalités peuvent ne pas fonctionner")

        # Partager l'instance du bot avec l'API
        try:
            set_bot_instance(bot)
            logger.info("🔗 Bot connecté à l'API")
        except Exception as e:
            logger.warning(f"⚠️ Erreur connexion API : {e}")

        # Enregistrer les vues persistantes
        try:
            auction_hub_view = AuctionHubView()
            bid_view = BidView()
            tribe_request_view = TribeRequestView()
            
            bot.add_view(auction_hub_view)
            bot.add_view(bid_view) 
            bot.add_view(tribe_request_view)
            
            logger.info("✅ Vues persistantes enregistrées :")
            logger.info(f"   • AuctionHubView (timeout: {auction_hub_view.timeout})")
            logger.info(f"   • BidView (timeout: {bid_view.timeout})")
            logger.info(f"   • TribeRequestView (timeout: {tribe_request_view.timeout})")
            
            # Ajouter une TransactionView persistante générique
            persistent_transaction_view = PersistentTransactionView()
            bot.add_view(persistent_transaction_view)
            logger.info(f"   • PersistentTransactionView (timeout: {persistent_transaction_view.timeout})")
        except Exception as e:
            logger.error(f"❌ Erreur lors de l'enregistrement des vues persistantes : {e}")
        
        # Récupération des enchères actives après redémarrage
        try:
            logger.info("🔄 Récupération des enchères actives après redémarrage...")
            loaded_auctions = await load_active_auctions_state()
            restored_views = await restore_auction_views_on_startup()
            
            if loaded_auctions > 0:
                logger.info(f"✅ Récupération terminée : {loaded_auctions} enchères chargées, {restored_views} Views restaurées")
            else:
                logger.info("✅ Aucune enchère active à récupérer")
                
        except Exception as e:
            logger.error(f"❌ Erreur lors de la récupération des enchères : {e}")
        
        # Démarrer la tâche de mise à jour
        bot.loop.create_task(update_stats_task())
        logger.info("📊 Tâche de mise à jour des stats démarrée")
        
        await bot.change_presence(status=discord.Status.idle, activity=discord.Game("⏳ En attente de la prochaine enchère"))
        
    except Exception as e:
        logger.error(f"❌ Erreur lors du démarrage : {e}")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Vérifie que le message est dans un thread du forum enchères + contient des fichiers
    if (isinstance(message.channel, discord.Thread) and 
        message.channel.parent and 
        message.channel.parent.id == FORUM_CHANNEL_ID and 
        message.attachments):
        try:
            last_msg = await get_last_message_with_embed(message.channel)
            if not last_msg or not last_msg.embeds:
                return

            embed = last_msg.embeds[0]

            # Récupération de l'ID vendeur
            vendeur_id = extract_vendor_id_safely(embed.footer.text if embed.footer else "")

            # Vérifie que l'auteur est bien le vendeur
            if vendeur_id and vendeur_id == message.author.id:
                files = []
                for attachment in message.attachments:
                    if attachment.content_type and "image" in attachment.content_type:
                        try:
                            file_data = await attachment.to_file()
                            files.append(file_data)
                        except Exception as e:
                            logger.error(f"Erreur lors du téléchargement de l'image : {e}")

                if not files:
                    try:
                        warn = await message.channel.send("❌ Merci d'envoyer uniquement des **images** (png, jpg, jpeg, gif).")
                        await warn.delete(delay=5)
                    except discord.Forbidden:
                        pass
                    return

                # On supprime l'image intégrée pour ne garder que la galerie au-dessus
                embed.set_image(url=None)
                embed.set_thumbnail(url=None)

                # Réédite le message avec l'embed + toutes les images en pièces jointes
                try:
                    await last_msg.edit(embed=embed, attachments=files)
                except discord.Forbidden:
                    pass

                # Supprimer le message brut du vendeur
                try:
                    await message.delete()
                except discord.Forbidden:
                    pass

                # Supprimer le message d'instruction si encore présent
                try:
                    async for msg in message.channel.history(limit=5):
                        if (msg.author == bot.user and 
                            ("📸" in msg.content and "merci d'envoyer" in msg.content.lower())):
                            try:
                                await msg.delete()
                                logger.info(f"🗑️ Message d'instruction supprimé après ajout d'image")
                            except discord.Forbidden:
                                logger.warning("⚠️ Permissions insuffisantes pour supprimer message d'instruction")
                            break
                except discord.Forbidden:
                    logger.warning("⚠️ Permissions insuffisantes pour accéder à l'historique")

                try:
                    confirm = await message.channel.send("✅ Images ajoutées à ton annonce !")
                    await confirm.delete(delay=5)
                except discord.Forbidden:
                    pass

        except Exception as e:
            logger.error(f"Erreur lors du traitement de l'image : {e}")

@bot.event
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Gère les erreurs des commandes slash"""
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ Vous n'avez pas les permissions nécessaires.", ephemeral=True)
    elif isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(f"❌ Commande en cooldown. Réessayez dans {error.retry_after:.1f}s", ephemeral=True)
    else:
        logger.error(f"Erreur commande slash : {error}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Une erreur inattendue s'est produite.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Une erreur inattendue s'est produite.", ephemeral=True)
        except Exception:
            pass

# ---------------- RUN -----------------
if __name__ == "__main__":
    # Lancer l'API FastAPI dans un thread
    def run_api():
        try:
            port = int(os.getenv("PORT", 8080))
            logger.info(f"🚀 Démarrage API sur port {port}")
            uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
        except Exception as e:
            logger.error(f"❌ Erreur démarrage API : {e}")

    threading.Thread(target=run_api, daemon=True).start()
    logger.info("🔗 Thread API démarré")

    # Lancer le bot Discord
    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"❌ Erreur critique du bot : {e}")
        raise
    finally:
        # Nettoyer les connexions
        try:
            loop = asyncio.get_event_loop()
            # Fermer le pool de connexions
            if hasattr(bot, 'db_pool') and bot.db_pool:
                loop.run_until_complete(bot.db_pool.close())
                logger.info("📦 Pool DB fermé")
        except Exception as e:
            logger.warning(f"⚠️ Erreur nettoyage : {e}")
