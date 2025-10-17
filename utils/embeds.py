# ===== GESTIONNAIRE D'EMBEDS OPTIMISÉ =====
import discord
from typing import Optional, Dict, Any, List
from datetime import datetime

# Couleurs standardisées
COLORS = {
    'success': 0x00ff9f,      # Vert aqua (succès)
    'error': 0xff4757,        # Rouge (erreur)
    'warning': 0xffa502,      # Orange (attention)
    'info': 0x3742fa,         # Bleu (information)
    'auction': 0x7bed9f,      # Vert clair (enchères)
    'money': 0xf1c40f,        # Jaune doré (argent)
    'neutral': 0x2f3542,      # Gris foncé (neutre)
    'premium': 0x9c88ff       # Violet (premium)
}

# Émojis standardisés
EMOJIS = {
    'success': '✅',
    'error': '❌', 
    'warning': '⚠️',
    'info': 'ℹ️',
    'money': '🪙',
    'auction': '🔨',
    'time': '⏰',
    'user': '👤',
    'level': '📊',
    'stats': '📈',
    'arrow_up': '📈',
    'arrow_down': '📉',
    'fire': '🔥',
    'crown': '👑',
    'gem': '💎',
    'male': '♂️',
    'female': '♀️',
    'couple': '💑',
    'mutation': '🧬',
    'clean': '🔹'
}

class EmbedBuilder:
    """Constructeur d'embeds optimisé avec templates prédéfinis"""
    
    @staticmethod
    def success(title: str, description: str = "", **kwargs) -> discord.Embed:
        """Embed de succès"""
        embed = discord.Embed(
            title=f"{EMOJIS['success']} {title}",
            description=description,
            color=COLORS['success'],
            timestamp=datetime.utcnow()
        )
        return EmbedBuilder._add_footer(embed, **kwargs)
    
    @staticmethod
    def error(title: str, description: str = "", **kwargs) -> discord.Embed:
        """Embed d'erreur"""
        embed = discord.Embed(
            title=f"{EMOJIS['error']} {title}",
            description=description,
            color=COLORS['error'],
            timestamp=datetime.utcnow()
        )
        return EmbedBuilder._add_footer(embed, **kwargs)
    
    @staticmethod
    def warning(title: str, description: str = "", **kwargs) -> discord.Embed:
        """Embed d'avertissement"""
        embed = discord.Embed(
            title=f"{EMOJIS['warning']} {title}",
            description=description,
            color=COLORS['warning'],
            timestamp=datetime.utcnow()
        )
        return EmbedBuilder._add_footer(embed, **kwargs)
    
    @staticmethod
    def info(title: str, description: str = "", **kwargs) -> discord.Embed:
        """Embed d'information"""
        embed = discord.Embed(
            title=f"{EMOJIS['info']} {title}",
            description=description,
            color=COLORS['info'],
            timestamp=datetime.utcnow()
        )
        return EmbedBuilder._add_footer(embed, **kwargs)
    
    @staticmethod
    def auction_created(dino_name: str, level: int, gender: str, mutations: str, 
                       price: int, seller: str, auction_id: int, seller_id: int = None) -> discord.Embed:
        """Embed pour une nouvelle enchère - Version ultra-claire"""
        
        # Icônes selon le genre et mutations
        gender_icon = {
            'Male': EMOJIS['male'],
            'Femelle': EMOJIS['female'], 
            'Couple': EMOJIS['couple']
        }.get(gender, '❓')
        
        mutation_icon = EMOJIS['mutation'] if 'Avec' in mutations else EMOJIS['clean']
        
        # Couleur dynamique selon les mutations
        embed_color = COLORS['premium'] if 'Avec' in mutations else COLORS['auction']
        
        # Title plus propre et lisible
        embed = discord.Embed(
            title=f"🔨 NOUVELLE ENCHÈRE",
            color=embed_color,
            timestamp=datetime.utcnow()
        )
        
        # Header principal avec le nom du dino en évidence  
        header = f"# � **{dino_name}** {gender_icon} {mutation_icon}\n"
        header += f"╭─ **Vendeur:** {seller}\n"
        header += f"╰─ **ID Enchère:** #{auction_id}"
        
        embed.description = header
        
        # Informations principales dans un layout clair
        embed.add_field(
            name="📊 Niveau",
            value=f"**`{level:,}`**",
            inline=True
        )
        
        embed.add_field(
            name="💰 Prix de Départ", 
            value=f"**`{price:,}`** Aqualis",
            inline=True
        )
        
        embed.add_field(
            name="🟢 Statut",
            value="**`EN COURS`**",
            inline=True
        )
        
        # Séparateur visuel
        embed.add_field(name="━━━━━━━━━━━━━━━━━━━━━━━", value="", inline=False)
        
        # Détails organisés avec des icônes claires
        details_line1 = f"**{gender_icon} Sexe:** {gender}"
        details_line2 = f"**{mutation_icon} Mutations:** {mutations}"
        
        seller_mention = f"<@{seller_id}>" if seller_id else seller
        details_line3 = f"**👤 Vendeur:** {seller_mention}"
        
        details_value = f"{details_line1}\n{details_line2}\n{details_line3}"
        
        embed.add_field(
            name="📋 Détails",
            value=details_value,
            inline=True
        )
        
        # Instructions claires et concises
        instructions = (
            "**💡 Comment enchérir:**\n"
            "• Tapez `/encherir` \n"
            "• Toutes les identités sont visibles\n"
            "• Pas de limite de temps fixe"
        )
        
        embed.add_field(
            name="🎯 Participation",
            value=instructions,
            inline=True
        )
        
        # Footer simplifié et informatif
        embed.set_footer(
            text=f"Atlant ARK • Système d'Enchères",
            icon_url="https://cdn.discordapp.com/emojis/🔨.png"
        )
        
        return embed
    
    @staticmethod
    def auction_bid(dino_name: str, old_price: int, new_price: int, 
                   bidder: str, auction_id: int, bidder_id: int = None) -> discord.Embed:
        """Embed pour une nouvelle enchère - Version ultra-claire"""
        
        increase = new_price - old_price
        percentage = (increase / old_price) * 100
        
        # Couleur et émoji dynamiques selon l'augmentation
        if percentage >= 50:
            embed_color = COLORS['premium']
            status_emoji = "🚀"
            status_text = "GROSSE ENCHÈRE"
        elif percentage >= 20:
            embed_color = COLORS['money']
            status_emoji = "🔥"
            status_text = "BELLE ENCHÈRE"
        else:
            embed_color = COLORS['success']
            status_emoji = "📈"
            status_text = "ENCHÈRE"
        
        embed = discord.Embed(
            title=f"{status_emoji} NOUVELLE {status_text}",
            color=embed_color,
            timestamp=datetime.utcnow()
        )
        
        # Header avec dino et enchérisseur
        header = f"# 🦖 **{dino_name}** (#{auction_id})\n"
        header += f"╰─ **Enchérisseur:** {bidder}"
        embed.description = header
        
        # Evolution des prix de façon très claire
        embed.add_field(
            name="� Ancien Prix",
            value=f"~~{old_price:,}~~ Aqualis",
            inline=True
        )
        
        embed.add_field(
            name="📊 Nouveau Prix", 
            value=f"**`{new_price:,}`** Aqualis",
            inline=True
        )
        
        embed.add_field(
            name="� Augmentation",
            value=f"**+{increase:,}** `({percentage:.1f}%)`",
            inline=True
        )
        
        # Séparateur
        embed.add_field(name="━━━━━━━━━━━━━━━━━━━━━━━", value="", inline=False)
        
        # Status et call to action clair
        bidder_mention = f"<@{bidder_id}>" if bidder_id else bidder
        
        status_section = f"**{status_emoji} {status_text} !**\n\n"
        status_section += f"**👤 Dernier enchérisseur:** {bidder_mention}\n"
        status_section += f"**⏰ Temps:** {datetime.utcnow().strftime('%H:%M:%S')}\n\n"
        status_section += f"💡 **Surenchérissez avec `/encherir` !**"
        
        embed.add_field(
            name="🎯 Statut de l'Enchère",
            value=status_section,
            inline=False
        )
        
        # Footer simplifié
        embed.set_footer(
            text="Atlant ARK • Enchères en temps réel"
        )
        return embed
    
    @staticmethod
    def auction_won(dino_name: str, final_price: int, winner: str, 
                   seller: str, auction_id: int, winner_id: int = None, seller_id: int = None) -> discord.Embed:
        """Embed pour une enchère gagnée - Version ultra-claire"""
        
        embed = discord.Embed(
            title="🏆 ENCHÈRE TERMINÉE",
            color=COLORS['success'],
            timestamp=datetime.utcnow()
        )
        
        # Header de victoire très visible
        header = f"# 🎉 **{dino_name} - VENDU !**\n"
        header += f"╰─ **Enchère #{auction_id}** • Transaction réussie ✅"
        embed.description = header
        
        # Informations de transaction claires
        embed.add_field(
            name="🏆 Gagnant",
            value=f"**{winner}**",
            inline=True
        )
        
        embed.add_field(
            name="💰 Prix Final",
            value=f"**`{final_price:,}`** Aqualis",
            inline=True
        )
        
        embed.add_field(
            name="👤 Vendeur", 
            value=f"**{seller}**",
            inline=True
        )
        
        # Grande séparation visuelle
        embed.add_field(name="━━━━━━━━━━━━━━━━━━━━━━━", value="", inline=False)
        
        # Instructions post-vente simplifiées et claires
        seller_mention = f"<@{seller_id}>" if seller_id else seller
        winner_mention = f"<@{winner_id}>" if winner_id else winner
        
        instructions = (
            "**📋 Prochaines étapes:**\n\n"
            f"**1️⃣ Contact:** {seller_mention} ↔️ {winner_mention}\n"
            f"**2️⃣ Livraison:** Organisez l'échange du dinosaure\n"
            f"**3️⃣ Serveur:** Partagez vos coordonnées si nécessaire\n\n"
            f"**✅ Transaction réussie !**"
        )
        
        embed.add_field(
            name="🎯 Instructions",
            value=instructions,
            inline=False
        )
        
        # Footer de félicitations simplifié
        embed.set_footer(
            text=f"🎉 Félicitations ! • {datetime.utcnow().strftime('%d/%m/%Y à %H:%M')} • Atlant ARK"
        )
        return embed
    
    @staticmethod
    def user_balance(username: str, balance: int, **kwargs) -> discord.Embed:
        """Embed pour afficher le solde"""
        
        embed = discord.Embed(
            title=f"{EMOJIS['money']} Solde de {username}",
            color=COLORS['money'],
            timestamp=datetime.utcnow()
        )
        
        # Couleur selon le solde
        if balance >= 1_000_000:
            description = f"{EMOJIS['gem']} **{balance:,}** Aqualis"
            embed.color = COLORS['premium']
        elif balance >= 100_000:
            description = f"{EMOJIS['crown']} **{balance:,}** Aqualis"
            embed.color = COLORS['success']
        elif balance <= 1000:
            description = f"⚠️ **{balance:,}** Aqualis"
            embed.color = COLORS['warning']
        else:
            description = f"💰 **{balance:,}** Aqualis"
        
        embed.description = description
        return EmbedBuilder._add_footer(embed, **kwargs)
    
    @staticmethod
    def admin_action(action: str, target: str, amount: int = None, 
                    reason: str = "Aucune raison", admin: str = "Système") -> discord.Embed:
        """Embed pour actions administratives"""
        
        embed = discord.Embed(
            title=f"🛡️ Action Administrative",
            color=COLORS['info'],
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(name="Action", value=action, inline=True)
        embed.add_field(name="Cible", value=target, inline=True)
        embed.add_field(name="Admin", value=admin, inline=True)
        
        if amount:
            embed.add_field(name="Montant", value=f"{amount:,} Aqualis", inline=True)
        
        embed.add_field(name="Raison", value=reason, inline=False)
        embed.set_footer(text="Action enregistrée dans les logs")
        return embed
    
    @staticmethod
    def leaderboard(title: str, users: List[Dict[str, Any]], 
                   field_name: str = "Solde") -> discord.Embed:
        """Embed pour classements"""
        
        embed = discord.Embed(
            title=f"{EMOJIS['crown']} {title}",
            color=COLORS['premium'],
            timestamp=datetime.utcnow()
        )
        
        medals = ['🥇', '🥈', '🥉']
        
        for i, user in enumerate(users[:10]):  # Top 10
            medal = medals[i] if i < 3 else f"{i+1}."
            username = user.get('username', 'Inconnu')
            value = user.get('value', 0)
            
            if isinstance(value, int):
                formatted_value = f"{value:,} Aqualis"
            else:
                formatted_value = str(value)
            
            embed.add_field(
                name=f"{medal} {username}",
                value=formatted_value,
                inline=True if i < 6 else False
            )
        
        embed.set_footer(text=f"Classement mis à jour • {len(users)} participants")
        return embed
    
    @staticmethod
    def _add_footer(embed: discord.Embed, footer: str = None, 
                   icon_url: str = None, **kwargs) -> discord.Embed:
        """Ajoute un footer personnalisé"""
        if footer:
            embed.set_footer(text=footer, icon_url=icon_url)
        elif not embed.footer:
            embed.set_footer(text="Atlant ARK • Système d'enchères")
        
        return embed

# Fonctions utilitaires pour embeds rapides
def quick_success(title: str, description: str = "") -> discord.Embed:
    return EmbedBuilder.success(title, description)

def quick_error(title: str, description: str = "") -> discord.Embed:
    return EmbedBuilder.error(title, description)

def quick_info(title: str, description: str = "") -> discord.Embed:
    return EmbedBuilder.info(title, description)

def quick_warning(title: str, description: str = "") -> discord.Embed:
    return EmbedBuilder.warning(title, description)