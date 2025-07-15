# commands.py

import discord
from discord.ext import commands
from discord import app_commands
import json
import time
from typing import List, Optional, Tuple 
import sqlite3
from datetime import datetime, timedelta
import traceback
import asyncio
import os

# --- Imports depuis les fichiers du projet ---

# ON IMPORTE DEPUIS shared_utils MAINTENANT
from shared_utils import (
    log_user_action, Logger, executor, CACHE_FILE,
    CATALOG_URL, DB_FILE, STAFF_ROLE_ID,
    config_manager, create_styled_embed,
    TIKTOK_EMOJI, LFONCEDALLE_EMOJI, TELEGRAM_EMOJI, INSTAGRAM_EMOJI,
    SELECTION_CHANNEL_ID, SUCETTE_EMOJI, NITRO_CODES_FILE, CLAIMED_CODES_FILE, paris_tz, get_product_counts,
    categorize_products, filter_catalog_products, APP_URL # <-- Ajout ici
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
    def __init__(self, products: List[dict], category: str = None):
        super().__init__(timeout=300)
        self.products = products
        self.current_index = 0
        self.category = category
        self.download_lab_url = None
        self.download_terpen_url = None
        self.update_buttons()
        self.update_download_buttons()

    def update_buttons(self):
        if len(self.children) >= 2:
            self.children[0].disabled = self.current_index == 0
            self.children[1].disabled = self.current_index >= len(self.products) - 1

    def update_download_buttons(self):
        self.download_lab_url = None
        self.download_terpen_url = None
        self.children = [c for c in self.children if not hasattr(c, "is_download_button")]
        product = self.products[self.current_index]
        stats = product.get('stats', {})
        for k, v in stats.items():
            if "lab" in k.lower() and ("pdf" in k.lower() or str(v).startswith("http")):
                self.download_lab_url = v
            if "terpen" in k.lower() and ("pdf" in k.lower() or str(v).startswith("http")):
                self.download_terpen_url = v
        if self.download_lab_url and str(self.download_lab_url).startswith("http"):
            self.add_item(self.DownloadButton("Télécharger Lab Test", self.download_lab_url, emoji="🧪"))
        if self.download_terpen_url and str(self.download_terpen_url).startswith("http"):
            self.add_item(self.DownloadButton("Télécharger Terpen Test", self.download_terpen_url, emoji="🌿"))

    def get_category_emoji(self):
        if self.category == "weed":
            return "🍃"
        if self.category == "hash":
            return "🍫"
        if self.category == "box":
            return "📦"
        if self.category == "accessoire":
            return "🛠️"
        return ""

    def create_embed(self) -> discord.Embed:
        product = self.products[self.current_index]
        emoji = self.get_category_emoji()
        embed_color = discord.Color.dark_red() if product.get('is_sold_out') else discord.Color.from_rgb(255, 204, 0)
        title = f"{emoji} **{product.get('name', 'Produit inconnu')}**"
        embed = discord.Embed(
            title=title,
            url=product.get('product_url', CATALOG_URL),
            description=None,
            color=embed_color
        )
        if product.get('image'):
            embed.set_thumbnail(url=product['image'])

        # Description courte
        description = product.get('detailed_description', "Aucune description.")
        if description and len(description) > 220:
            description = description[:220] + "..."
        embed.add_field(name="Description", value=description, inline=False)

        # Prix et promo
        price_text = ""
        if product.get('is_sold_out'):
            price_text = "❌ **ÉPUISÉ**"
        elif product.get('is_promo'):
            price_text = f"🏷️ **{product.get('price')}** ~~{product.get('original_price')}~~"
        else:
            price_text = f"💰 **{product.get('price', 'N/A')}**"
        embed.add_field(name="Prix", value=price_text, inline=True)

        # Stock
        if not product.get('is_sold_out') and product.get('stats', {}).get('Stock'):
            embed.add_field(name="Stock", value=f"{product['stats']['Stock']}", inline=True)

        # Caractéristiques stylisées
        stats = product.get('stats', {})
        char_lines = []
        for k, v in stats.items():
            if "pdf" in k.lower() or "lab" in k.lower() or "terpen" in k.lower():
                continue
            if "effet" in k.lower():
                char_lines.append(f"**Effet :** {v}")
            elif "gout" in k.lower():
                char_lines.append(f"**Goût :** {v}")
            elif "cbd" in k.lower():
                char_lines.append(f"**CBD :** {v}")
            elif "thc" in k.lower():
                char_lines.append(f"**THC :** {v}")
            elif "stock" in k.lower():
                continue
            else:
                char_lines.append(f"**{k.capitalize()} :** {v}")
        if char_lines:
            embed.add_field(name="Caractéristiques", value="\n".join(char_lines), inline=False)

        # Lien direct vers la fiche produit
        embed.add_field(name="Voir sur le site", value=f"[Fiche produit]({product.get('product_url', CATALOG_URL)})", inline=False)

        # Lab test et terpen test affichés si non bouton
        for k, v in stats.items():
            if ("lab" in k.lower() or "terpen" in k.lower()) and not str(v).startswith("http"):
                embed.add_field(name=k.replace("_", " ").capitalize(), value=v, inline=False)

        embed.set_footer(text=f"Produit {self.current_index + 1} sur {len(self.products)}")
        return embed

    async def update_message(self, interaction: discord.Interaction):
        self.update_buttons()
        self.update_download_buttons()
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

    class DownloadButton(discord.ui.Button):
        def __init__(self, label, url, emoji=None):
            super().__init__(label=label, style=discord.ButtonStyle.link, url=url, emoji=emoji)
            self.is_download_button = True

# Fichier : commands.py

class MenuView(discord.ui.View):
    def __init__(self, all_products: List[dict]):
        super().__init__(timeout=None)  # Vue persistante

        # --- Catégorisation des produits ---
        categorized = categorize_products(all_products)
        self.weed_products = categorized["weed"]
        self.hash_products = categorized["hash"]
        self.box_products = categorized["box"]
        self.accessoire_products = categorized["accessoire"]

        # --- Ajout des boutons ---
        # On ajoute les boutons qui sont toujours présents
        self.add_item(self.WeedButton(self))
        self.add_item(self.HashButton(self))

        # On ajoute les boutons conditionnels
        if self.box_products:
            self.add_item(self.BoxButton(self))
        
        if self.accessoire_products:
            self.add_item(self.AccessoireButton(self))

    # --- Logique partagée pour afficher la vue du produit ---
    async def start_product_view(self, interaction: discord.Interaction, products: List[dict], category_name: str):
        # --- ÉTAPE 1 : DÉFÉRER L'INTERACTION IMMÉDIATEMENT ---
        # On dit à Discord "j'ai reçu le clic", et on demande à ce que la réponse soit cachée (ephemeral).
        await interaction.response.defer(ephemeral=True)

        if not products:
            # --- ÉTAPE 2 : UTILISER .followup.send POUR LA RÉPONSE ---
            await interaction.followup.send(f"Désolé, aucun produit de type '{category_name}' trouvé.", ephemeral=True)
            return
        
        view = ProductView(products, category=category_name.lower())
        embed = view.create_embed()
        
        # --- ÉTAPE 2 : UTILISER .followup.send POUR LA RÉPONSE ---
        # On envoie le nouveau menu en utilisant le "suivi" de l'interaction.
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    # --- Sous-classes pour chaque bouton ---
    # C'est la méthode la plus fiable pour les vues persistantes.
    
    class WeedButton(discord.ui.Button):
        def __init__(self, parent_view):
            super().__init__(label="Nos Fleurs 🍃", style=discord.ButtonStyle.success, emoji="🍃", custom_id="persistent_menu:fleurs")
            self.parent_view = parent_view
        
        async def callback(self, interaction: discord.Interaction):
            # --- AJOUTEZ CETTE LIGNE ---
            Logger.info(f"CLICK: Bouton '{self.label}' pressé par {interaction.user.name}. Tentative de defer...")
            
            # Le reste du code est identique
            await self.parent_view.start_product_view(interaction, self.parent_view.weed_products, "weed")

    class HashButton(discord.ui.Button):
        def __init__(self, parent_view):
            super().__init__(label="Nos Résines 🍫", style=discord.ButtonStyle.primary, emoji="🍫", custom_id="persistent_menu:resines")
            self.parent_view = parent_view

        async def callback(self, interaction: discord.Interaction):
            await self.parent_view.start_product_view(interaction, self.parent_view.hash_products, "hash")

    class BoxButton(discord.ui.Button):
        def __init__(self, parent_view):
            super().__init__(label="Nos Box 📦", style=discord.ButtonStyle.success, emoji="📦", custom_id="persistent_menu:box")
            self.parent_view = parent_view

        async def callback(self, interaction: discord.Interaction):
            await self.parent_view.start_product_view(interaction, self.parent_view.box_products, "box")

    class AccessoireButton(discord.ui.Button):
        def __init__(self, parent_view):
            super().__init__(label="Accessoires 🛠️", style=discord.ButtonStyle.secondary, emoji="🛠️", custom_id="persistent_menu:accessoires")
            self.parent_view = parent_view
            
        async def callback(self, interaction: discord.Interaction):
            await self.parent_view.start_product_view(interaction, self.parent_view.accessoire_products, "accessoire")

class ProductSelectViewForGraph(discord.ui.View):
    def __init__(self, products, bot):
        super().__init__(timeout=60)
        self.add_item(ProductSelectForGraph(products, bot))

class ProductSelectForGraph(discord.ui.Select):
    def __init__(self, products, bot):
        self.bot = bot
        options = [discord.SelectOption(label=p, value=p) for p in products]
        super().__init__(placeholder="Choisissez un produit pour voir son graphique...", options=options)

    async def callback(self, interaction: discord.Interaction):
        import graph_generator
        product_name = self.values[0]
        await interaction.response.send_message(f"Génération du graphique pour **{product_name}**...", ephemeral=True, delete_after=10)
        
        chart_path = await asyncio.to_thread(graph_generator.create_radar_chart, product_name)
        if chart_path:
            file = discord.File(chart_path, filename="radar_chart.png")
            embed = discord.Embed(
                title=f"Graphique Radar pour {product_name}",
                description="Moyenne des notes de la communauté pour ce produit.",
                color=discord.Color.green()
            ).set_image(url="attachment://radar_chart.png")
            await interaction.followup.send(embed=embed, file=file, ephemeral=True)
            os.remove(chart_path)
        else:
            await interaction.followup.send("Impossible de générer le graphique (pas assez de données ?).", ephemeral=True)
            
class ProfilePaginatorView(discord.ui.View):
    def __init__(self, target_user, user_stats, user_ratings, can_reset, bot, items_per_page=3):
        super().__init__(timeout=300)
        self.target_user = target_user
        self.user_stats = user_stats
        self.user_ratings = user_ratings
        self.can_reset = can_reset
        self.bot = bot
        self.items_per_page = items_per_page
        
        # Pagination pour les notes
        self.current_page = 0
        self.total_pages = (len(self.user_ratings) - 1) // self.items_per_page
        
        # On ajoute les boutons
        self.update_buttons()

    def update_buttons(self):
        # On vide les boutons pour les recréer proprement
        self.clear_items()
        
        # Bouton pour la page de profil
        self.add_item(self.ProfileButton(self))

        # Boutons de pagination des notes, si nécessaire
        if self.total_pages > 0:
            self.add_item(self.PrevButton(self))
            self.add_item(self.NextButton(self))
            
        # Bouton de réinitialisation pour le staff
        if self.can_reset:
            self.add_item(self.ResetButton(self))
            
        # Mise à jour de l'état des boutons
        for item in self.children:
            if isinstance(item, self.PrevButton):
                item.disabled = self.current_page == 0
            if isinstance(item, self.NextButton):
                item.disabled = self.current_page >= self.total_pages

    def create_embed(self) -> discord.Embed:
        if self.current_page == -1: # Page de profil
            return self.create_profile_embed()
        else: # Pages de notes
            return self.create_ratings_embed()

    def create_profile_embed(self) -> discord.Embed:
        # ... (Logique pour l'embed du profil principal)
        embed = discord.Embed(title=f"Profil de {self.target_user.display_name}", color=discord.Color.blue())
        embed.set_thumbnail(url=self.target_user.display_avatar.url)

        rank = self.user_stats.get('rank', 'Non classé')
        count = self.user_stats.get('count', 0)
        avg = f"{self.user_stats.get('avg', 0):.2f}/10"
        
        embed.add_field(name="🏆 Classement", value=f"**#{rank}**", inline=True)
        embed.add_field(name="📝 Notations", value=f"**{count}** produits", inline=True)
        embed.add_field(name="📊 Moyenne", value=f"**{avg}**", inline=True)
        
        if self.user_stats.get('is_top_3_monthly'):
             embed.add_field(name="Badge", value="🏅 Top Noteur du Mois", inline=False)
        
        footer_text = f"Cliquez sur les boutons pour voir les notes."
        embed.set_footer(text=footer_text)
        return embed

    def create_ratings_embed(self) -> discord.Embed:
        # ... (Logique pour l'embed des notes paginées)
        embed = discord.Embed(title=f"Notes de {self.target_user.display_name}", color=discord.Color.green())
        embed.set_thumbnail(url=self.target_user.display_avatar.url)

        start_index = self.current_page * self.items_per_page
        end_index = start_index + self.items_per_page
        page_ratings = self.user_ratings[start_index:end_index]

        if not page_ratings:
            embed.description = "Aucune note à afficher sur cette page."
        else:
            for rating in page_ratings:
                avg_score = (rating.get('visual_score',0) + rating.get('smell_score',0) + rating.get('touch_score',0) + rating.get('taste_score',0) + rating.get('effects_score',0)) / 5
                date = datetime.fromisoformat(rating['rating_timestamp']).strftime('%d/%m/%Y')
                embed.add_field(
                    name=f"**{rating['product_name']}** - Noté le {date}",
                    value=f"> **Note moyenne : {avg_score:.2f}/10**",
                    inline=False
                )
        
        if self.total_pages >= 0:
            embed.set_footer(text=f"Page de notes {self.current_page + 1}/{self.total_pages + 1}")
        return embed

    async def update_view(self, interaction: discord.Interaction):
        self.update_buttons()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    class ProfileButton(discord.ui.Button):
        def __init__(self, parent_view):
            super().__init__(label="Profil", style=discord.ButtonStyle.primary, emoji="👤")
            self.parent_view = parent_view
        async def callback(self, interaction: discord.Interaction):
            self.parent_view.current_page = -1
            await self.parent_view.update_view(interaction)

    class PrevButton(discord.ui.Button):
        def __init__(self, parent_view):
            super().__init__(label="⬅️ Préc.", style=discord.ButtonStyle.secondary)
            self.parent_view = parent_view
        async def callback(self, interaction: discord.Interaction):
            if self.parent_view.current_page > 0:
                self.parent_view.current_page -= 1
            await self.parent_view.update_view(interaction)
            
    class NextButton(discord.ui.Button):
        def __init__(self, parent_view):
            super().__init__(label="Suiv. ➡️", style=discord.ButtonStyle.secondary)
            self.parent_view = parent_view
        async def callback(self, interaction: discord.Interaction):
            if self.parent_view.current_page < self.parent_view.total_pages:
                self.parent_view.current_page += 1
            await self.parent_view.update_view(interaction)

    class ResetButton(discord.ui.Button):
        def __init__(self, parent_view):
            super().__init__(label="Réinitialiser", style=discord.ButtonStyle.danger, emoji="🗑️")
            self.parent_view = parent_view
        async def callback(self, interaction: discord.Interaction):
            # Logique pour confirmer la suppression, qui utilise ConfirmResetNotesView
            await interaction.response.send_message(
                f"Êtes-vous sûr de vouloir supprimer **toutes** les notes de {self.parent_view.target_user.mention} ?",
                view=ConfirmResetNotesView(self.parent_view.target_user, self.parent_view.bot),
                ephemeral=True
            )

class ConfirmResetNotesView(discord.ui.View):
    def __init__(self, user, bot):
        super().__init__(timeout=60)
        self.user = user
        self.bot = bot
    @discord.ui.button(label="Confirmer la suppression", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Logique de suppression
        def _delete_notes_sync(user_id):
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM ratings WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
        await asyncio.to_thread(_delete_notes_sync, self.user.id)
        await interaction.response.edit_message(content=f"✅ Toutes les notes de {self.user.mention} ont été supprimées.", view=None)
    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Opération annulée.", view=None)

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

            promos_list = site_data.get('general_promos', [])
            general_promos_text = "\n".join([f"• {promo.strip()}" for promo in promos_list if promo.strip()]) or "Aucune promotion générale en cours."
            hash_count, weed_count, box_count, accessoire_count = get_product_counts(products)

            description_text = (
                f"__**📦 Produits disponibles :**__\n\n"
                f"**`Fleurs 🍃 :` {weed_count}**\n"
                f"**`Résines 🍫 :` {hash_count}**\n"
                f"**`Box 📦 :` {box_count}**\n"
                f"**`Accessoires 🛠️ :` {accessoire_count}**\n\n"
                f"__**💰 Promotions disponibles :**__\n\n{general_promos_text}\n\n"
                f"*(Données mises à jour <t:{int(site_data.get('timestamp'))}:R>)*"
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

            api_url = f"{APP_URL}/api/get_purchased_products/{interaction.user.id}"

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
        import graph_generator 
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

    @app_commands.command(name="lier_compte", description="Démarre la liaison de ton compte via ton e-mail de commande.")
    @app_commands.describe(email="L'adresse e-mail que tu utilises pour tes commandes sur la boutique.")
    async def lier_compte(self, interaction: discord.Interaction, email: str):
        await interaction.response.defer(ephemeral=True)
        api_url = f"{APP_URL}/api/start-verification"
        payload = {"discord_id": str(interaction.user.id), "email": email}
        
        try:
            response = requests.post(api_url, json=payload, timeout=15)
            response.raise_for_status()

            await interaction.followup.send(
                f"✅ Un e-mail de vérification a été envoyé à **{email}**.\n"
                f"Consulte ta boîte de réception (et tes spams !) puis utilise la commande `/verifier` avec le code reçu.",
                ephemeral=True
            )
        except requests.exceptions.RequestException as e:
            Logger.error(f"Erreur API /start-verification : {e}")
            await interaction.followup.send("❌ Impossible de contacter le service de vérification. Merci de réessayer plus tard.", ephemeral=True)

    @app_commands.command(name="verifier", description="Valide ton adresse e-mail avec le code reçu.")
    @app_commands.describe(code="Le code à 6 chiffres reçu par e-mail.")
    async def verifier(self, interaction: discord.Interaction, code: str):
        await interaction.response.defer(ephemeral=True)
        api_url = f"{APP_URL}/api/confirm-verification"
        payload = {"discord_id": str(interaction.user.id), "code": code.strip()}

        try:
            response = requests.post(api_url, json=payload, timeout=15)
            
            if response.ok:
                 await interaction.followup.send("🎉 **Félicitations !** Ton compte est maintenant lié. Tu peux utiliser la commande `/noter`.", ephemeral=True)
            else:
                error_message = response.json().get("error", "Une erreur inconnue est survenue.")
                await interaction.followup.send(f"❌ **Échec de la vérification :** {error_message}", ephemeral=True)

        except requests.exceptions.RequestException as e:
            Logger.error(f"Erreur API /confirm-verification : {e}")
            await interaction.followup.send("❌ Impossible de contacter le service de vérification. Merci de réessayer plus tard.", ephemeral=True)

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


        except Exception as e:
            Logger.error(f"Erreur lors de la génération du classement général : {e}")
            traceback.print_exc()
            await interaction.followup.send("❌ Une erreur est survenue lors de la récupération du classement.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(SlashCommands(bot))
