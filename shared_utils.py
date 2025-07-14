# shared_utils.py

import os
import sqlite3
import discord
import json
from dotenv import load_dotenv
from colorama import init, Fore
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
import threading
import asyncio

# --- Initialisation ---
init(autoreset=True)
load_dotenv()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

# --- Constantes & Secrets (depuis .env) ---
TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = int(os.getenv('CHANNEL_ID')) if os.getenv('CHANNEL_ID') else None
RANKING_CHANNEL_ID = int(os.getenv('RANKING_CHANNEL_ID')) if os.getenv('RANKING_CHANNEL_ID') else None
ROLE_ID_TO_MENTION = os.getenv('ROLE_ID_TO_MENTION')
STAFF_ROLE_ID = os.getenv('STAFF_ROLE_ID')
SELECTION_CHANNEL_ID = int(os.getenv('SELECTION_CHANNEL_ID')) if os.getenv('SELECTION_CHANNEL_ID') else None
GUILD_ID = int(os.getenv('GUILD_ID')) if os.getenv('GUILD_ID') else None # Ajouté pour post_weekly_selection

# --- Fichiers de données ---
CACHE_FILE = os.path.join(BASE_DIR, 'scrape_cache.json')
USER_LOG_FILE = os.path.join(BASE_DIR, "user_actions.log")
DB_FILE = os.path.join(BASE_DIR, "ratings.db")
STATE_FILE = os.path.join(BASE_DIR, "bot_state.json")
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
        self._lock = threading.Lock()
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

    async def get_state(self, key, default=None):
        with self._lock:
            current_state = await self._async_load_json(self.state_path)
            return current_state.get(key, default)
    async def update_state(self, key, value):
        with self._lock:
            current_state = await self._async_load_json(self.state_path)
            current_state[key] = value
            success = await asyncio.to_thread(self._sync_save_json, current_state, self.state_path)
            if not success:
                Logger.error(f"Échec de la mise à jour de l'état pour la clé '{key}'.")
    def _sync_load_json(self, file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f: return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError): return {}
    async def _async_load_json(self, file_path):
        return await asyncio.to_thread(self._sync_load_json, file_path)
    def _sync_save_json(self, data, file_path):
        try:
            with open(file_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=2)
            return True
        except Exception as e:
            Logger.error(f"Impossible de sauvegarder l'état dans '{file_path}': {e}")
            return False

# --- ORDRE DE DÉFINITION CORRIGÉ ---
config_manager = ConfigManager(CONFIG_FILE, STATE_FILE)
CATALOG_URL = config_manager.get_config("general.CATALOG_URL", "")
BASE_URL = "https://la-foncedalle.fr"
THUMBNAIL_LOGO_URL = config_manager.get_config("contact_info.thumbnail_logo_url", "")


# --- Fonctions Utilitaires Globales ---

async def log_user_action(interaction: discord.Interaction, action_description: str):
    user = interaction.user; guild = interaction.guild
    timestamp = datetime.now(paris_tz).strftime('%Y-%m-%d %H:%M:%S')
    log_message = f"[{timestamp}] User: {user.name} ({user.id}) | Guild: {guild.name if guild else 'DM'} | Action: {action_description}\n"
    Logger.action(f"User: {user.name} | Action: {action_description}")
    try:
        await asyncio.to_thread(lambda: open(USER_LOG_FILE, 'a', encoding='utf-8').write(log_message))
    except Exception as e: Logger.error(f"Impossible d'écrire dans le log : {e}")

def initialize_database():
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute(''' CREATE TABLE IF NOT EXISTS ratings (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, user_name TEXT NOT NULL, product_name TEXT NOT NULL, visual_score REAL, smell_score REAL, touch_score REAL, taste_score REAL, effects_score REAL, rating_timestamp TEXT NOT NULL, UNIQUE(user_id, product_name)) ''')
    conn.commit(); conn.close()
    Logger.success(f"Base de données '{DB_FILE}' initialisée.")

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

def categorize_products(products: list):
    """
    Catégorise les produits en fleurs, résines, box, accessoires.
    Retourne un dict : {"weed": [...], "hash": [...], "box": [...], "accessoire": [...]}
    """
    hash_keywords = config_manager.get_config("categorization.hash_keywords", [])
    box_keywords = ["box", "pack"]
    accessoire_keywords = ["briquet", "feuille", "papier", "accessoire"]
    exclude_keywords = ["telegram", "instagram", "tiktok", "promo", "offre"]

    categorized = {"weed": [], "hash": [], "box": [], "accessoire": []}
    for p in products:
        name = p.get('name', '').lower()
        if any(kw in name for kw in exclude_keywords):
            continue
        if any(kw in name for kw in box_keywords):
            categorized["box"].append(p)
        elif any(kw in name for kw in accessoire_keywords):
            categorized["accessoire"].append(p)
        elif any(kw in name for kw in hash_keywords):
            categorized["hash"].append(p)
        else:
            categorized["weed"].append(p)
    return categorized

def get_product_counts(products: list):
    """
    Retourne le nombre de produits par catégorie (weed/hash/box/accessoire).
    """
    categorized = categorize_products(products)
    return (
        len(categorized["hash"]),
        len(categorized["weed"]),
        len(categorized["box"]),
        len(categorized["accessoire"])
    )

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