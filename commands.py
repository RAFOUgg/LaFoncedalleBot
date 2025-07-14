# commands.py

import discord
from discord.ext import commands
from discord import app_commands
import json
import time
import requests
from typing import List, Optional, Tuple 
import sqlite3
from datetime import datetime, timedelta
import traceback
import asyncio
import os

# --- Imports depuis les fichiers du projet ---
import graph_generator
# ON IMPORTE DEPUIS shared_utils MAINTENANT
from shared_utils import (
    log_user_action, Logger, executor, CACHE_FILE,
    CATALOG_URL, DB_FILE, STAFF_ROLE_ID,
    config_manager, create_styled_embed,
    TIKTOK_EMOJI, LFONCEDALLE_EMOJI, TELEGRAM_EMOJI, INSTAGRAM_EMOJI,
    SELECTION_CHANNEL_ID, SUCETTE_EMOJI, NITRO_CODES_FILE, CLAIMED_CODES_FILE, paris_tz, get_product_counts,
    categorize_products, filter_catalog_products # <-- Ajout ici
)


# --- Logique des permissions ---
async def is_staff_or_owner(interaction: discord.Interaction) -> bool:
    if await interaction.client.is_owner(interaction.user): return True
    if not STAFF_ROLE_ID: return False
    try: staff_role_id_int = int(STAFF_ROLE_ID)
    except (ValueError, TypeError): return False
    return any(role.id == staff_role_id_int for role in interaction.user.roles)

# --- VUES ET MODALES ---

# --- Vues pour la commande /menu
class ProductView(discord.ui.View):
    def __init__(self, products: List[dict]):
        super().__init__(timeout=300)
        self.products = products
        self.current_index = 0
        self.update_buttons()

    def update_buttons(self):
        if len(self.children) >= 2:
            self.children[0].disabled = self.current_index == 0
            self.children[1].disabled = self.current_index >= len(self.products) - 1

    def create_embed(self) -> discord.Embed:
        product = self.products[self.current_index]
        # Détermine l'emoji selon la catégorie
        name_lower = product.get('name', '').lower()
        if "peach" in name_lower or "pêche" in name_lower:
            emoji = "🍑"
        elif "blueberry" in name_lower or "bleu" in name_lower:
            emoji = "🫐"
        elif "dry sift" in name_lower or "résine" in name_lower:
            emoji = "🍫"
        elif "box" in name_lower or "pack" in name_lower:
            emoji = "📦"
        elif "accessoire" in name_lower or "briquet" in name_lower or "feuille" in name_lower:
            emoji = "🛠️"
        else:
            emoji = "🌿"

        embed_color = discord.Color.dark_red() if product.get('is_sold_out') else discord.Color.from_rgb(255, 204, 0)
        embed = discord.Embed(
            title=f"{emoji} {product.get('name', 'Produit inconnu')}",
            url=product.get('product_url', CATALOG_URL),
            description=product.get('detailed_description', "Aucune description."),
            color=embed_color
        )
        if product.get('image'):
            embed.set_thumbnail(url=product['image'])

        # Prix et stock
        if product.get('is_sold_out'):
            price_text = "❌ **ÉPUISÉ**"
        elif product.get('is_promo'):
            price_text = f"🏷️ **{product.get('price')}** ~~{product.get('original_price')}~~"
        else:
            price_text = f"💰 **{product.get('price', 'N/A')}**"
        embed.add_field(name="Prix", value=price_text, inline=False)

        # Caractéristiques stylisées
        stats = product.get('stats', {})
        if stats:
            stats_lines = []
            for label, value in stats.items():
                # Si c'est un lien PDF, on le rend cliquable
                if "pdf" in label.lower() or "lab" in label.lower():
                    if value.startswith("gid://"):
                        # On ne peut pas rendre cliquable, on affiche brut
                        stats_lines.append(f"**Lab test PDF :** `{value}`")
                    else:
                        stats_lines.append(f"**Lab test PDF :** [Voir le PDF]({value})")
                else:
                    stats_lines.append(f"**{label} :** {value}")
            embed.add_field(name="Caractéristiques", value="\n".join(stats_lines), inline=False)

        embed.set_footer(text=f"Produit {self.current_index + 1} sur {len(self.products)}")
        return embed

    async def update_message(self, interaction: discord.Interaction):
        self.update_buttons()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="⬅️ Précédent", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_index > 0:
            self.current_index -= 1
        await self.update_message(interaction)

    @discord.ui.button(label="Suivant ➡️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_index < len(self.products) - 1:
            self.current_index += 1
        await self.update_message(interaction)


class MenuView(discord.ui.View):
    def __init__(self, all_products: List[dict]):
        super().__init__(timeout=None)
        categorized = categorize_products(all_products)
        self.weed_products = categorized["weed"]
        self.hash_products = categorized["hash"]
        self.box_products = categorized["box"]
        self.accessoire_products = categorized["accessoire"]

        self.children[0].custom_id = "menu_view_fleurs_button"
        self.children[1].custom_id = "menu_view_resines_button"
        btn_idx = 2
        if self.box_products:
            self.add_item(discord.ui.Button(label="Nos Box 📦", style=discord.ButtonStyle.success, emoji="📦", custom_id="menu_view_box_button"))
        if self.accessoire_products:
            self.add_item(discord.ui.Button(label="Accessoires 🛠️", style=discord.ButtonStyle.secondary, emoji="🛠️", custom_id="menu_view_accessoire_button"))

    async def start_product_view(self, interaction: discord.Interaction, products: List[dict], category_name: str):
        if not products:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"Désolé, aucun produit de type '{category_name}' trouvé.", ephemeral=True)
            else:
                await interaction.followup.send(f"Désolé, aucun produit de type '{category_name}' trouvé.", ephemeral=True)
            return
        
        view = ProductView(products)
        embed = view.create_embed()
        
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Nos Fleurs 🍃", style=discord.ButtonStyle.success, emoji="🍃")
    async def weed_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.start_product_view(interaction, self.weed_products, "Fleurs")

    @discord.ui.button(label="Nos Résines 🍫", style=discord.ButtonStyle.primary, emoji="🍫")
    async def hash_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.start_product_view(interaction, self.hash_products, "Résines")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Permet de router les boutons dynamiques
        if interaction.data.get("custom_id") == "menu_view_box_button":
            await self.start_product_view(interaction, self.box_products, "Box")
            return False
        if interaction.data.get("custom_id") == "menu_view_accessoire_button":
            await self.start_product_view(interaction, self.accessoire_products, "Accessoires")
            return False
        return True

# --- COMMANDES ---

class SlashCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # --- DÉBUT DES COMMANDES INDENTÉES CORRECTEMENT ---
    @app_commands.command(name="menu", description="Affiche le menu interactif des produits disponibles.")
    async def menu(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await log_user_action(interaction, "a demandé le menu interactif (/menu)")

        try:
            def _read_cache_sync():
                with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            site_data = await asyncio.to_thread(_read_cache_sync)

            if not site_data or not (products := site_data.get('products')):
                await interaction.followup.send("Désolé, le menu n'est pas disponible pour le moment. Réessayez dans un instant.", ephemeral=True)
                return

            # Filtrer les produits pour exclure box/accessoires/réseaux sociaux
            filtered_products = filter_catalog_products(products)

            general_promos_text = "\n".join([f"• {promo}" for promo in site_data.get('general_promos', [])]) or "Aucune promotion générale en cours."
            hash_count, weed_count = get_product_counts(products) # Utilise la fonction filtrée

            embed = discord.Embed(
                title="📢 Menu et Promotions !",
                url=CATALOG_URL,
                description=f"__**📦 Produits disponibles :**__\n\n"
                            f"**`Fleurs 🍃 :` {weed_count}**\n"
                            f"**`Résines 🍫 :` {hash_count}**\n\n"
                            f"__**💰 Promotions disponibles :**__\n\n{general_promos_text}\n\n"
                            f"*(Données mises à jour <t:{int(site_data.get('timestamp'))}:R>)*",
                color=discord.Color.from_rgb(0, 102, 204)
            )
            main_logo_url = config_manager.get_config("contact_info.main_logo_url")
            if main_logo_url:
                embed.set_thumbnail(url=main_logo_url)

            # Créer la vue avec les boutons sur les produits filtrés
            view = MenuView(filtered_products)

            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except (FileNotFoundError, json.JSONDecodeError):
            await interaction.followup.send("Le menu est en cours de construction, veuillez réessayer dans quelques instants.", ephemeral=True)
        except Exception as e:
            Logger.error(f"Erreur dans /menu : {e}")
            traceback.print_exc()
            await interaction.followup.send("❌ Une erreur est survenue lors de l'affichage du menu.", ephemeral=True)

    @app_commands.command(name="export_db", description="Télécharger la base de données des notes utilisateur (staff uniquement)")
    @app_commands.check(is_staff_or_owner)
    async def export_db(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            if not os.path.exists(DB_FILE):
                await interaction.followup.send("Fichier de base de données introuvable.", ephemeral=True)
                return
            file = discord.File(DB_FILE, filename=os.path.basename(DB_FILE))
            await interaction.followup.send("Voici la base de données des notes utilisateur :", file=file, ephemeral=True)
        except Exception as e:
            Logger.error(f"Erreur lors de l'envoi du fichier DB : {e}")
            await interaction.followup.send("Erreur lors de l'envoi du fichier de base de données.", ephemeral=True)

    @app_commands.command(name="noter", description="Note un produit que tu as acheté sur la boutique.")
    async def noter(self, interaction: discord.Interaction):
        try:
            Logger.info("[NOTER DEBUG] Commande reçue. Appel de defer()...")
            await interaction.response.defer(ephemeral=True)
            await log_user_action(interaction, "a initié la commande /noter")
            Logger.info("[NOTER DEBUG] Log réussi. Récupération des achats Shopify...")

            # Appel à l'API Flask pour récupérer les produits achetés
            app_url = "https://votre-app-hebergee.com" # À adapter selon votre hébergement
            api_url = f"{app_url}/api/get_purchased_products/{interaction.user.id}"

            def fetch_purchased_products():
                import requests
                try:
                    response = requests.get(api_url, timeout=10)
                    if response.status_code == 404:
                        return None
                    response.raise_for_status()
                    data = response.json()
                    return data.get("products", [])
                except Exception as e:
                    Logger.error(f"Erreur API Flask get_purchased_products: {e}")
                    return None

            purchased_products = await asyncio.to_thread(fetch_purchased_products)

            if purchased_products is None:
                await interaction.followup.send(
                    "Ton compte Discord n'est pas encore lié à un compte sur la boutique. Utilise la commande `/lier_compte` pour commencer.",
                    ephemeral=True
                )
                return

            if not purchased_products:
                await interaction.followup.send(
                    "Nous n'avons trouvé aucun produit dans ton historique d'achats. Si tu penses que c'est une erreur, contacte le staff.",
                    ephemeral=True
                )
                return

            Logger.info(f"[NOTER DEBUG] {len(purchased_products)} produits achetés trouvés. Création de la vue...")
            view = NotationProductSelectView(purchased_products, interaction.user, self.bot)

            Logger.info("[NOTER DEBUG] Vue créée. Envoi du message followup...")
            await interaction.followup.send("Veuillez choisir un produit à noter :", view=view, ephemeral=True)
            Logger.success("[NOTER DEBUG] Commande /noter terminée avec succès.")

        except Exception as e:
            Logger.error("="*50); Logger.error(f"ERREUR FATALE DANS /noter:"); traceback.print_exc(); Logger.error("="*50)

    @app_commands.command(name="contacts", description="Afficher les informations de contact et réseaux de LaFoncedalle")
    async def contacts(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await log_user_action(interaction, "Commande /contacts")
        contact_info = {
            "site": "https://la-foncedalle.fr/",
            "instagram": "https://www.instagram.com/lafoncedalle.frr/",
            "telegram": "https://t.me/+X1P65R4EVZAXZmEO",
            "tiktok": "https://www.tiktok.com/@terpsbymaaaax"
        }
        # Récupérer la date/heure actuelle pour l'instantanéité
        embed = create_styled_embed(
            f"{SUCETTE_EMOJI} LaFoncedalle - Contacts \n\n",
            "Si vous avez la moindre question, nous vous répondrons avec plaisir ! \n\n"
            "💌 Vous pouvez nous contacter **n'importe quand par mail** : \n `contact@la-foncedalle.fr` \n\n" 
            "📞 Ou à ce numéro (celui de Max) : `07.63.40.31.12`\n"
            "Sur what's app ou directement par appel ou message.\n\n"
            "*(Nous traitons généralement les demandes écrites sous 24H.)*\n\n",
            color=discord.Color.blue()
        )
        view = ContactButtonsView(contact_info)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="debug", description="Force la republication du menu (staff uniquement)")
    @app_commands.check(is_staff_or_owner)
    async def debug(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.bot.force_republish_menu(self.bot) 
        await interaction.followup.send("Menu republication forcée.", ephemeral=True)

    @app_commands.command(name="check", description="Vérifie si de nouveaux produits sont disponibles (cooldown de 12h).")
    async def check(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        cooldown_period = timedelta(hours=12)
        last_check_iso = await config_manager.get_state('last_check_command_timestamp')
        if last_check_iso:
            time_since_last_check = datetime.utcnow() - datetime.fromisoformat(last_check_iso)
            if time_since_last_check < cooldown_period:
                next_allowed_time = datetime.fromisoformat(last_check_iso) + cooldown_period
                await interaction.followup.send(f"⏳ Prochaine vérification possible <t:{int(next_allowed_time.timestamp())}:R>.", ephemeral=True)
                return
        
        await log_user_action(interaction, "a utilisé /check.")
        try:
            updates_found = await self.bot.check_for_updates(self.bot, force_publish=False)
            await config_manager.update_state('last_check_command_timestamp', datetime.utcnow().isoformat())
            if updates_found:
                await interaction.followup.send("✅ Merci ! Le menu a été mis à jour grâce à vous.", ephemeral=True)
            else:
                await interaction.followup.send("👍 Le menu est déjà à jour. Merci d'avoir vérifié !", ephemeral=True)
        except Exception as e:
            Logger.error(f"Erreur dans /check: {e}"); traceback.print_exc()
            await interaction.followup.send("❌ Oups, une erreur est survenue lors de la vérification.", ephemeral=True)

    @app_commands.command(name="graph", description="Voir un graphique radar des moyennes du serveur pour un produit")
    @app_commands.check(is_staff_or_owner)
    async def graph(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await log_user_action(interaction, "Commande /graph")
        # Récupère tous les produits ayant au moins une note
        def fetch_products():
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT product_name FROM ratings")
            products = [row[0] for row in cursor.fetchall()]
            conn.close()
            return products

        products = await asyncio.to_thread(fetch_products)
        if not products:
            await interaction.followup.send("Aucun produit n'a encore été noté sur le serveur.", ephemeral=True)
            return

        view = ProductSelectViewForGraph(products, self.bot)
        await interaction.followup.send("Sélectionnez un produit pour voir le graphique radar des moyennes du serveur :", view=view, ephemeral=True)

    @app_commands.command(name="nitro_gift", description="Réclame ton code de réduction pour avoir boosté le serveur !")
    @app_commands.guild_only() # Cette commande ne peut pas être utilisée en MP
    async def nitro_gift(self, interaction: discord.Interaction):
        """Offre un code de réduction unique aux membres qui boostent le serveur."""
        await interaction.response.defer(ephemeral=True) # Réponse privée à l'utilisateur
        
        user = interaction.user
        guild = interaction.guild

        if not user.premium_since:
            await interaction.followup.send("Désolé, cette commande est réservée aux membres qui boostent actuellement le serveur. Merci pour ton soutien ! 🚀", ephemeral=True)
            return

        claimed_users = {}
        try:
            with open(CLAIMED_CODES_FILE, 'r') as f:
                claimed_users = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass # Le fichier n'existe pas ou est vide, c'est normal au début

        if str(user.id) in claimed_users:
            await interaction.followup.send(f"Tu as déjà réclamé ton code de réduction le {claimed_users[str(user.id)]}. Merci encore pour ton boost ! ✨", ephemeral=True)
            return

        try:
            with open(NITRO_CODES_FILE, 'r+') as f:
                # On lit tous les codes disponibles
                codes = [line.strip() for line in f if line.strip()]
                
                if not codes:
                    await interaction.followup.send("Oh non ! Il semble que nous soyons à court de codes de réduction pour le moment. Merci de contacter un membre du staff. 😥", ephemeral=True)
                    Logger.warning("Tentative de réclamation de code Nitro alors que le fichier est vide.")
                    return
                # On prend le premier code de la liste
                gift_code = codes.pop(0)
                # On réécrit le fichier sans le code qui vient d'être donné
                f.seek(0)
                f.truncate()
                f.write('\n'.join(codes))
            try:
                embed = create_styled_embed(
                    title="Merci pour ton Boost ! 💖",
                    description=f"Encore merci de soutenir **{guild.name}** ! Pour te remercier, voici ton code de réduction personnel à usage unique.\n\n"
                                f"Utilise-le lors de ta prochaine commande sur notre boutique.",
                    color=discord.Color.nitro_pink() # Couleur spéciale Nitro
                )
                embed.add_field(name="🎟️ Ton Code de Réduction", value=f"**`{gift_code}`**")
                embed.set_footer(text="Ce code est à usage unique. Ne le partage pas !")

                await user.send(embed=embed)
                
                # 5. On confirme à l'utilisateur et on enregistre sa réclamation
                await interaction.followup.send("Je viens de t'envoyer ton code de réduction en message privé ! Vérifie tes MPs. 😉", ephemeral=True)
                
                # On sauvegarde l'ID de l'utilisateur et la date de réclamation
                claimed_users[str(user.id)] = datetime.now(paris_tz).strftime('%d/%m/%Y')
                with open(CLAIMED_CODES_FILE, 'w') as f:
                    json.dump(claimed_users, f, indent=4)
                
                await log_user_action(interaction, f"a réclamé avec succès le code Nitro : {gift_code}")

            except discord.Forbidden:
                await interaction.followup.send("Je n'ai pas pu t'envoyer ton code en message privé. Assure-toi d'autoriser les messages privés venant des membres de ce serveur, puis réessaye.", ephemeral=True)

        except FileNotFoundError:
            await interaction.followup.send("Le fichier de codes de réduction n'a pas été trouvé. Merci de contacter un membre du staff.", ephemeral=True)
            Logger.error(f"Le fichier '{NITRO_CODES_FILE}' est introuvable.")
        except Exception as e:
            Logger.error(f"Erreur inattendue dans la commande /nitro_gift : {e}")
            traceback.print_exc()
            await interaction.followup.send("❌ Une erreur interne est survenue. Merci de réessayer ou de contacter un admin.", ephemeral=True)


    @app_commands.command(name="profil", description="Affiche le profil et les notations d'un membre.")
    @app_commands.describe(membre="Le membre dont vous voulez voir le profil (optionnel).")
    async def profil(self, interaction: discord.Interaction, membre: Optional[discord.Member] = None):
        await interaction.response.defer(ephemeral=True)
        
        target_user = membre or interaction.user
        await log_user_action(interaction, f"a consulté le profil de {target_user.display_name}")

        # Déterminer les permissions
        can_reset = False
        if membre and membre.id != interaction.user.id and await is_staff_or_owner(interaction):
            can_reset = True
        def _fetch_user_data_sync(user_id):
            conn = sqlite3.connect(DB_FILE)
            # Permet de récupérer les résultats comme des dictionnaires
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 1. Obtenir toutes les notes de l'utilisateur
            cursor.execute("""
                SELECT product_name, visual_score, smell_score, touch_score, taste_score, effects_score, rating_timestamp
                FROM ratings WHERE user_id = ? ORDER BY rating_timestamp DESC
            """, (user_id,))
            # Convertit les objets Row en dictionnaires
            user_ratings = [dict(row) for row in cursor.fetchall()]

            # 2. Obtenir les statistiques globales (rang, moyenne, etc.)
            # REQUÊTE CORRIGÉE
            cursor.execute("""
                WITH AllRanks AS (
                    SELECT 
                        user_id,
                        COUNT(id) as rating_count,
                        AVG((COALESCE(visual_score, 0) + COALESCE(smell_score, 0) + COALESCE(touch_score, 0) + COALESCE(taste_score, 0) + COALESCE(effects_score, 0)) / 5.0) as avg_note,
                        RANK() OVER (ORDER BY COUNT(id) DESC, AVG((COALESCE(visual_score, 0) + COALESCE(smell_score, 0) + COALESCE(touch_score, 0) + COALESCE(taste_score, 0) + COALESCE(effects_score, 0)) / 5.0) DESC) as user_rank
                    FROM ratings
                    GROUP BY user_id
                )
                SELECT user_rank, rating_count, avg_note FROM AllRanks WHERE user_id = ?
            """, (user_id,))
            stats = cursor.fetchone()
            user_stats = {'rank': stats['user_rank'], 'count': stats['rating_count'], 'avg': stats['avg_note']} if stats else {}

            # 3. Vérifier s'il est top 3 du mois (pour le badge)
            one_month_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
            cursor.execute("""
                SELECT user_id FROM ratings WHERE rating_timestamp >= ? 
                GROUP BY user_id ORDER BY COUNT(id) DESC LIMIT 3
            """, (one_month_ago,))
            top_3_monthly_ids = [row['user_id'] for row in cursor.fetchall()]
            user_stats['is_top_3_monthly'] = user_id in top_3_monthly_ids

            conn.close()
            return user_stats, user_ratings

        try:
            # Récupération et traitement
            user_stats, user_ratings = await asyncio.to_thread(_fetch_user_data_sync, target_user.id)

            if not user_stats:
                await interaction.followup.send("Cet utilisateur n'a encore noté aucun produit.", ephemeral=True)
                return

            # Création et envoi de la vue
            paginator = ProfilePaginatorView(target_user, user_stats, user_ratings, can_reset, self.bot)
            embed = paginator.create_embed()
            await interaction.followup.send(embed=embed, view=paginator, ephemeral=True)

        except Exception as e:
            Logger.error(f"Erreur lors de la génération du profil pour {target_user.display_name}: {e}")
            traceback.print_exc()
            await interaction.followup.send("❌ Une erreur est survenue lors de la récupération du profil.", ephemeral=True)

# commands.py

    @app_commands.command(name="lier_compte", description="Lie ton compte Discord à ton compte sur la boutique pour noter tes achats.")
    async def lier_compte(self, interaction: discord.Interaction):
        # L'URL de base de votre application pont. Doit être accessible publiquement.
        app_url = "https://votre-app-hebergee.com" 
        
        link = f"{app_url}/connect/{interaction.user.id}"
        
        embed = discord.Embed(
            title="🔗 Lier votre compte",
            description="Pour pouvoir noter les produits que tu as achetés, nous devons lier ton compte Discord à ton compte client sur la boutique.\n\n"
                        "**Le processus est simple et sécurisé :**\n"
                        "1. Clique sur le bouton ci-dessous.\n"
                        "2. Connecte-toi à ton compte sur notre boutique.\n"
                        "3. Autorise l'accès à tes commandes (en lecture seule).\n\n"
                        "*Nous ne stockons aucune information personnelle sensible.*",
            color=discord.Color.blue()
        )
        
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Lier mon compte Shopify", url=link, emoji="🔗"))
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    @app_commands.command(name="top_noteurs", description="Affiche le classement des membres qui ont noté le plus de produits.")
    @app_commands.guild_only()
    async def top_noteurs(self, interaction: discord.Interaction):
        """Affiche le classement complet et paginé des membres avec leurs statistiques de notation."""
        # MODIFICATION 1 : On rend le "defer" éphémère.
        # Ainsi, le message "L'application réfléchit..." ne sera visible que par l'utilisateur.
        await interaction.response.defer(ephemeral=True) 
    
        await log_user_action(interaction, "a demandé le classement des top noteurs.")

        def _fetch_top_raters_sync():
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
        
            cursor.execute("""
                WITH UserAverageNotes AS (
                    SELECT 
                        user_id, user_name, rating_timestamp,
                        (COALESCE(visual_score, 0) + COALESCE(smell_score, 0) + COALESCE(touch_score, 0) + COALESCE(taste_score, 0) + COALESCE(effects_score, 0)) / 5.0 AS average_note_per_product
                    FROM ratings
                )
                SELECT
                    uan.user_id,
                    (SELECT user_name FROM UserAverageNotes WHERE user_id = uan.user_id ORDER BY rating_timestamp DESC LIMIT 1) as last_user_name,
                    COUNT(uan.user_id) as rating_count,
                    AVG(uan.average_note_per_product) as global_average,
                    MIN(uan.average_note_per_product) as min_note,
                    MAX(uan.average_note_per_product) as max_note
                FROM UserAverageNotes uan
                GROUP BY uan.user_id
                ORDER BY rating_count DESC, global_average DESC;
            """)
            results = cursor.fetchall()
            conn.close()
            return results

        try:
            top_raters = await asyncio.to_thread(_fetch_top_raters_sync)

            if not top_raters:
                # Ce message est déjà éphémère, c'est parfait.
                await interaction.followup.send("Personne n'a encore noté de produit ! Soyez le premier avec la commande `/noter`.", ephemeral=True)
                return

            paginator = TopRatersPaginatorView(top_raters, interaction.guild, items_per_page=6)
            embed = paginator.create_embed_for_page()
        
        # MODIFICATION 2 : On envoie la réponse finale en mode éphémère.
        # Seul l'utilisateur qui a tapé la commande verra le classement.
            await interaction.followup.send(embed=embed, view=paginator, ephemeral=True)

        except Exception as e:
            Logger.error(f"Erreur lors de la génération du top des noteurs : {e}")
            traceback.print_exc()
            # Ce message est déjà éphémère, c'est parfait.
            await interaction.followup.send("❌ Une erreur est survenue lors de la récupération du classement.", ephemeral=True)

    @app_commands.command(name="selection", description="Publier immédiatement la sélection de la semaine (staff uniquement)")
    @app_commands.check(is_staff_or_owner)
    async def selection(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        # MODIFICATION ICI
        await self.bot.post_weekly_selection(self.bot)
        await interaction.followup.send("La sélection de la semaine a été (re)publiée dans le salon dédié.", ephemeral=True)
    
    # Dans commands.py, à l'intérieur de la classe SlashCommands

    @app_commands.command(name="promos", description="Affiche toutes les promotions en cours sur le site.")
    async def promos(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await log_user_action(interaction, "a demandé la liste des promotions.")

        try:
            def _read_product_cache_sync():
                try:
                    with open(CACHE_FILE, 'r', encoding='utf-8') as f: return json.load(f)
                except (FileNotFoundError, json.JSONDecodeError): return {}

            site_data = await asyncio.to_thread(_read_product_cache_sync)
            if not site_data:
                await interaction.followup.send("Désolé, les informations ne sont pas disponibles.", ephemeral=True)
                return

            promo_products = [p for p in site_data.get('products', []) if p.get('is_promo')]
            general_promos = site_data.get('general_promos', [])
            general_promos_text = "\n".join([f"• {promo}" for promo in general_promos]) if general_promos else ""

            # On passe toutes les infos nécessaires à la vue dès sa création
            paginator = PromoPaginatorView(promo_products, general_promos_text)
            embed = paginator.create_embed()
            
            await interaction.followup.send(embed=embed, view=paginator, ephemeral=True)

        except Exception as e:
            Logger.error(f"Erreur lors de l'exécution de la commande /promos : {e}")
            traceback.print_exc()
            # Ce message ne devrait plus être précédé par une réponse correcte
            await interaction.followup.send("❌ Une erreur est survenue lors de la récupération des promotions.", ephemeral=True)

    @app_commands.command(name="classement_general", description="Affiche la moyenne de tous les produits notés.")
    async def classement_general(self, interaction: discord.Interaction):
        """Affiche un classement complet et paginé de tous les produits ayant reçu une note."""
        await interaction.response.defer()
        await log_user_action(interaction, "a demandé le classement général des produits.")

        # --- Début de la zone "protégée" ---
        try:
            # Fonctions pour récupérer les données
            def _fetch_all_ratings_sync():
                # ... (code de la fonction)
                conn = sqlite3.connect(DB_FILE)
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT product_name, AVG((COALESCE(visual_score, 0) + COALESCE(smell_score, 0) + COALESCE(touch_score, 0) + COALESCE(taste_score, 0) + COALESCE(effects_score, 0)) / 5.0), COUNT(id)
                    FROM ratings GROUP BY product_name HAVING COUNT(id) > 0
                    ORDER BY AVG((visual_score + smell_score + touch_score + taste_score + effects_score) / 5.0) DESC
                """)
                results = cursor.fetchall()
                conn.close()
                return results

            def _read_product_cache_sync():
                # ... (code de la fonction)
                try:
                    with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                        return json.load(f)
                except (FileNotFoundError, json.JSONDecodeError):
                    return {}

            # 1. On récupère les données
            all_products_ratings, site_data = await asyncio.gather(
                asyncio.to_thread(_fetch_all_ratings_sync),
                asyncio.to_thread(_read_product_cache_sync)
            )

            # 2. On vérifie les données
            if not all_products_ratings:
                await interaction.followup.send("Aucun produit n'a encore été noté sur le serveur.", ephemeral=True)
                return

            # 3. On traite les données (création de la map)
            # CETTE PARTIE EST MAINTENANT CORRECTEMENT INDENTÉE DANS LE 'TRY'
            product_map = {
                p['name'].strip().lower(): p 
                for p in site_data.get('products', [])
            }

            # 4. On prépare l'affichage
            # CETTE PARTIE EST AUSSI DANS LE 'TRY'
            paginator = RankingPaginatorView(all_products_ratings, product_map, items_per_page=5)
            embed = paginator.create_embed_for_page()
            
            # 5. On envoie le résultat si tout a réussi
            await interaction.followup.send(embed=embed, view=paginator)

        # --- Fin de la zone "protégée" ---
        
        # Si n'importe quelle ligne dans le 'try' échoue, on arrive ici.
        except Exception as e:
            Logger.error(f"Erreur lors de la génération du classement général : {e}")
            traceback.print_exc()
            await interaction.followup.send("❌ Une erreur est survenue lors de la récupération du classement.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(SlashCommands(bot))

def get_purchased_products_from_shopify(email: str) -> list:
    """
    Récupère la liste des produits achetés par un client via l'API Shopify Admin.
    """
    import shopify
    shop_url = os.getenv('SHOPIFY_SHOP_URL')
    api_version = os.getenv('SHOPIFY_API_VERSION')
    access_token = os.getenv('SHOPIFY_ADMIN_ACCESS_TOKEN')
    session = shopify.Session(shop_url, api_version, access_token)
    shopify.ShopifyResource.activate_session(session)
    try:
        orders = shopify.Order.find(email=email, status='any', limit=50)
        products = set()
        for order in orders:
            for item in order.line_items:
                products.add(item.title)
        return list(products)
    finally:
        shopify.ShopifyResource.clear_session()
    """
    Récupère la liste des produits achetés par un client via l'API Shopify Admin.
    """
    import shopify
    shop_url = os.getenv('SHOPIFY_SHOP_URL')
    api_version = os.getenv('SHOPIFY_API_VERSION')
    access_token = os.getenv('SHOPIFY_ADMIN_ACCESS_TOKEN')
    session = shopify.Session(shop_url, api_version, access_token)
    shopify.ShopifyResource.activate_session(session)
    try:
        orders = shopify.Order.find(email=email, status='any', limit=50)
        products = set()
        for order in orders:
            for item in order.line_items:
                products.add(item.title)
        return list(products)
    finally:
        shopify.ShopifyResource.clear_session()
            
        if self.total_pages > 0:
                embed.set_footer(text=f"Page de notes {self.current_page + 1}/{self.total_pages + 1}")
        
        return embed

    # --- Sous-classes pour les boutons ---
    class PrevButton(discord.ui.Button):
        def __init__(self, parent_view):
            super().__init__(label="⬅️ Notes Préc.", style=discord.ButtonStyle.secondary)
            self.parent_view = parent_view
        async def callback(self, interaction: discord.Interaction):
            self.parent_view.current_page -= 1
            await interaction.response.edit_message(embed=self.parent_view.create_embed(), view=self.parent_view)

    class NextButton(discord.ui.Button):
        def __init__(self, parent_view):
            super().__init__(label="Notes Suiv. ➡️", style=discord.ButtonStyle.secondary)
            self.parent_view = parent_view
        async def callback(self, interaction: discord.Interaction):
            self.parent_view.current_page += 1
            await interaction.response.edit_message(embed=self.parent_view.create_embed(), view=self.parent_view)

    class ResetButton(discord.ui.Button):
        def __init__(self, parent_view):
            super().__init__(label="Réinitialiser les Notes", style=discord.ButtonStyle.danger, emoji="🗑️")
            self.parent_view = parent_view
        async def callback(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.send_message(
                f"Êtes-vous sûr de vouloir supprimer **toutes** les notes de {self.parent_view.target_user.mention} ?",
                view=ConfirmResetNotesView(self.parent_view.target_user, self.parent_view.bot),
                ephemeral=True
            )

class ConfirmResetNotesView(discord.ui.View):
    def __init__(self, user, bot):
        super().__init__(timeout=30)
        self.user = user
        self.bot = bot

    @discord.ui.button(label="Confirmer la suppression", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Suppression des notes
        def delete_notes():
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM ratings WHERE user_id = ?", (self.user.id,))
            conn.commit()
            conn.close()
        await asyncio.to_thread(delete_notes)
        await interaction.response.edit_message(content=f"✅ Toutes les notes de {self.user.mention} ont été supprimées.", view=None)

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Suppression annulée.", view=None)

class PromoPaginatorView(discord.ui.View):
    def __init__(self, promo_products: List[dict], general_promos_text: str, items_per_page: int = 6):
        super().__init__(timeout=300)
        self.promo_products = promo_products
        self.general_promos_text = general_promos_text # On stocke le texte des promos
        self.items_per_page = items_per_page
        self.current_page = 0
        self.total_pages = (len(self.promo_products) - 1) // self.items_per_page

        # On ajoute les boutons uniquement s'il y a des produits à paginer
        if self.promo_products and self.total_pages > 0:
            self.add_item(self.PrevButton())
            self.add_item(self.NextButton())
            self.update_buttons()

    def update_buttons(self):
        # On vérifie que les boutons existent avant de les manipuler
        if len(self.children) >= 2:
            self.children[0].disabled = self.current_page == 0
            self.children[1].disabled = self.current_page >= self.total_pages

    def create_embed(self) -> discord.Embed:
        start_index = self.current_page * self.items_per_page
        end_index = start_index + self.items_per_page
        page_items = self.promo_products[start_index:end_index]

        embed = create_styled_embed(
            title="💰 Promotions et Offres Spéciales",
            description="",
            color=discord.Color.from_rgb(255, 105, 180)
        )
        
        promo_display_text = self.general_promos_text if self.general_promos_text.strip() else "Aucune offre générale en ce moment."
        embed.add_field(name="🎁 Offres sur le site", value=promo_display_text, inline=False)

        if not page_items:
            embed.add_field(name="🛍️ Produits en Promotion", value="Aucun produit spécifique n'est en promotion actuellement.", inline=False)
        else:
            for product in page_items:
                prix_promo = product.get('price', 'N/A')
                prix_original = product.get('original_price', '')
                prix_text = f"**{prix_promo}** ~~{prix_original}~~" if prix_original else f"**{prix_promo}**"
                embed.add_field(name=f"🏷️ {product.get('name', 'Produit inconnu')}", value=f"{prix_text}\n[Voir sur le site]({product.get('product_url', '#')})", inline=True)

        if self.promo_products and self.total_pages > 0:
             embed.set_footer(text=f"Page {self.current_page + 1} sur {self.total_pages + 1}")

        return embed

    async def update_message(self, interaction: discord.Interaction):
        self.update_buttons()
        embed = self.create_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    class PrevButton(discord.ui.Button):
        def __init__(self):
            super().__init__(label="⬅️ Précédent", style=discord.ButtonStyle.secondary)
        async def callback(self, interaction: discord.Interaction):
            if self.view.current_page > 0: self.view.current_page -= 1
            await self.view.update_message(interaction)

    class NextButton(discord.ui.Button):
        def __init__(self):
            super().__init__(label="Suivant ➡️", style=discord.ButtonStyle.secondary)
        async def callback(self, interaction: discord.Interaction):
            if self.view.current_page < self.view.total_pages: self.view.current_page += 1
            await self.view.update_message(interaction)

class ProductSelect(discord.ui.Select):
    def __init__(self, products):
        options = [
            discord.SelectOption(label=prod, value=prod)
            for prod in products
        ]
        super().__init__(placeholder="Choisissez un produit", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        # Cette Select est utilisée pour la commande /graph, PAS pour /noter !
        await interaction.response.defer(ephemeral=True, thinking=True)
        product_name = self.values[0]
        try:
            # Génère le graphique radar pour ce produit (moyenne de toutes les notes du serveur)
            chart_path = await asyncio.to_thread(graph_generator.create_radar_chart, product_name)
            if chart_path and os.path.exists(chart_path):
                file = discord.File(chart_path, filename="radar.png")
                embed = discord.Embed(
                    title=f"Graphique radar pour {product_name}",
                    description="Voici la moyenne des notes de toute la communauté pour ce produit.",
                    color=discord.Color.green()
                )
                embed.set_image(url="attachment://radar.png")
                await interaction.followup.send(embed=embed, file=file, ephemeral=True)
                # Nettoyage du fichier temporaire
                await asyncio.to_thread(os.remove, chart_path)
            else:
                await interaction.followup.send("Impossible de générer le graphique pour ce produit (pas assez de notes ?).", ephemeral=True)
        except Exception as e:
            Logger.error(f"Erreur lors de la génération du graphique radar : {e}")
            await interaction.followup.send("Impossible de générer le graphique pour ce produit.", ephemeral=True)

class ProductSelectView(discord.ui.View):
    def __init__(self, products):
        super().__init__(timeout=60)
        self.add_item(ProductSelect(products))

class ContactButtonsView(discord.ui.View):
    def __init__(self, contact_info):
        super().__init__(timeout=120)
        if contact_info.get("site"):
            self.add_item(discord.ui.Button(
                label="Boutique", 
                style=discord.ButtonStyle.link, 
                url=contact_info["site"],
                emoji=LFONCEDALLE_EMOJI
            ))
        if contact_info.get("instagram"):
            self.add_item(discord.ui.Button(
                label="Instagram", 
                style=discord.ButtonStyle.link, 
                url=contact_info["instagram"],
                emoji=INSTAGRAM_EMOJI
            ))
        if contact_info.get("telegram"):
            self.add_item(discord.ui.Button(
                label="Telegram", 
                style=discord.ButtonStyle.link, 
                url=contact_info["telegram"],
                emoji=TELEGRAM_EMOJI
            ))
        if contact_info.get("tiktok"):
            self.add_item(discord.ui.Button(
                label="TikTok", 
                style=discord.ButtonStyle.link, 
                url=contact_info["tiktok"],
                emoji=TIKTOK_EMOJI
            ))



# Classe pour les boutons de contact (à placer avant SlashCommands)
class ContactButtonsView(discord.ui.View):
    def __init__(self, contact_info):
        super().__init__(timeout=120)
        # Vérifiez que les IDs sont bien des entiers et que le bot a accès aux emojis personnalisés
        if contact_info.get("site"):
            self.add_item(discord.ui.Button(
                label="Boutique", 
                style=discord.ButtonStyle.link, 
                url=contact_info["site"],
                emoji=LFONCEDALLE_EMOJI
            ))
        if contact_info.get("instagram"):
            self.add_item(discord.ui.Button(
                label="Instagram", 
                style=discord.ButtonStyle.link, 
                url=contact_info["instagram"],
                emoji=INSTAGRAM_EMOJI
            ))
        if contact_info.get("telegram"):
            self.add_item(discord.ui.Button(
                label="Telegram", 
                style=discord.ButtonStyle.link, 
                url=contact_info["telegram"],
                emoji=TELEGRAM_EMOJI
            ))
        if contact_info.get("tiktok"):
            self.add_item(discord.ui.Button(
                label="TikTok", 
                style=discord.ButtonStyle.link, 
                url=contact_info["tiktok"],
                emoji=TIKTOK_EMOJI
            ))
class RankingPaginatorView(discord.ui.View):
    """Vue pour paginer le classement général des produits."""
    # MODIFICATION 1 : Le constructeur accepte maintenant une map de produits pour les URLs
    def __init__(self, ratings_data: List[Tuple[str, float, int]], product_map: dict, items_per_page: int = 10):
        super().__init__(timeout=300)
        self.ratings = ratings_data
        self.product_map = product_map  # Stocke les détails des produits (nom -> infos)
        self.items_per_page = items_per_page
        self.current_page = 0
        self.total_pages = (len(self.ratings) - 1) // self.items_per_page

        self.update_buttons()

    def update_buttons(self):
        """Active ou désactive les boutons de navigation."""
        # On s'assure que les enfants existent avant de les manipuler
        if len(self.children) >= 2:
            self.children[0].disabled = self.current_page == 0
            self.children[1].disabled = self.current_page >= self.total_pages

    def create_embed_for_page(self) -> discord.Embed:
        """Génère l'embed pour la page actuelle."""
        start_index = self.current_page * self.items_per_page
        end_index = start_index + self.items_per_page
        page_items = self.ratings[start_index:end_index]

        embed = create_styled_embed(
            title="🏆 Classement Général des Produits",
            description="Cliquez sur le nom d'un produit pour visiter sa page sur le site.", # Description mise à jour
            color=discord.Color.blue()
        )

        description_text = ""
        medals = ["🥇", "🥈", "🥉"]
        for i, (name, avg_score, count) in enumerate(page_items):
            rank = start_index + i
            prefix = medals[rank] if rank < 3 else f"**`{rank + 1}.`**"
            
            # MODIFICATION 2 : On cherche le produit dans notre map pour obtenir l'URL
            # On normalise le nom pour être sûr de la correspondance
            normalized_name = name.strip().lower()
            product_details = self.product_map.get(normalized_name)

            # Si on trouve le produit et son URL, on crée un lien, sinon, juste le nom en gras
            if product_details and product_details.get('product_url'):
                product_line = f"[{name}]({product_details['product_url']})"
            else:
                product_line = f"{name}"

            description_text += f"{prefix} **{product_line}**\n"
            description_text += f"> Note moyenne : **{avg_score:.2f}/10** | *({count} avis)*\n\n"
        
        embed.description = description_text
        embed.set_footer(text=f"Page {self.current_page + 1} sur {self.total_pages + 1}")
        
        return embed

    async def update_message(self, interaction: discord.Interaction):
        """Met à jour le message avec la nouvelle page."""
        """Met à jour le message avec la nouvelle page."""
        self.update_buttons()
        embed = self.create_embed_for_page()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="⬅️ Précédent", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
        await self.update_message(interaction)

    @discord.ui.button(label="Suivant ➡️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.total_pages:
            self.current_page += 1
        await self.update_message(interaction)

class SlashCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # --- DÉBUT DES COMMANDES INDENTÉES CORRECTEMENT ---
    @app_commands.command(name="menu", description="Affiche le menu interactif des produits disponibles.")
    async def menu(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await log_user_action(interaction, "a demandé le menu interactif (/menu)")

        try:
            def _read_cache_sync():
                with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            site_data = await asyncio.to_thread(_read_cache_sync)

            if not site_data or not (products := site_data.get('products')):
                await interaction.followup.send("Désolé, le menu n'est pas disponible pour le moment. Réessayez dans un instant.", ephemeral=True)
                return

            # Filtrer les produits pour exclure box/accessoires/réseaux sociaux
            filtered_products = filter_catalog_products(products)

            general_promos_text = "\n".join([f"• {promo}" for promo in site_data.get('general_promos', [])]) or "Aucune promotion générale en cours."
            hash_count, weed_count = get_product_counts(products) # Utilise la fonction filtrée

            embed = discord.Embed(
                title="📢 Menu et Promotions !",
                url=CATALOG_URL,
                description=f"__**📦 Produits disponibles :**__\n\n"
                            f"**`Fleurs 🍃 :` {weed_count}**\n"
                            f"**`Résines 🍫 :` {hash_count}**\n\n"
                            f"__**💰 Promotions disponibles :**__\n\n{general_promos_text}\n\n"
                            f"*(Données mises à jour <t:{int(site_data.get('timestamp'))}:R>)*",
                color=discord.Color.from_rgb(0, 102, 204)
            )
            main_logo_url = config_manager.get_config("contact_info.main_logo_url")
            if main_logo_url:
                embed.set_thumbnail(url=main_logo_url)

            # Créer la vue avec les boutons sur les produits filtrés
            view = MenuView(filtered_products)

            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except (FileNotFoundError, json.JSONDecodeError):
            await interaction.followup.send("Le menu est en cours de construction, veuillez réessayer dans quelques instants.", ephemeral=True)
        except Exception as e:
            Logger.error(f"Erreur dans /menu : {e}")
            traceback.print_exc()
            await interaction.followup.send("❌ Une erreur est survenue lors de l'affichage du menu.", ephemeral=True)

    @app_commands.command(name="export_db", description="Télécharger la base de données des notes utilisateur (staff uniquement)")
    @app_commands.check(is_staff_or_owner)
    async def export_db(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            if not os.path.exists(DB_FILE):
                await interaction.followup.send("Fichier de base de données introuvable.", ephemeral=True)
                return
            file = discord.File(DB_FILE, filename=os.path.basename(DB_FILE))
            await interaction.followup.send("Voici la base de données des notes utilisateur :", file=file, ephemeral=True)
        except Exception as e:
            Logger.error(f"Erreur lors de l'envoi du fichier DB : {e}")
            await interaction.followup.send("Erreur lors de l'envoi du fichier de base de données.", ephemeral=True)

    @app_commands.command(name="noter", description="Note un produit que tu as acheté sur la boutique.")
    async def noter(self, interaction: discord.Interaction):
        try:
            Logger.info("[NOTER DEBUG] Commande reçue. Appel de defer()...")
            await interaction.response.defer(ephemeral=True)
            await log_user_action(interaction, "a initié la commande /noter")
            Logger.info("[NOTER DEBUG] Log réussi. Récupération des achats Shopify...")

            # Appel à l'API Flask pour récupérer les produits achetés
            app_url = "https://votre-app-hebergee.com" # À adapter selon votre hébergement
            api_url = f"{app_url}/api/get_purchased_products/{interaction.user.id}"

            def fetch_purchased_products():
                import requests
                try:
                    response = requests.get(api_url, timeout=10)
                    if response.status_code == 404:
                        return None
                    response.raise_for_status()
                    data = response.json()
                    return data.get("products", [])
                except Exception as e:
                    Logger.error(f"Erreur API Flask get_purchased_products: {e}")
                    return None

            purchased_products = await asyncio.to_thread(fetch_purchased_products)

            if purchased_products is None:
                await interaction.followup.send(
                    "Ton compte Discord n'est pas encore lié à un compte sur la boutique. Utilise la commande `/lier_compte` pour commencer.",
                    ephemeral=True
                )
                return

            if not purchased_products:
                await interaction.followup.send(
                    "Nous n'avons trouvé aucun produit dans ton historique d'achats. Si tu penses que c'est une erreur, contacte le staff.",
                    ephemeral=True
                )
                return

            Logger.info(f"[NOTER DEBUG] {len(purchased_products)} produits achetés trouvés. Création de la vue...")
            view = NotationProductSelectView(purchased_products, interaction.user, self.bot)

            Logger.info("[NOTER DEBUG] Vue créée. Envoi du message followup...")
            await interaction.followup.send("Veuillez choisir un produit à noter :", view=view, ephemeral=True)
            Logger.success("[NOTER DEBUG] Commande /noter terminée avec succès.")

        except Exception as e:
            Logger.error("="*50); Logger.error(f"ERREUR FATALE DANS /noter:"); traceback.print_exc(); Logger.error("="*50)

    @app_commands.command(name="contacts", description="Afficher les informations de contact et réseaux de LaFoncedalle")
    async def contacts(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await log_user_action(interaction, "Commande /contacts")
        contact_info = {
            "site": "https://la-foncedalle.fr/",
            "instagram": "https://www.instagram.com/lafoncedalle.frr/",
            "telegram": "https://t.me/+X1P65R4EVZAXZmEO",
            "tiktok": "https://www.tiktok.com/@terpsbymaaaax"
        }
        # Récupérer la date/heure actuelle pour l'instantanéité
        embed = create_styled_embed(
            f"{SUCETTE_EMOJI} LaFoncedalle - Contacts \n\n",
            "Si vous avez la moindre question, nous vous répondrons avec plaisir ! \n\n"
            "💌 Vous pouvez nous contacter **n'importe quand par mail** : \n `contact@la-foncedalle.fr` \n\n" 
            "📞 Ou à ce numéro (celui de Max) : `07.63.40.31.12`\n"
            "Sur what's app ou directement par appel ou message.\n\n"
            "*(Nous traitons généralement les demandes écrites sous 24H.)*\n\n",
            color=discord.Color.blue()
        )
        view = ContactButtonsView(contact_info)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="debug", description="Force la republication du menu (staff uniquement)")
    @app_commands.check(is_staff_or_owner)
    async def debug(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.bot.force_republish_menu(self.bot) 
        await interaction.followup.send("Menu republication forcée.", ephemeral=True)

    @app_commands.command(name="check", description="Vérifie si de nouveaux produits sont disponibles (cooldown de 12h).")
    async def check(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        cooldown_period = timedelta(hours=12)
        last_check_iso = await config_manager.get_state('last_check_command_timestamp')
        if last_check_iso:
            time_since_last_check = datetime.utcnow() - datetime.fromisoformat(last_check_iso)
            if time_since_last_check < cooldown_period:
                next_allowed_time = datetime.fromisoformat(last_check_iso) + cooldown_period
                await interaction.followup.send(f"⏳ Prochaine vérification possible <t:{int(next_allowed_time.timestamp())}:R>.", ephemeral=True)
                return
        
        await log_user_action(interaction, "a utilisé /check.")
        try:
            updates_found = await self.bot.check_for_updates(self.bot, force_publish=False)
            await config_manager.update_state('last_check_command_timestamp', datetime.utcnow().isoformat())
            if updates_found:
                await interaction.followup.send("✅ Merci ! Le menu a été mis à jour grâce à vous.", ephemeral=True)
            else:
                await interaction.followup.send("👍 Le menu est déjà à jour. Merci d'avoir vérifié !", ephemeral=True)
        except Exception as e:
            Logger.error(f"Erreur dans /check: {e}"); traceback.print_exc()
            await interaction.followup.send("❌ Oups, une erreur est survenue lors de la vérification.", ephemeral=True)

    @app_commands.command(name="graph", description="Voir un graphique radar des moyennes du serveur pour un produit")
    @app_commands.check(is_staff_or_owner)
    async def graph(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await log_user_action(interaction, "Commande /graph")
        # Récupère tous les produits ayant au moins une note
        def fetch_products():
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT product_name FROM ratings")
            products = [row[0] for row in cursor.fetchall()]
            conn.close()
            return products

        products = await asyncio.to_thread(fetch_products)
        if not products:
            await interaction.followup.send("Aucun produit n'a encore été noté sur le serveur.", ephemeral=True)
            return

        view = ProductSelectViewForGraph(products, self.bot)
        await interaction.followup.send("Sélectionnez un produit pour voir le graphique radar des moyennes du serveur :", view=view, ephemeral=True)

    @app_commands.command(name="nitro_gift", description="Réclame ton code de réduction pour avoir boosté le serveur !")
    @app_commands.guild_only() # Cette commande ne peut pas être utilisée en MP
    async def nitro_gift(self, interaction: discord.Interaction):
        """Offre un code de réduction unique aux membres qui boostent le serveur."""
        await interaction.response.defer(ephemeral=True) # Réponse privée à l'utilisateur
        
        user = interaction.user
        guild = interaction.guild

        if not user.premium_since:
            await interaction.followup.send("Désolé, cette commande est réservée aux membres qui boostent actuellement le serveur. Merci pour ton soutien ! 🚀", ephemeral=True)
            return

        claimed_users = {}
        try:
            with open(CLAIMED_CODES_FILE, 'r') as f:
                claimed_users = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass # Le fichier n'existe pas ou est vide, c'est normal au début

        if str(user.id) in claimed_users:
            await interaction.followup.send(f"Tu as déjà réclamé ton code de réduction le {claimed_users[str(user.id)]}. Merci encore pour ton boost ! ✨", ephemeral=True)
            return

        try:
            with open(NITRO_CODES_FILE, 'r+') as f:
                # On lit tous les codes disponibles
                codes = [line.strip() for line in f if line.strip()]
                
                if not codes:
                    await interaction.followup.send("Oh non ! Il semble que nous soyons à court de codes de réduction pour le moment. Merci de contacter un membre du staff. 😥", ephemeral=True)
                    Logger.warning("Tentative de réclamation de code Nitro alors que le fichier est vide.")
                    return
                # On prend le premier code de la liste
                gift_code = codes.pop(0)
                # On réécrit le fichier sans le code qui vient d'être donné
                f.seek(0)
                f.truncate()
                f.write('\n'.join(codes))
            try:
                embed = create_styled_embed(
                    title="Merci pour ton Boost ! 💖",
                    description=f"Encore merci de soutenir **{guild.name}** ! Pour te remercier, voici ton code de réduction personnel à usage unique.\n\n"
                                f"Utilise-le lors de ta prochaine commande sur notre boutique.",
                    color=discord.Color.nitro_pink() # Couleur spéciale Nitro
                )
                embed.add_field(name="🎟️ Ton Code de Réduction", value=f"**`{gift_code}`**")
                embed.set_footer(text="Ce code est à usage unique. Ne le partage pas !")

                await user.send(embed=embed)
                
                # 5. On confirme à l'utilisateur et on enregistre sa réclamation
                await interaction.followup.send("Je viens de t'envoyer ton code de réduction en message privé ! Vérifie tes MPs. 😉", ephemeral=True)
                
                # On sauvegarde l'ID de l'utilisateur et la date de réclamation
                claimed_users[str(user.id)] = datetime.now(paris_tz).strftime('%d/%m/%Y')
                with open(CLAIMED_CODES_FILE, 'w') as f:
                    json.dump(claimed_users, f, indent=4)
                
                await log_user_action(interaction, f"a réclamé avec succès le code Nitro : {gift_code}")

            except discord.Forbidden:
                await interaction.followup.send("Je n'ai pas pu t'envoyer ton code en message privé. Assure-toi d'autoriser les messages privés venant des membres de ce serveur, puis réessaye.", ephemeral=True)

        except FileNotFoundError:
            await interaction.followup.send("Le fichier de codes de réduction n'a pas été trouvé. Merci de contacter un membre du staff.", ephemeral=True)
            Logger.error(f"Le fichier '{NITRO_CODES_FILE}' est introuvable.")
        except Exception as e:
            Logger.error(f"Erreur inattendue dans la commande /nitro_gift : {e}")
            traceback.print_exc()
            await interaction.followup.send("❌ Une erreur interne est survenue. Merci de réessayer ou de contacter un admin.", ephemeral=True)


    @app_commands.command(name="profil", description="Affiche le profil et les notations d'un membre.")
    @app_commands.describe(membre="Le membre dont vous voulez voir le profil (optionnel).")
    async def profil(self, interaction: discord.Interaction, membre: Optional[discord.Member] = None):
        await interaction.response.defer(ephemeral=True)
        
        target_user = membre or interaction.user
        await log_user_action(interaction, f"a consulté le profil de {target_user.display_name}")

        # Déterminer les permissions
        can_reset = False
        if membre and membre.id != interaction.user.id and await is_staff_or_owner(interaction):
            can_reset = True
        def _fetch_user_data_sync(user_id):
            conn = sqlite3.connect(DB_FILE)
            # Permet de récupérer les résultats comme des dictionnaires
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 1. Obtenir toutes les notes de l'utilisateur
            cursor.execute("""
                SELECT product_name, visual_score, smell_score, touch_score, taste_score, effects_score, rating_timestamp
                FROM ratings WHERE user_id = ? ORDER BY rating_timestamp DESC
            """, (user_id,))
            # Convertit les objets Row en dictionnaires
            user_ratings = [dict(row) for row in cursor.fetchall()]

            # 2. Obtenir les statistiques globales (rang, moyenne, etc.)
            # REQUÊTE CORRIGÉE
            cursor.execute("""
                WITH AllRanks AS (
                    SELECT 
                        user_id,
                        COUNT(id) as rating_count,
                        AVG((COALESCE(visual_score, 0) + COALESCE(smell_score, 0) + COALESCE(touch_score, 0) + COALESCE(taste_score, 0) + COALESCE(effects_score, 0)) / 5.0) as avg_note,
                        RANK() OVER (ORDER BY COUNT(id) DESC, AVG((COALESCE(visual_score, 0) + COALESCE(smell_score, 0) + COALESCE(touch_score, 0) + COALESCE(taste_score, 0) + COALESCE(effects_score, 0)) / 5.0) DESC) as user_rank
                    FROM ratings
                    GROUP BY user_id
                )
                SELECT user_rank, rating_count, avg_note FROM AllRanks WHERE user_id = ?
            """, (user_id,))
            stats = cursor.fetchone()
            user_stats = {'rank': stats['user_rank'], 'count': stats['rating_count'], 'avg': stats['avg_note']} if stats else {}

            # 3. Vérifier s'il est top 3 du mois (pour le badge)
            one_month_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
            cursor.execute("""
                SELECT user_id FROM ratings WHERE rating_timestamp >= ? 
                GROUP BY user_id ORDER BY COUNT(id) DESC LIMIT 3
            """, (one_month_ago,))
            top_3_monthly_ids = [row['user_id'] for row in cursor.fetchall()]
            user_stats['is_top_3_monthly'] = user_id in top_3_monthly_ids

            conn.close()
            return user_stats, user_ratings

        try:
            # Récupération et traitement
            user_stats, user_ratings = await asyncio.to_thread(_fetch_user_data_sync, target_user.id)

            if not user_stats:
                await interaction.followup.send("Cet utilisateur n'a encore noté aucun produit.", ephemeral=True)
                return

            # Création et envoi de la vue
            paginator = ProfilePaginatorView(target_user, user_stats, user_ratings, can_reset, self.bot)
            embed = paginator.create_embed()
            await interaction.followup.send(embed=embed, view=paginator, ephemeral=True)

        except Exception as e:
            Logger.error(f"Erreur lors de la génération du profil pour {target_user.display_name}: {e}")
            traceback.print_exc()
            await interaction.followup.send("❌ Une erreur est survenue lors de la récupération du profil.", ephemeral=True)

# commands.py

    @app_commands.command(name="lier_compte", description="Lie ton compte Discord à ton compte sur la boutique pour noter tes achats.")
    async def lier_compte(self, interaction: discord.Interaction):
        # L'URL de base de votre application pont. Doit être accessible publiquement.
        app_url = "https://votre-app-hebergee.com" 
        
        link = f"{app_url}/connect/{interaction.user.id}"
        
        embed = discord.Embed(
            title="🔗 Lier votre compte",
            description="Pour pouvoir noter les produits que tu as achetés, nous devons lier ton compte Discord à ton compte client sur la boutique.\n\n"
                        "**Le processus est simple et sécurisé :**\n"
                        "1. Clique sur le bouton ci-dessous.\n"
                        "2. Connecte-toi à ton compte sur notre boutique.\n"
                        "3. Autorise l'accès à tes commandes (en lecture seule).\n\n"
                        "*Nous ne stockons aucune information personnelle sensible.*",
            color=discord.Color.blue()
        )
        
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Lier mon compte Shopify", url=link, emoji="🔗"))
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    @app_commands.command(name="top_noteurs", description="Affiche le classement des membres qui ont noté le plus de produits.")
    @app_commands.guild_only()
    async def top_noteurs(self, interaction: discord.Interaction):
        """Affiche le classement complet et paginé des membres avec leurs statistiques de notation."""
        # MODIFICATION 1 : On rend le "defer" éphémère.
        # Ainsi, le message "L'application réfléchit..." ne sera visible que par l'utilisateur.
        await interaction.response.defer(ephemeral=True) 
    
        await log_user_action(interaction, "a demandé le classement des top noteurs.")

        def _fetch_top_raters_sync():
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
        
            cursor.execute("""
                WITH UserAverageNotes AS (
                    SELECT 
                        user_id, user_name, rating_timestamp,
                        (COALESCE(visual_score, 0) + COALESCE(smell_score, 0) + COALESCE(touch_score, 0) + COALESCE(taste_score, 0) + COALESCE(effects_score, 0)) / 5.0 AS average_note_per_product
                    FROM ratings
                )
                SELECT
                    uan.user_id,
                    (SELECT user_name FROM UserAverageNotes WHERE user_id = uan.user_id ORDER BY rating_timestamp DESC LIMIT 1) as last_user_name,
                    COUNT(uan.user_id) as rating_count,
                    AVG(uan.average_note_per_product) as global_average,
                    MIN(uan.average_note_per_product) as min_note,
                    MAX(uan.average_note_per_product) as max_note
                FROM UserAverageNotes uan
                GROUP BY uan.user_id
                ORDER BY rating_count DESC, global_average DESC;
            """)
            results = cursor.fetchall()
            conn.close()
            return results

        try:
            top_raters = await asyncio.to_thread(_fetch_top_raters_sync)

            if not top_raters:
                # Ce message est déjà éphémère, c'est parfait.
                await interaction.followup.send("Personne n'a encore noté de produit ! Soyez le premier avec la commande `/noter`.", ephemeral=True)
                return

            paginator = TopRatersPaginatorView(top_raters, interaction.guild, items_per_page=6)
            embed = paginator.create_embed_for_page()
        
        # MODIFICATION 2 : On envoie la réponse finale en mode éphémère.
        # Seul l'utilisateur qui a tapé la commande verra le classement.
            await interaction.followup.send(embed=embed, view=paginator, ephemeral=True)

        except Exception as e:
            Logger.error(f"Erreur lors de la génération du top des noteurs : {e}")
            traceback.print_exc()
            # Ce message est déjà éphémère, c'est parfait.
            await interaction.followup.send("❌ Une erreur est survenue lors de la récupération du classement.", ephemeral=True)

    @app_commands.command(name="selection", description="Publier immédiatement la sélection de la semaine (staff uniquement)")
    @app_commands.check(is_staff_or_owner)
    async def selection(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        # MODIFICATION ICI
        await self.bot.post_weekly_selection(self.bot)
        await interaction.followup.send("La sélection de la semaine a été (re)publiée dans le salon dédié.", ephemeral=True)
    
    # Dans commands.py, à l'intérieur de la classe SlashCommands

    @app_commands.command(name="promos", description="Affiche toutes les promotions en cours sur le site.")
    async def promos(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await log_user_action(interaction, "a demandé la liste des promotions.")

        try:
            def _read_product_cache_sync():
                try:
                    with open(CACHE_FILE, 'r', encoding='utf-8') as f: return json.load(f)
                except (FileNotFoundError, json.JSONDecodeError): return {}

            site_data = await asyncio.to_thread(_read_product_cache_sync)
            if not site_data:
                await interaction.followup.send("Désolé, les informations ne sont pas disponibles.", ephemeral=True)
                return

            promo_products = [p for p in site_data.get('products', []) if p.get('is_promo')]
            general_promos = site_data.get('general_promos', [])
            general_promos_text = "\n".join([f"• {promo}" for promo in general_promos]) if general_promos else ""

            # On passe toutes les infos nécessaires à la vue dès sa création
            paginator = PromoPaginatorView(promo_products, general_promos_text)
            embed = paginator.create_embed()
            
            await interaction.followup.send(embed=embed, view=paginator, ephemeral=True)

        except Exception as e:
            Logger.error(f"Erreur lors de l'exécution de la commande /promos : {e}")
            traceback.print_exc()
            # Ce message ne devrait plus être précédé par une réponse correcte
            await interaction.followup.send("❌ Une erreur est survenue lors de la récupération des promotions.", ephemeral=True)

    @app_commands.command(name="classement_general", description="Affiche la moyenne de tous les produits notés.")
    async def classement_general(self, interaction: discord.Interaction):
        """Affiche un classement complet et paginé de tous les produits ayant reçu une note."""
        await interaction.response.defer()
        await log_user_action(interaction, "a demandé le classement général des produits.")

        # --- Début de la zone "protégée" ---
        try:
            # Fonctions pour récupérer les données
            def _fetch_all_ratings_sync():
                # ... (code de la fonction)
                conn = sqlite3.connect(DB_FILE)
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT product_name, AVG((COALESCE(visual_score, 0) + COALESCE(smell_score, 0) + COALESCE(touch_score, 0) + COALESCE(taste_score, 0) + COALESCE(effects_score, 0)) / 5.0), COUNT(id)
                    FROM ratings GROUP BY product_name HAVING COUNT(id) > 0
                    ORDER BY AVG((visual_score + smell_score + touch_score + taste_score + effects_score) / 5.0) DESC
                """)
                results = cursor.fetchall()
                conn.close()
                return results

            def _read_product_cache_sync():
                # ... (code de la fonction)
                try:
                    with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                        return json.load(f)
                except (FileNotFoundError, json.JSONDecodeError):
                    return {}

            # 1. On récupère les données
            all_products_ratings, site_data = await asyncio.gather(
                asyncio.to_thread(_fetch_all_ratings_sync),
                asyncio.to_thread(_read_product_cache_sync)
            )

            # 2. On vérifie les données
            if not all_products_ratings:
                await interaction.followup.send("Aucun produit n'a encore été noté sur le serveur.", ephemeral=True)
                return

            # 3. On traite les données (création de la map)
            # CETTE PARTIE EST MAINTENANT CORRECTEMENT INDENTÉE DANS LE 'TRY'
            product_map = {
                p['name'].strip().lower(): p 
                for p in site_data.get('products', [])
            }

            # 4. On prépare l'affichage
            # CETTE PARTIE EST AUSSI DANS LE 'TRY'
            paginator = RankingPaginatorView(all_products_ratings, product_map, items_per_page=5)
            embed = paginator.create_embed_for_page()
            
            # 5. On envoie le résultat si tout a réussi
            await interaction.followup.send(embed=embed, view=paginator)

        # --- Fin de la zone "protégée" ---
        
        # Si n'importe quelle ligne dans le 'try' échoue, on arrive ici.
        except Exception as e:
            Logger.error(f"Erreur lors de la génération du classement général : {e}")
            traceback.print_exc()
            await interaction.followup.send("❌ Une erreur est survenue lors de la récupération du classement.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(SlashCommands(bot))

def get_purchased_products_from_shopify(email: str) -> list:
    """
    Récupère la liste des produits achetés par un client via l'API Shopify Admin.
    """
    import shopify
    shop_url = os.getenv('SHOPIFY_SHOP_URL')
    api_version = os.getenv('SHOPIFY_API_VERSION')
    access_token = os.getenv('SHOPIFY_ADMIN_ACCESS_TOKEN')
    session = shopify.Session(shop_url, api_version, access_token)
    shopify.ShopifyResource.activate_session(session)
    try:
        orders = shopify.Order.find(email=email, status='any', limit=50)
        products = set()
        for order in orders:
            for item in order.line_items:
                products.add(item.title)
        return list(products)
    finally:
        shopify.ShopifyResource.clear_session()
    """
    Récupère la liste des produits achetés par un client via l'API Shopify Admin.
    """
    import shopify
    shop_url = os.getenv('SHOPIFY_SHOP_URL')
    api_version = os.getenv('SHOPIFY_API_VERSION')
    access_token = os.getenv('SHOPIFY_ADMIN_ACCESS_TOKEN')
    session = shopify.Session(shop_url, api_version, access_token)
    shopify.ShopifyResource.activate_session(session)
    try:
        orders = shopify.Order.find(email=email, status='any', limit=50)
        products = set()
        for order in orders:
            for item in order.line_items:
                products.add(item.title)
        return list(products)
    finally:
        shopify.ShopifyResource.clear_session()
            
        if self.total_pages > 0:
                embed.set_footer(text=f"Page de notes {self.current_page + 1}/{self.total_pages + 1}")
        
        return embed

    # --- Sous-classes pour les boutons ---
    class PrevButton(discord.ui.Button):
        def __init__(self, parent_view):
            super().__init__(label="⬅️ Notes Préc.", style=discord.ButtonStyle.secondary)
            self.parent_view = parent_view
        async def callback(self, interaction: discord.Interaction):
            self.parent_view.current_page -= 1
            await interaction.response.edit_message(embed=self.parent_view.create_embed(), view=self.parent_view)

    class NextButton(discord.ui.Button):
        def __init__(self, parent_view):
            super().__init__(label="Notes Suiv. ➡️", style=discord.ButtonStyle.secondary)
            self.parent_view = parent_view
        async def callback(self, interaction: discord.Interaction):
            self.parent_view.current_page += 1
            await interaction.response.edit_message(embed=self.parent_view.create_embed(), view=self.parent_view)

    class ResetButton(discord.ui.Button):
        def __init__(self, parent_view):
            super().__init__(label="Réinitialiser les Notes", style=discord.ButtonStyle.danger, emoji="🗑️")
            self.parent_view = parent_view
        async def callback(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.send_message(
                f"Êtes-vous sûr de vouloir supprimer **toutes** les notes de {self.parent_view.target_user.mention} ?",
                view=ConfirmResetNotesView(self.parent_view.target_user, self.parent_view.bot),
                ephemeral=True
            )

class ConfirmResetNotesView(discord.ui.View):
    def __init__(self, user, bot):
        super().__init__(timeout=30)
        self.user = user
        self.bot = bot

    @discord.ui.button(label="Confirmer la suppression", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Suppression des notes
        def delete_notes():
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM ratings WHERE user_id = ?", (self.user.id,))
            conn.commit()
            conn.close()
        await asyncio.to_thread(delete_notes)
        await interaction.response.edit_message(content=f"✅ Toutes les notes de {self.user.mention} ont été supprimées.", view=None)

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Suppression annulée.", view=None)

class PromoPaginatorView(discord.ui.View):
    def __init__(self, promo_products: List[dict], general_promos_text: str, items_per_page: int = 6):
        super().__init__(timeout=300)
        self.promo_products = promo_products
        self.general_promos_text = general_promos_text # On stocke le texte des promos
        self.items_per_page = items_per_page
        self.current_page = 0
        self.total_pages = (len(self.promo_products) - 1) // self.items_per_page

        # On ajoute les boutons uniquement s'il y a des produits à paginer
        if self.promo_products and self.total_pages > 0:
            self.add_item(self.PrevButton())
            self.add_item(self.NextButton())
            self.update_buttons()

    def update_buttons(self):
        # On vérifie que les boutons existent avant de les manipuler
        if len(self.children) >= 2:
            self.children[0].disabled = self.current_page == 0
            self.children[1].disabled = self.current_page >= self.total_pages

    def create_embed(self) -> discord.Embed:
        start_index = self.current_page * self.items_per_page
        end_index = start_index + self.items_per_page
        page_items = self.promo_products[start_index:end_index]

        embed = create_styled_embed(
            title="💰 Promotions et Offres Spéciales",
            description="",
            color=discord.Color.from_rgb(255, 105, 180)
        )
        
        promo_display_text = self.general_promos_text if self.general_promos_text.strip() else "Aucune offre générale en ce moment."
        embed.add_field(name="🎁 Offres sur le site", value=promo_display_text, inline=False)

        if not page_items:
            embed.add_field(name="🛍️ Produits en Promotion", value="Aucun produit spécifique n'est en promotion actuellement.", inline=False)
        else:
            for product in page_items:
                prix_promo = product.get('price', 'N/A')
                prix_original = product.get('original_price', '')
                prix_text = f"**{prix_promo}** ~~{prix_original}~~" if prix_original else f"**{prix_promo}**"
                embed.add_field(name=f"🏷️ {product.get('name', 'Produit inconnu')}", value=f"{prix_text}\n[Voir sur le site]({product.get('product_url', '#')})", inline=True)

        if self.promo_products and self.total_pages > 0:
             embed.set_footer(text=f"Page {self.current_page + 1} sur {self.total_pages + 1}")

        return embed

    async def update_message(self, interaction: discord.Interaction):
        self.update_buttons()
        embed = self.create_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    class PrevButton(discord.ui.Button):
        def __init__(self):
            super().__init__(label="⬅️ Précédent", style=discord.ButtonStyle.secondary)
        async def callback(self, interaction: discord.Interaction):
            if self.view.current_page > 0: self.view.current_page -= 1
            await self.view.update_message(interaction)

    class NextButton(discord.ui.Button):
        def __init__(self):
            super().__init__(label="Suivant ➡️", style=discord.ButtonStyle.secondary)
        async def callback(self, interaction: discord.Interaction):
            if self.view.current_page < self.view.total_pages: self.view.current_page += 1
            await self.view.update_message(interaction)

class ProductSelect(discord.ui.Select):
    def __init__(self, products):
        options = [
            discord.SelectOption(label=prod, value=prod)
            for prod in products
        ]
        super().__init__(placeholder="Choisissez un produit", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        # Cette Select est utilisée pour la commande /graph, PAS pour /noter !
        await interaction.response.defer(ephemeral=True, thinking=True)
        product_name = self.values[0]
        try:
            # Génère le graphique radar pour ce produit (moyenne de toutes les notes du serveur)
            chart_path = await asyncio.to_thread(graph_generator.create_radar_chart, product_name)
            if chart_path and os.path.exists(chart_path):
                file = discord.File(chart_path, filename="radar.png")
                embed = discord.Embed(
                    title=f"Graphique radar pour {product_name}",
                    description="Voici la moyenne des notes de toute la communauté pour ce produit.",
                    color=discord.Color.green()
                )
                embed.set_image(url="attachment://radar.png")
                await interaction.followup.send(embed=embed, file=file, ephemeral=True)
                # Nettoyage du fichier temporaire
                await asyncio.to_thread(os.remove, chart_path)
            else:
                await interaction.followup.send("Impossible de générer le graphique pour ce produit (pas assez de notes ?).", ephemeral=True)
        except Exception as e:
            Logger.error(f"Erreur lors de la génération du graphique radar : {e}")
            await interaction.followup.send("Impossible de générer le graphique pour ce produit.", ephemeral=True)

class ProductSelectView(discord.ui.View):
    def __init__(self, products):
        super().__init__(timeout=60)
        self.add_item(ProductSelect(products))

class ContactButtonsView(discord.ui.View):
    def __init__(self, contact_info):
        super().__init__(timeout=120)
        if contact_info.get("site"):
            self.add_item(discord.ui.Button(
                label="Boutique", 
                style=discord.ButtonStyle.link, 
                url=contact_info["site"],
                emoji=LFONCEDALLE_EMOJI
            ))
        if contact_info.get("instagram"):
            self.add_item(discord.ui.Button(
                label="Instagram", 
                style=discord.ButtonStyle.link, 
                url=contact_info["instagram"],
                emoji=INSTAGRAM_EMOJI
            ))
        if contact_info.get("telegram"):
            self.add_item(discord.ui.Button(
                label="Telegram", 
                style=discord.ButtonStyle.link, 
                url=contact_info["telegram"],
                emoji=TELEGRAM_EMOJI
            ))
        if contact_info.get("tiktok"):
            self.add_item(discord.ui.Button(
                label="TikTok", 
                style=discord.ButtonStyle.link, 
                url=contact_info["tiktok"],
                emoji=TIKTOK_EMOJI
            ))



# Classe pour les boutons de contact (à placer avant SlashCommands)
class ContactButtonsView(discord.ui.View):
    def __init__(self, contact_info):
        super().__init__(timeout=120)
        # Vérifiez que les IDs sont bien des entiers et que le bot a accès aux emojis personnalisés
        if contact_info.get("site"):
            self.add_item(discord.ui.Button(
                label="Boutique", 
                style=discord.ButtonStyle.link, 
                url=contact_info["site"],
                emoji=LFONCEDALLE_EMOJI
            ))
        if contact_info.get("instagram"):
            self.add_item(discord.ui.Button(
                label="Instagram", 
                style=discord.ButtonStyle.link, 
                url=contact_info["instagram"],
                emoji=INSTAGRAM_EMOJI
            ))
        if contact_info.get("telegram"):
            self.add_item(discord.ui.Button(
                label="Telegram", 
                style=discord.ButtonStyle.link, 
                url=contact_info["telegram"],
                emoji=TELEGRAM_EMOJI
            ))
        if contact_info.get("tiktok"):
            self.add_item(discord.ui.Button(
                label="TikTok", 
                style=discord.ButtonStyle.link, 
                url=contact_info["tiktok"],
                emoji=TIKTOK_EMOJI
            ))
class RankingPaginatorView(discord.ui.View):
    """Vue pour paginer le classement général des produits."""
    # MODIFICATION 1 : Le constructeur accepte maintenant une map de produits pour les URLs
    def __init__(self, ratings_data: List[Tuple[str, float, int]], product_map: dict, items_per_page: int = 10):
        super().__init__(timeout=300)
        self.ratings = ratings_data
        self.product_map = product_map  # Stocke les détails des produits (nom -> infos)
        self.items_per_page = items_per_page
        self.current_page = 0
        self.total_pages = (len(self.ratings) - 1) // self.items_per_page

        self.update_buttons()

    def update_buttons(self):
        """Active ou désactive les boutons de navigation."""
        # On s'assure que les enfants existent avant de les manipuler
        if len(self.children) >= 2:
            self.children[0].disabled = self.current_page == 0
            self.children[1].disabled = self.current_page >= self.total_pages

    def create_embed_for_page(self) -> discord.Embed:
        """Génère l'embed pour la page actuelle."""
        start_index = self.current_page * self.items_per_page
        end_index = start_index + self.items_per_page
        page_items = self.ratings[start_index:end_index]

        embed = create_styled_embed(
            title="🏆 Classement Général des Produits",
            description="Cliquez sur le nom d'un produit pour visiter sa page sur le site.", # Description mise à jour
            color=discord.Color.blue()
        )

        description_text = ""
        medals = ["🥇", "🥈", "🥉"]
        for i, (name, avg_score, count) in enumerate(page_items):
            rank = start_index + i
            prefix = medals[rank] if rank < 3 else f"**`{rank + 1}.`**"
            
            # MODIFICATION 2 : On cherche le produit dans notre map pour obtenir l'URL
            # On normalise le nom pour être sûr de la correspondance
            normalized_name = name.strip().lower()
            product_details = self.product_map.get(normalized_name)

            # Si on trouve le produit et son URL, on crée un lien, sinon, juste le nom en gras
            if product_details and product_details.get('product_url'):
                product_line = f"[{name}]({product_details['product_url']})"
            else:
                product_line = f"{name}"

            description_text += f"{prefix} **{product_line}**\n"
            description_text += f"> Note moyenne : **{avg_score:.2f}/10** | *({count} avis)*\n\n"
        
        embed.description = description_text
        embed.set_footer(text=f"Page {self.current_page + 1} sur {self.total_pages + 1}")
        
        return embed

    async def update_message(self, interaction: discord.Interaction):
        """Met à jour le message avec la nouvelle page."""
        """Met à jour le message avec la nouvelle page."""
        self.update_buttons()
        embed = self.create_embed_for_page()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="⬅️ Précédent", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
        await self.update_message(interaction)

    @discord.ui.button(label="Suivant ➡️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.total_pages:
            self.current_page += 1
        await self.update_message(interaction)


