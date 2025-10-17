# ===== VALIDATEURS OPTIMISÉS =====
import re
from typing import Tuple, Union

def validate_price(price_str: str, min_price: int = 100) -> Tuple[bool, str, int]:
    """Valide un prix avec des règles améliorées"""
    try:
        price = int(price_str.strip())
        
        if price <= 0:
            return False, "Le prix doit être positif.", 0
        
        if price < min_price:
            return False, f"Prix minimum : {min_price:,} Aqualis.", 0
        
        if price % 100 != 0:
            return False, "Le prix doit être un multiple de 100 (ex: 1000, 1500, 2000).", 0
        
        if price > 10_000_000:  # 10 millions max
            return False, "Prix maximum : 10,000,000 Aqualis.", 0
        
        return True, "", price
        
    except ValueError:
        return False, "Prix invalide. Veuillez entrer un nombre entier.", 0

def validate_level(level_str: str) -> Tuple[bool, str, int]:
    """Valide un niveau de dino"""
    try:
        level = int(level_str.strip())
        
        if level < 1:
            return False, "Le niveau minimum est 1.", 0
        
        if level > 2000:
            return False, "Le niveau maximum est 2000.", 0
        
        return True, "", level
        
    except ValueError:
        return False, "Niveau invalide. Veuillez entrer un nombre entier.", 0

def validate_gender(gender_str: str) -> Tuple[bool, str, str]:
    """Valide et normalise le sexe avec variantes étendues"""
    gender = gender_str.strip().lower()
    
    gender_mapping = {
        # Mâle/Male - variantes
        'male': 'Male',
        'mâle': 'Male',
        'male': 'Male',
        'mål': 'Male',
        'mal': 'Male',
        'm': 'Male',
        'masculin': 'Male',
        'garçon': 'Male',
        'boy': 'Male',
        'homme': 'Male',
        'man': 'Male',
        
        # Femelle/Female - variantes
        'femelle': 'Femelle',
        'female': 'Femelle',
        'femel': 'Femelle',
        'femele': 'Femelle',
        'fémelle': 'Femelle',
        'f': 'Femelle',
        'féminin': 'Femelle',
        'fille': 'Femelle',
        'girl': 'Femelle',
        'femme': 'Femelle',
        'woman': 'Femelle',
        
        # Couple - variantes
        'couple': 'Couple',
        'couplé': 'Couple',
        'coupl': 'Couple',
        'c': 'Couple',
        'pair': 'Couple',
        'paire': 'Couple',
        'duo': 'Couple',
        'breeding': 'Couple',
        'breed': 'Couple',
        'reproduction': 'Couple',
        'repro': 'Couple',
        '2': 'Couple',
        'deux': 'Couple'
    }
    
    normalized = gender_mapping.get(gender)
    if not normalized:
        return False, "Sexe invalide. Utilisez : Male, Femelle ou Couple (accepte plusieurs variantes).", ""
    
    return True, "", normalized

def validate_mutations(mutations_str: str) -> Tuple[bool, str, str]:
    """Valide et normalise les mutations avec variantes étendues"""
    mutations = mutations_str.strip().lower()
    
    mutations_mapping = {
        # Avec mutations - variantes
        'avec': 'Avec muta',
        'avec muta': 'Avec muta',
        'avec mutations': 'Avec muta',
        'avec mut': 'Avec muta',
        'avec mutation': 'Avec muta',
        'avecmuta': 'Avec muta',
        'avecmutation': 'Avec muta',
        'oui': 'Avec muta',
        'yes': 'Avec muta',
        'true': 'Avec muta',
        'vrai': 'Avec muta',
        '1': 'Avec muta',
        'muta': 'Avec muta',
        'mut': 'Avec muta',
        'mutation': 'Avec muta',
        'mutations': 'Avec muta',
        'muté': 'Avec muta',
        'mutée': 'Avec muta',
        'mutant': 'Avec muta',
        'mutante': 'Avec muta',
        'colored': 'Avec muta',
        'color': 'Avec muta',
        'couleur': 'Avec muta',
        'coloré': 'Avec muta',
        'colorée': 'Avec muta',
        
        # Sans mutations - variantes  
        'sans': 'Sans muta',
        'sans muta': 'Sans muta',
        'sans mutations': 'Sans muta',
        'sans mut': 'Sans muta',
        'sans mutation': 'Sans muta',
        'sansmuta': 'Sans muta',
        'sansmutation': 'Sans muta',
        'non': 'Sans muta',
        'no': 'Sans muta',
        'false': 'Sans muta',
        'faux': 'Sans muta',
        '0': 'Sans muta',
        'normal': 'Sans muta',
        'naturel': 'Sans muta',
        'natural': 'Sans muta',
        'base': 'Sans muta',
        'basic': 'Sans muta',
        'basique': 'Sans muta',
        'standard': 'Sans muta',
        'classique': 'Sans muta',
        'wild': 'Sans muta',
        'sauvage': 'Sans muta'
    }
    
    normalized = mutations_mapping.get(mutations)
    if not normalized:
        return False, "Mutations invalides. Utilisez : Avec/Sans (accepte plusieurs variantes : oui/non, muta/normal, etc.).", ""
    
    return True, "", normalized

def validate_dino_name(name_str: str) -> Tuple[bool, str, str]:
    """Valide le nom du dino"""
    name = name_str.strip()
    
    if not name:
        return False, "Le nom du dino ne peut pas être vide.", ""
    
    if len(name) > 50:
        return False, "Le nom du dino ne peut pas dépasser 50 caractères.", ""
    
    # Vérifier les caractères interdits
    if re.search(r'[<>@#&]', name):
        return False, "Le nom contient des caractères interdits (<>@#&).", ""
    
    return True, "", name

def validate_ark_username(username_str: str) -> Tuple[bool, str, str]:
    """Valide un pseudo ARK"""
    username = username_str.strip()
    
    if not username:
        return False, "Le pseudo ne peut pas être vide.", ""
    
    if len(username) < 3:
        return False, "Le pseudo doit faire au moins 3 caractères.", ""
    
    if len(username) > 32:
        return False, "Le pseudo ne peut pas dépasser 32 caractères.", ""
    
    # Caractères autorisés : lettres, chiffres, tirets, underscores, espaces
    if not re.match(r'^[a-zA-Z0-9\-_ ]+$', username):
        return False, "Le pseudo ne peut contenir que des lettres, chiffres, tirets, underscores et espaces.", ""
    
    return True, "", username

def validate_amount_positive(amount: Union[str, int]) -> Tuple[bool, str]:
    """Valide qu'un montant est positif"""
    try:
        if isinstance(amount, str):
            amount = int(amount.strip())
        
        if amount <= 0:
            return False, "Le montant doit être positif."
        
        if amount > 1_000_000_000:  # 1 milliard max
            return False, "Montant trop élevé (max: 1,000,000,000)."
        
        return True, ""
        
    except (ValueError, TypeError):
        return False, "Montant invalide."

def validate_reason(reason_str: str) -> Tuple[bool, str, str]:
    """Valide une raison administrative"""
    reason = reason_str.strip()
    
    if len(reason) > 200:
        return False, "La raison ne peut pas dépasser 200 caractères.", ""
    
    # Filtrer les caractères potentiellement dangereux
    if re.search(r'[<>@]', reason):
        return False, "La raison contient des caractères interdits (<>@).", ""
    
    return True, "", reason or "Aucune raison spécifiée"

# Fonction utilitaire pour formater les montants
def format_currency(amount: int, currency: str = "Aqualis") -> str:
    """Formate un montant avec séparateurs"""
    return f"{amount:,} {currency}".replace(',', ' ')

def format_level(level: int) -> str:
    """Formate un niveau"""
    return f"Niv.{level}"

def sanitize_string(text: str, max_length: int = 100) -> str:
    """Nettoie et limite une chaîne de caractères"""
    # Retirer les caractères de contrôle
    text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
    
    # Limiter la longueur
    if len(text) > max_length:
        text = text[:max_length-3] + "..."
    
    return text.strip()

def get_gender_variants() -> str:
    """Retourne les variantes acceptées pour le sexe"""
    return ("**Mâle/Male:** male, mâle, m, masculin, garçon, homme\n"
            "**Femelle:** femelle, female, f, féminin, fille, femme\n" 
            "**Couple:** couple, c, pair, duo, breeding, repro, 2")

def get_mutations_variants() -> str:
    """Retourne les variantes acceptées pour les mutations"""
    return ("**Avec mutations:** avec, muta, mut, oui, yes, colored, couleur\n"
            "**Sans mutations:** sans, normal, non, no, naturel, wild, sauvage")