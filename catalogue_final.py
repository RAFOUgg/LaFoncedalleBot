# catalogue_final.py

# --- Imports ---
import os
import json
import hashlib
import asyncio
import traceback
import time
import time as a_time
from datetime import time as dt_time, datetime, timedelta
from typing import List, Optional
import sqlite3
import re
import asyncio # Assurez-vous qu'il est bien importé
# Imports des librairies nécessaires
import shopify
import discord
from discord.ext import commands, tasks # <--- CORRECTION : 'commands' et 'tasks' importés ici
from discord import app_commands
from bs4 import BeautifulSoup

# Imports depuis vos fichiers de projet
from commands import MenuView
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
bot.product_cache = {}

# Configuration des heures pour les tâches programmées
update_time = dt_time(hour=8, minute=0, tzinfo=paris_tz)
ranking_time = dt_time(hour=16, minute=0, tzinfo=paris_tz)
selection_time = dt_time(hour=12, minute=0, tzinfo=paris_tz)
role_sync_time = dt_time(hour=8, minute=5, tzinfo=paris_tz)

PRODUCTS_WITH_METAFIELDS_QUERY = """
query getProductsWithMetafields {
  products(first: 100, query: "published_status:published") {
    edges {
      node {
        id
        title
        handle
        bodyHtml
        images(first: 1) {
          edges {
            node { url }
          }
        }
        variants(first: 10) {
          edges {
            node {
              price
              compareAtPrice
              inventoryPolicy
              inventoryQuantity
            }
          }
        }
        collections(first: 5) {
          edges {
            node { title }
          }
        }
        metafields(first: 20) {
          edges {
            node {
              namespace
              key
              value
            }
          }
        }
      }
    }
  }
}
"""

def get_site_data_from_graphql():
    """
    Récupère toutes les données du site (produits, collections, méta-champs)
    en une seule requête GraphQL pour éviter le rate limiting.
    """
    Logger.info("Démarrage de la récupération via GraphQL Shopify...")
    
    try:
        shop_url = os.getenv('SHOPIFY_SHOP_URL')
        api_version = os.getenv('SHOPIFY_API_VERSION')
        access_token = os.getenv('SHOPIFY_ADMIN_ACCESS_TOKEN')

        if not all([shop_url, api_version, access_token]): 
            Logger.error("Identifiants Shopify manquants.")
            return None

        session = shopify.Session(shop_url, api_version, access_token)
        shopify.ShopifyResource.activate_session(session)
        
        client = shopify.GraphQL()
        result_json = client.execute(PRODUCTS_WITH_METAFIELDS_QUERY)
        result = json.loads(result_json)
        
        shopify.ShopifyResource.clear_session()

        # --- On traite la réponse GraphQL pour la transformer dans notre format habituel ---
        final_products = []
        WHITELISTED_STATS = ['effet', 'gout', 'goût', 'cbd', 'thc']
        
        for product_edge in result.get('data', {}).get('products', {}).get('edges', []):
            prod = product_edge['node']
            
            # Déterminer la catégorie
            category = "accessoire" # Par défaut
            collection_titles = [c['node']['title'].lower() for c in prod.get('collections', {}).get('edges', [])]
            if any("box" in title for title in collection_titles): category = "box"
            elif any("weed" in title for title in collection_titles): category = "weed"
            elif any("hash" in title for title in collection_titles): category = "hash"
            
            # Créer la structure de base du produit
            category_map_display = {"weed": "fleurs", "hash": "résines", "box": "box", "accessoire": "accessoires"}
            product_data = {
                'name': prod.get('title'),
                'product_url': f"https://la-foncedalle.fr/products/{prod.get('handle')}",
                'image': prod.get('images', {}).get('edges', [{}])[0].get('node', {}).get('url'),
                'category': category_map_display.get(category),
                'detailed_description': BeautifulSoup(prod.get('bodyHtml', ''), 'html.parser').get_text(separator='\n', strip=True),
                'stats': {},
                'box_contents': []
            }

            # Gestion des variants (prix, promo, stock)
            variants = [v['node'] for v in prod.get('variants', {}).get('edges', [])]
            available_variants = [v for v in variants if v.get('inventoryQuantity', 0) > 0 or v.get('inventoryPolicy') == 'CONTINUE']
            product_data['is_sold_out'] = not available_variants
            if available_variants:
                min_price_variant = min(available_variants, key=lambda v: float(v['price']))
                price = float(min_price_variant.get('price', 0))
                compare_price = float(min_price_variant.get('compareAtPrice', 0) or 0)
                product_data['is_promo'] = compare_price > price
                product_data['original_price'] = f"{compare_price:.2f} €".replace('.', ',') if product_data['is_promo'] else None
                price_prefix = "à partir de " if len(available_variants) > 1 and price > 0 else ""
                product_data['price'] = f"{price_prefix}{price:.2f} €".replace('.', ',') if price > 0 else "Cadeau !"
            else:
                product_data.update({'price': "N/A", 'is_promo': False, 'original_price': None})

            # Gestion des méta-champs
            metafields = [m['node'] for m in prod.get('metafields', {}).get('edges', [])]
            for meta in metafields:
                key_lower = meta.get('key', '').lower()
                value = meta.get('value', '')

                if category == 'box' and ('composition' in key_lower or 'contenu' in key_lower):
                    soup_meta = BeautifulSoup(value, 'html.parser')
                    all_lines = soup_meta.get_text(separator='\n').split('\n')
                    content_items = [line.strip().lstrip('-•* ').replace('*', '') for line in all_lines if line.strip() and not line.lower().startswith(('les hash', 'les fleurs', ':', 'les '))]
                    if content_items: product_data['box_contents'] = content_items
                    continue

                if key_lower in WHITELISTED_STATS:
                    product_data['stats'][meta.get('key').replace('_', ' ').capitalize()] = value
            
            final_products.append(product_data)
            
        general_promos = get_smart_promotions_from_api() # On garde l'ancienne méthode pour les promos

        Logger.success(f"Récupération GraphQL terminée. {len(final_products)} produits valides trouvés.")
        return {"timestamp": time.time(), "products": final_products, "general_promos": general_promos}

    except Exception as e:
        Logger.error(f"CRITIQUE lors de la récupération via GraphQL Shopify : {e}")
        traceback.print_exc()
        return None


# [MODIFIÉ]
def get_site_data_from_api():
    """
    Version FINALE ET ROBUSTE : Catégorise les produits en se basant sur leurs collections
    ET ne récupère QUE les produits PUBLIÉS sur la boutique en ligne.
    Cette version est refactorisée pour utiliser une fonction d'aide.
    """
    Logger.info("Démarrage de la récupération via API Shopify (par collection)...")
    
    try:
        shop_url = os.getenv('SHOPIFY_SHOP_URL')
        api_version = os.getenv('SHOPIFY_API_VERSION')
        access_token = os.getenv('SHOPIFY_ADMIN_ACCESS_TOKEN')

        if not all([shop_url, api_version, access_token]): 
            Logger.error("Identifiants Shopify manquants.")
            return None

        session = shopify.Session(shop_url, api_version, access_token)
        shopify.ShopifyResource.activate_session(session)
        shopify.Shop.current()

        # --- ÉTAPE 1 : Récupérer la liste de tous les produits PUBLIÉS ---
        published_products_api = shopify.Product.find(published_status='published', limit=250)
        published_product_ids = {prod.id for prod in published_products_api}
        Logger.info(f"{len(published_product_ids)} produits publiés trouvés sur la boutique.")

        # --- ÉTAPE 2 : Récupérer les promotions ---
        general_promos = get_smart_promotions_from_api()

        # --- ÉTAPE 3 : Traiter les collections pour catégoriser les produits ---
        collection_keyword_map = {
            "hash": "hash",
            "weed": "weed",
            "box": "box",
        }
        
        all_products = {} 
        gids_to_resolve = set()

        collections = shopify.CustomCollection.find()
        
        for collection in collections:
            collection_title_lower = collection.title.lower()
            category = None
            
            for keyword, cat in collection_keyword_map.items():
                if keyword in collection_title_lower:
                    category = cat
                    break

            if category:
                Logger.info(f"Analyse des produits de la collection '{collection.title}'...")
                products_in_collection = collection.products()
                
                for prod in products_in_collection:
                    if prod.id not in published_product_ids or prod.id in all_products:
                        continue
                    
                    if any(kw in prod.title.lower() for kw in ["telegram", "instagram", "tiktok"]):
                        continue

                    # On appelle la fonction d'aide pour extraire les données
                    product_data = _extract_product_data(prod, category, gids_to_resolve)
                    all_products[prod.id] = product_data

        # --- Logique de Fallback pour les produits hors-collection (ex: accessoires) ---
        Logger.info("Recherche des produits hors-collections (type accessoires)...")
        for prod in published_products_api:
            if prod.id in all_products:
                continue
            
            if any(kw in prod.title.lower() for kw in ["briquet", "feuille", "grinder", "accessoire"]):
                # On réutilise la même fonction d'aide, beaucoup plus propre !
                product_data = _extract_product_data(prod, "accessoire", gids_to_resolve)
                all_products[prod.id] = product_data
                Logger.info(f"Produit accessoire trouvé : {prod.title}")

        raw_products_data = list(all_products.values())
        
        # --- ÉTAPE 4 : Résolution des GIDs ---
        gid_url_map = {}
        if gids_to_resolve:
            Logger.info(f"Résolution de {len(gids_to_resolve)} GIDs pour les fichiers...")
            client = shopify.GraphQL()
            result_json = client.execute(RESOLVE_FILES_QUERY, variables={"ids": list(gids_to_resolve)})
            result = json.loads(result_json)
            for node in result.get('data', {}).get('nodes', []):
                if node:
                    gid = node.get('id')
                    url = node.get('url') or (node.get('image', {}).get('url') if 'image' in node else None)
                    if gid and url: 
                        gid_url_map[gid] = url

        # --- ÉTAPE 5 : Finalisation des données ---
        final_products = []
        for product_data in raw_products_data:
            for key, value in product_data['stats'].items():
                # Remplace les GID par les URL résolues
                if isinstance(value, str) and value in gid_url_map:
                    product_data['stats'][key] = gid_url_map[value]
            final_products.append(product_data)

        Logger.success(f"Récupération API terminée. {len(final_products)} produits PUBLIÉS valides trouvés.")
        return {"timestamp": a_time.time(), "products": final_products, "general_promos": general_promos}

    except Exception as e:
        Logger.error(f"CRITIQUE lors de la récupération via API Shopify : {repr(e)}")
        traceback.print_exc()
        return None
    finally:
        if 'shopify' in locals() and shopify.ShopifyResource.get_session():
            shopify.ShopifyResource.clear_session()

# Dans catalogue_final.py

async def post_weekly_selection(bot_instance: commands.Bot, guild_id_to_run: Optional[int] = None):
    async def run_for_guild(guild_id):
        Logger.info(f"Génération de la sélection de la semaine pour le serveur {guild_id}...")
        selection_channel_id = await config_manager.get_state(guild_id, 'selection_channel_id')

        if not selection_channel_id:
            Logger.warning(f"Pas de salon de sélection configuré pour le serveur {guild_id}. On saute.")
            return

        guild = bot_instance.get_guild(guild_id)
        channel = bot_instance.get_channel(selection_channel_id)
        if not guild or not channel:
            Logger.error(f"Impossible de trouver la guilde ou le salon pour la sélection sur le serveur {guild_id}.")
            return

        try:
            # --- DÉBUT DE LA LOGIQUE RESTAURÉE ---
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
                await channel.send("⚠️ Aucune sélection de la semaine à publier, pas assez de données.")
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
            Logger.success(f"Sélection de la semaine publiée avec succès sur le serveur {guild_id}.")
            # --- FIN DE LA LOGIQUE RESTAURÉE ---
        except Exception as e:
            Logger.error(f"Erreur lors de la génération de la sélection pour le serveur {guild_id}: {e}")
            traceback.print_exc()

    if guild_id_to_run:
        await run_for_guild(guild_id_to_run)
    else:
        configured_guilds = await config_manager.get_all_configured_guilds()
        for guild_id in configured_guilds:
            await run_for_guild(guild_id)

def get_smart_promotions_from_api():
    """
    Interroge l'API Shopify pour trouver toutes les promotions VRAIMENT disponibles
    (actives, non épuisées, publiques et non-destinées aux tests).
    [MODIFIÉ] : Ne montre que les codes se terminant par "10".
    """
    Logger.info("Recherche des promotions intelligentes et disponibles via l'API...")
    promo_texts = []
    try:
        price_rules = shopify.PriceRule.find()

        for rule in price_rules:
            # --- VÉRIFICATION N°1 : Période de validité ---
            now = datetime.utcnow().isoformat()
            if rule.starts_at > now or (rule.ends_at and rule.ends_at < now):
                continue

            # --- VÉRIFICATION N°2 : Convention de nommage pour les tests ---
            title_lower = rule.title.lower()
            if title_lower.startswith(('test', '_', 'z-')):
                continue

            discount_codes = shopify.DiscountCode.find(price_rule_id=rule.id)
            is_shipping_offer = "livraison" in title_lower

            # --- VÉRIFICATION N°3 : Ne garder que les offres publiques ---
            if not discount_codes and not is_shipping_offer:
                continue

            # --- VÉRIFICATION N°4 : Limite d'utilisation ---
            if discount_codes and rule.usage_limit is not None:
                code = discount_codes[0]
                if code.usage_count >= rule.usage_limit:
                    continue
            
            # --- NOUVELLE VÉRIFICATION : Filtrer les codes de réduction ---
            # Une promotion est valide si c'est une offre de livraison (pas de code)
            # OU si elle a un code qui se termine par "10".
            is_valid_promo = False
            if is_shipping_offer:
                is_valid_promo = True
            elif discount_codes and discount_codes[0].code.endswith('10'):
                is_valid_promo = True

            # Si la promotion n'est pas valide selon nos nouveaux critères, on passe à la suivante.
            if not is_valid_promo:
                continue

            # Si la promotion est valide, on peut formater le texte.
            code_text = f" (avec le code `{discount_codes[0].code}`)" if discount_codes else ""
            
            value = float(rule.value)
            value_type = rule.value_type

            if is_shipping_offer:
                 promo_texts.append(f"🚚 {rule.title}")
            elif value_type == 'percentage':
                promo_texts.append(f"💰 {abs(value):.0f}% de réduction sur {rule.title}{code_text}")
            elif value_type == 'fixed_amount':
                promo_texts.append(f"💰 {abs(value):.2f}€ de réduction sur {rule.title}{code_text}")
                
        if not promo_texts:
            Logger.info("Aucune promotion publique et active (terminant par 10) trouvée.")
            return ["Aucune promotion spéciale en ce moment."]
            
        Logger.success(f"{len(promo_texts)} promotions disponibles (terminant par 10) trouvées.")
        return promo_texts

    except Exception as e:
        Logger.error(f"Erreur lors de la récupération des PriceRule : {e}")
        return ["Impossible de charger les promotions."]
    
async def publish_menu(bot_instance: commands.Bot, site_data: dict, guild_id: int, mention: bool = False):
    Logger.info(f"Publication du menu pour le serveur {guild_id} (mention: {mention})...")
    
    # On récupère la config spécifique à ce serveur
    channel_id = await config_manager.get_state(guild_id, 'menu_channel_id', CHANNEL_ID)
    if not channel_id:
        Logger.error(f"Aucun ID de salon pour le menu n'est configuré pour le serveur {guild_id}.")
        return False
        
    channel = bot_instance.get_channel(int(channel_id))
    if not channel:
        Logger.error(f"Salon avec l'ID {channel_id} non trouvé pour la publication sur le serveur {guild_id}.")
        return False

    products = site_data.get('products', [])
    promos_list = site_data.get('general_promos', [])
    general_promos_text = "\n".join([f"• {promo.strip()}" for promo in promos_list if promo.strip()]) or "Aucune promotion générale en cours."

    hash_count, weed_count, box_count, accessoire_count = get_product_counts(products)

    description_text = (f"__**📦 Produits disponibles :**__\n\n"
                      f"**`Fleurs 🍃 :` {weed_count}**\n"
                      f"**`Résines 🍫 :` {hash_count}**\n"
                      f"**`Box 📦 :` {box_count}**\n"
                      f"**`Accessoires 🛠️ :` {accessoire_count}**\n\n"
                      f"__**💰 Promotions disponibles :**__\n\n{general_promos_text}\n\n"
                      f"*(Mise à jour <t:{int(site_data.get('timestamp'))}:R>)*")
    
    embed = discord.Embed(title="📢 Nouveautés et Promotions !", url=CATALOG_URL, description=description_text, color=discord.Color.from_rgb(0, 102, 204))
    
    main_logo_url = config_manager.get_config("contact_info.main_logo_url")
    if main_logo_url:
        embed.set_thumbnail(url=main_logo_url)
    
    view = MenuView()
    
    role_id_to_mention = await config_manager.get_state(guild_id, 'mention_role_id', ROLE_ID_TO_MENTION)
    content = f"<@&{role_id_to_mention}>" if mention and role_id_to_mention else None
    
    # Le last_message_id est maintenant aussi par serveur
    last_message_id = await config_manager.get_state(guild_id, 'last_message_id')
    
    try:
        if last_message_id:
            try:
                old_message = await channel.fetch_message(int(last_message_id))
                await old_message.delete()
            except (discord.NotFound, discord.Forbidden): pass
        
        # On s'assure que la vue est enregistrée avant l'envoi
        # C'est une bonne pratique, même si add_view est global
        bot_instance.add_view(view) 
        
        new_message = await channel.send(content=content, embed=embed, view=view)
        await config_manager.update_state(guild_id, 'last_message_id', str(new_message.id))
        Logger.success(f"Nouveau menu publié (ID: {new_message.id}) sur le serveur {guild_id}.")
        return True
    except Exception as e:
        Logger.error(f"Erreur fatale lors de la publication du menu sur le serveur {guild_id} : {e}"); traceback.print_exc()
        return False


async def check_for_updates(bot_instance: commands.Bot, force_publish: bool = False):
    Logger.info(f"Vérification du menu... (Forcé: {force_publish})")

    site_data = await bot_instance.loop.run_in_executor(
        executor, get_site_data_from_graphql # <--- Changement ici
    )
    
    if not site_data or 'products' not in site_data:
        Logger.error("Récupération des données API échouée, la vérification s'arrête.")
        bot_instance.product_cache = {} 
        return False
        
    def write_cache():
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(site_data, f, indent=4, ensure_ascii=False)
    await asyncio.to_thread(write_cache)
    bot_instance.product_cache = site_data
    Logger.success(f"Cache de produits mis à jour sur le disque avec {len(site_data.get('products', []))} produits.")

    data_to_hash = {
        'products': site_data.get('products', []),
        'general_promos': sorted(site_data.get('general_promos', [])) 
    }
    current_hash = hashlib.sha256(json.dumps(data_to_hash, sort_keys=True).encode('utf-8')).hexdigest()

    # On boucle sur tous les serveurs qui ont une configuration
    configured_guilds = await config_manager.get_all_configured_guilds()
    Logger.info(f"Vérification des mises à jour pour {len(configured_guilds)} serveur(s) configuré(s).")

    for guild_id in configured_guilds:
        last_hash = await config_manager.get_state(guild_id, 'last_menu_hash', "")
        
        if current_hash != last_hash or force_publish:
            Logger.info(f"Changement détecté (ou forcé) pour le serveur {guild_id}. Publication du menu.")
            if await publish_menu(bot_instance, site_data, guild_id, mention=True): 
                await config_manager.update_state(guild_id, 'last_menu_hash', current_hash)
        else:
            Logger.info(f"Aucun changement pour le serveur {guild_id}. Mise à jour silencieuse.")
            await publish_menu(bot_instance, site_data, guild_id, mention=False)
            
    return True # La fonction a terminé son travail

async def generate_and_send_ranking(bot_instance: commands.Bot, force_run: bool = False):
    Logger.info("Exécution de la logique de classement...")
    today = datetime.now(paris_tz)
    if not force_run and today.weekday() != 6:
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
        return cursor.fetchall()
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
        Logger.warning(f"Cache des produits non trouvé pour classement : {e}.")
    embed = discord.Embed(title=title_prefix, description="Voici les 3 produits les mieux notés par la communauté ces 7 derniers jours.", color=discord.Color.gold())
    winner_name = top_products[0][0]
    if (winner_details := product_details_map.get(winner_name.strip().lower())) and (winner_image := winner_details.get('image')):
        embed.set_thumbnail(url=winner_image)
    medals = ["🥇", "🥈", "🥉"]
    for i, (name, avg_score, count) in enumerate(top_products):
        embed.add_field(name=f"{medals[i]} {name}", value=f"**Note moyenne : {avg_score:.2f}/10**\n*sur la base de {count} notation(s)*", inline=False)
    embed.set_footer(text=f"Classement du {today.strftime('%d/%m/%Y')}.")
    try:
        await channel.send(embed=embed)
        Logger.success(f"Classement (Forcé: {force_run}) publié avec succès.")
    except Exception as e:
        Logger.error(f"Impossible d'envoyer le message de classement : {e}")

async def sync_all_loyalty_roles(bot_instance: commands.Bot):
    """Tâche quotidienne pour synchroniser les rôles de tous les membres."""
    Logger.info("Démarrage de la synchronisation quotidienne des rôles de fidélité...")
    
    slash_commands_cog = bot_instance.get_cog("SlashCommands")
    if not slash_commands_cog:
        Logger.error("Impossible de démarrer la synchro des rôles : le cog 'SlashCommands' est introuvable.")
        return

    def _get_all_raters_sync():
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, COUNT(id) as rating_count FROM ratings GROUP BY user_id")
        return cursor.fetchall()

    try:
        all_raters = await asyncio.to_thread(_get_all_raters_sync)
        if not all_raters:
            Logger.info("Aucun membre avec des notes trouvé. Fin de la synchro des rôles.")
            return

        configured_guilds = await config_manager.get_all_configured_guilds()
        for guild_id in configured_guilds:
            guild = bot_instance.get_guild(guild_id)
            if not guild:
                continue

            Logger.info(f"Synchro des rôles pour le serveur '{guild.name}'...")
            for user_id, rating_count in all_raters:
                member = guild.get_member(user_id)
                if member:
                    await slash_commands_cog._update_all_user_roles(guild, member)
                    await asyncio.sleep(0.2)

        Logger.success("Synchronisation quotidienne des rôles de fidélité terminée.")
    except Exception as e:
        Logger.error(f"Erreur critique lors de la synchronisation des rôles : {e}")
        traceback.print_exc()

@tasks.loop(hours=504) # S'exécute toutes les 3 semaines
async def scheduled_db_export(bot_instance: commands.Bot):
    """
    Parcourt tous les serveurs, et si un salon de sauvegarde est configuré,
    envoie le fichier de la base de données.
    """
    await bot_instance.wait_until_ready() # Sécurité pour s'assurer que le bot est connecté
    Logger.info("Lancement de la tâche de sauvegarde (tri-hebdomadaire) de la base de données...")
    
    if not os.path.exists(DB_FILE):
        Logger.error(f"Sauvegarde annulée : le fichier {DB_FILE} n'a pas été trouvé.")
        return

    # On récupère tous les serveurs où le bot est présent
    for guild in bot_instance.guilds:
        try:
            # On utilise votre config_manager pour récupérer l'ID du salon pour ce serveur
            db_export_channel_id_str = await config_manager.get_state(guild.id, 'db_export_channel_id')
            if not db_export_channel_id_str:
                # Pas de salon configuré pour ce serveur, on passe au suivant.
                continue

            channel_id = int(db_export_channel_id_str)
            channel = bot_instance.get_channel(channel_id)

            if not channel or not isinstance(channel, discord.TextChannel):
                Logger.warning(f"Salon de sauvegarde introuvable ou invalide pour le serveur '{guild.name}' (ID: {channel_id}).")
                continue
            
            # Préparation du fichier Discord
            filename = f"backup_periodic_{datetime.now().strftime('%Y-%m-%d')}.db"
            discord_file = discord.File(DB_FILE, filename=filename)

            # Préparation de l'embed avec votre fonction `create_styled_embed`
            embed = create_styled_embed(
                title="⚙️ Sauvegarde Automatique",
                description="Voici la sauvegarde périodique de la base de données (`ratings.db`).",
                color=discord.Color.blue()
            )
            embed.set_footer(text=f"Sauvegarde du {datetime.now(paris_tz).strftime('%d/%m/%Y à %H:%M')}")

            await channel.send(embed=embed, file=discord_file)
            Logger.success(f"Sauvegarde de la DB envoyée avec succès sur le serveur '{guild.name}' dans le salon '{channel.name}'.")

        except discord.Forbidden:
            Logger.error(f"Permissions manquantes pour envoyer la sauvegarde sur le serveur '{guild.name}'.")
        except Exception as e:
            Logger.error(f"Erreur inattendue lors de la sauvegarde pour le serveur '{guild.name}': {e}")
            traceback.print_exc()

bot.sync_all_loyalty_roles = sync_all_loyalty_roles
bot.check_for_updates = check_for_updates
bot.post_weekly_selection = post_weekly_selection

@tasks.loop(time=update_time)
async def scheduled_check(): await check_for_updates(bot)

@tasks.loop(time=ranking_time)
async def post_weekly_ranking(): await generate_and_send_ranking(bot)

@tasks.loop(time=selection_time)
async def scheduled_selection():
    if datetime.now(paris_tz).weekday() == 0: await post_weekly_selection(bot)

@tasks.loop(time=role_sync_time)
async def daily_role_sync():
    await sync_all_loyalty_roles(bot)

# Dans catalogue_final.py

@bot.event
async def on_ready():
    # --- DÉBUT DU BLOC DE SYNCHRONISATION FORCÉE ---
    try:
        # ÉTAPE 1 : On vide les commandes pour le serveur de test (si GUILD_ID est défini)
        # Cela force Discord à oublier l'ancienne structure.
        if GUILD_ID:
            guild_obj = discord.Object(id=GUILD_ID)
            # Cette ligne est la plus importante, elle dit à Discord "Oublie tout pour ce serveur"
            bot.tree.clear_commands(guild=guild_obj)
            await bot.tree.sync(guild=guild_obj)
            Logger.warning(f"Commandes vidées pour le serveur de test (ID: {GUILD_ID}).")
        # Ensuite on synchronise globalement
        synced = await bot.tree.sync()
        Logger.success(f"Synchronisation globale terminée : {len(synced)} commandes enregistrées.")
    except Exception as e:
        Logger.error(f"Échec de la synchronisation des commandes : {e}")
    # --- FIN DU BLOC DE SYNCHRONISATION ---
    await asyncio.to_thread(initialize_database)
    async def initial_update_task():
        await asyncio.sleep(5) 
        Logger.info("Lancement de la vérification initiale différée...")
        await check_for_updates(bot, force_publish=False)
    asyncio.create_task(initial_update_task())
    try:
        bot.add_view(MenuView())
        Logger.success("Vue de menu persistante ré-enregistrée avec succès.")
    except Exception as e:
        Logger.error(f"Échec critique du chargement de la vue persistante : {e}")

    if not scheduled_check.is_running(): scheduled_check.start()
    if not post_weekly_ranking.is_running(): post_weekly_ranking.start()
    if not scheduled_selection.is_running(): scheduled_selection.start()
    if not daily_role_sync.is_running(): daily_role_sync.start()
    if not scheduled_db_export.is_running(): scheduled_db_export.start(bot) # [AJOUT] Démarrage de la nouvelle tâche
    Logger.success("Toutes les tâches programmées ont démarré.")


# --- FIX STARTS HERE: ROBUST ERROR HANDLER ---
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    command_name = interaction.command.name if interaction.command else "commande inconnue"
    Logger.error(f"Erreur dans la commande /{command_name} par {interaction.user}: {error}")
    
    # On vérifie la cause racine de l'erreur
    original_error = getattr(error, 'original', error)

    # Cas 1: L'interaction a expiré (démarrage à froid du serveur)
    if isinstance(original_error, discord.errors.NotFound) and original_error.code == 10062:
        Logger.warning("Erreur 'Unknown Interaction' détectée (démarrage à froid). Envoi du message d'attente.")
        
        staff_mention = "@Staff"
        if interaction.guild: # On ne peut récupérer le rôle que si on est sur un serveur
            staff_role_id = await config_manager.get_state(interaction.guild.id, 'staff_role_id', STAFF_ROLE_ID)
            if staff_role_id:
                staff_mention = f"<@&{staff_role_id}>"

        embed = discord.Embed(
            title="⏳ Le bot est en train de démarrer",
            description=(
                "Le bot était en veille et vient de se réveiller. Votre commande n'a pas pu être traitée à temps.\n\n"
                "**Veuillez simplement relancer votre commande.** Elle devrait fonctionner maintenant."
            ),
            color=discord.Color.orange()
        )
        embed.add_field(
            name="Que faire si ça ne marche toujours pas ?",
            value=f"Si le problème persiste, un membre du staff ({staff_mention}) peut utiliser la commande `/debug` pour forcer une réinitialisation."
        )
        embed.set_footer(text="Merci de votre patience !")
    
    # Cas 2: Problème de permissions
    elif isinstance(error, app_commands.CheckFailure):
        error_message = "🚫 Désolé, tu n'as pas les permissions pour utiliser cette commande."
    
    # Cas 3: Commande inconnue (rare avec les slash commands, mais sécurisant)
    elif isinstance(error, app_commands.CommandNotFound):
        error_message = "🤔 Cette commande n'existe pas ou n'est plus à jour."
        
    # Cas 4: Toutes les autres erreurs
    else:
        # On log le traceback complet pour le débogage
        traceback.print_exc()
        error_message = "❌ Oups ! Une erreur inattendue est survenue. Le staff a été notifié."

    # On envoie la réponse de manière sécurisée
    try:
        if interaction.response.is_done():
            await interaction.followup.send(error_message, ephemeral=True)
        else:
            # On utilise defer() ici pour les cas où la commande plante AVANT le defer initial.
            # Cela évite une nouvelle erreur "Interaction has already been acknowledged".
            await interaction.response.defer(ephemeral=True, thinking=False)
            await interaction.followup.send(error_message, ephemeral=True)
    except discord.errors.InteractionResponded:
        # Si une réponse a déjà été envoyée dans une condition de concurrence rare, on utilise followup.
        try:
            await interaction.followup.send(error_message, ephemeral=True)
        except Exception as e:
            Logger.error(f"CRITICAL: Impossible d'envoyer un message d'erreur même avec followup: {e}")
    except Exception as e:
        Logger.error(f"CRITICAL: Impossible d'envoyer un message d'erreur à l'utilisateur: {e}")


async def main():
    async with bot:
        await bot.load_extension("commands")
        await bot.start(TOKEN)

if __name__ == "__main__":
    if TOKEN and CHANNEL_ID:
        try: asyncio.run(main())
        except KeyboardInterrupt: Logger.warning("Arrêt du bot demandé.")
        finally:
            if not executor._shutdown:
                Logger.info("Fermeture de l'exécuteur...")
                executor.shutdown(wait=True)
                Logger.success("Exécuteur fermé.")
    else: Logger.error("Le DISCORD_TOKEN ou le CHANNEL_ID ne sont pas définis dans le fichier .env")