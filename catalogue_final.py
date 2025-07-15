# catalogue_final.py

# --- Imports ---
import os
import json
import hashlib
import asyncio
import traceback
import time as a_time
from datetime import time as dt_time, datetime, timedelta
from typing import List
import sqlite3

# Imports des librairies nécessaires
import shopify
import discord
from discord.ext import commands, tasks
from discord import app_commands
from bs4 import BeautifulSoup # Toujours utile pour nettoyer le HTML des descriptions

# Imports depuis vos fichiers de projet
from commands import MenuView # On importe MenuView car on en a besoin dans on_ready
from shared_utils import (
    TOKEN, CHANNEL_ID, ROLE_ID_TO_MENTION, CATALOG_URL,
    Logger, executor, paris_tz, initialize_database, config_manager,
    CACHE_FILE, RANKING_CHANNEL_ID, DB_FILE, THUMBNAIL_LOGO_URL,
    create_styled_embed, get_product_counts, GUILD_ID, SELECTION_CHANNEL_ID, 
)
from graph_generator import create_radar_chart

# --- Initialisation du bot ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Configuration des heures pour les tâches programmées
update_time = dt_time(hour=8, minute=0, tzinfo=paris_tz)
ranking_time = dt_time(hour=16, minute=0, tzinfo=paris_tz)
selection_time = dt_time(hour=12, minute=0, tzinfo=paris_tz)


# --- NOUVELLE FONCTION BASÉE UNIQUEMENT SUR L'API SHOPIFY ---
def get_site_data_from_api():
    """
    Récupère les données des produits directement depuis l'API Admin de Shopify.
    """
    Logger.info("Démarrage de la récupération des données via l'API Shopify Admin...")
    
    try:
        shop_url = os.getenv('SHOPIFY_SHOP_URL')
        api_version = os.getenv('SHOPIFY_API_VERSION')
        access_token = os.getenv('SHOPIFY_ADMIN_ACCESS_TOKEN')

        if not all([shop_url, api_version, access_token]):
            Logger.error("CRITIQUE : Les informations d'API Shopify Admin sont manquantes dans le .env.")
            # Log pour voir ce qui manque exactement
            Logger.error(f"URL: {'OK' if shop_url else 'MANQUANT'}, Version: {'OK' if api_version else 'MANQUANT'}, Token: {'OK' if access_token else 'MANQUANT'}")
            return None

        session = shopify.Session(shop_url, api_version, access_token)
        shopify.ShopifyResource.activate_session(session)

        # 2. Récupérer tous les produits publiés
        all_products_api = shopify.Product.find(status='active', limit=250)
        
        products = []
        for prod in all_products_api:
            product_data = {}
            
            # --- Mappage des données ---
            product_data['name'] = prod.title
            product_data['product_url'] = f"https://la-foncedalle.fr/products/{prod.handle}"
            product_data['image'] = prod.image.src if prod.image else None
            
            desc_html = prod.body_html
            product_data['detailed_description'] = BeautifulSoup(desc_html, 'html.parser').get_text(strip=True, separator='\n') if desc_html else "Pas de description."

            # Gestion des variants (prix, stock)
            available_variants = [v for v in prod.variants if v.inventory_quantity > 0 or v.inventory_policy == 'continue']
            
            if not available_variants:
                product_data['is_sold_out'] = True
                product_data['price'] = "N/A"
                product_data['is_promo'] = False
                product_data['original_price'] = None
            else:
                product_data['is_sold_out'] = False
                min_price_variant = min(available_variants, key=lambda v: float(v.price))
                
                price = float(min_price_variant.price)
                compare_price = float(min_price_variant.compare_at_price) if min_price_variant.compare_at_price else 0.0
                
                price_prefix = "à partir de " if len(available_variants) > 1 else ""
                product_data['price'] = f"{price_prefix}{price:.2f} €".replace('.', ',')
                
                product_data['is_promo'] = compare_price > price
                product_data['original_price'] = f"{compare_price:.2f} €".replace('.', ',') if product_data['is_promo'] else None

            # Récupérer les metafields (taux CBD, etc.)
            product_data['stats'] = {}
            metafields = prod.metafields()
            for meta in metafields:
                # Vous pouvez affiner ici si vous connaissez les 'namespace' et 'key' exacts
                label = meta.key.replace('_', ' ').capitalize()
                product_data['stats'][label] = meta.value

            products.append(product_data)
        
        Logger.success(f"Récupération API terminée. {len(products)} produits trouvés.")
        
        # NOTE: La récupération des "general_promos" (bandeaux, popups) n'est pas possible via l'API.
        # Cette partie est maintenant vide. Vous pouvez gérer les promotions générales manuellement
        # dans votre config.json si nécessaire.
        return {"timestamp": a_time.time(), "products": products, "general_promos": []}

    except Exception as e:
        Logger.error(f"CRITIQUE lors de la récupération via API Shopify : {repr(e)}")
        traceback.print_exc()
        return None
    finally:
        # S'assurer de toujours nettoyer la session
        shopify.ShopifyResource.clear_session()


# --- La suite du code reste identique, car elle dépend du format des données, pas de la méthode de récupération ---


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
                description = prod.get('detailed_description', 'Pas de description.')
                if len(description) > 150:
                    description = description[:150] + "..."
                
                value = f"{note_str}{count_str}[Voir sur le site]({prod.get('product_url', '#')})\nPrix : {prod.get('price', 'N/A')}\n{description}"
                
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
                member = guild.get_member(user_id)
                if member is None:
                    try:
                        member = await guild.fetch_member(user_id)
                    except discord.NotFound:
                        member = None
                
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


async def publish_menu(bot_instance: commands.Bot, site_data: dict, mention: bool = False):
    Logger.info(f"Publication du menu (mention: {mention})...")
    channel = bot_instance.get_channel(CHANNEL_ID)
    if not channel:
        Logger.error(f"Salon avec l'ID {CHANNEL_ID} non trouvé pour la publication. Vérifiez que CHANNEL_ID correspond bien au salon #nouveaux-drop.")
        return False

    products = site_data.get('products', [])
    promos_list = site_data.get('general_promos', [])
    general_promos_text = "\n".join([f"• {promo.strip()}" for promo in promos_list if promo.strip()]) or "Aucune promotion générale en cours."

    # Correction ici : on récupère toutes les catégories
    hash_count, weed_count, box_count, accessoire_count = get_product_counts(products)

    description_text = (
        f"__**📦 Produits disponibles :**__\n\n"
        f"**`Fleurs 🍃 :` {weed_count}**\n"
        f"**`Résines 🍫 :` {hash_count}**\n"
        f"**`Box 📦 :` {box_count}**\n"
        f"**`Accessoires 🛠️ :` {accessoire_count}**\n\n"
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
    bot_instance.add_view(view)  # Ajoute la vue persistante à chaque publication

    content = f"<@&{ROLE_ID_TO_MENTION}>" if mention and ROLE_ID_TO_MENTION else None
    last_message_id = await config_manager.get_state('last_message_id')
    
    try:
        # Toujours supprimer l'ancien menu avant d'envoyer le nouveau
        if last_message_id:
            try:
                old_message = await channel.fetch_message(int(last_message_id))
                await old_message.delete()
            except (discord.NotFound, discord.Forbidden):
                pass
        new_message = await channel.send(content=content, embed=embed, view=view)
        await config_manager.update_state('last_message_id', str(new_message.id))
        Logger.success(f"Nouveau menu publié (ID: {new_message.id}).")
        return True
    except Exception as e:
        Logger.error(f"Erreur fatale lors de la publication du menu : {e}"); traceback.print_exc()
        return False


async def check_for_updates(bot_instance: commands.Bot, force_publish: bool = False):
    Logger.info("Vérification programmée du menu...")
    site_data = await bot_instance.loop.run_in_executor(executor, get_site_data_from_api)
    
    if not site_data or 'products' not in site_data:
        Logger.error("Récupération des données API échouée, la vérification s'arrête.")
        return False

    # --- ÉTAPE 1 : ON ÉCRIT LE CACHE IMMÉDIATEMENT APRÈS LA RÉCUPÉRATION ---
    # C'est la correction la plus importante.
    def write_cache():
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(site_data, f, indent=4, ensure_ascii=False)
    await asyncio.to_thread(write_cache)
    Logger.success(f"Cache de produits mis à jour sur le disque avec {len(site_data.get('products', []))} produits.")

    # --- ÉTAPE 2 : On continue avec la logique de hash comme avant ---
    data_to_hash = {
        'products': site_data.get('products', []),
        'general_promos': sorted(site_data.get('general_promos', [])) 
    }
    
    current_hash = hashlib.sha256(json.dumps(data_to_hash, sort_keys=True).encode('utf-8')).hexdigest()
    last_hash = await config_manager.get_state('last_menu_hash', "")

    if current_hash != last_hash or force_publish:
        Logger.info(f"Changement détecté (ou forcé). Publication du menu. Forcé: {force_publish}")
        
        # On n'a plus besoin d'écrire le cache ici, c'est déjà fait.
        
        if await publish_menu(bot_instance, site_data, mention=True): 
            await config_manager.update_state('last_menu_hash', current_hash)
            return True
        else:
            return False
    else:
        Logger.info("Aucun changement détecté.")
        # On appelle quand même publish_menu pour s'assurer que le message est bien là, mais sans mention.
        await publish_menu(bot_instance, site_data, mention=False)
        return False
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

    # --- NOUVEL ORDRE DE DÉMARRAGE ---

    # 1. On lance la vérification qui va obligatoirement remplir le cache
    Logger.info("Exécution de la vérification initiale au démarrage pour remplir le cache...")
    await check_for_updates(bot, force_publish=False)
    
    # 2. Maintenant que le cache est rempli, on charge la vue persistante
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            site_data = json.load(f)
        products = site_data.get('products', [])
        if products:
            bot.add_view(MenuView(products))
            Logger.success("Vue de menu persistante ré-enregistrée avec succès.")
        else:
            # Ce cas ne devrait plus arriver, mais c'est une sécurité
            Logger.warning("Le cache est valide mais ne contient aucun produit. La vue persistante n'a pas été chargée.")
    except Exception as e:
        Logger.error(f"Échec critique du chargement de la vue persistante après la mise à jour : {e}")

    # 3. On démarre les tâches programmées pour le futur
    if not scheduled_check.is_running(): scheduled_check.start()
    if not post_weekly_ranking.is_running(): post_weekly_ranking.start()
    if not scheduled_selection.is_running(): scheduled_selection.start()
    Logger.success("Toutes les tâches programmées ont démarré.")


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
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