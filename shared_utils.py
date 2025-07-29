import os
import sqlite3
import discord
import json
from dotenv import load_dotenv
from colorama import init, Fore
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
import asyncio
from typing import List, Optional

# --- Initialisation ---
init(autoreset=True)
load_dotenv()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
STATE_FILE = os.path.join(BASE_DIR, "bot_state.json") # Définir STATE_FILE ici

# --- Constantes & Secrets (depuis .env) ---
TOKEN = os.getenv('DISCORD_TOKEN')
APP_URL = os.getenv('APP_URL')
CHANNEL_ID = int(os.getenv('CHANNEL_ID')) if os.getenv('CHANNEL_ID') else None
RANKING_CHANNEL_ID = int(os.getenv('RANKING_CHANNEL_ID')) if os.getenv('RANKING_CHANNEL_ID') else None
ROLE_ID_TO_MENTION = os.getenv('ROLE_ID_TO_MENTION')
STAFF_ROLE_ID = os.getenv('STAFF_ROLE_ID')
SELECTION_CHANNEL_ID = int(os.getenv('SELECTION_CHANNEL_ID')) if os.getenv('SELECTION_CHANNEL_ID') else None
GUILD_ID = int(os.getenv('GUILD_ID')) if os.getenv('GUILD_ID') else None

# --- Fichiers de données ---
CACHE_FILE = os.path.join(BASE_DIR, 'scrape_cache.json')
USER_LOG_FILE = os.path.join(BASE_DIR, "user_actions.log")
DB_FILE = "/app/ratings.db"
NITRO_CODES_FILE = os.path.join(BASE_DIR, "nitro_codes.txt")
CLAIMED_CODES_FILE = os.path.join(BASE_DIR, "claimed_nitro_codes.json")

# --- Objets Partagés ---
executor = ThreadPoolExecutor(max_workers=2)
paris_tz = timezone(timedelta(hours=2))

# --- Emojis (définis avant d'être utilisés) ---
TIKTOK_EMOJI = discord.PartialEmoji(name="TikToklogo", id=1392768463642296361)
LFONCEDALLE_EMOJI = discord.PartialEmoji(name="LaFoncedalle_logo", id=1391890495088754769)
LFONCEDALLE_PLAT_EMOJI = discord.PartialEmoji(name="LaFoncedalle_plat", id=1392778604122738729)
TELEGRAM_EMOJI = discord.PartialEmoji(name="Telegram_logo", id=1392126944543244389)
INSTAGRAM_EMOJI = discord.PartialEmoji(name="Instagram_logo", id=1392125999726071918)
SUCETTE_EMOJI = discord.PartialEmoji(name="Sucette", id=1392148327851753572)

# --- Classes Utilitaires ---
class Logger:
    @staticmethod
    def info(message): print(f"{Fore.CYAN}INFO: {message}")
    @staticmethod
    def success(message): print(f"{Fore.GREEN}SUCCESS: {message}")
    @staticmethod
    def error(message): print(f"{Fore.RED}ERROR: {message}")
    @staticmethod
    def action(message): print(f"{Fore.BLUE}ACTION: {message}")
    @staticmethod
    def warning(message): print(f"{Fore.YELLOW}WARNING: {message}")

class ConfigManager:
    def __init__(self, config_path, state_path):
        self.config_path = config_path
        self.state_path = state_path
        self._lock = asyncio.Lock()
        self.config = self._sync_load_json(self.config_path)
        if self.config:
            Logger.success(f"Configuration chargée depuis '{self.config_path}'.")
        else:
            Logger.warning(f"Fichier de configuration '{self.config_path}' non trouvé ou vide.")

    def get_config(self, key, default=None):
        keys = key.split('.')
        val = self.config
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k)
            else:
                return default
        return val if val is not None else default

    # --- MÉTHODES MODIFIÉES ---
    async def update_config(self, key_path: str, value):
        """Met à jour une valeur dans le fichier de configuration principal (config.json) et le sauvegarde."""
        async with self._lock:
            keys = key_path.split('.')
            current_level = self.config
            
            for i, key in enumerate(keys[:-1]):
                if key not in current_level or not isinstance(current_level[key], dict):
                    current_level[key] = {}
                current_level = current_level[key]
            
            current_level[keys[-1]] = value
            
            # Sauvegarde asynchrone dans le fichier config.json
            success = await asyncio.to_thread(self._sync_save_json, self.config, self.config_path)
            if not success:
                Logger.error(f"Échec de la mise à jour de la configuration pour la clé '{key_path}'.")
            else:
                Logger.info(f"Configuration mise à jour pour la clé '{key_path}'.")

    async def get_state(self, guild_id: int, key: str, default=None):
        """Récupère une valeur de configuration pour un serveur spécifique."""
        async with self._lock:
            current_state = await self._async_load_json(self.state_path)
            # On cherche d'abord dans le dictionnaire du serveur, puis on retourne le défaut
            return current_state.get(str(guild_id), {}).get(key, default)

    async def update_state(self, guild_id: int, key: str, value):
        """Met à jour une valeur de configuration pour un serveur spécifique."""
        async with self._lock:
            current_state = await self._async_load_json(self.state_path)
            guild_id_str = str(guild_id)
            
            # Si c'est la première config pour ce serveur, on crée son dictionnaire
            if guild_id_str not in current_state:
                current_state[guild_id_str] = {}
            
            current_state[guild_id_str][key] = value
            
            success = await asyncio.to_thread(self._sync_save_json, current_state, self.state_path)
            if not success:
                Logger.error(f"Échec de la mise à jour de l'état pour la clé '{key}' sur le serveur {guild_id}.")

    # --- NOUVELLE MÉTHODE UTILE ---
    async def get_all_configured_guilds(self) -> List[int]:
        """Retourne une liste des ID de tous les serveurs ayant une configuration."""
        async with self._lock:
            current_state = await self._async_load_json(self.state_path)
            try:
                # On ne retourne que les clés qui sont des ID de serveur valides
                return [int(guild_id) for guild_id in current_state.keys() if guild_id.isdigit()]
            except (ValueError, TypeError):
                return []

    def _sync_load_json(self, file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f: return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError): return {}

    async def _async_load_json(self, file_path):
        return await asyncio.to_thread(self._sync_load_json, file_path)

    def _sync_save_json(self, data, file_path):
        """Sauvegarde de manière synchrone les données JSON dans un fichier (écriture directe)."""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            Logger.error(f"Impossible de sauvegarder le JSON dans '{file_path}': {e}")
            return False

# --- ORDRE DE DÉFINITION CORRIGÉ ---
config_manager = ConfigManager(CONFIG_FILE, STATE_FILE)
CATALOG_URL = os.getenv('CATALOG_URL')
BASE_URL = "https://la-foncedalle.fr"
THUMBNAIL_LOGO_URL = config_manager.get_config("contact_info.thumbnail_logo_url", "")

def anonymize_email(email: str) -> str:
    """Anonymise une adresse e-mail en gardant la première et la dernière lettre."""
    if not email or '@' not in email:
        return "Inconnu"
    local_part, domain = email.split('@', 1)
    if len(local_part) <= 2:
        return f"{local_part[0]}*@{domain}"
    else:
        return f"{local_part[0]}{'*' * (len(local_part) - 2)}{local_part[-1]}@{domain}"
    
    
def categorize_products(products: list):
    """
    VERSION FINALE : Catégorise les produits en se basant sur la clé 'category' 
    qui a déjà été assignée lors de la récupération des données.
    """
    categorized = {
        "weed": [],
        "hash": [],
        "box": [],
        "accessoire": []
    }
    
    # Dictionnaire pour mapper les noms de catégorie du produit ('fleurs')
    # vers nos clés internes ('weed').
    category_map = {
        "fleurs": "weed",
        "résines": "hash",
        "box": "box",
        "accessoires": "accessoire"
    }
    
    for p in products:
        product_category = p.get('category')  # ex: "fleurs"
        internal_key = category_map.get(product_category)
        
        if internal_key and internal_key in categorized:
            categorized[internal_key].append(p)
            
    return categorized

def get_product_counts(products: list):
    """
    VERSION FINALE : Compte les produits en utilisant la même logique de catégorisation.
    """
    # On réutilise la fonction ci-dessus pour être 100% cohérent.
    categorized = categorize_products(products)
    
    return (
        len(categorized["hash"]),
        len(categorized["weed"]),
        len(categorized["box"]),
        len(categorized["accessoire"])
    )

async def log_user_action(interaction: discord.Interaction, action_description: str):
    user = interaction.user; guild = interaction.guild
    timestamp = datetime.now(paris_tz).strftime('%Y-%m-%d %H:%M:%S')
    log_message = f"[{timestamp}] User: {user.name} ({user.id}) | Guild: {guild.name if guild else 'DM'} | Action: {action_description}\n"
    Logger.action(f"User: {user.name} | Action: {action_description}")
    try:
        await asyncio.to_thread(lambda: open(USER_LOG_FILE, 'a', encoding='utf-8').write(log_message))
    except Exception as e: Logger.error(f"Impossible d'écrire dans le log : {e}")

def initialize_database():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(''' CREATE TABLE IF NOT EXISTS ratings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, 
                        user_id INTEGER NOT NULL, 
                        user_name TEXT NOT NULL, 
                        product_name TEXT NOT NULL, 
                        visual_score REAL, 
                        smell_score REAL, 
                        touch_score REAL, 
                        taste_score REAL, 
                        effects_score REAL, 
                        rating_timestamp TEXT NOT NULL, 
                        UNIQUE(user_id, product_name)) ''')
    try:
        cursor.execute("ALTER TABLE ratings ADD COLUMN comment TEXT")
        Logger.info("Colonne 'comment' ajoutée à la base de données.")
    except sqlite3.OperationalError:
        # La colonne existe déjà, on ne fait rien.
        pass

    conn.commit()
    conn.close()
    Logger.success(f"Base de données '{DB_FILE}' initialisée et à jour.")

def filter_catalog_products(products: list) -> list:
    """
    Filtre les produits pour exclure les box, accessoires, réseaux sociaux, etc.
    """
    exclude_keywords = [
        "box", "pack", "briquet", "feuille", "papier", "accessoire", "telegram", "instagram", "tiktok", "promo", "offre"
    ]
    filtered = []
    for p in products:
        name = p.get('name', '').lower()
        if any(kw in name for kw in exclude_keywords):
            continue
        filtered.append(p)
    return filtered

def create_styled_embed(title: str, description: str, color=discord.Color.blurple(), show_logo: bool = True) -> discord.Embed:
    """Crée un embed Discord avec un style prédéfini."""
    embed = discord.Embed(
        title=title,
        description=description,
        color=color
    )
    if show_logo and LFONCEDALLE_PLAT_EMOJI and LFONCEDALLE_PLAT_EMOJI.url:
        embed.set_thumbnail(url=LFONCEDALLE_PLAT_EMOJI.url)
    
    if LFONCEDALLE_EMOJI and LFONCEDALLE_EMOJI.url:
        embed.set_footer(text="LaFoncedalle", icon_url=LFONCEDALLE_EMOJI.url)
    else:
        embed.set_footer(text="LaFoncedalle")
    return embed

def get_general_promos():
    """Retourne la liste des promos générales depuis la config."""
    promos = config_manager.get_config("general.general_promos", [])
    # Nettoie les éventuels '\n' ou chaînes vides
    return [p.strip() for p in promos if p.strip()]

def get_db_connection():
    """Crée et retourne une connexion à la base de données avec le mode WAL activé."""
    conn = sqlite3.connect(DB_FILE, timeout=10) # On augmente un peu le timeout par sécurité
    conn.row_factory = sqlite3.Row # Permet d'accéder aux colonnes par leur nom
    conn.execute("PRAGMA journal_mode=WAL;") # La ligne la plus importante !
    return conn