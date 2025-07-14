# catalogue_final.py

# --- Imports ---
import shopify
import os, re, json, hashlib, asyncio, traceback
import time as a_time, time as time_sleep
from datetime import time as dt_time, datetime, timedelta
from typing import List
import undetected_chromedriver as uc
import sqlite3, cloudscraper, discord
import requests 
from discord.ext import commands, tasks
from discord import app_commands
from commands import SlashCommands, MenuView
from bs4 import BeautifulSoup
from selenium import webdriver

from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

from shared_utils import (
    TOKEN, CHANNEL_ID, ROLE_ID_TO_MENTION, CATALOG_URL, BASE_URL,
    Logger, executor, paris_tz, initialize_database, config_manager,
    CACHE_FILE, RANKING_CHANNEL_ID, DB_FILE, THUMBNAIL_LOGO_URL, 
    create_styled_embed, get_product_counts, GUILD_ID, SELECTION_CHANNEL_ID

)

from graph_generator import create_radar_chart

# --- Initialisation du bot ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)
intents.members = True

update_time = dt_time(hour=8, minute=0, tzinfo=paris_tz)
ranking_time = dt_time(hour=16, minute=0, tzinfo=paris_tz)
selection_time = dt_time(hour=12, minute=0, tzinfo=paris_tz)

def scrape_site_data(): # On garde le même nom pour ne rien casser
    Logger.info("Démarrage de la récupération des données via l'API Shopify Admin...")
    
    try:
        # 1. Configuration de la session API avec le jeton d'accès Admin
        # Ces valeurs doivent venir de votre fichier .env ou config
        shop_url = os.getenv('SHOPIFY_SHOP_URL')
        api_version = os.getenv('SHOPIFY_API_VERSION')
        access_token = os.getenv('SHOPIFY_ADMIN_ACCESS_TOKEN')

        if not all([shop_url, api_version, access_token]):
            Logger.error("CRITIQUE : Les informations d'API Shopify Admin sont manquantes dans la configuration.")
            return None

        session = shopify.Session(shop_url, api_version, access_token)
        shopify.ShopifyResource.activate_session(session)

        # 2. Récupérer tous les produits publiés
        # Le statut 'active' assure qu'on ne prend que les produits visibles sur la boutique
        all_products_api = shopify.Product.find(status='active')
        
        products = []
        for prod in all_products_api:
            # On convertit l'objet API en dictionnaire, comme le faisait le scraper
            product_data = {}
            
            # --- Mappage des données ---
            product_data['name'] = prod.title
            # On construit l'URL du produit à partir du "handle"
            product_data['product_url'] = f"https://la-foncedalle.fr/products/{prod.handle}"
            
            # Image du produit
            product_data['image'] = prod.image.src if prod.image else None
            
            # Description
            desc_html = prod.body_html
            product_data['detailed_description'] = BeautifulSoup(desc_html, 'html.parser').get_text(strip=True) if desc_html else "Pas de description."

            # Gestion des variants (prix, stock)
            available_variants = [v for v in prod.variants if v.inventory_quantity > 0 or v.inventory_policy == 'continue']
            
            if not available_variants:
                product_data['is_sold_out'] = True
                product_data['price'] = "N/A"
                product_data['is_promo'] = False
                product_data['original_price'] = None
            else:
                product_data['is_sold_out'] = False
                # On prend le prix le plus bas parmi les variants disponibles
                min_price_variant = min(available_variants, key=lambda v: float(v.price))
                
                price = float(min_price_variant.price)
                compare_price = float(min_price_variant.compare_at_price) if min_price_variant.compare_at_price else 0.0
                
                # Le prix est "à partir de" s'il y a plus d'un variant disponible
                price_prefix = "à partir de " if len(available_variants) > 1 else ""
                product_data['price'] = f"{price_prefix}{price:.2f} €".replace('.', ',')
                
                product_data['is_promo'] = compare_price > price
                if product_data['is_promo']:
                    product_data['original_price'] = f"{compare_price:.2f} €".replace('.', ',')
                else:
                    product_data['original_price'] = None

            # Récupérer les metafields (taux CBD, etc.)
            product_data['stats'] = {}
            metafields = prod.metafields()
            for meta in metafields:
                # Vous devrez peut-être ajuster le "namespace" et la "key" selon votre configuration Shopify
                # Pour l'instant, on suppose une structure simple `namespace.key`
                label = meta.key.replace('_', ' ').capitalize() # Ex: 'taux_cbd' -> 'Taux cbd'
                product_data['stats'][label] = meta.value

            products.append(product_data)
            Logger.success(f"Produit récupéré via API : {product_data['name']}")

        # Nettoyer la session
        shopify.ShopifyResource.clear_session()
        
        Logger.success(f"Récupération API terminée. {len(products)} produits trouvés.")
        
        # NOTE: La récupération des "general_promos" du site n'est pas possible via l'API standard.
        # Vous pouvez soit les gérer manuellement dans votre config.json, soit garder une petite partie
        # de scraping juste pour ça si c'est absolument nécessaire. Pour l'instant, on la laisse vide.
        return {"timestamp": a_time.time(), "products": products, "general_promos": []}

    except Exception as e:
        Logger.error(f"CRITIQUE lors de la récupération via API Shopify : {repr(e)}")
        traceback.print_exc()
        return None

# Dans catalogue_final.py

async def post_weekly_selection(bot_instance: commands.Bot):
    Logger.info("Génération et publication de la sélection de la semaine...")
    
    if not GUILD_ID or not SELECTION_CHANNEL_ID:
        Logger.error("GUILD_ID ou SELECTION_CHANNEL_ID ne sont pas définis. Annulation.")
        return

    guild = bot_instance.get_guild(GUILD_ID)
    channel = bot_instance.get_channel(SELECTION_CHANNEL_ID)
    if not guild or not channel:
        Logger.error(f"Impossible de trouver la guilde ({GUILD_ID}) ou le salon ({SELECTION_CHANNEL_ID}).")
        return

    try:
        def _get_top_products_sync():
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    product_name,
                    AVG((COALESCE(visual_score,0) + COALESCE(smell_score,0) + COALESCE(touch_score,0) + COALESCE(taste_score,0) + COALESCE(effects_score,0)) / 5.0) as avg_score,
                    COUNT(id) as num_ratings
                FROM ratings GROUP BY LOWER(TRIM(product_name)) HAVING COUNT(id) > 0
                ORDER BY avg_score DESC LIMIT 3
            """)
            results = cursor.fetchall()
            conn.close()
            return results

        def _get_weekly_top_raters_sync():
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            seven_days_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
            cursor.execute("""
                SELECT user_id, COUNT(id) as weekly_rating_count FROM ratings
                WHERE rating_timestamp >= ? GROUP BY user_id ORDER BY weekly_rating_count DESC LIMIT 3
            """, (seven_days_ago,))
            results = cursor.fetchall()
            conn.close()
            return results

        def _read_product_cache_sync():
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)

        top_products, weekly_top_raters, site_data = await asyncio.gather(
            asyncio.to_thread(_get_top_products_sync),
            asyncio.to_thread(_get_weekly_top_raters_sync),
            asyncio.to_thread(_read_product_cache_sync)
        )

        if not top_products or not site_data.get("products"):
            Logger.warning("Données insuffisantes pour générer la sélection. Annulation.")
            return

        week_number = datetime.utcnow().isocalendar()[1]
        product_map = {p['name'].strip().lower(): p for p in site_data.get("products", [])}
        
        embed = create_styled_embed(
            f"🔎 Sélection de la Semaine #{week_number}",
            "Voici les 3 produits les mieux notés par la communauté !",
            color=discord.Color.purple()
        )
        
        medals = ["🥇", "🥈", "🥉"]
        for i, (prod_name, avg_score, num_ratings) in enumerate(top_products):
            prod = product_map.get(prod_name.strip().lower())
            note_str = f"**Note :** {round(avg_score,2)}/10\n"
            count_str = f"**Nombre de notations :** {num_ratings}\n"
            if prod:
                # --- LIGNE CORRIGÉE ---
                # On utilise 'detailed_description' et la méthode .get() pour plus de sécurité
                description = prod.get('detailed_description', 'Pas de description.')
                # On limite la description pour ne pas surcharger l'embed
                if len(description) > 150:
                    description = description[:150] + "..."
                
                value = f"{note_str}{count_str}[Voir sur le site]({prod.get('product_url', '#')})\nPrix : {prod.get('price', 'N/A')}\n{description}"
                # --- FIN DE LA CORRECTION ---
                
                embed.add_field(name=f"{medals[i]} {prod['name']}", value=value, inline=False)
                if i == 0 and prod.get("image"):
                    embed.set_thumbnail(url=prod["image"])
            else:
                embed.add_field(name=f"{medals[i]} {prod_name}", value=f"{note_str}{count_str}Produit non trouvé dans le cache.", inline=False)
            
            if i < len(top_products) - 1:
                embed.add_field(name="\u200b", value="▬▬▬▬▬▬▬▬▬▬", inline=False)

        if weekly_top_raters:
            embed.add_field(name="\u200b", value="▬▬▬▬▬▬▬▬▬▬", inline=False)
            thanks_text = ""
            for i, (user_id, weekly_count) in enumerate(weekly_top_raters):
                member = guild.get_member(user_id) # Essaye de trouver dans le cache (rapide)
                if member is None:
                    try:
                        # Si non trouvé, on le demande directement à Discord (fiable)
                        member = await guild.fetch_member(user_id)
                    except discord.NotFound:
                        member = None # L'utilisateur a vraiment quitté le serveur
                
                display_name = member.mention if member else f"Ancien Membre (ID: {user_id})"
                plural_s = 's' if weekly_count > 1 else ''
                thanks_text += f"{medals[i]} {display_name} (**{weekly_count}** nouvelle{plural_s} notation{plural_s})\n"
            
            embed.add_field(
                name="🌟 Un grand merci à nos Critiques de la Semaine !",
                value=thanks_text,
                inline=False
            )
        
        await channel.send(embed=embed)
        Logger.success("Sélection de la semaine publiée avec succès.")

    except Exception as e:
        Logger.error(f"Erreur lors de la génération de la sélection : {e}")
        traceback.print_exc()
def get_product_counts(products: List[dict]):
    hash_keywords = config_manager.get_config("categorization", {}).get("hash_keywords", [])
    hash_count = sum(1 for p in products if any(kw in p['name'].lower() for kw in hash_keywords))
    weed_count = len(products) - hash_count
    return hash_count, weed_count
class ProductView(discord.ui.View):
    def __init__(self, products: List[dict]):
        super().__init__(timeout=300)
        self.products = products; self.current_index = 0
        self.update_buttons()
    def update_buttons(self):
        self.children[0].disabled = self.current_index == 0
        self.children[1].disabled = self.current_index >= len(self.products) - 1
    def create_embed(self) -> discord.Embed:
        product = self.products[self.current_index]
        embed = discord.Embed(title=product['name'], url=product.get('product_url', CATALOG_URL), description=product['description'], color=discord.Color.from_rgb(255, 204, 0))
        embed.add_field(name="Prix à partir de", value=product['price'], inline=False)
        if product.get('image'): embed.set_thumbnail(url=product['image'])
        embed.set_footer(text=f"Produit {self.current_index + 1} sur {len(self.products)}")
        return embed
    async def update_message(self, interaction: discord.Interaction):
        self.update_buttons()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)
    @discord.ui.button(label="⬅️ Précédent", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_index > 0: self.current_index -= 1
        await self.update_message(interaction)
    @discord.ui.button(label="Suivant ➡️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_index < len(self.products) - 1: self.current_index += 1
        await self.update_message(interaction)


async def publish_menu(bot_instance: commands.Bot, site_data: dict, mention: bool = False):
    Logger.info(f"Publication du menu (mention: {mention})...")
    channel = bot_instance.get_channel(CHANNEL_ID)
    if not channel:
        Logger.error(f"Salon avec l'ID {CHANNEL_ID} non trouvé pour la publication.")
        return False
    
    products = site_data.get('products', [])
    
    # LOGIQUE D'AFFICHAGE EXPLICITE ET SÛRE
    promos_list = site_data.get('general_promos', [])
    if promos_list:
        general_promos_text = "\n".join([f"• {promo.strip()}" for promo in promos_list if promo.strip()])
    else:
        general_promos_text = "Aucune promotion générale en cours."
    
    # Si après le nettoyage la liste est vide, on remet le message par défaut
    if not general_promos_text:
        general_promos_text = "Aucune promotion générale en cours."

    hash_count, weed_count = get_product_counts(products)
    
    description_text = (
        f"__**📦 Produits disponibles :**__\n\n"
        f"**`Fleurs 🍃 :` {weed_count}**\n"
        f"**`Résines 🍫 :` {hash_count}**\n\n"
        f"__**💰 Promotions disponibles :**__\n\n{general_promos_text}\n\n"
        f"*(Mise à jour <t:{int(site_data.get('timestamp'))}:R>)*"
    )
    
    embed = discord.Embed(
        title="📢 Nouveautés et Promotions !", 
        url=CATALOG_URL, 
        description=description_text, 
        color=discord.Color.from_rgb(0, 102, 204)
    )
    
    main_logo_url = config_manager.get_config("contact_info.main_logo_url")
    if main_logo_url:
        embed.set_thumbnail(url=main_logo_url)
    
    view = MenuView(products)
    content = f"<@&{ROLE_ID_TO_MENTION}>" if mention and ROLE_ID_TO_MENTION else None
    last_message_id = await config_manager.get_state('last_message_id')
    
    try:
        # Le reste de la logique de publication est déjà correct
        if mention:
            if last_message_id:
                try:
                    old_message = await channel.fetch_message(int(last_message_id))
                    await old_message.delete()
                    Logger.info(f"Ancien message (ID: {last_message_id}) supprimé.")
                except (discord.NotFound, discord.Forbidden): pass
            new_message = await channel.send(content=content, embed=embed, view=view)
            await config_manager.update_state('last_message_id', str(new_message.id))
            Logger.success(f"Nouveau menu publié avec notification (ID: {new_message.id}).")
        else:
            if last_message_id:
                try:
                    message = await channel.fetch_message(int(last_message_id))
                    await message.edit(content=content, embed=embed, view=view)
                    Logger.info(f"Ancien message (ID: {last_message_id}) édité sans notification.")
                    return True
                except (discord.NotFound, discord.Forbidden):
                    Logger.warning(f"Impossible d'éditer le message {last_message_id}. Création d'un nouveau.")
            new_message = await channel.send(content=content, embed=embed, view=view)
            await config_manager.update_state('last_message_id', str(new_message.id))
            Logger.info(f"Nouveau menu créé sans notification (ID: {new_message.id}).")
        return True
    except Exception as e:
        Logger.error(f"Erreur fatale lors de la publication du menu : {e}"); traceback.print_exc()
        return False

# Dans catalogue_final.py

async def check_for_updates(bot_instance: commands.Bot, force_publish: bool = False):
    Logger.info("Vérification programmée du menu...")
    site_data = await bot_instance.loop.run_in_executor(executor, scrape_site_data)
    
    if not site_data or not site_data.get('products'):
        Logger.error("Scraping échoué, la vérification s'arrête.")
        return False # Indique qu'aucune mise à jour n'a été faite

    data_to_hash = {
        'products': site_data.get('products', []),
        'general_promos': sorted(site_data.get('general_promos', [])) 
    }
    
    current_hash = hashlib.sha256(json.dumps(data_to_hash, sort_keys=True).encode('utf-8')).hexdigest()
    last_hash = await config_manager.get_state('last_menu_hash', "")

    if current_hash != last_hash or force_publish:
        Logger.info(f"Changement détecté (ou forcé). Publication du menu. Forcé: {force_publish}")
        
        def write_cache():
            with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(site_data, f, indent=4, ensure_ascii=False)
        await asyncio.to_thread(write_cache)
        Logger.success(f"Nouveau hash {current_hash} et cache sauvegardés.")
        
        if await publish_menu(bot_instance, site_data, mention=True): 
            await config_manager.update_state('last_menu_hash', current_hash)
            return True # Indique qu'une mise à jour a été faite
        else:
            return False # La publication a échoué
    else:
        Logger.info("Aucun changement détecté.")
        await publish_menu(bot_instance, site_data, mention=False) # On met quand même à jour le timestamp
        return False # Indique qu'aucune mise à jour n'a été faite
async def force_republish_menu(bot_instance: commands.Bot):
    Logger.info("Publication forcée du menu demandée..."); await check_for_updates(bot_instance, force_publish=True)
async def generate_and_send_ranking(bot_instance: commands.Bot, force_run: bool = False):
    Logger.info("Exécution de la logique de classement...")
    today = datetime.now(paris_tz)
    if not force_run and today.weekday() != 6: # 6 = Dimanche
        Logger.info("Aujourd'hui n'est pas dimanche, le classement hebdomadaire est sauté.")
        return
    ranking_channel_id = RANKING_CHANNEL_ID or CHANNEL_ID
    channel = bot_instance.get_channel(ranking_channel_id)
    if not channel:
        Logger.error(f"Salon du classement (ID: {ranking_channel_id}) non trouvé.")
        return
    def _get_top_products_sync():
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        seven_days_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        cursor.execute("SELECT product_name, AVG((visual_score + smell_score + touch_score + taste_score + effects_score) / 5.0), COUNT(id) FROM ratings WHERE rating_timestamp >= ? GROUP BY product_name HAVING COUNT(id) > 0 ORDER BY AVG((visual_score + smell_score + touch_score + taste_score + effects_score) / 5.0) DESC LIMIT 3", (seven_days_ago,))
        results = cursor.fetchall()
        conn.close()
        return results
    try:
        top_products = await asyncio.to_thread(_get_top_products_sync)
    except Exception as e:
        Logger.error(f"Erreur lors de la génération du classement : {e}"); traceback.print_exc()
        return
    title_prefix = "🏆 Podium de la Semaine"
    if force_run: title_prefix = "DEBUG - " + title_prefix
    if not top_products:
        Logger.info("Aucune nouvelle note cette semaine, pas de classement à publier.")
        if force_run: await channel.send("🏆 (DEBUG) Aucune nouvelle note cette semaine, pas de classement à publier.")
        return
    product_details_map = {}
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f: site_data = json.load(f)
        product_details_map = {p['name'].strip().lower(): p for p in site_data.get('products', [])}
    except (FileNotFoundError, json.JSONDecodeError) as e:
        Logger.warning(f"Cache des produits non trouvé pour classement : {e}. Le classement sera publié sans images.")
    embed = discord.Embed(title=title_prefix, description="Voici les 3 produits les mieux notés par la communauté ces 7 derniers jours. Bravo à eux !", color=discord.Color.gold())
    winner_name = top_products[0][0]
    if (winner_details := product_details_map.get(winner_name.strip().lower())) and (winner_image := winner_details.get('image')):
        embed.set_thumbnail(url=winner_image)
    medals = ["🥇", "🥈", "🥉"]
    for i, (name, avg_score, count) in enumerate(top_products):
        embed.add_field(name=f"{medals[i]} {name}", value=f"**Note moyenne : {avg_score:.2f}/10**\n*sur la base de {count} notation(s)*", inline=False)
    embed.set_footer(text=f"Classement du {today.strftime('%d/%m/%Y')}. Continuez de noter !")
    try:
        await channel.send(embed=embed)
        Logger.success(f"Classement (Forcé: {force_run}) publié avec succès.")
    except Exception as e:
        Logger.error(f"Impossible d'envoyer le message de classement : {e}")

bot.force_republish_menu = force_republish_menu
bot.check_for_updates = check_for_updates
bot.post_weekly_selection = post_weekly_selection

# --- Tâches et Commandes ---
@tasks.loop(time=update_time)
async def scheduled_check(): await check_for_updates(bot)
@tasks.loop(time=ranking_time)
async def post_weekly_ranking(): await generate_and_send_ranking(bot)
@tasks.loop(time=selection_time)
async def scheduled_selection():
    if datetime.now(paris_tz).weekday() == 0: await post_weekly_selection(bot)

# --- Événements et Gestionnaires d'erreur ---
@bot.event
async def on_ready():
    Logger.success(f'Connecté en tant que {bot.user.name}')
    await bot.tree.sync()
    Logger.success("Commandes slash synchronisées.")
    
    await asyncio.to_thread(initialize_database)

    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f: site_data = json.load(f)
        products = site_data.get('products', [])
        if products: bot.add_view(MenuView(products)); Logger.success("Vue de menu persistante ré-enregistrée.")
    except Exception as e: Logger.warning(f"Impossible de charger la vue persistante: {e}")

    await check_for_updates(bot, force_publish=False)
    
    # Démarrage des tâches une seule fois
    if not scheduled_check.is_running(): scheduled_check.start()
    if not post_weekly_ranking.is_running(): post_weekly_ranking.start()
    if not scheduled_selection.is_running(): scheduled_selection.start()
    Logger.success("Toutes les tâches programmées ont démarré.")

# GESTIONNAIRE D'ERREUR CORRECT ET UNIQUE
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        Logger.warning(f"Accès refusé pour {interaction.user.name} à la commande /{interaction.command.name}.")
        embed = discord.Embed(title="🚫 Accès Refusé", description="Désolé, mais tu n'as pas les permissions nécessaires pour utiliser cette commande.", color=discord.Color.red())
        if THUMBNAIL_LOGO_URL:
            embed.set_thumbnail(url=THUMBNAIL_LOGO_URL)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    Logger.error(f"Erreur non gérée dans la commande /{interaction.command.name}: {error}")
    traceback.print_exc()
    error_message = "❌ Oups ! Une erreur inattendue est survenue. Le staff a été notifié."
    if interaction.response.is_done():
        await interaction.followup.send(error_message, ephemeral=True)
    else:
        await interaction.response.send_message(error_message, ephemeral=True)

# --- Main ---
async def main():
    async with bot:
        await bot.load_extension("commands")
        await bot.start(TOKEN)

if __name__ == "__main__":
    if TOKEN and CHANNEL_ID:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            Logger.warning("Arrêt du bot demandé.")
        finally:
            if not executor._shutdown:
                Logger.info("Fermeture de l'exécuteur...")
                executor.shutdown(wait=True)
                Logger.success("Exécuteur fermé.")
    else:
        Logger.error("Le DISCORD_TOKEN ou le CHANNEL_ID ne sont pas définis dans le fichier .env")