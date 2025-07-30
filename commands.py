import discord
from discord.ext import commands
from discord import app_commands
import json, time, sqlite3, traceback, asyncio, os
from typing import List, Optional
from datetime import datetime, timedelta
from typing import List, Optional, Union
from discord.app_commands import Choice
from profil_image_generator import create_profile_card
from shared_utils import *
from graph_generator import create_radar_chart
import re
import numpy as np

FLASK_SECRET_KEY = os.getenv('FLASK_SECRET_KEY')

# --- Logique des permissions ---
async def is_staff_or_owner(interaction: discord.Interaction) -> bool:
    if await interaction.client.is_owner(interaction.user): return True
    if not interaction.guild: return False # Ne peut pas être staff en DM
    # On récupère l'ID du rôle pour CE serveur spécifique
    staff_role_id = await config_manager.get_state(interaction.guild.id, 'staff_role_id', STAFF_ROLE_ID)
    if not staff_role_id: return False
    
    try: 
        staff_role_id_int = int(staff_role_id)
    except (ValueError, TypeError): 
        return False
    return any(role.id == staff_role_id_int for role in interaction.user.roles)

   
# --- VUES ET MODALES ---

class UnsubscribeButton(discord.ui.View):
    def __init__(self, user_id: int, order_id: str, bot):
        super().__init__(timeout=None)  # Le timeout est mis à None pour que les vues soient persistantes
        self.user_id = user_id
        self.order_id = order_id
        self.bot = bot

    @discord.ui.button(label="Je ne veux plus de rappels", style=discord.ButtonStyle.secondary, custom_id="unsubscribe_reminder")
    async def unsubscribe_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True) # Répond à l'interaction pour montrer que quelque chose se passe
        
        # --- Appel de l'API pour ajouter à la liste noire ---
        api_url_blacklist = f"{APP_URL}/api/blacklist_user_for_reminders"
        payload = {"discord_id": str(self.user_id)}

        try:
            import aiohttp # Assurez-vous que aiohttp est importé en haut de votre fichier commands.py

            async with aiohttp.ClientSession() as session:
                async with session.post(api_url_blacklist, json=payload, timeout=10) as response:
                    if response.ok:
                        Logger.success(f"Utilisateur {self.user_id} ajouté à la liste noire via le bouton.")
                        await interaction.followup.send("Vous ne recevrez plus de rappels de notation. Si vous changez d'avis, utilisez la commande `/settings` (si vous l'implémentez).", ephemeral=True)
                        
                        # Désactiver le bouton une fois utilisé
                        button.disabled = True
                        await interaction.message.edit(view=self) # Mettre à jour le message avec le bouton désactivé

                    else:
                        Logger.error(f"Erreur API lors de la désinscription de {self.user_id}: {response.status}")
                        await interaction.followup.send("Une erreur est survenue lors de la désinscription. Veuillez réessayer.", ephemeral=True)
        
        except Exception as e:
            Logger.error(f"Erreur lors du traitement du bouton de désinscription pour {self.user_id}: {e}")
            traceback.print_exc()
            await interaction.followup.send("Une erreur critique est survenue. Contactez un administrateur.", ephemeral=True)

class ConfirmResetLoyaltyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Oui, tout supprimer", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        # Réinitialise la configuration en la remplaçant par un dictionnaire vide
        await config_manager.update_config("loyalty_roles", {})
        
        Logger.warning(f"L'administrateur {interaction.user} a réinitialisé la configuration des rôles de fidélité.")
        await interaction.followup.send(
            "✅ La configuration des rôles de fidélité a été entièrement réinitialisée.",
            ephemeral=True
        )
        # On désactive les boutons du message de confirmation
        await interaction.edit_original_response(view=None)
        self.stop()

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Opération annulée.", view=None)
        self.stop()

class HelpView(discord.ui.View):
    def __init__(self, cog_instance):
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.main_embed = self.create_main_embed()
        # On pré-charge les IDs des commandes pour les rendre cliquables
        self.cmd_map = {}

    async def _get_cmd_map(self):
        """Charge la map des commandes si elle n'existe pas déjà."""
        if not self.cmd_map:
            app_commands = await self.cog.bot.tree.fetch_commands()
            self.cmd_map = {cmd.name: cmd.id for cmd in app_commands}
        return self.cmd_map

    def format_cmd(self, name):
        """Formate une commande pour la rendre cliquable dans un embed."""
        return f"</{name}:{self.cmd_map.get(name, 0)}>"

    def create_main_embed(self) -> discord.Embed:
        return create_styled_embed(
            title="👋 Centre d'Aide de LaFoncedalleBot",
            description=(
                "Bienvenue ! Ce bot est là pour enrichir ton expérience sur le serveur.\n"
                "Utilise les boutons ci-dessous pour explorer toutes ses fonctionnalités."
            )
        )

    @discord.ui.button(label="🚀 Pour Bien Démarrer", style=discord.ButtonStyle.success, row=0)
    async def start_guide(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._get_cmd_map()
        embed = create_styled_embed(
            title="🚀 Guide de Démarrage Rapide",
            description="Voici le parcours idéal pour profiter de toutes les fonctionnalités :"
        )
        embed.add_field(
            name="1️⃣ Lie ton compte",
            value=f"C'est l'étape **essentielle** ! Utilise {self.format_cmd('lier_compte')} avec l'e-mail de tes commandes. Tu recevras un code à valider avec {self.format_cmd('verifier')}. Cela te permettra de noter les produits que tu as achetés.",
            inline=False
        )
        embed.add_field(
            name="2️⃣ Explore le menu",
            value=f"La commande {self.format_cmd('menu')} t'ouvre les portes de notre catalogue interactif. Navigue par catégorie, consulte les fiches produits détaillées et découvre les nouveautés.",
            inline=False
        )
        embed.add_field(
            name="3️⃣ Donne ton avis",
            value=f"Une fois un produit testé, utilise {self.format_cmd('noter')} pour lui donner une note sur plusieurs critères. Chaque note te fait gagner des points pour le système de fidélité !",
            inline=False
        )
        await interaction.response.edit_message(embed=embed, view=HelpNavigateView(self))

    @discord.ui.button(label="🤖 Commandes Principales", style=discord.ButtonStyle.primary, row=0)
    async def main_commands_guide(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._get_cmd_map()
        embed = create_styled_embed("🤖 Commandes Principales", "Les commandes que tu utiliseras le plus souvent.")
        
        embed.add_field(name=self.format_cmd("profil"), value="Affiche ton profil complet : statistiques, badge de fidélité, historique de notes, et infos de commandes.", inline=False)
        embed.add_field(name=self.format_cmd("promos"), value="Consulte toutes les promotions et avantages en cours sur la boutique.", inline=False)
        embed.add_field(name=self.format_cmd("top_noteurs"), value="Découvre le classement des membres les plus actifs et experts de la communauté.", inline=False)
        embed.add_field(name=self.format_cmd("classement_produits"), value="Consulte le top des produits les mieux notés par l'ensemble des membres.", inline=False)
        embed.add_field(name=self.format_cmd("contacts"), value="Retrouve tous nos liens utiles (boutique, réseaux sociaux).", inline=False)
        
        await interaction.response.edit_message(embed=embed, view=HelpNavigateView(self))

    @discord.ui.button(label="🛠️ Outils & Utilitaires", style=discord.ButtonStyle.primary, row=1)
    async def tools_guide(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._get_cmd_map()
        embed = create_styled_embed("🛠️ Outils & Utilitaires", "Des commandes pratiques pour aller plus loin.")
        
        embed.add_field(name=self.format_cmd("comparer"), value="Compare deux produits côte à côte : prix, caractéristiques et notes moyennes de la communauté.", inline=False)
        embed.add_field(name=self.format_cmd("ma_commande"), value="Affiche le statut de ta dernière commande (paiement, expédition, suivi de colis).", inline=False)
        embed.add_field(name=self.format_cmd("delier_compte"), value="Supprime la liaison entre ton Discord et ton e-mail, si tu souhaites en changer.", inline=False)

        await interaction.response.edit_message(embed=embed, view=HelpNavigateView(self))

    @discord.ui.button(label="🏆 Fidélité & Succès", style=discord.ButtonStyle.primary, row=1)
    async def loyalty_guide(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = create_styled_embed("🏆 Le Système de Fidélité & Succès", "Chaque note que tu donnes est récompensée !")
        
        loyalty_config = config_manager.get_config("loyalty_roles", {})
        
        # Séparer les rôles par type
        tiered_roles = sorted([v for v in loyalty_config.values() if v.get('type') == 'threshold'], key=lambda i: i.get('threshold', 0))
        achievement_roles = [v for v in loyalty_config.values() if v.get('type') != 'threshold']

        if tiered_roles:
            embed.add_field(
                name="\nPaliers de Fidélité",
                value="Débloque ces rôles exclusifs en accumulant les notes. Seul ton plus haut palier est affiché.",
                inline=False
            )
            for role_data in tiered_roles:
                embed.add_field(
                    name=f"{role_data.get('emoji', '⭐')} {role_data.get('name', 'N/A')}",
                    value=f"**{role_data.get('threshold', 0)}** notes",
                    inline=True
                )
        
        if achievement_roles:
            embed.add_field(
                name="\nSuccès à Débloquer",
                value="Accomplis des défis spécifiques pour gagner ces badges uniques. Ils sont cumulables !",
                inline=False
            )
            for role_data in achievement_roles:
                type_desc = "Condition inconnue"
                if role_data.get('type') == 'explorer': type_desc = "Noter 1 produit de chaque catégorie principale."
                elif role_data.get('type') == 'specialist': type_desc = "Noter 5 produits dans une même catégorie."
                
                embed.add_field(
                    name=f"{role_data.get('emoji', '🏆')} {role_data.get('name', 'N/A')}",
                    value=type_desc,
                    inline=False
                )
        embed.add_field(name=self.format_cmd("nitro_gift"), value="Si tu boostes le serveur, utilise cette commande pour réclamer ta récompense !", inline=False)

        if not loyalty_config:
            embed.description += "\n\nAucun palier ou succès n'est configuré pour le moment."

        await interaction.response.edit_message(embed=embed, view=HelpNavigateView(self))

class HelpNavigateView(discord.ui.View):
    def __init__(self, main_view: HelpView):
        super().__init__(timeout=None)
        self.main_view = main_view

    @discord.ui.button(label="⬅️ Retour", style=discord.ButtonStyle.secondary)
    async def go_back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=self.main_view.main_embed, view=self.main_view)


class EmailTestModal(discord.ui.Modal, title="Tester l'envoi d'e-mail"):
    email_input = discord.ui.TextInput(
        label="Adresse e-mail de destination",
        placeholder="exemple@domaine.com",
        required=True,
        style=discord.TextStyle.short
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        recipient_email = self.email_input.value

        api_url = f"{APP_URL}/api/test-email"
        payload = {"recipient_email": recipient_email}
        headers = {"Authorization": f"Bearer {FLASK_SECRET_KEY}"}

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, json=payload, headers=headers, timeout=20) as response:
                    data = await response.json()
                    if response.ok:
                        await interaction.followup.send(f"✅ **Succès !** Un e-mail de test a été envoyé à `{recipient_email}`.", ephemeral=True)
                    else:
                        error_details = data.get("details", "Aucun détail.")
                        await interaction.followup.send(f"❌ **Échec :** `{data.get('error')}`\n\n**Détails:**\n```{error_details}```", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ **Erreur Critique :** Impossible de contacter l'API Flask. `{e}`", ephemeral=True)

class ConfirmOverwriteView(discord.ui.View):
    def __init__(self, api_url: str, payload: dict, headers: Optional[dict]):
        super().__init__(timeout=60)
        self.api_url = api_url
        self.payload = payload
        self.headers = headers

    @discord.ui.button(label="Confirmer le remplacement", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True)
        try:
            import aiohttp
            # On ajoute le paramètre "force=true" pour la deuxième requête
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.api_url}?force=true", json=self.payload, headers=self.headers) as response:
                    if response.ok:
                        email = self.payload.get("email")
                        if "force-link" in self.api_url:
                            await interaction.followup.send(f"✅ **Succès !** Le compte a été mis à jour et est maintenant lié à `{email}`.", ephemeral=True)
                        else:
                            await interaction.followup.send(f"✅ **C'est fait !** Un nouvel e-mail de vérification a été envoyé à `{email}` pour confirmer le changement.", ephemeral=True)
                    else:
                        data = await response.json()
                        await interaction.followup.send(f"❌ Une erreur est survenue : {data.get('error', 'Erreur inconnue')}", ephemeral=True)
            self.stop()
        except Exception as e:
            Logger.error(f"Erreur dans ConfirmOverwriteView: {e}")
            await interaction.followup.send("❌ Oups, une erreur critique est survenue.", ephemeral=True)
            self.stop()

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Opération annulée.", view=None)
        self.stop()

class PromoPaginatorView(discord.ui.View):
    def __init__(self, promo_products: List[dict], general_promos: List[str], items_per_page=2): # On affiche 2 produits par page pour plus de clarté
        super().__init__(timeout=180)
        self.promo_products = promo_products
        self.general_promos = general_promos
        self.items_per_page = items_per_page
        self.current_page = 0
        self.total_product_pages = max(0, (len(self.promo_products) - 1) // self.items_per_page)
        self.update_buttons()

    def update_buttons(self):
        for item in self.children[:]:
            if isinstance(item, (self.PrevButton, self.NextButton)):
                self.remove_item(item)

        if self.total_product_pages > 0:
            self.add_item(self.PrevButton(disabled=(self.current_page == 0)))
            self.add_item(self.NextButton(disabled=(self.current_page >= self.total_product_pages)))

    def create_embed(self) -> discord.Embed:
        embed = create_styled_embed(
            title="🎁 Promotions & Avantages en Cours",
            description="Toutes les offres actuellement disponibles sur la boutique.",
            color=discord.Color.from_rgb(230, 80, 150)
        )

        banner_url = config_manager.get_config("contact_info.promo_banner_url")
        if banner_url:
            embed.set_image(url=banner_url)

        # --- Section 1 : Avantages Généraux (liste verticale) ---
        if self.general_promos:
            promo_lines = []
            for promo in self.general_promos:
                p_lower = promo.lower()
                emoji = "✨"
                if "livraison" in p_lower or "offert" in p_lower: emoji = "🚚"
                elif "%" in p_lower or "€" in p_lower: emoji = "💰"
                promo_lines.append(f"{emoji} {promo}")
            
            embed.add_field(
                name="\u200b\nAvantages Généraux",
                value="\n".join(promo_lines),
                inline=False
            )
        
        # --- Section 2 : Produits en Promotion (liste verticale) ---
        if not self.promo_products:
            if not self.general_promos:
                 embed.description = "Il n'y a aucune promotion ou avantage en cours pour le moment."
        else:
            start_index = self.current_page * self.items_per_page
            page_products = self.promo_products[start_index : start_index + self.items_per_page]
            
            product_entries = []
            for product in page_products:
                discount_str = ""
                try:
                    price_str = product.get('price', '0').split(' ')[-2].replace(',', '.')
                    compare_price_str = product.get('original_price', '0').replace(' €', '').replace(',', '.')
                    price = float(price_str)
                    compare_price = float(compare_price_str)
                    if compare_price > price:
                        percentage = round((1 - (price / compare_price)) * 100)
                        discount_str = f" **(-{percentage}%)**"
                except (ValueError, IndexError): pass

                price_text = f"**{product.get('price')}** ~~{product.get('original_price')}~~"
                product_url = product.get('product_url', CATALOG_URL)
                
                entry = (
                    f"**🏷️ {product.get('name', 'Produit Inconnu')}**\n"
                    f"> 💰 {price_text}{discount_str}\n"
                    f"> 🛒 **[Voir le produit sur le site]({product_url})**"
                )
                product_entries.append(entry)
            
            # On joint les entrées avec un séparateur visuel
            separator = "\n\n"
            embed.add_field(
                name="\u200b\nProduits en Promotion",
                value=separator.join(product_entries),
                inline=False
            )
        
        if self.total_product_pages > 0:
            embed.set_footer(text=f"Page {self.current_page + 1}/{self.total_product_pages + 1}", icon_url=embed.footer.icon_url)
            
        return embed
        
    async def update_message(self, interaction: discord.Interaction):
        self.update_buttons()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    class PrevButton(discord.ui.Button):
        def __init__(self, disabled=False): super().__init__(label="⬅️ Précédent", style=discord.ButtonStyle.secondary, disabled=disabled)
        async def callback(self, interaction: discord.Interaction):
            if self.view.current_page > 0: self.view.current_page -= 1
            await self.view.update_message(interaction)

    class NextButton(discord.ui.Button):
        def __init__(self, disabled=False): super().__init__(label="Suivant ➡️", style=discord.ButtonStyle.secondary, disabled=disabled)
        async def callback(self, interaction: discord.Interaction):
            if self.view.current_page < self.view.total_product_pages: self.view.current_page += 1
            await self.view.update_message(interaction)
            
class RatingsPaginatorView(discord.ui.View):
    def __init__(self, target_user, user_ratings, community_ratings_map, items_per_page=1):
        super().__init__(timeout=180)
        self.target_user = target_user
        self.user_ratings = user_ratings
        self.community_ratings_map = community_ratings_map  # On stocke les notes de la communauté
        self.items_per_page = items_per_page
        self.current_page = 0
        self.total_pages = (len(self.user_ratings) - 1) // self.items_per_page
        
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f: self.product_map = {p['name'].strip().lower(): p for p in json.load(f).get('products', [])}
        except: self.product_map = {}
        
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        if self.total_pages > 0:
            self.add_item(self.PrevButton(disabled=self.current_page == 0))
            self.add_item(self.NextButton(disabled=self.current_page >= self.total_pages))
    
    def create_embed(self) -> discord.Embed:
        if not self.user_ratings: return discord.Embed(description="Aucune note à afficher.")
        
        rating = self.user_ratings[self.current_page]
        p_name = rating['product_name']
        p_details = self.product_map.get(p_name.strip().lower(), {})
        
        # Récupérer la note moyenne de la communauté
        community_score = self.community_ratings_map.get(p_name.strip().lower())
        community_score_str = f"**{community_score:.2f} / 10**" if community_score else "N/A"
        
        # Calculer la note personnelle de l'utilisateur
        user_avg = sum(rating.get(s, 0) for s in ['visual_score', 'smell_score', 'touch_score', 'taste_score', 'effects_score']) / 5
        
        embed = discord.Embed(title=f"Avis sur : {p_name}", url=p_details.get('product_url'), color=discord.Color.green())
        if p_details.get('image'): 
            embed.set_thumbnail(url=p_details['image'])
        
        embed.add_field(name="Description du Produit", value=p_details.get('detailed_description', 'N/A')[:1024], inline=True)
        embed.add_field(name="Prix", value=p_details.get('price', 'N/A'), inline=True)        
        embed.add_field(name="Note de la Communauté", value=community_score_str, inline=False)
        embed.add_field(name="Votre Note Globale", value=f"**{user_avg:.2f} / 10**", inline=False)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        notes = (f"👀 Visuel: `{rating.get('visual_score', 'N/A')}`\n👃 Odeur: `{rating.get('smell_score', 'N/A')}`\n"
                 f"🤏 Toucher: `{rating.get('touch_score', 'N/A')}`\n👅 Goût: `{rating.get('taste_score', 'N/A')}`\n"
                 f"🧠 Effets: `{rating.get('effects_score', 'N/A')}`")
        
        embed.add_field(name=f"Vos Notes Détaillées", value=notes, inline=False)
        
        if rating.get('comment'): 
            embed.add_field(name="💬 Votre Commentaire", value=f"```{rating['comment']}```", inline=False)
        
        if self.total_pages >= 0: 
            embed.set_footer(text=f"Avis {self.current_page + 1} sur {len(self.user_ratings)}")
            
        return embed

    async def update_message(self, i: discord.Interaction):
        self.update_buttons()
        await i.response.edit_message(embed=self.create_embed(), view=self)

    class PrevButton(discord.ui.Button):
        def __init__(self, disabled): super().__init__(label="⬅️ Avis Précédent", style=discord.ButtonStyle.secondary, disabled=disabled)
        async def callback(self, i: discord.Interaction):
            if self.view.current_page > 0: self.view.current_page -= 1
            await self.view.update_message(i)

    class NextButton(discord.ui.Button):
        def __init__(self, disabled): super().__init__(label="Avis Suivant ➡️", style=discord.ButtonStyle.secondary, disabled=disabled)
        async def callback(self, i: discord.Interaction):
            if self.view.current_page < self.view.total_pages: self.view.current_page += 1
            await self.view.update_message(i)

class ProfileView(discord.ui.View):
    def __init__(self, target_user, user_stats, user_ratings, shopify_data, can_reset, bot):
        super().__init__(timeout=300)
        self.target_user, self.user_stats, self.user_ratings, self.shopify_data, self.can_reset, self.bot = target_user, user_stats, user_ratings, shopify_data, can_reset, bot
        if not self.user_ratings: self.show_notes_button.disabled = True
        if not self.can_reset: self.remove_item(self.reset_button)

    @discord.ui.button(label="Voir les notes en détail", style=discord.ButtonStyle.secondary, emoji="📝")
    async def show_notes_button(self, i: discord.Interaction, button: discord.ui.Button):
        # On lance le chargement en attendant la requête DB
        await i.response.defer(ephemeral=True, thinking=True)
        
        # Fonction pour récupérer toutes les notes moyennes de la communauté en une seule requête
        def _fetch_community_ratings_sync():
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    LOWER(TRIM(product_name)), 
                    AVG((COALESCE(visual_score, 0) + COALESCE(smell_score, 0) + COALESCE(touch_score, 0) + COALESCE(taste_score, 0) + COALESCE(effects_score, 0)) / 5.0)
                FROM ratings 
                GROUP BY LOWER(TRIM(product_name))
            """)
            # On transforme le résultat en un dictionnaire pour un accès facile
            ratings_map = {name: score for name, score in cursor.fetchall()}
            conn.close()
            return ratings_map

        # On exécute la fonction dans un thread séparé
        community_ratings = await asyncio.to_thread(_fetch_community_ratings_sync)
        
        # On passe le dictionnaire des notes au paginateur
        paginator = RatingsPaginatorView(self.target_user, self.user_ratings, community_ratings)
        await i.followup.send(embed=paginator.create_embed(), view=paginator, ephemeral=True)

    @discord.ui.button(label="Afficher la Carte de Profil", style=discord.ButtonStyle.secondary, emoji="🖼️")
    async def show_card_button(self, i: discord.Interaction, button: discord.ui.Button):
        await i.response.defer(ephemeral=True, thinking=True)
        
        try:
            card_data = {"name": str(self.target_user), "avatar_url": self.target_user.display_avatar.url, **self.user_stats, **self.shopify_data}
            image_buffer = await create_profile_card(card_data)
            await i.followup.send(file=discord.File(fp=image_buffer, filename="profile_card.png"), ephemeral=True)
        except Exception as e:
            Logger.error(f"Erreur lors de la génération de la carte de profil : {e}")
            traceback.print_exc()
            await i.followup.send("❌ Oups ! Une erreur est survenue lors de la création de votre carte de profil.", ephemeral=True)
    
    @discord.ui.button(label="Réinitialiser les notes", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def reset_button(self, i: discord.Interaction, button: discord.ui.Button):
        await i.response.send_message(f"Voulez-vous vraiment supprimer toutes les notes de {self.target_user.mention} ?", view=ConfirmResetNotesView(self.target_user, self.bot), ephemeral=True)

class ConfigMenuView(discord.ui.View):
    def __init__(self, bot, author, original_embed):
        super().__init__(timeout=300)
        self.bot = bot
        self.author = author
        self.original_embed = original_embed # Pour le bouton retour

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Vous n'êtes pas autorisé à utiliser ces boutons.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🔧 Config Principale", style=discord.ButtonStyle.primary)
    async def show_main_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        guild = interaction.guild
        
        # --- Logique de l'ancienne commande /config view ---
        staff_role_id = await config_manager.get_state(guild.id, 'staff_role_id')
        mention_role_id = await config_manager.get_state(guild.id, 'mention_role_id')
        menu_channel_id = await config_manager.get_state(guild.id, 'menu_channel_id')
        selection_channel_id = await config_manager.get_state(guild.id, 'selection_channel_id')
        db_export_channel_id = await config_manager.get_state(guild.id, 'db_export_channel_id')

        def format_setting(item_id, item_type, is_critical=False):
            if not item_id: return f"{'❌' if is_critical else '⚠️'} `Non défini`"
            try:
                item_id_int = int(item_id)
                item = guild.get_role(item_id_int) if item_type == 'role' else guild.get_channel(item_id_int)
                if item: return f"✅ {item.mention}"
                return f"{'❌' if is_critical else '⚠️'} `Introuvable (ID: {item_id})`"
            except (ValueError, TypeError): return f"❌ `ID Invalide ({item_id})`"

        embed = create_styled_embed("🔧 Configuration Principale", f"Paramètres pour **{guild.name}**.")
        embed.add_field(name="📌 Rôles", value=f"**Staff :** {format_setting(staff_role_id, 'role')}\n**Mention :** {format_setting(mention_role_id, 'role')}", inline=False)
        embed.add_field(name="📺 Salons", value=f"**Menu :** {format_setting(menu_channel_id, 'channel', True)}\n**Sélection :** {format_setting(selection_channel_id, 'channel')}\n**Sauvegardes :** {format_setting(db_export_channel_id, 'channel')}", inline=False)
        
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="🏆 Config Fidélité", style=discord.ButtonStyle.primary)
    async def show_loyalty_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        guild = interaction.guild

        # --- Logique de l'ancienne commande /config loyalty view ---
        loyalty_config = config_manager.get_config("loyalty_roles", {})
        embed = create_styled_embed("🏆 Configuration Fidélité & Succès", "Voici les rôles actuellement configurés.", color=discord.Color.gold())
        
        if not loyalty_config:
            embed.description += "\nAucun rôle n'est configuré. Utilisez `/config loyalty set` pour en ajouter un."
        else:
            sorted_roles = sorted(loyalty_config.values(), key=lambda item: item.get('threshold', 9999))
            for data in sorted_roles:
                role_id = data.get('id')
                role = guild.get_role(int(role_id)) if role_id else None
                value_str = f"**Rôle :** {role.mention if role else f'⚠️ Rôle introuvable'}\n"
                if data.get('type') == 'threshold': value_str += f"**Condition :** `{data.get('threshold')} notes`"
                elif data.get('type') == 'explorer': value_str += "**Condition :** `Noter 1 produit de chaque catégorie`"
                elif data.get('type') == 'specialist': value_str += "**Condition :** `Noter 5 produits dans une même catégorie`"
                embed.add_field(name=f"{data.get('emoji', '')} {data.get('name', 'N/A')}", value=value_str, inline=False)
        
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="⬅️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def go_back(self, interaction: discord.Interaction, button: discord.ui.Button):
        # On recrée la vue de debug originale et on remet l'embed d'origine
        view = DebugView(self.bot, self.author)
        await interaction.response.edit_message(embed=self.original_embed, view=view)
class DebugView(discord.ui.View):
    def __init__(self, bot, author):
        super().__init__(timeout=300)
        self.bot = bot
        self.author = author

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Vous n'êtes pas autorisé à utiliser ces boutons.", ephemeral=True)
            return False
        return True

    # --- Ligne 0 : Actions de Publication ---
    @discord.ui.button(label="📢 Forcer Publication Menu", style=discord.ButtonStyle.success, row=0)
    async def force_publish(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            await self.bot.check_for_updates(self.bot, force_publish=True)
            await interaction.followup.send("✅ Tâche de publication du menu lancée.", ephemeral=True)
        except Exception as e: await interaction.followup.send(f"❌ **Échec :**\n```py\n{e}\n```", ephemeral=True)
    
    @discord.ui.button(label="📤 Forcer Sélection Semaine", style=discord.ButtonStyle.primary, row=0)
    async def force_selection(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True, ephemeral=True)
        if not interaction.guild: return await interaction.followup.send("❌ Action impossible en DM.", ephemeral=True)
        try:
            await self.bot.post_weekly_selection(self.bot, interaction.guild.id)
            await interaction.followup.send("✅ Tâche de publication de la sélection lancée.", ephemeral=True)
        except Exception as e: await interaction.followup.send(f"❌ **Échec :**\n```py\n{e}\n```", ephemeral=True)

    # --- Ligne 1 : Actions de Synchronisation ---
    @discord.ui.button(label="🔄 Sync Commandes", style=discord.ButtonStyle.primary, row=1)
    async def sync_commands(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            synced = await self.bot.tree.sync()
            await interaction.followup.send(f"✅ {len(synced)} commandes synchronisées.", ephemeral=True)
        except Exception as e: await interaction.followup.send(f"❌ **Échec :**\n```py\n{e}\n```", ephemeral=True)

    @discord.ui.button(label="👥 Forcer Synchro Rôles", style=discord.ButtonStyle.success, row=1)
    async def force_sync_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            await self.bot.sync_all_loyalty_roles(self.bot)
            await interaction.followup.send("✅ Tâche de synchronisation des rôles lancée.", ephemeral=True)
        except Exception as e: await interaction.followup.send(f"❌ **Échec :**\n```py\n{e}\n```", ephemeral=True)

    # --- Ligne 2 : Outils de Diagnostic et Configuration ---
    @discord.ui.button(label="📊 Dashboard", style=discord.ButtonStyle.secondary, row=2)
    async def show_dashboard(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True, ephemeral=True)
        if not interaction.guild: return await interaction.followup.send("❌ Action impossible en DM.", ephemeral=True)
        try:
            slash_commands_cog = self.bot.get_cog("SlashCommands")
            dashboard_embed = await slash_commands_cog.generate_dashboard_embed(interaction.guild)
            await interaction.followup.send(embed=dashboard_embed, ephemeral=True)
        except Exception as e: await interaction.followup.send(f"❌ **Échec :**\n```py\n{e}\n```", ephemeral=True)

    @discord.ui.button(label="🔧 Afficher la Configuration", style=discord.ButtonStyle.secondary, row=2)
    async def show_config_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = create_styled_embed("🔧 Menu de Configuration", "Choisissez une catégorie à afficher.")
        view = ConfigMenuView(self.bot, self.author, interaction.message.embeds[0])
        await interaction.response.edit_message(embed=embed, view=view)
    
    @discord.ui.button(label="Reset Rôles Fidélité", style=discord.ButtonStyle.danger, row=2, emoji="🗑️")
    async def reset_loyalty_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ConfirmResetLoyaltyView()
        await interaction.response.send_message(
            "⚠️ **Êtes-vous absolument certain ?**\n"
            "Cette action va supprimer **toute** la configuration des rôles de fidélité et de succès. "
            "Vous devrez les recréer un par un avec la commande `/config loyalty set`.\n\n"
            "Cette action est **irréversible**.",
            view=view,
            ephemeral=True
        )
        
    # --- Ligne 3 : Actions de Maintenance ---
    @discord.ui.button(label="🗑️ Vider Cache", style=discord.ButtonStyle.secondary, row=3)
    async def clear_cache(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.bot.product_cache = {}
        await interaction.response.send_message("✅ Cache de produits en mémoire vidé.", ephemeral=True)
    
    @discord.ui.button(label="📁 Exporter DB", style=discord.ButtonStyle.secondary, row=3)
    async def export_db(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if not os.path.exists(DB_FILE): return await interaction.followup.send("Fichier DB introuvable.", ephemeral=True)
        file = discord.File(DB_FILE, filename=f"backup_manual_{int(time.time())}.db")
        await interaction.followup.send("Voici la base de données :", file=file, ephemeral=True)
        
    @discord.ui.button(label="📨 Tester E-mail", style=discord.ButtonStyle.danger, row=3)
    async def test_email(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmailTestModal())

class MenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _load_and_categorize_products(self, interaction: discord.Interaction) -> dict:
        try:
            # Cette ligne fonctionnera maintenant
            site_data = interaction.client.product_cache
            if not site_data or 'products' not in site_data:
                raise ValueError("Les données des produits sont actuellement indisponibles.")
            return categorize_products(site_data['products'])
        except (FileNotFoundError, json.JSONDecodeError):
            raise ValueError("Le menu est en cours de construction, veuillez réessayer.")
        except Exception as e:
            Logger.error(f"Erreur en chargeant les produits pour MenuView: {e}")
            raise ValueError("Une erreur est survenue lors de la récupération du menu.")

    async def _handle_button_click(self, interaction: discord.Interaction, category_key: str, category_name: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            categorized_products = await self._load_and_categorize_products(interaction)
            products_for_category = categorized_products.get(category_key, [])
            if not products_for_category:
                await interaction.followup.send(f"Désolé, aucun produit de type '{category_name}' n'est disponible.", ephemeral=True)
                return
            view = ProductView(products_for_category, category=category_key)
            embed = view.create_embed()
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except ValueError as e:
            await interaction.followup.send(str(e), ephemeral=True)
        except Exception as e:
            Logger.error(f"Erreur imprévue dans le clic du menu ({category_key}): {e}")
            traceback.print_exc()
            await interaction.followup.send("❌ Une erreur interne est survenue. Le staff a été notifié.", ephemeral=True)

    @discord.ui.button(label="Nos Fleurs 🍃", style=discord.ButtonStyle.success, custom_id="persistent_menu:fleurs")
    async def weed_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_button_click(interaction, "weed", "Fleurs")

    @discord.ui.button(label="Nos Résines 🍫", style=discord.ButtonStyle.primary, custom_id="persistent_menu:resines")
    async def hash_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_button_click(interaction, "hash", "Résines")

    @discord.ui.button(label="Nos Box 📦", style=discord.ButtonStyle.success, custom_id="persistent_menu:box")
    async def box_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_button_click(interaction, "box", "Box")

    @discord.ui.button(label="Accessoires 🛠️", style=discord.ButtonStyle.secondary, custom_id="persistent_menu:accessoires")
    async def accessoire_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_button_click(interaction, "accessoire", "Accessoires")

class ProductReviewsPaginatorView(discord.ui.View):
    def __init__(self, reviews: list, product_name: str, product_image_url: Optional[str]):
        super().__init__(timeout=180)
        self.reviews = reviews
        self.product_name = product_name
        self.product_image_url = product_image_url
        self.current_page = 0
        self.total_pages = len(self.reviews)
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        if self.total_pages > 1:
            self.add_item(self.PrevButton(disabled=(self.current_page == 0)))
            self.add_item(self.NextButton(disabled=(self.current_page >= self.total_pages - 1)))

    def create_embed(self) -> discord.Embed:
        if not self.reviews:
            return create_styled_embed("Avis Clients", "Il n'y a encore aucun avis pour ce produit.")

        review = self.reviews[self.current_page]
        user_name = review.get('user_name', 'Utilisateur Anonyme').split('#')[0]
        rating_date = datetime.fromisoformat(review['rating_timestamp']).strftime('%d/%m/%Y')
        
        scores = [review.get(s, 0) for s in ['visual_score', 'smell_score', 'touch_score', 'taste_score', 'effects_score']]
        avg_score = sum(scores) / len(scores) if scores else 0

        embed = create_styled_embed(
            title=f"Avis sur : {self.product_name}",
            description=f"✍️ **Par :** {user_name}\n📅 **Le :** {rating_date}\n⭐ **Note globale :** {avg_score:.1f}/10",
            color=discord.Color.blue()
        )
        if self.product_image_url:
            embed.set_thumbnail(url=self.product_image_url)

        notes_detaillees = (
            f"👀 Visuel: `{review.get('visual_score', 'N/A')}`\n👃 Odeur: `{review.get('smell_score', 'N/A')}`\n"
            f"🤏 Toucher: `{review.get('touch_score', 'N/A')}`\n👅 Goût: `{review.get('taste_score', 'N/A')}`\n"
            f"🧠 Effets: `{review.get('effects_score', 'N/A')}`"
        )
        embed.add_field(name="Notes Détaillées", value=notes_detaillees, inline=False)

        if review.get('comment'):
            embed.add_field(name="💬 Commentaire", value=f"```{review['comment']}```", inline=False)

        embed.set_footer(text=f"Avis {self.current_page + 1} sur {self.total_pages}")
        return embed

    async def update_message(self, interaction: discord.Interaction):
        self.update_buttons()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    class PrevButton(discord.ui.Button):
        def __init__(self, disabled=False): super().__init__(label="⬅️ Précédent", style=discord.ButtonStyle.secondary, disabled=disabled)
        async def callback(self, interaction: discord.Interaction):
            if self.view.current_page > 0: self.view.current_page -= 1
            await self.view.update_message(interaction)

    class NextButton(discord.ui.Button):
        def __init__(self, disabled=False): super().__init__(label="Suivant ➡️", style=discord.ButtonStyle.secondary, disabled=disabled)
        async def callback(self, interaction: discord.Interaction):
            if self.view.current_page < self.view.total_pages - 1: self.view.current_page += 1
            await self.view.update_message(interaction)


# Dans commands.py, remplacez l'ancienne classe ProductView par celle-ci

class ProductView(discord.ui.View):
    def __init__(self, products: List[dict], category: str = None):
        super().__init__(timeout=300)
        self.products = products
        self.current_index = 0
        self.category = category
        
        # [AMÉLIORATION] On pré-charge le nombre d'avis pour tous les produits de la vue en une seule fois
        self.review_counts = self._get_review_counts()
        
        # On ajoute les boutons fixes
        self.add_item(self.PrevButton())
        self.add_item(self.NextButton())
        self.add_item(self.ShowReviewsButton())
        self.add_item(self.ShowGraphButton())
        
        # On met à jour l'état de tous les boutons
        self.update_ui_elements()

    def _get_review_counts(self) -> dict:
        """[CORRIGÉ] Récupère le nombre total de notes ET le nombre de commentaires en une seule requête."""
        product_names = [p['name'] for p in self.products]
        if not product_names: return {}
        
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholders = ','.join('?' for _ in product_names)
        
        # Cette requête récupère les deux comptes nécessaires
        query = f"""
            SELECT 
                product_name, 
                COUNT(id) as total_ratings,
                COUNT(CASE WHEN comment IS NOT NULL AND TRIM(comment) != '' THEN 1 END) as comment_count
            FROM ratings 
            WHERE product_name IN ({placeholders})
            GROUP BY product_name
        """
        cursor.execute(query, product_names)
        
        # On stocke les deux comptes dans un dictionnaire
        counts = {name: {"total": total, "comments": comments} for name, total, comments in cursor.fetchall()}
        conn.close()
        return counts
    
    def update_ui_elements(self):
        """Met à jour l'état de tous les boutons en fonction du produit actuel."""
        if not self.products: return
        product = self.products[self.current_index]
        product_name = product.get('name', '')

        # Navigation
        prev_button = discord.utils.get(self.children, custom_id="prev_product")
        next_button = discord.utils.get(self.children, custom_id="next_product")
        if prev_button: prev_button.disabled = self.current_index == 0
        if next_button: next_button.disabled = self.current_index >= len(self.products) - 1

        # Téléchargements (Analyse PDF, etc.)
        for item in [c for c in self.children if hasattr(c, "is_download_button")]: self.remove_item(item)
        stats = product.get('stats', {})
        for key, value in stats.items():
            if isinstance(value, str) and ("lab" in key.lower() or "terpen" in key.lower()) and value.startswith("http"):
                label = "Télécharger Lab Test" if "lab" in key.lower() else "Télécharger Terpènes"
                emoji = "🧪" if "lab" in key.lower() else "🌿"
                self.add_item(self.DownloadButton(label, value, emoji))

        # [CORRIGÉ] On récupère le dictionnaire des comptes pour le produit actuel
        counts_for_product = self.review_counts.get(product_name, {"total": 0, "comments": 0})

        # Bouton Avis
        reviews_button = discord.utils.get(self.children, custom_id="show_reviews_button")
        if reviews_button:
            comment_count = counts_for_product.get('comments', 0)
            reviews_button.label = f"💬 Avis Clients ({comment_count})"
            reviews_button.disabled = (comment_count == 0)

        # Bouton Graphique
        graph_button = discord.utils.get(self.children, custom_id="show_graph_button")
        if graph_button:
            total_rating_count = counts_for_product.get('total', 0)
            graph_button.disabled = (total_rating_count == 0)

    def get_category_emoji(self):
        if self.category == "weed": return "🍃"
        if self.category == "hash": return "🍫"
        if self.category == "box": return "📦"
        if self.category == "accessoire": return "🛠️"
        return ""

    def create_embed(self) -> discord.Embed:
        product = self.products[self.current_index]
        emoji = self.get_category_emoji()
        embed_color = discord.Color.dark_red() if product.get('is_sold_out') else discord.Color.from_rgb(255, 204, 0)
        title = f"{emoji} **{product.get('name', 'Produit inconnu')}**"
        embed = discord.Embed(title=title, url=product.get('product_url', CATALOG_URL), color=embed_color)
        if product.get('image'):
            embed.set_thumbnail(url=product['image'])
        
        description = product.get('detailed_description', "Aucune description.")
        if description:
            embed.add_field(name="Description", value=description[:1024], inline=False)
        
        price_text = ""
        if product.get('is_sold_out'): price_text = "❌ **ÉPUISÉ**"
        elif product.get('is_promo'): price_text = f"🏷️ **{product.get('price')}** ~~{product.get('original_price')}~~"
        else: price_text = f"💰 **{product.get('price', 'N/A')}**"
        embed.add_field(name="Prix", value=price_text, inline=False)
        
        if product.get('category') == 'box' and product.get('box_contents'):
            content_str = ""
            for section, items in product['box_contents'].items():
                if items:
                    if section != "Général": content_str += f"**{section}**\n"
                    content_str += "\n".join([f"• {item}" for item in items]) + "\n\n"
            embed.add_field(name="📦 Contenu de la Box", value=content_str.strip(), inline=False)
        else:
            stats = product.get('stats', {})
            char_lines = []
            if 'Effet' in stats: char_lines.append(f"🧠 **Effet :** `{stats['Effet']}`")
            if 'Goût' in stats: char_lines.append(f"👅 **Goût :** `{stats['Goût']}`")
            if 'Cbd' in stats: char_lines.append(f"🌿 **CBD :** `{stats['Cbd']}`")
            if char_lines:
                embed.add_field(name="Caractéristiques", value="\n".join(char_lines), inline=False)

        embed.add_field(name="\u200b", value=f"**🌐 [Voir la fiche produit sur le site]({product.get('product_url', CATALOG_URL)})**", inline=False)
        embed.set_footer(text=f"Produit {self.current_index + 1} sur {len(self.products)}")
        return embed
        
    async def update_message(self, interaction: discord.Interaction):
        self.update_ui_elements()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    # --- Les boutons ---
    # (Les classes de boutons PrevButton, NextButton, ShowReviewsButton, ShowGraphButton et DownloadButton ne changent pas et restent les mêmes que dans votre fichier)
    class PrevButton(discord.ui.Button):
        def __init__(self): super().__init__(label="⬅️ Précédent", style=discord.ButtonStyle.secondary, row=0, custom_id="prev_product")
        async def callback(self, interaction: discord.Interaction):
            if self.view.current_index > 0: self.view.current_index -= 1
            await self.view.update_message(interaction)

    class NextButton(discord.ui.Button):
        def __init__(self): super().__init__(label="Suivant ➡️", style=discord.ButtonStyle.secondary, row=0, custom_id="next_product")
        async def callback(self, interaction: discord.Interaction):
            if self.view.current_index < len(self.view.products) - 1: self.view.current_index += 1
            await self.view.update_message(interaction)

    class ShowReviewsButton(discord.ui.Button):
        def __init__(self): super().__init__(label="💬 Avis Clients", style=discord.ButtonStyle.primary, row=1, custom_id="show_reviews_button")
        async def callback(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True, thinking=True)
            product = self.view.products[self.view.current_index]
            product_name, product_image = product.get('name'), product.get('image')
            def _fetch_reviews_sync(p_name):
                conn = get_db_connection()
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM ratings WHERE product_name = ? AND comment IS NOT NULL AND TRIM(comment) != '' ORDER BY rating_timestamp DESC", (p_name,))
                results = [dict(row) for row in cursor.fetchall()]
                conn.close()
                return results
            reviews = await asyncio.to_thread(_fetch_reviews_sync, product_name)
            if not reviews:
                await interaction.followup.send("Il n'y a pas encore d'avis avec des commentaires pour ce produit.", ephemeral=True)
                return
            paginator = ProductReviewsPaginatorView(reviews, product_name, product_image)
            await interaction.followup.send(embed=paginator.create_embed(), view=paginator, ephemeral=True)

    class ShowGraphButton(discord.ui.Button):
        def __init__(self):
            super().__init__(label="📊 Afficher le Graphique", style=discord.ButtonStyle.primary, row=1, custom_id="show_graph_button")
            
        async def callback(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True, thinking=True)
            
            product = self.view.products[self.view.current_index]
            product_name = product.get('name')
            chart_path = None

            try:
                chart_path = await asyncio.to_thread(create_radar_chart, product_name)
                if chart_path:
                    file = discord.File(chart_path, filename="radar_chart.png")
                    embed = discord.Embed(
                        title=f"Graphique Radar pour {product_name}",
                        description="Moyenne des notes de la communauté.",
                        color=discord.Color.green()
                    ).set_image(url="attachment://radar_chart.png")
                    await interaction.followup.send(embed=embed, file=file, ephemeral=True)
                else:
                    await interaction.followup.send("Impossible de générer le graphique (pas assez de données ?).", ephemeral=True)
            except Exception as e:
                Logger.error(f"Échec de la génération du graphique pour '{product_name}': {e}")
                traceback.print_exc()
                await interaction.followup.send("❌ Oups ! Une erreur est survenue lors de la création du graphique.", ephemeral=True)
            finally:
                if chart_path and os.path.exists(chart_path):
                    os.remove(chart_path)

    class DownloadButton(discord.ui.Button):
        def __init__(self, label, url, emoji=None):
            super().__init__(label=label, style=discord.ButtonStyle.link, url=url, emoji=emoji)
            self.is_download_button = True

class CommentModal(discord.ui.Modal, title="Ajouter un commentaire"):
    def __init__(self, product_name: str, user: discord.User):
        super().__init__(timeout=None)
        self.product_name = product_name
        self.user = user
        self.comment_input = discord.ui.TextInput(
            label="Votre commentaire",
            style=discord.TextStyle.paragraph,
            placeholder="Le goût était incroyable, les effets très relaxants...",
            required=True,
            max_length=500
        )
        self.add_item(self.comment_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        comment_text = self.comment_input.value

        api_url = f"{APP_URL}/api/add-comment"
        payload = {
            "user_id": self.user.id,
            "product_name": self.product_name,
            "comment": comment_text
        }
        
        try:
            # On utilise aiohttp car c'est plus robuste
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, json=payload, timeout=10) as response:
                    if response.ok:
                        await interaction.followup.send("✅ Votre commentaire a bien été ajouté. Merci !", ephemeral=True)
                    else:
                        await interaction.followup.send("❌ Une erreur est survenue lors de l'ajout de votre commentaire.", ephemeral=True)
        except Exception as e:
            Logger.error(f"Erreur API lors de l'ajout du commentaire : {e}")
            await interaction.followup.send("❌ Une erreur critique est survenue. Le staff a été notifié.", ephemeral=True)

class AddCommentView(discord.ui.View):
    def __init__(self, product_name: str, user: discord.User):
        super().__init__(timeout=180) # Le bouton expire après 3 minutes
        self.product_name = product_name
        self.user = user

    @discord.ui.button(label="Ajouter un Commentaire", style=discord.ButtonStyle.success, emoji="💬")
    async def add_comment_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Ouvre le modal de commentaire
        await interaction.response.send_modal(CommentModal(self.product_name, self.user))
        # On désactive le bouton pour qu'il ne soit pas cliquable à nouveau
        button.disabled = True
        await interaction.message.edit(view=self)

class NotationProductSelectView(discord.ui.View):
    def __init__(self, products: list, user: discord.User, cog_instance):
        super().__init__(timeout=180)
        self.products = products
        self.cog_instance = cog_instance
        if products:
            self.add_item(self.ProductSelect(products, user, self.cog_instance))

    class ProductSelect(discord.ui.Select):
        def __init__(self, products: list, user: discord.User, cog_instance):
            self.user = user
            self.cog_instance = cog_instance
            options = [discord.SelectOption(label=p[:100], value=p[:100]) for p in products[:25]]
            if not options:
                options = [discord.SelectOption(label="Aucun produit à noter", value="disabled", default=True)]
            super().__init__(placeholder="Choisissez un produit à noter...", options=options)
        
        async def callback(self, interaction: discord.Interaction):
            try:
                if not self.values or self.values[0] == "disabled":
                    await interaction.response.edit_message(content="Aucun produit sélectionné.", view=None)
                    return
                
                selected_value = self.values[0]
                full_product_name = next((p for p in self.view.products if p.startswith(selected_value)), selected_value)
                
                # Pas besoin de defer ici, la recherche DB est rapide
                # await interaction.response.defer(thinking=True, ephemeral=True)

                def _fetch_existing_rating_sync(user_id, product_name):
                    conn = get_db_connection()
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    cursor.execute("SELECT * FROM ratings WHERE user_id = ? AND product_name = ?", (user_id, product_name))
                    row = cursor.fetchone()
                    conn.close()
                    return dict(row) if row else None

                existing_rating = await asyncio.to_thread(
                    _fetch_existing_rating_sync, interaction.user.id, full_product_name
                )
                
                if existing_rating:
                    # Affiche la vue de confirmation
                    Logger.info(f"Note existante trouvée pour '{full_product_name}'. Demande de confirmation.")
                    scores = [existing_rating.get(s, 0) for s in ['visual_score', 'smell_score', 'touch_score', 'taste_score', 'effects_score']]
                    avg_score = sum(scores) / len(scores) if scores else 0
                    
                    view = ConfirmRatingOverwriteView(full_product_name, self.user, self.cog_instance, existing_rating, avg_score)
                    # On répond directement à l'interaction du select
                    await interaction.response.send_message(
                        f"⚠️ Vous avez déjà noté **{full_product_name}** avec une moyenne de **{avg_score:.2f}/10**.\n\n"
                        "Voulez-vous modifier votre note ?",
                        view=view,
                        ephemeral=True
                    )
                else:
                    # Aucune note, on ouvre le modal directement
                    Logger.info(f"Aucune note existante pour '{full_product_name}'. Affichage du modal de notation.")
                    modal = RatingModal(full_product_name, self.user, self.cog_instance)
                    await interaction.response.send_modal(modal)

            except Exception as e:
                Logger.error(f"Échec de l'affichage du modal de notation : {e}"); traceback.print_exc()
                message_erreur = "❌ Oups, une erreur est survenue."
                if not interaction.response.is_done():
                     await interaction.response.send_message(message_erreur, ephemeral=True)
                else:
                    try:
                        await interaction.followup.send(message_erreur, ephemeral=True)
                    except:
                        pass

class RatingModal(discord.ui.Modal):
    def __init__(self, product_name: str, user: discord.User, cog_instance, existing_rating: Optional[dict] = None):
        super().__init__(title="Modifier votre note" if existing_rating else "Noter un produit", timeout=None)
        
        self.product_name, self.user = product_name, user
        self.cog_instance = cog_instance
        def get_score(key: str) -> str:
            return str(existing_rating.get(key, '')) if existing_rating else ''

        self.visual_score = discord.ui.TextInput(label="👀 Note Visuel /10", placeholder="Ex: 8.5", required=True, default=get_score('visual_score'))
        self.smell_score = discord.ui.TextInput(label="👃🏼 Note Odeur /10", placeholder="Ex: 9", required=True, default=get_score('smell_score'))
        self.touch_score = discord.ui.TextInput(label="🤏🏼 Note Toucher /10", placeholder="Ex: 7", required=True, default=get_score('touch_score'))
        self.taste_score = discord.ui.TextInput(label="👅 Note Goût /10", placeholder="Ex: 8", required=True, default=get_score('taste_score'))
        self.effects_score = discord.ui.TextInput(label="🧠 Note Effets /10", placeholder="Ex: 9.5", required=True, default=get_score('effects_score'))
        
        for item in [self.visual_score, self.smell_score, self.touch_score, self.taste_score, self.effects_score]:
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        scores = {}
        try:
            scores['visual'] = float(self.visual_score.value.replace(',', '.'))
            scores['smell'] = float(self.smell_score.value.replace(',', '.'))
            scores['touch'] = float(self.touch_score.value.replace(',', '.'))
            scores['taste'] = float(self.taste_score.value.replace(',', '.'))
            scores['effects'] = float(self.effects_score.value.replace(',', '.'))
            for key, value in scores.items():
                if not (0 <= value <= 10):
                    await interaction.followup.send(f"❌ La note '{key.capitalize()}' doit être entre 0 et 10.", ephemeral=True); return
        except ValueError:
            await interaction.followup.send("❌ Veuillez n'entrer que des nombres pour les notes.", ephemeral=True); return
        
        api_url = f"{APP_URL}/api/submit-rating"
        payload = {"user_id": self.user.id, "user_name": str(self.user), "product_name": self.product_name, "scores": scores, "comment": None}
        
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, json=payload, timeout=10) as response:
                    response.raise_for_status()
            avg_score = sum(scores.values()) / len(scores)
            await self.cog_instance._update_all_user_roles(interaction.guild, interaction.user)
            view = AddCommentView(self.product_name, self.user)
            await interaction.followup.send(
                f"✅ Merci ! Votre note de **{avg_score:.2f}/10** pour **{self.product_name}** a été enregistrée.",
                view=view, ephemeral=True
            )
        except Exception as e:
            Logger.error(f"Erreur API lors de la soumission de la note : {e}"); traceback.print_exc()
            await interaction.followup.send("❌ Une erreur est survenue lors de l'enregistrement de votre note.", ephemeral=True)

async def callback(self, interaction: discord.Interaction):
            try:
                if not self.values or self.values[0] == "disabled":
                    await interaction.response.edit_message(content="Aucun produit sélectionné.", view=None)
                    return
                
                selected_value = self.values[0]
                full_product_name = next((p for p in self.view.products if p.startswith(selected_value)), selected_value)
                
                # On informe l'utilisateur que la recherche est en cours
                await interaction.response.defer(thinking=True, ephemeral=True)

                def _fetch_existing_rating_sync(user_id, product_name):
                    conn = get_db_connection()
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    cursor.execute("SELECT * FROM ratings WHERE user_id = ? AND product_name = ?", (user_id, product_name))
                    row = cursor.fetchone()
                    conn.close()
                    return dict(row) if row else None

                existing_rating = await asyncio.to_thread(
                    _fetch_existing_rating_sync, interaction.user.id, full_product_name
                )
                
                if existing_rating:
                    # Une note existe, on affiche la confirmation
                    Logger.info(f"Note existante trouvée pour '{full_product_name}'. Demande de confirmation.")
                    
                    # Calculer la moyenne existante pour l'afficher
                    scores = [existing_rating.get(s, 0) for s in ['visual_score', 'smell_score', 'touch_score', 'taste_score', 'effects_score']]
                    avg_score = sum(scores) / len(scores) if scores else 0
                    
                    view = ConfirmRatingOverwriteView(full_product_name, self.user, self.cog_instance, existing_rating, avg_score)
                    await interaction.followup.send(
                        f"⚠️ Vous avez déjà noté **{full_product_name}** avec une moyenne de **{avg_score:.2f}/10**.\n\n"
                        "Voulez-vous modifier votre note ?",
                        view=view,
                        ephemeral=True
                    )
                else:
                    # Aucune note, on ouvre le modal directement
                    Logger.info(f"Aucune note existante pour '{full_product_name}'. Affichage du modal de notation.")
                    modal = RatingModal(full_product_name, self.user, self.cog_instance)
                    await interaction.followup.send("Veuillez remplir le formulaire ci-dessous.", ephemeral=True, view=None) # Message placeholder
                    await interaction.response.send_modal(modal) # Utiliser l'interaction originale
                    # Supprimer le message placeholder après un court délai
                    await asyncio.sleep(0.1)
                    await interaction.delete_original_response()


            except Exception as e:
                Logger.error(f"Échec de l'affichage du modal de notation : {e}"); traceback.print_exc()
                # Assurons-nous d'avoir un message de retour même si ça plante
                if not interaction.response.is_done():
                     await interaction.response.send_message("❌ Oups, une erreur est survenue.", ephemeral=True)
                else:
                    try:
                        await interaction.followup.send("❌ Oups, une erreur est survenue.", ephemeral=True)
                    except:
                        pass # Si même le followup échoue, on ne peut plus rien faire

class TopRatersPaginatorView(discord.ui.View):
    def __init__(self, top_raters, guild, items_per_page=5):
        super().__init__(timeout=180)
        self.top_raters = top_raters
        self.guild = guild
        self.items_per_page = items_per_page
        self.current_page = 0
        self.total_pages = max(0, (len(self.top_raters) - 1) // self.items_per_page)
        self.update_buttons()
        
    def update_buttons(self):
        self.clear_items()
        if self.total_pages > 0:
            self.add_item(self.PrevButton(disabled=(self.current_page == 0)))
            self.add_item(self.NextButton(disabled=(self.current_page >= self.total_pages)))
            
    def create_embed_for_page(self):
        start_index = self.current_page * self.items_per_page
        end_index = start_index + self.items_per_page
        page_raters = self.top_raters[start_index:end_index]
        
        embed = create_styled_embed(
            title="🏆 Top des Noteurs",
            description="Classement basé sur le nombre de notes uniques.",
            color=discord.Color.gold()
        )
        
        if self.current_page == 0 and page_raters:
            first_rater_id = page_raters[0].get('user_id')
            member = self.guild.get_member(first_rater_id)
            if member:
                embed.set_thumbnail(url=member.display_avatar.url)

        medals = ["🥇", "🥈", "🥉"]
        
        # On récupère la configuration de fidélité une seule fois
        loyalty_config = config_manager.get_config("loyalty_roles", {})
        sorted_roles = sorted(loyalty_config.values(), key=lambda r: r.get('threshold', 0), reverse=True) if loyalty_config else []

        for i, rater_data in enumerate(page_raters):
            rank = start_index + i + 1
            user_id = rater_data.get('user_id')
            last_user_name = rater_data.get('last_user_name')
            rating_count = rater_data.get('rating_count')
            global_average = rater_data.get('global_avg', 0)
            best_product = rater_data.get('best_rated_product', 'N/A')
            
            member = self.guild.get_member(user_id)
            display_name = member.display_name if member else last_user_name
            mention_text = member.mention if member else f"`{last_user_name} (parti)`"
            
            medal_emoji = medals[rank - 1] if rank <= len(medals) else "🔹"
            field_name = f"{medal_emoji} #{rank} - {display_name}"
            
            # --- NOUVELLE LOGIQUE POUR LE BADGE ---
            loyalty_badge_text = ""
            if sorted_roles:
                for role_data in sorted_roles:
                    if rating_count >= role_data.get('threshold', 0):
                        loyalty_badge_text = f"\n> {role_data.get('emoji', '⭐')} **Badge :** `{role_data.get('name', 'Fidèle')}`"
                        break
            
            field_value = (
                f"{mention_text}\n"
                f"> 📝 **Notes :** `{rating_count}`\n"
                f"> 📊 **Moyenne :** `{global_average:.2f}/10`\n"
                f"> ⭐ **Produit Préféré :** *{best_product}*"
            )
            
            embed.add_field(name=field_name, value=field_value, inline=False)
            
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.total_pages + 1}")
        return embed

    async def update_message(self, interaction: discord.Interaction):
        self.update_buttons()
        await interaction.response.edit_message(embed=self.create_embed_for_page(), view=self)

    class PrevButton(discord.ui.Button):
        def __init__(self, disabled=False): super().__init__(label="⬅️", style=discord.ButtonStyle.secondary, disabled=disabled)
        async def callback(self, interaction: discord.Interaction):
            if self.view.current_page > 0: self.view.current_page -= 1
            await self.view.update_message(interaction)

    class NextButton(discord.ui.Button):
        def __init__(self, disabled=False): super().__init__(label="➡️", style=discord.ButtonStyle.secondary, disabled=disabled)
        async def callback(self, interaction: discord.Interaction):
            if self.view.current_page < self.view.total_pages: self.view.current_page += 1
            await self.view.update_message(interaction)
            
class RankingPaginatorView(discord.ui.View):
    def __init__(self, all_products_ratings, product_map, items_per_page=5):
        super().__init__(timeout=180)
        self.all_products_ratings = all_products_ratings
        self.product_map = product_map
        self.items_per_page = items_per_page
        self.current_page = 0
        self.total_pages = (len(self.all_products_ratings) - 1) // self.items_per_page
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        if self.total_pages > 0:
            self.add_item(self.PrevButton())
            self.add_item(self.NextButton())
            self.children[0].disabled = self.current_page == 0
            self.children[1].disabled = self.current_page >= self.total_pages

    def create_embed_for_page(self):
        start_index = self.current_page * self.items_per_page
        end_index = start_index + self.items_per_page
        page_ratings = self.all_products_ratings[start_index:end_index]
        
        embed = discord.Embed(
            title="📈 Classement Général des Produits", 
            description="Moyenne de tous les produits notés par la communauté.", 
            color=discord.Color.purple() # Une couleur plus "brandée"
        )
        if self.current_page == 0 and page_ratings:
            top_product_name = page_ratings[0][0]
            top_product_info = self.product_map.get(top_product_name.strip().lower())
            if top_product_info and top_product_info.get('image'):
                embed.set_thumbnail(url=top_product_info['image'])

        medals = ["🥇", "🥈", "🥉"]
        for i, (name, avg_score, count) in enumerate(page_ratings):
            rank = start_index + i + 1
            rank_prefix = f"{medals[rank-1]} " if rank <= 3 else "🔹 "
            field_name = f"{rank_prefix} #{rank} - {name}"
            value_str = f"> 📊 **Note moyenne :** `{avg_score:.2f}/10`\n> 👥 sur la base de **{count} avis**"
            product_info = self.product_map.get(name.strip().lower())
            if product_info and not product_info.get('is_sold_out'):
                product_url = product_info.get('product_url')
                if product_url:
                    value_str += f"\n> 🛒 **[Acheter ce produit]({product_url})**"
            
            embed.add_field(name=field_name, value=value_str, inline=False)
            
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.total_pages + 1}")
        return embed
        
    async def update_message(self, interaction: discord.Interaction):
        self.update_buttons()
        embed = self.create_embed_for_page()
        await interaction.response.edit_message(embed=embed, view=self)

    class PrevButton(discord.ui.Button):
        def __init__(self):
            super().__init__(label="⬅️", style=discord.ButtonStyle.secondary)
        async def callback(self, interaction: discord.Interaction):
            if self.view.current_page > 0: self.view.current_page -= 1
            await self.view.update_message(interaction)

    class NextButton(discord.ui.Button):
        def __init__(self):
            super().__init__(label="➡️", style=discord.ButtonStyle.secondary)
        async def callback(self, interaction: discord.Interaction):
            if self.view.current_page < self.view.total_pages: self.view.current_page += 1
            await self.view.update_message(interaction)

class ProfilePaginatorView(discord.ui.View):
    def __init__(self, target_user, user_stats, user_ratings, shopify_data, can_reset, bot, initial_image_file, items_per_page=3):
        super().__init__(timeout=300)
        self.target_user = target_user
        self.user_stats = user_stats
        self.user_ratings = user_ratings
        self.shopify_data = shopify_data
        self.can_reset = can_reset
        self.bot = bot
        self.items_per_page = items_per_page
        self.total_pages = (len(self.user_ratings) - 1) // self.items_per_page
        self.initial_image_file = initial_image_file
        self.current_page = 0 
        
        self.add_item(self.ShowProfileButton())
        if self.user_ratings:
            self.add_item(self.PrevButton())
            self.add_item(self.NextButton())
        if self.can_reset:
            self.add_item(self.ResetButton())
        
        self.update_buttons_state()

    def update_buttons_state(self):
        for item in self.children:
            if isinstance(item, self.PrevButton): item.disabled = self.current_page == 0
            elif isinstance(item, self.NextButton): item.disabled = self.current_page >= self.total_pages

    def create_ratings_embed(self) -> discord.Embed:
        embed = discord.Embed(title=f"Notes de {self.target_user.display_name}", color=discord.Color.green())
        embed.set_thumbnail(url=self.target_user.display_avatar.url)
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        
        for r in self.user_ratings[start:end]:
            avg = (r.get('visual_score', 0) + r.get('smell_score', 0) + r.get('touch_score', 0) + r.get('taste_score', 0) + r.get('effects_score', 0)) / 5
            date = datetime.fromisoformat(r['rating_timestamp']).strftime('%d/%m/%Y')
            embed.add_field(name=f"**{r['product_name']}** ({date})", value=f"> Note : **{avg:.2f}/10**", inline=False)
            
        if self.total_pages >= 0:
            embed.set_footer(text=f"Page {self.current_page + 1}/{self.total_pages + 1}")
        return embed

    async def show_profile_view(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title=f"Profil de {self.target_user.display_name}",
            description="Cliquez sur les boutons `⬅️` et `➡️` pour voir la liste des produits notés.",
            color=self.target_user.color
        )
        embed.set_image(url=f"attachment://{self.initial_image_file.filename}")
        await interaction.response.edit_message(embed=embed, attachments=[self.initial_image_file], view=self)

    async def show_ratings_view(self, interaction: discord.Interaction):
        self.update_buttons_state()
        embed = self.create_ratings_embed()
        await interaction.response.edit_message(embed=embed, attachments=[], view=self)

    class ShowProfileButton(discord.ui.Button):
        def __init__(self): super().__init__(label="Afficher le Profil", style=discord.ButtonStyle.primary, emoji="👤", row=1)
        async def callback(self, interaction: discord.Interaction):
            await self.view.show_profile_view(interaction)

    class PrevButton(discord.ui.Button):
        def __init__(self): super().__init__(label="⬅️ Précédent", style=discord.ButtonStyle.secondary, row=0)
        async def callback(self, interaction: discord.Interaction):
            if self.view.current_page > 0: self.view.current_page -= 1
            await self.view.show_ratings_view(interaction)
            
    class NextButton(discord.ui.Button):
        def __init__(self): super().__init__(label="Suivant ➡️", style=discord.ButtonStyle.secondary, row=0)
        async def callback(self, interaction: discord.Interaction):
            if self.view.current_page < self.view.total_pages: self.view.current_page += 1
            await self.view.show_ratings_view(interaction)

    class ResetButton(discord.ui.Button):
        def __init__(self): super().__init__(label="Réinitialiser", style=discord.ButtonStyle.danger, emoji="🗑️", row=1)
        async def callback(self, i: discord.Interaction):
            await i.response.send_message(f"Voulez-vous vraiment supprimer les notes de {self.view.target_user.mention} ?", view=ConfirmResetNotesView(self.view.target_user, self.view.bot), ephemeral=True)

class ConfirmRatingOverwriteView(discord.ui.View):
    def __init__(self, product_name: str, user: discord.User, cog_instance, existing_rating: dict, avg_score: float):
        super().__init__(timeout=60)
        self.product_name = product_name
        self.user = user
        self.cog_instance = cog_instance
        self.existing_rating = existing_rating
        self.avg_score = avg_score
    @discord.ui.button(label="Modifier ma note", style=discord.ButtonStyle.primary, emoji="✏️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = RatingModal(
            self.product_name,
            self.user,
            self.cog_instance,
            existing_rating=self.existing_rating
        )
        await interaction.response.send_modal(modal)
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)
    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Opération annulée.", view=None)

class ConfirmResetNotesView(discord.ui.View):
    def __init__(self, user, bot): super().__init__(timeout=60); self.user=user; self.bot=bot
    @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.danger)
    async def confirm(self, i: discord.Interaction, b: discord.ui.Button):
        def _del(uid):
            conn = get_db_connection(); c=conn.cursor(); c.execute("DELETE FROM ratings WHERE user_id=?",(uid,)); conn.commit(); conn.close()
        await asyncio.to_thread(_del, self.user.id)
        await i.response.edit_message(content=f"✅ Notes de {self.user.mention} supprimées.", view=None)
    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, i: discord.Interaction, b: discord.ui.Button): await i.response.edit_message(content="Opération annulée.", view=None)

class ContactButtonsView(discord.ui.View):
    def __init__(self, contact_info: dict):
        super().__init__(timeout=None) # Pas de timeout pour que les boutons restent cliquables

        # On définit les boutons que l'on veut créer
        # Format : (clé_dans_le_json, Label du bouton, Emoji)
        button_map = [
            ("site", "Boutique", LFONCEDALLE_EMOJI),
            ("tiktok", "TikTok", TIKTOK_EMOJI),
            ("instagram", "Instagram", INSTAGRAM_EMOJI),
            ("telegram", "Telegram", TELEGRAM_EMOJI)
        ]

        for key, label, emoji in button_map:
            # On récupère l'URL depuis la configuration
            url = contact_info.get(key)
            # On ajoute le bouton UNIQUEMENT si une URL est trouvée
            if url: 
                self.add_item(discord.ui.Button(label=label, style=discord.ButtonStyle.link, url=url, emoji=emoji))
@app_commands.guild_only()
class ConfigCog(commands.GroupCog, name="config", description="Gère l'édition de la configuration du bot."):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()

    # --- Sous-groupe pour /config set ---
    set_group = app_commands.Group(name="set", description="Définit un paramètre de configuration.")

    @set_group.command(name="role", description="[STAFF] Configure un rôle spécifique (staff, mentions).")
    @app_commands.check(is_staff_or_owner)
    @app_commands.describe(parametre="Le type de rôle à configurer.", valeur="Le rôle à assigner.")
    @app_commands.choices(parametre=[
        Choice(name="Staff", value="staff_role_id"),
        Choice(name="Mention Nouveautés", value="mention_role_id"),
    ])
    async def set_role(self, interaction: discord.Interaction, parametre: Choice[str], valeur: discord.Role):
        await config_manager.update_state(interaction.guild.id, parametre.value, valeur.id)
        await interaction.response.send_message(f"✅ Le paramètre **{parametre.name}** est maintenant assigné à {valeur.mention}.", ephemeral=True)

    @set_group.command(name="salon", description="[STAFF] Configure un salon spécifique (menu, sélection, etc.).")
    @app_commands.check(is_staff_or_owner)
    @app_commands.describe(parametre="Le type de salon à configurer.", valeur="Le salon à assigner.")
    @app_commands.choices(parametre=[
        Choice(name="Menu Principal", value="menu_channel_id"),
        Choice(name="Sélection de la Semaine", value="selection_channel_id"),
        Choice(name="Sauvegardes Base de Données", value="db_export_channel_id"),
    ])
    async def set_salon(self, interaction: discord.Interaction, parametre: Choice[str], valeur: discord.TextChannel):
        await config_manager.update_state(interaction.guild.id, parametre.value, valeur.id)
        await interaction.response.send_message(f"✅ Le paramètre **{parametre.name}** est maintenant assigné à {valeur.mention}.", ephemeral=True)

    
    # --- Sous-groupe pour /config loyalty ---
    loyalty_group = app_commands.Group(name="loyalty", description="Gère l'édition des rôles de fidélité et succès.")
    
    @loyalty_group.command(name="set", description="[STAFF] Ajoute ou modifie un rôle de fidélité ou de succès.")
    @app_commands.check(is_staff_or_owner)
    @app_commands.describe(
        role="Le rôle Discord à assigner.",
        name="Le nom du palier ou du succès (ex: Fidèle, Explorateur).",
        emoji="L'émoji à afficher pour ce badge (ex: 💚).",
        type="Le type de condition pour débloquer le rôle.",
        threshold="[Pour Paliers] Le nombre de notes requis."
    )
    @app_commands.choices(type=[
        Choice(name="Palier par Nombre de Notes", value="threshold"),
        Choice(name="Succès - Explorateur", value="explorer"),
        Choice(name="Succès - Spécialiste", value="specialist"),
    ])
    async def set_loyalty(self, interaction: discord.Interaction, role: discord.Role, name: str, emoji: str, type: Choice[str], threshold: Optional[app_commands.Range[int, 1, 1000]] = None):
        await interaction.response.defer(ephemeral=True)

        if type.value == 'threshold' and threshold is None:
            await interaction.followup.send("❌ Pour un rôle de type 'Palier', vous devez spécifier un `threshold`.", ephemeral=True)
            return
            
        loyalty_config = config_manager.get_config("loyalty_roles", {})
        role_id_str = str(role.id)
        
        loyalty_config[role_id_str] = {
            "id": role_id_str, "name": name, "emoji": emoji, "type": type.value
        }
        if type.value == 'threshold':
            loyalty_config[role_id_str]['threshold'] = threshold
        
        await config_manager.update_config("loyalty_roles", loyalty_config)
        await interaction.followup.send(f"✅ Le rôle **{name}** a été configuré avec succès pour {role.mention}.", ephemeral=True)

# -- COMMANDES --
class SlashCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    async def product_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        products = self.bot.product_cache.get('products', [])
        
        if not products or not isinstance(products[0], dict):
            return []

        # [MODIFICATION] Liste de mots-clés à exclure SPÉCIFIQUEMENT pour la comparaison
        # On ne veut pas comparer des accessoires.
        exclude_keywords = ["briquet", "feuille", "papier", "grinder", "accessoire", "telegram", "instagram", "tiktok"]

        choices = [
            prod['name'] for prod in products 
            if 'name' in prod 
            # On vérifie que le nom du produit ne contient aucun mot-clé d'exclusion
            and not any(keyword in prod['name'].lower() for keyword in exclude_keywords)
            # Puis on filtre par la saisie de l'utilisateur
            and current.lower() in prod['name'].lower()
        ]
        
        return [
            app_commands.Choice(name=choice, value=choice)
            for choice in choices[:25]
        ]
    
    async def generate_dashboard_embed(self, guild: discord.Guild) -> discord.Embed:
        """
        [MODIFIÉ] Récupère les statistiques et génère l'embed du dashboard amélioré pour un serveur.
        """
        one_week_ago_dt = datetime.utcnow() - timedelta(days=7)
        one_week_ago_iso = one_week_ago_dt.isoformat()

        # 1. Requêtes à la base de données (inchangé)
        def _fetch_stats_sync():
            conn = get_db_connection()
            cursor = conn.cursor()
            
            total_ratings = cursor.execute("SELECT COUNT(id) FROM ratings").fetchone()[0]
            total_linked_accounts = cursor.execute("SELECT COUNT(discord_id) FROM user_links").fetchone()[0]
            total_raters = cursor.execute("SELECT COUNT(DISTINCT user_id) FROM ratings").fetchone()[0]

            weekly_ratings = cursor.execute("SELECT COUNT(id) FROM ratings WHERE rating_timestamp >= ?", (one_week_ago_iso,)).fetchone()[0]
            
            cursor.execute("SELECT user_id, COUNT(id) as count FROM ratings WHERE rating_timestamp >= ? GROUP BY user_id ORDER BY count DESC LIMIT 1", (one_week_ago_iso,))
            top_rater_row = cursor.fetchone()

            cursor.execute("SELECT product_name, AVG((visual_score+smell_score+touch_score+taste_score+effects_score)/5.0) as avg_score FROM ratings WHERE rating_timestamp >= ? GROUP BY product_name ORDER BY avg_score DESC LIMIT 1", (one_week_ago_iso,))
            top_product_row = cursor.fetchone()
            
            cursor.execute("SELECT product_name, AVG((visual_score+smell_score+touch_score+taste_score+effects_score)/5.0) as avg_score FROM ratings WHERE rating_timestamp >= ? GROUP BY product_name ORDER BY avg_score ASC LIMIT 1", (one_week_ago_iso,))
            worst_product_row = cursor.fetchone()

            conn.close()
            return {
                "total_ratings": total_ratings, "total_linked": total_linked_accounts,
                "total_raters": total_raters, "weekly_ratings": weekly_ratings,
                "top_rater": top_rater_row, "top_product": top_product_row,
                "worst_product": worst_product_row
            }

        db_stats = await asyncio.to_thread(_fetch_stats_sync)

        # 2. Appel à l'API Flask (inchangé)
        shop_stats = {}
        try:
            import aiohttp
            api_url = f"{APP_URL}/api/get_shop_stats"
            headers = {"Authorization": f"Bearer {FLASK_SECRET_KEY}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, headers=headers, timeout=20) as response:
                    if response.ok:
                        shop_stats = await response.json()
        except Exception:
            pass

        # 3. [MODIFIÉ] Création de l'embed
        embed = create_styled_embed(
            title=f"📊 Tableau de Bord - {guild.name}",
            description=f"Statistiques globales et activité récente.",
            color=discord.Color.blue()
        )

        # --- Section 1 : Boutique ---
        shop_text_weekly = (
            f"**CA (7j) :** `{shop_stats.get('weekly_revenue', 0.0):.2f} €`\n"
            f"**Commandes (7j) :** `{shop_stats.get('weekly_order_count', 'N/A')}`"
        )
        shop_text_monthly = (
            f"**CA (Mois) :** `{shop_stats.get('monthly_revenue', 0.0):.2f} €`\n"
            f"**Commandes (Mois) :** `{shop_stats.get('monthly_order_count', 'N/A')}`"
        )
        embed.add_field(name=f"{SHOPIFY_EMOJI} Activité de la Boutique", value=shop_text_weekly, inline=True)
        embed.add_field(name="\u200b", value=shop_text_monthly, inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=False) # Ligne de séparation

        # --- Section 2 : Communauté ---
        top_rater_text = "*Aucun*"
        if db_stats['top_rater']:
            user_id, count = db_stats['top_rater']
            member = guild.get_member(user_id)
            top_rater_text = f"{member.mention if member else f'ID: {user_id}'} (`{count}`)"

        community_text_weekly = (
            f"**Notes (7j) :** `{db_stats['weekly_ratings']}`\n"
            f"**Top Noteur (7j) :** {top_rater_text}"
        )
        avg_notes = (db_stats['total_ratings'] / db_stats['total_raters']) if db_stats['total_raters'] > 0 else 0
        community_text_global = (
            f"**Notes totales :** `{db_stats['total_ratings']}`\n"
            f"**Comptes Liés :** `{db_stats['total_linked']}`"
        )
        
        embed.add_field(name="👥 Activité Communautaire", value=community_text_weekly, inline=True)
        embed.add_field(name="\u200b", value=community_text_global, inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=False) # Ligne de séparation

        # --- Section 3 : Performance Produits ---
        product_text = ""
        if db_stats['top_product']:
            product_name, score = db_stats['top_product']
            product_text += f"⭐ **Produit Star (7j) :** *{product_name}* (`{score:.2f}/10`)\n"
        if db_stats['worst_product']:
            product_name, score = db_stats['worst_product']
            product_text += f"⚠️ **À surveiller (7j) :** *{product_name}* (`{score:.2f}/10`)"
        
        if not product_text: product_text = "*Pas de nouvelles notes cette semaine.*"
        embed.add_field(name="🌿 Performance Produits", value=product_text, inline=False)

        embed.set_footer(text=f"Rapport généré le {datetime.now(paris_tz).strftime('%d/%m/%Y à %H:%M')}")
        
        return embed

    async def _update_all_user_roles(self, guild: discord.Guild, member: discord.Member):
        """
        Vérifie et synchronise TOUS les rôles de fidélité et de succès pour un membre.
        Gère les paliers (exclusifs) et les succès (additifs).
        """
        if not guild or not member:
            return

        loyalty_config = config_manager.get_config("loyalty_roles", {})
        if not loyalty_config:
            return

        # 1. Récupérer les données de l'utilisateur une seule fois
        def _get_user_ratings_summary(user_id):
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT product_name FROM ratings WHERE user_id = ?", (user_id,))
            all_rated_products = [row[0] for row in cursor.fetchall()]
            conn.close()
            return all_rated_products
        
        rated_products = await asyncio.to_thread(_get_user_ratings_summary, member.id)
        total_rating_count = len(rated_products)
        
        # 2. Déterminer les rôles que le membre DEVRAIT avoir
        roles_member_should_have = set()

        # a) Gérer les rôles de type "palier" (mutuellement exclusifs)
        tiered_roles = [data for data in loyalty_config.values() if data.get('type') == 'threshold']
        if tiered_roles:
            # Trier par seuil décroissant pour trouver le plus haut palier atteint
            sorted_tiered_roles = sorted(tiered_roles, key=lambda r: r.get('threshold', 0), reverse=True)
            for role_data in sorted_tiered_roles:
                if total_rating_count >= role_data.get('threshold', 9999):
                    roles_member_should_have.add(int(role_data['id']))
                    break # On a trouvé le plus haut palier, on arrête

        # b) Gérer les rôles de type "succès" (additifs)
        # Catégoriser les produits notés
        product_categories = {"weed": set(), "hash": set(), "accessoire": set()}
        for p_name in rated_products:
            name_lower = p_name.lower()
            # Note: Cette logique est simple et peut être améliorée si vous avez des catégories plus complexes
            if "weed" in name_lower or "fleur" in name_lower:
                product_categories["weed"].add(p_name)
            elif "hash" in name_lower or "résine" in name_lower:
                product_categories["hash"].add(p_name)
            elif any(kw in name_lower for kw in ["briquet", "feuille", "grinder", "accessoire"]):
                product_categories["accessoire"].add(p_name)
        
        has_explorer = all(len(products) > 0 for products in product_categories.values())
        has_specialist = any(len(products) >= 5 for products in product_categories.values())

        for role_data in loyalty_config.values():
            if role_data.get('type') == 'explorer' and has_explorer:
                roles_member_should_have.add(int(role_data['id']))
            elif role_data.get('type') == 'specialist' and has_specialist:
                roles_member_should_have.add(int(role_data['id']))

        # 3. Synchroniser les rôles
        all_loyalty_role_ids = {int(r['id']) for r in loyalty_config.values()}
        member_role_ids = {role.id for role in member.roles}
        
        roles_to_add_ids = roles_member_should_have - member_role_ids
        roles_to_remove_ids = (all_loyalty_role_ids & member_role_ids) - roles_member_should_have

        # Convertir les IDs en objets Role
        roles_to_add = [guild.get_role(role_id) for role_id in roles_to_add_ids if guild.get_role(role_id)]
        roles_to_remove = [guild.get_role(role_id) for role_id in roles_to_remove_ids if guild.get_role(role_id)]

        try:
            if roles_to_add:
                await member.add_roles(*roles_to_add, reason="Mise à jour automatique des rôles de fidélité/succès")
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove, reason="Mise à jour automatique des rôles de fidélité/succès")
        except discord.Forbidden:
            Logger.error(f"Permissions manquantes pour gérer les rôles de {member.name} sur le serveur {guild.name}.")
        except Exception as e:
            Logger.error(f"Erreur lors de la mise à jour des rôles pour {member.name}: {e}")

    @app_commands.command(name="menu", description="Affiche le menu interactif des produits disponibles.")
    async def menu(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await log_user_action(interaction, "a demandé le menu interactif (/menu)")
        try:
            def _read_cache_sync():
                with open(CACHE_FILE, 'r', encoding='utf-8') as f: return json.load(f)
            site_data = self.bot.product_cache
            if not site_data or not (products := site_data.get('products')):
                await interaction.followup.send("Désolé, le menu n'est pas disponible.", ephemeral=True)
                return
            
            promos_list = site_data.get('general_promos', [])
            general_promos_text = "\n".join([f"• {promo}" for promo in promos_list]) or "Aucune promotion générale en cours."
            
            hash_count, weed_count, box_count, accessoire_count = get_product_counts(products)
            description_text = (f"__**📦 Produits disponibles :**__\n\n"
                              f"**`Fleurs 🍃 :` {weed_count}**\n"
                              f"**`Résines 🍫 :` {hash_count}**\n"
                              f"**`Boxs 📦 :` {box_count}**\n"
                              f"**`Accessoires 🛠️ :` {accessoire_count}**\n\n"
                              f"__**💰 Promotions disponibles :**__\n\n{general_promos_text}\n\n"
                              f"*(Données mises à jour <t:{int(site_data.get('timestamp'))}:R>)*")
            embed = discord.Embed(title="📢 Nouveautés et Promotions !", url=CATALOG_URL, description=description_text, color=discord.Color.from_rgb(0, 102, 204))
            main_logo_url = config_manager.get_config("contact_info.main_logo_url")
            if main_logo_url: embed.set_thumbnail(url=main_logo_url)
            view = MenuView()
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except (FileNotFoundError, json.JSONDecodeError):
            await interaction.followup.send("Le menu est en cours de construction, veuillez réessayer.", ephemeral=True)
        except Exception as e:
            Logger.error(f"Erreur dans /menu : {e}")
            traceback.print_exc()
            await interaction.followup.send("❌ Une erreur est survenue lors de l'affichage du menu.", ephemeral=True)

    @app_commands.command(name="noter", description="Note un produit que tu as acheté sur la boutique.")
    async def noter(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await log_user_action(interaction, "a initié la commande /noter")
        
        try:
            # Cette fonction interne contacte l'API Flask
            def fetch_purchased_products():
                import requests
                try:
                    api_url = f"{APP_URL}/api/get_purchased_products/{interaction.user.id}"
                    res = requests.get(api_url, timeout=10)
                    
                    # --- NOUVELLE GESTION D'ERREUR DÉTAILLÉE ---
                    if res.status_code == 404:
                        # L'API a explicitement dit que le compte n'est pas lié
                        return {"error": "not_linked"}
                    
                    res.raise_for_status() # Lève une exception pour les autres erreurs HTTP (500, etc.)
                    return {"products": res.json().get("products", [])}

                except requests.RequestException as e:
                    # L'API n'a pas pu être contactée
                    Logger.error(f"Erreur de connexion à l'API pour /noter : {e}")
                    return {"error": "api_unavailable"}
                except Exception as e:
                    # Autre erreur inattendue
                    Logger.error(f"Erreur inattendue dans fetch_purchased_products: {e}")
                    return {"error": "unknown"}

            # On exécute la fonction dans un thread pour ne pas bloquer le bot
            result = await asyncio.to_thread(fetch_purchased_products)

            # Cas 1: Erreur détectée (compte non lié, API indisponible, etc.)
            if "error" in result:
                if result["error"] == "not_linked":
                    message = "❌ **Compte non lié !**\nPour pouvoir noter tes produits, tu dois d'abord lier ton compte Discord à l'e-mail de tes commandes avec la commande `/lier_compte`."
                elif result["error"] == "api_unavailable":
                    message = "🔌 Le service de vérification des achats est momentanément indisponible. Merci de réessayer plus tard."
                else:
                    message = "❌ Oups, une erreur inattendue est survenue. Le staff a été notifié."
                await interaction.followup.send(message, ephemeral=True)
                return

            # Cas 2: Le compte est lié, mais aucun produit n'est disponible à la notation
            purchased_products = result.get("products", [])
            if not purchased_products:
                message = "🤔 **Aucun produit à noter pour le moment.**\nIl se peut que tu n'aies pas encore de commande enregistrée."
                await interaction.followup.send(message, ephemeral=True)
                return

            # Cas 3: Tout est OK, on affiche le menu de sélection
            view = NotationProductSelectView(purchased_products, interaction.user, self)
            await interaction.followup.send("Veuillez choisir un produit à noter dans la liste ci-dessous :", view=view, ephemeral=True)

        except Exception as e:
            Logger.error(f"Erreur majeure dans la commande /noter : {e}"); traceback.print_exc()
            await interaction.followup.send("❌ Oups, une erreur critique est survenue. Le staff a été notifié.", ephemeral=True)

    @app_commands.command(name="top_noteurs", description="Affiche le classement des membres qui ont noté le plus de produits.")
    @app_commands.guild_only()
    async def top_noteurs(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) 
        await log_user_action(interaction, "a demandé le classement des top noteurs.")
        
        def _fetch_top_raters_sync():
            conn = get_db_connection()
            conn.row_factory = sqlite3.Row # Important pour accéder aux colonnes par leur nom
            cursor = conn.cursor()
            
            # --- NOUVELLE REQUÊTE SQL PLUS COMPLÈTE ---
            cursor.execute("""
                WITH UserAverageNotes AS (
                    SELECT
                        user_id,
                        user_name,
                        product_name,
                        (COALESCE(visual_score, 0) + COALESCE(smell_score, 0) + COALESCE(touch_score, 0) + COALESCE(taste_score, 0) + COALESCE(effects_score, 0)) / 5.0 AS avg_note,
                        -- On utilise ROW_NUMBER pour trouver la meilleure note de chaque utilisateur
                        ROW_NUMBER() OVER(PARTITION BY user_id ORDER BY (COALESCE(visual_score, 0) + COALESCE(smell_score, 0) + COALESCE(touch_score, 0) + COALESCE(taste_score, 0) + COALESCE(effects_score, 0)) DESC, rating_timestamp DESC) as rn
                    FROM ratings
                ),
                UserStats AS (
                    SELECT
                        user_id,
                        COUNT(user_id) as rating_count,
                        AVG(avg_note) as global_avg
                    FROM UserAverageNotes
                    GROUP BY user_id
                ),
                BestProduct AS (
                    SELECT
                        user_id,
                        product_name as best_rated_product
                    FROM UserAverageNotes
                    WHERE rn = 1
                )
                SELECT
                    us.user_id,
                    (SELECT user_name FROM ratings WHERE user_id = us.user_id ORDER BY rating_timestamp DESC LIMIT 1) as last_user_name,
                    us.rating_count,
                    us.global_avg,
                    bp.best_rated_product
                FROM UserStats us
                JOIN BestProduct bp ON us.user_id = bp.user_id
                ORDER BY us.rating_count DESC, us.global_avg DESC;
            """)
            
            results = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return results
            
        try:
            top_raters = await asyncio.to_thread(_fetch_top_raters_sync)
            if not top_raters:
                await interaction.followup.send("Personne n'a encore noté de produit !", ephemeral=True)
                return
            
            # On passe les données à la vue qui saura comment les afficher
            paginator = TopRatersPaginatorView(top_raters, interaction.guild)
            embed = paginator.create_embed_for_page()
            await interaction.followup.send(embed=embed, view=paginator, ephemeral=True)
        except Exception as e:
            Logger.error(f"Erreur dans /top_noteurs : {e}")
            traceback.print_exc()
            await interaction.followup.send("❌ Erreur lors de la récupération du classement.", ephemeral=True)

    @app_commands.command(name="classement_produits", description="Affiche la moyenne de tous les produits notés.")
    async def classement_general(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await log_user_action(interaction, "a demandé le classement général des produits.")
        try:
            def _fetch_all_ratings_sync():
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT product_name, AVG((COALESCE(visual_score, 0) + COALESCE(smell_score, 0) + COALESCE(touch_score, 0) + COALESCE(taste_score, 0) + COALESCE(effects_score, 0)) / 5.0), COUNT(id)
                    FROM ratings GROUP BY product_name HAVING COUNT(id) > 0
                    ORDER BY AVG((visual_score + smell_score + touch_score + taste_score + effects_score) / 5.0) DESC
                """)
                return cursor.fetchall()
            def _read_product_cache_sync():
                try:
                    with open(CACHE_FILE, 'r', encoding='utf-8') as f: return json.load(f)
                except (FileNotFoundError, json.JSONDecodeError): return {}

            all_products_ratings, site_data = await asyncio.gather(
                asyncio.to_thread(_fetch_all_ratings_sync),
                asyncio.to_thread(_read_product_cache_sync)
            )
            if not all_products_ratings:
                await interaction.followup.send("Aucun produit n'a encore été noté.", ephemeral=True)
                return
            product_map = {p['name'].strip().lower(): p for p in site_data.get('products', [])}
            paginator = RankingPaginatorView(all_products_ratings, product_map, items_per_page=5)
            embed = paginator.create_embed_for_page()
            await interaction.followup.send(embed=embed, view=paginator, ephemeral=True)
        except Exception as e:
            Logger.error(f"Erreur dans /classement_general : {e}")
            traceback.print_exc()
            await interaction.followup.send("❌ Erreur lors de la récupération du classement.", ephemeral=True)

    @app_commands.command(name="contacts", description="Affiche tous les liens utiles de LaFoncedalle.")
    async def contacts(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await log_user_action(interaction, "a demandé les contacts.")
        
        contact_info = config_manager.get_config("contact_info", {})
        
        embed = create_styled_embed(
            title=f"Nos Plateformes",
            description=contact_info.get("description", "Rejoignez-nous sur nos réseaux !"),
            color=discord.Color.from_rgb(167, 68, 232) # Violet "brandé"
        )
        
        # On utilise le thumbnail du config, qui est le logo rond
        thumbnail_url = contact_info.get("thumbnail_logo_url")
        if thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url)
        
        # On crée la vue avec les boutons
        view = ContactButtonsView(contact_info)
        
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="debug", description="[STAFF] Affiche un diagnostic complet du bot et propose des actions.")
    @app_commands.check(is_staff_or_owner)
    async def debug(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        guild = interaction.guild
        embed = discord.Embed(
            title=f"⚙️ Panneau de Diagnostic - {self.bot.user.name}",
            description=f"Rapport généré pour le serveur **{guild.name}**.",
            color=discord.Color.orange(),
            timestamp=datetime.now(paris_tz)
        )

        # --- 1. Connectivité ---
        status_text = f"**API Discord :** `{round(self.bot.latency * 1000)} ms`\n"
        
        try:
            import shopify
            start_time = time.time()
            shop_url = os.getenv('SHOPIFY_SHOP_URL')
            api_version = os.getenv('SHOPIFY_API_VERSION')
            access_token = os.getenv('SHOPIFY_ADMIN_ACCESS_TOKEN')
            
            session = shopify.Session(shop_url, api_version, access_token)
            shopify.ShopifyResource.activate_session(session)
            shopify.Shop.current()
            shopify.ShopifyResource.clear_session()
            
            end_time = time.time()
            status_text += f"✅ **API Shopify :** `Connectée en {round((end_time - start_time) * 1000)} ms`\n"
        except Exception:
            status_text += f"❌ **API Shopify :** `Échec de connexion`\n"
        start_time = time.time()
        try:
            import requests
            duration = round((time.time() - start_time) * 1000)
            res = await asyncio.to_thread(requests.get, f"{APP_URL}/", timeout=5)
            res.raise_for_status()
            status_text += f"✅ **API Flask :** `En ligne ({duration} ms)`\n"
        except Exception:
            status_text += f"❌ **API Flask :** `Injoignable ou erreur`\n"
        
        embed.add_field(name="🌐 Connectivité", value=status_text, inline=False)
        
        # --- 2. Tâches Programmées (NOUVELLE SECTION) ---
        tasks_text = ""
        # Accéder aux tâches enregistrées dans le fichier principal du bot
        from catalogue_final import scheduled_check, post_weekly_ranking, scheduled_selection, daily_role_sync, scheduled_db_export, scheduled_reengagement_check

        tasks_to_check = {
            "Vérification Menu": scheduled_check,
            "Classement Hebdo": post_weekly_ranking,
            "Sélection Semaine": scheduled_selection,
            "Synchro Rôles": daily_role_sync,
            "Sauvegarde DB": scheduled_db_export,
            "Rappel Notations" : scheduled_reengagement_check,
        }

        for name, task in tasks_to_check.items():
            if task.is_running():
                next_run = task.next_iteration
                if next_run:
                    # On utilise le format de timestamp Discord R (relatif)
                    tasks_text += f"✅ **{name} :** Prochaine <t:{int(next_run.timestamp())}:R>\n"
                else:
                    tasks_text += f"⚠️ **{name} :** En cours (pas de prochaine itération prévue)\n"
            else:
                tasks_text += f"❌ **{name} :** `Arrêtée`\n"
        
        embed.add_field(name="⏰ Tâches Programmées", value=tasks_text, inline=False)

        # --- 3. Configuration du Serveur ---
        config_text = ""
        def format_setting(item_id, get_method, is_critical=False):
            if not item_id: return f"{'❌' if is_critical else '⚠️'} `Non défini`"
            try:
                item = get_method(int(item_id))
                return f"✅ {item.mention}" if item else f"⚠️ `Introuvable`"
            except (ValueError, TypeError): return "❌ `ID invalide`"

        staff_role_id = await config_manager.get_state(guild.id, 'staff_role_id')
        config_text += f"**Rôle Staff :** {format_setting(staff_role_id, guild.get_role)}\n"
        
        menu_channel_id = await config_manager.get_state(guild.id, 'menu_channel_id')
        config_text += f"**Salon Menu :** {format_setting(menu_channel_id, guild.get_channel, is_critical=True)}"
        
        embed.add_field(name="🔧 Configuration Locale (Principale)", value=config_text, inline=False)
        
        # --- 4. & 5. Cache et Base de Données ---
        if self.bot.product_cache:
            products_count = len(self.bot.product_cache.get('products', []))
            cache_age_ts = self.bot.product_cache.get('timestamp', 0)
            embed.add_field(name="🗃️ Cache de Produits", value=f"✅ `Chargé`\n**Produits :** `{products_count}`\n**MàJ :** <t:{int(cache_age_ts)}:R>", inline=True)
        else:
            embed.add_field(name="🗃️ Cache de Produits", value="❌ `Vide`", inline=True)
            
        try:
            conn = get_db_connection()
            c = conn.cursor()
            ratings_count = c.execute("SELECT COUNT(*) FROM ratings").fetchone()[0]
            links_count = c.execute("SELECT COUNT(*) FROM user_links").fetchone()[0]
            conn.close()
            embed.add_field(name="💾 Base de Données", value=f"✅ `Accessible`\n**Notes :** `{ratings_count}`\n**Comptes liés :** `{links_count}`", inline=True)
        except Exception as e:
            embed.add_field(name="💾 Base de Données", value=f"❌ `Erreur d'accès`\n`{e}`", inline=True)

        # --- 6. Variables d'Environnement ---
        env_text = ""
        env_vars_to_check = ['SHOPIFY_SHOP_URL', 'SHOPIFY_API_VERSION', 'SHOPIFY_ADMIN_ACCESS_TOKEN', 'APP_URL', 'FLASK_SECRET_KEY']
        for var in env_vars_to_check:
            value = os.getenv(var)
            env_text += f"{'✅' if value else '❌'} **{var}:** `{'Présente' if value else 'Manquante'}`\n"
        embed.add_field(name="🔑 Variables d'Environnement", value=env_text, inline=False)
        
        embed.set_footer(text=f"ID du Bot: {self.bot.user.id}")
        
        view = DebugView(self.bot, interaction.user)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


    @app_commands.command(name="check", description="Vérifie si de nouveaux produits sont disponibles (cooldown 12h).")
    async def check(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild:
            await interaction.followup.send("Cette commande doit être utilisée sur un serveur.", ephemeral=True)
            return

        cooldown_period = timedelta(hours=12)
        last_check_iso = await config_manager.get_state(interaction.guild.id, 'last_check_command_timestamp')
        
        if last_check_iso:
            time_since = datetime.utcnow() - datetime.fromisoformat(last_check_iso)
            if time_since < cooldown_period:
                next_time = datetime.fromisoformat(last_check_iso) + cooldown_period
                await interaction.followup.send(f"⏳ Prochaine vérification possible pour ce serveur <t:{int(next_time.timestamp())}:R>.", ephemeral=True)
                return
        
        await log_user_action(interaction, "a utilisé /check.")
        try:
            updates_found = await self.bot.check_for_updates(self.bot, force_publish=False)
            await config_manager.update_state(interaction.guild.id, 'last_check_command_timestamp', datetime.utcnow().isoformat())
            
            followup_message = "👍 Le menu est déjà à jour. Merci d'avoir vérifié !"
            if updates_found:
                followup_message = "✅ Merci ! Le menu a été mis à jour grâce à vous."
            
            await interaction.followup.send(followup_message, ephemeral=True)

        except Exception as e:
            Logger.error(f"Erreur dans /check: {e}"); traceback.print_exc()
            await interaction.followup.send("❌ Oups, une erreur est survenue.", ephemeral=True)

    @app_commands.command(name="nitro_gift", description="Réclame ton code de réduction pour avoir boosté le serveur !")
    @app_commands.guild_only()
    async def nitro_gift(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user, guild = interaction.user, interaction.guild
        if not user.premium_since:
            await interaction.followup.send("Désolé, cette commande est pour les Boosters. Merci pour ton soutien ! 🚀", ephemeral=True)
            return
        
        claimed_users = {}
        try:
            with open(CLAIMED_CODES_FILE, 'r') as f: claimed_users = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError): pass

        if str(user.id) in claimed_users:
            await interaction.followup.send(f"Tu as déjà réclamé ton code le {claimed_users[str(user.id)]}. Merci encore ! ✨", ephemeral=True)
            return
        
        try:
            with open(NITRO_CODES_FILE, 'r+') as f:
                codes = [line.strip() for line in f if line.strip()]
                if not codes:
                    await interaction.followup.send("Oh non ! Plus de codes dispo. Contactez le staff. 😥", ephemeral=True)
                    Logger.warning("Fichier de codes Nitro vide.")
                    return
                gift_code = codes.pop(0)
                f.seek(0); f.truncate(); f.write('\n'.join(codes))
            
            try:
                embed = create_styled_embed(title="Merci pour ton Boost ! 💖", 
                    description=f"Merci de soutenir **{guild.name}** ! Voici ton code de réduction unique.", 
                    color=discord.Color.nitro_pink())
                embed.add_field(name="🎟️ Ton Code", value=f"**`{gift_code}`**")
                await user.send(embed=embed)
                await interaction.followup.send("Code envoyé en MP ! 😉", ephemeral=True)
                claimed_users[str(user.id)] = datetime.now(paris_tz).strftime('%d/%m/%Y')
                with open(CLAIMED_CODES_FILE, 'w') as f: json.dump(claimed_users, f, indent=4)
                await log_user_action(interaction, f"a réclamé le code Nitro : {gift_code}")
            except discord.Forbidden:
                await interaction.followup.send("Impossible de t'envoyer un MP. Vérifie tes paramètres de confidentialité.", ephemeral=True)
        except FileNotFoundError:
            await interaction.followup.send("Fichier de codes introuvable. Contactez le staff.", ephemeral=True)
            Logger.error(f"Fichier '{NITRO_CODES_FILE}' introuvable.")
        except Exception as e:
            Logger.error(f"Erreur dans /nitro_gift : {e}"); traceback.print_exc()
            await interaction.followup.send("❌ Erreur interne.", ephemeral=True)
    

    @app_commands.command(name="profil", description="Affiche le profil et les notations d'un membre.")
    @app_commands.describe(membre="Le membre dont vous voulez voir le profil (optionnel).")
    async def profil(self, interaction: discord.Interaction, membre: Optional[discord.Member] = None):
        await interaction.response.defer(ephemeral=True)
        target_user = membre or interaction.user
        await log_user_action(interaction, f"a consulté le profil de {target_user.display_name}")
        def _fetch_user_data_sync(user_id):
            conn = get_db_connection(); conn.row_factory = sqlite3.Row; c = conn.cursor()
            
            # 1. Notes
            c.execute("SELECT * FROM ratings WHERE user_id = ? ORDER BY rating_timestamp DESC", (user_id,))
            user_ratings = [dict(row) for row in c.fetchall()]

            # 2. Statistiques
            user_stats = {'rank': 'N/C', 'count': 0, 'avg': 0, 'min_note': 0, 'max_note': 0, 'loyalty_badge': None}
            c.execute("""
                WITH UserAverageNotes AS (
                    SELECT user_id, (COALESCE(visual_score, 0) + COALESCE(smell_score, 0) + COALESCE(touch_score, 0) + COALESCE(taste_score, 0) + COALESCE(effects_score, 0)) / 5.0 AS avg_note
                    FROM ratings
                ), AllRanks AS (
                    SELECT user_id, COUNT(user_id) as rating_count, AVG(avg_note) as global_avg, MIN(avg_note) as min_note, MAX(avg_note) as max_note,
                        RANK() OVER (ORDER BY COUNT(user_id) DESC, AVG(avg_note) DESC) as user_rank
                    FROM UserAverageNotes GROUP BY user_id
                )
                SELECT user_rank, rating_count, global_avg, min_note, max_note FROM AllRanks WHERE user_id = ?
            """, (user_id,))
            stats_row = c.fetchone()
            
            # --- CORRECTION APPLIQUÉE ICI ---
            if stats_row:
                user_stats['rank'] = stats_row['user_rank']
                user_stats['count'] = stats_row['rating_count']
                user_stats['avg'] = stats_row['global_avg']
                user_stats['min_note'] = stats_row['min_note']
                user_stats['max_note'] = stats_row['max_note']
            # --- FIN DE LA CORRECTION ---

            # 3. Badge de fidélité
            loyalty_config = config_manager.get_config("loyalty_roles", {})
            if loyalty_config and user_stats.get('count', 0) > 0:
                sorted_roles = sorted(loyalty_config.values(), key=lambda r: r.get('threshold', 0), reverse=True)
                for role_data in sorted_roles:
                    if user_stats['count'] >= role_data.get('threshold', 0):
                        user_stats['loyalty_badge'] = {"name": role_data.get('name'), "emoji": role_data.get('emoji')}
                        break
            
            # 4. Email
            c.execute("SELECT user_email FROM user_links WHERE discord_id = ?", (str(user_id),))
            email_row = c.fetchone()
            user_email = email_row['user_email'] if email_row else None
            conn.close()
            
            # 5. Données Shopify
            shopify_data = {}
            if user_email:
                shopify_data['anonymized_email'] = anonymize_email(user_email)
                api_url = f"{APP_URL}/api/get_purchased_products/{user_id}"
                try:
                    import requests
                    res = requests.get(api_url, timeout=10)
                    if res.ok: shopify_data.update(res.json())
                except requests.RequestException: pass
            
            return user_stats, user_ratings, shopify_data
        try:
            user_stats, user_ratings, shopify_data = await asyncio.to_thread(_fetch_user_data_sync, target_user.id)
            if user_stats.get('count', 0) == 0 and not shopify_data.get('purchase_count'):
                await interaction.followup.send("Cet utilisateur n'a aucune activité enregistrée.", ephemeral=True)
                return
            embed = discord.Embed(title=f"Profil de {target_user.display_name}", color=target_user.color)
            embed.set_thumbnail(url=target_user.display_avatar.url)

            # Section Boutique
            anonymized_email = shopify_data.get('anonymized_email')
            if anonymized_email:
                purchase_count = shopify_data.get('purchase_count', 0)
                shop_activity_text = (
                    f"**Commandes :** `{purchase_count}`\n"
                    f"**Total dépensé :** `{shopify_data.get('total_spent', 0.0):.2f} €`\n"
                    f"**E-mail lié :** `{anonymized_email}`"
                )
            else:
                shop_activity_text = "❌ Compte non lié. Utilise `/lier_compte`."
            embed.add_field(name="🛍️ Activité sur la Boutique", value=shop_activity_text, inline=False)

            # Section Discord
            if user_stats.get('count', 0) > 0:
                discord_activity_text = (f"**Classement :** `#{user_stats.get('rank', 'N/C')}`\n"
                                         f"**Nombre de notes :** `{user_stats.get('count', 0)}`\n"
                                         f"**Moyenne des notes :** `{user_stats.get('avg', 0):.2f}/10`")
                if badge := user_stats.get('loyalty_badge'):
                    discord_activity_text += f"\n**Badge :** {badge.get('emoji', '⭐')} `{badge.get('name', 'Fidèle')}`"
            else:
                discord_activity_text = "Aucune note enregistrée."
            embed.add_field(name="📝 Activité sur le Discord", value=discord_activity_text, inline=False)
            
            can_reset = membre and membre.id != interaction.user.id and await is_staff_or_owner(interaction)
            view = ProfileView(target_user, user_stats, user_ratings, shopify_data, can_reset, self.bot)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            Logger.error(f"Erreur /profil pour {target_user.display_name}: {e}"); traceback.print_exc()
            await interaction.followup.send("❌ Erreur lors de la récupération du profil.", ephemeral=True)

    @app_commands.command(name="lier_force", description="[STAFF] Lie un compte à un e-mail sans vérification.")
    @app_commands.check(is_staff_or_owner)
    @app_commands.describe(membre="Le membre à lier.", email="L'email à associer.")
    async def lier_force(self, interaction: discord.Interaction, email: str, membre: Optional[discord.Member] = None):
        await interaction.response.defer(ephemeral=True)
        target_user = membre or interaction.user
        
        api_url = f"{APP_URL}/api/force-link"
        payload = {"discord_id": str(target_user.id), "email": email}
        headers = {"Authorization": f"Bearer {FLASK_SECRET_KEY}"}
        
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, json=payload, headers=headers) as response:
                    if response.ok:
                        await interaction.followup.send(f"✅ **Succès !** Le compte de {target_user.mention} est maintenant lié à l'e-mail `{email}`.", ephemeral=True)
                    elif response.status == 409:
                        data = await response.json()
                        if data.get("status") == "conflict":
                            existing_email = data.get("existing_email")
                            anonymized_new_email = anonymize_email(email)
                            view = ConfirmOverwriteView(api_url, payload, headers)
                            await interaction.followup.send(
                                f"⚠️ **Attention !** Le compte de {target_user.mention} est déjà lié à `{existing_email}`.\n\n"
                                f"Voulez-vous le remplacer par `{anonymized_new_email}` ?",
                                view=view, ephemeral=True
                            )
                        else:
                            await interaction.followup.send(f"❌ Erreur inattendue : {await response.text()}", ephemeral=True)
                    else:
                        data = await response.json()
                        await interaction.followup.send(f"❌ **Échec :** {data.get('error', 'Erreur inconnue')}", ephemeral=True)
        except Exception as e:
            Logger.error(f"Erreur API /force-link : {e}"); traceback.print_exc()
            await interaction.followup.send("❌ Impossible de contacter le service de liaison.", ephemeral=True)

    @app_commands.command(name="lier_compte", description="Démarre la liaison de ton compte via ton e-mail.")
    @app_commands.describe(email="L'adresse e-mail de tes commandes.")
    async def lier_compte(self, interaction: discord.Interaction, email: str):
        await interaction.response.defer(ephemeral=True)
        api_url = f"{APP_URL}/api/start-verification"
        payload = {"discord_id": str(interaction.user.id), "email": email}
        
        try:
            import requests
            response = await asyncio.to_thread(requests.post, api_url, json=payload, timeout=15)
            
            if response.ok:
                await interaction.followup.send(f"✅ E-mail de vérification envoyé à **{email}**. Utilise `/verifier` avec le code.", ephemeral=True)
            elif response.status_code == 409:
                data = response.json()
                if data.get("status") == "conflict":
                    existing_email = data.get("existing_email")
                    anonymized_new_email = anonymize_email(email)
                    view = ConfirmOverwriteView(api_url, payload, headers=None)
                    await interaction.followup.send(
                        f"⚠️ **Attention !** Votre compte Discord est déjà lié à l'e-mail `{existing_email}`.\n\n"
                        f"Voulez-vous le remplacer par `{anonymized_new_email}` ?",
                        view=view, ephemeral=True
                    )
                else:
                    await interaction.followup.send(f"⚠️ **Échec :** {data.get('error', 'Erreur inconnue')}", ephemeral=True)
            else:
                await interaction.followup.send(f"⚠️ **Échec :** {response.json().get('error', 'Une erreur est survenue.')}", ephemeral=True)
                
        except requests.exceptions.RequestException as e:
            Logger.error(f"Erreur de connexion à l'API /start-verification : {e}")
            await interaction.followup.send("❌ Impossible de contacter le service de vérification.", ephemeral=True)

    @app_commands.command(name="verifier", description="Valide ton adresse e-mail avec le code reçu.")
    @app_commands.describe(code="Le code à 6 chiffres reçu par e-mail.")
    async def verifier(self, interaction: discord.Interaction, code: str):
        await interaction.response.defer(ephemeral=True)
        api_url = f"{APP_URL}/api/confirm-verification"
        payload = {"discord_id": str(interaction.user.id), "code": code.strip()}
        try:
            import requests
            response = await asyncio.to_thread(requests.post, api_url, json=payload, timeout=15)
            
            if response.ok:
                data = response.json()
                gift_sent = data.get("gift_sent")

                if gift_sent:
                    # Cas 1 : C'est la première fois, le cadeau a été envoyé
                    await interaction.followup.send(
                        "🎉 **Félicitations !** Ton compte est maintenant lié. Tu peux utiliser la commande `/noter`.\n\n"
                        "✨ **Vérifie tes e-mails, une surprise t'y attend !**",
                        ephemeral=True
                    )
                else:
                    # Cas 2 : Le compte a bien été lié, mais le cadeau avait déjà été envoyé
                    await interaction.followup.send(
                        "✅ **Compte lié avec succès !** Votre compte est maintenant à nouveau associé.\n\n"
                        "*(Vous avez déjà reçu votre cadeau de bienvenue par le passé.)*",
                        ephemeral=True
                    )
            else:
                # Gestion des erreurs (code invalide, etc.)
                error_message = response.json().get("error", "Une erreur inconnue est survenue.")
                await interaction.followup.send(f"❌ **Échec de la vérification :** {error_message}", ephemeral=True)

        except Exception as e:
            Logger.error(f"Erreur API /confirm-verification : {e}")
            await interaction.followup.send("❌ Impossible de contacter le service de vérification. Merci de réessayer plus tard.", ephemeral=True)

    @app_commands.command(name="delier_compte", description="Supprime la liaison entre ton compte Discord et ton e-mail.")
    async def delier_compte(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await log_user_action(interaction, "a demandé à délier son compte.")

        api_url = f"{APP_URL}/api/unlink"
        payload = {"discord_id": str(interaction.user.id)}

        try:
            import requests
            response = await asyncio.to_thread(requests.post, api_url, json=payload, timeout=15)

            if response.status_code == 200:
                data = response.json()
                unlinked_email = data.get("unlinked_email", "votre e-mail")
                await interaction.followup.send(
                    f"✅ **Succès !** Votre compte Discord a été délié de l'adresse e-mail `{unlinked_email}`.\n"
                    "Vous pouvez maintenant utiliser `/lier_compte` avec une autre adresse si vous le souhaitez.",
                    ephemeral=True
                )
            elif response.status_code == 404:
                await interaction.followup.send(
                    "🤔 Votre compte Discord n'est actuellement lié à aucune adresse e-mail. "
                    "Utilisez `/lier_compte` pour commencer.",
                    ephemeral=True
                )
            else:
                # Gérer d'autres erreurs potentielles de l'API
                error_message = response.json().get("error", "Une erreur inconnue est survenue.")
                await interaction.followup.send(f"❌ **Échec :** {error_message}", ephemeral=True)

        except Exception as e:
            Logger.error(f"Erreur API /unlink : {e}")
            traceback.print_exc()
            await interaction.followup.send("❌ Impossible de contacter le service de liaison. Merci de réessayer plus tard.", ephemeral=True)
    
    @app_commands.command(name="promos", description="Affiche toutes les promotions en cours.")
    async def promos(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await log_user_action(interaction, "a demandé les promotions.")
        try:
            # On utilise le cache du bot qui est toujours à jour
            site_data = self.bot.product_cache
            if not site_data:
                await interaction.followup.send("Les informations sur les promotions ne sont pas disponibles pour le moment.", ephemeral=True); return
            
            promo_products = [p for p in site_data.get('products', []) if p.get('is_promo')]
            general_promos = site_data.get('general_promos', [])
            
            # On utilise la NOUVELLE vue
            paginator = PromoPaginatorView(promo_products, general_promos)
            embed = paginator.create_embed()
            await interaction.followup.send(embed=embed, view=paginator, ephemeral=True)
        except Exception as e:
            Logger.error(f"Erreur dans /promos : {e}"); traceback.print_exc()
            await interaction.followup.send("❌ Erreur lors de la récupération des promotions.", ephemeral=True)

    @app_commands.command(name="aide", description="Affiche le menu d'aide interactif du bot.")
    async def help(self, interaction: discord.Interaction):
        view = HelpView(self)
        await interaction.response.send_message(embed=view.main_embed, view=view, ephemeral=True)

    # Dans commands.py, remplacez la méthode comparer de la classe SlashCommands

    @app_commands.command(name="comparer", description="Compare deux produits côte à côte.")
    @app_commands.autocomplete(produit1=product_autocomplete, produit2=product_autocomplete)
    @app_commands.describe(
        produit1="Le premier produit à comparer.",
        produit2="Le second produit à comparer."
    )
    async def comparer(self, interaction: discord.Interaction, produit1: str, produit2: str):
        await interaction.response.defer(ephemeral=True)

        # --- NOUVELLE FONCTION INTERNE POUR ACCÉDER À LA DB ---
        def _fetch_comparison_data_sync(p1_name: str, p2_name: str) -> dict:
            """Récupère les données de notation agrégées directement depuis la DB."""
            conn = get_db_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            data_map = {}

            for name in [p1_name, p2_name]:
                query = """
                    SELECT 
                        (SELECT r2.product_name FROM ratings r2 WHERE LOWER(TRIM(r2.product_name)) LIKE ? ORDER BY r2.rating_timestamp DESC LIMIT 1) as display_name,
                        COUNT(r1.id) as count,
                        COALESCE(AVG((COALESCE(r1.visual_score,0)+COALESCE(r1.smell_score,0)+COALESCE(r1.touch_score,0)+COALESCE(r1.taste_score,0)+COALESCE(r1.effects_score,0))/5.0), 0) as avg_total,
                        COALESCE(AVG(r1.visual_score), 0) as visuel,
                        COALESCE(AVG(r1.smell_score), 0) as odeur,
                        COALESCE(AVG(r1.touch_score), 0) as toucher,
                        COALESCE(AVG(r1.taste_score), 0) as gout,
                        COALESCE(AVG(r1.effects_score), 0) as effets
                    FROM ratings r1
                    WHERE LOWER(TRIM(r1.product_name)) LIKE ?
                """
                like_param = f"%{name.lower().strip()}%"
                cursor.execute(query, (like_param, like_param))
                result = cursor.fetchone()
                
                if result and result['count'] > 0:
                    data_map[name.lower().strip()] = {
                        "name": result['display_name'],
                        "count": result['count'],
                        "avg_total": result['avg_total'],
                        "details": { 'Visuel': result['visuel'], 'Odeur': result['odeur'], 'Toucher': result['toucher'], 'Goût': result['gout'], 'Effets': result['effets'] }
                    }
            conn.close()
            return data_map

        try:
            if produit1.lower() == produit2.lower():
                return await interaction.followup.send("❌ Veuillez choisir deux produits différents.", ephemeral=True)

            product_map = {p['name'].lower().strip(): p for p in self.bot.product_cache.get('products', [])}
            
            p1_full_name = next((p['name'] for name_key, p in product_map.items() if produit1.lower() in name_key), None)
            p2_full_name = next((p['name'] for name_key, p in product_map.items() if produit2.lower() in name_key), None)
            
            if not p1_full_name or not p2_full_name:
                missing = f"'{produit1 if not p1_full_name else produit2}'"
                return await interaction.followup.send(f"😕 Impossible de trouver les informations pour {missing}.", ephemeral=True)

            p1_data = product_map.get(p1_full_name.lower().strip())
            p2_data = product_map.get(p2_full_name.lower().strip())

            # --- On appelle la fonction de DB locale, plus d'appel API ---
            rating_data_map = await asyncio.to_thread(_fetch_comparison_data_sync, p1_full_name, p2_full_name)
            
            p1_rating_data = rating_data_map.get(p1_full_name.lower().strip())
            p2_rating_data = rating_data_map.get(p2_full_name.lower().strip())

            embed = create_styled_embed(title=f"⚔️ Comparaison : {p1_data['name']} vs {p2_data['name']}", description="Voici un résumé des caractéristiques et des notes moyennes.", color=discord.Color.orange())

            def format_product_field(p_data, p_rating):
                price_text = f"💰 **{p_data.get('price', 'N/A')}**"
                if p_data.get('is_sold_out'): price_text = "❌ **Épuisé**"
                elif p_data.get('is_promo'): price_text = f"🏷️ **{p_data.get('price')}** ~~{p_data.get('original_price')}~~"
                
                note_text = "⭐ **Note :** N/A"
                if p_rating and p_rating.get('count', 0) > 0:
                    note_text = f"⭐ **Note :** **{p_rating['avg_total']:.2f}/10** ({p_rating['count']} avis)"
                
                stats = p_data.get('stats', {})
                gout = stats.get('Goût', "N/A")
                effet = stats.get('Effet', "N/A")

                return f"{price_text}\n{note_text}\n\n👅 **Goût :** `{gout}`\n🧠 **Effet :** `{effet}`"

            embed.add_field(name=f"1️⃣ {p1_data['name']}", value=format_product_field(p1_data, p1_rating_data), inline=True)
            embed.add_field(name=f"2️⃣ {p2_data['name']}", value=format_product_field(p2_data, p2_rating_data), inline=True)

            def format_scores_details(rating_data):
                if not rating_data or not rating_data.get('details') or rating_data.get('count', 0) == 0:
                    return "Pas de notes détaillées"
                scores_dict = rating_data['details']
                cats = ['Visuel', 'Odeur', 'Toucher', 'Goût', 'Effets']
                return "\n".join([f"**{cat} :** `{scores_dict.get(cat, 0):.2f}/10`" for cat in cats])

            embed.add_field(name="\u200b", value="\u200b", inline=False)
            embed.add_field(name=f"Notes Détaillées - {p1_data['name']}", value=format_scores_details(p1_rating_data), inline=True)
            embed.add_field(name=f"Notes Détaillées - {p2_data['name']}", value=format_scores_details(p2_rating_data), inline=True)
            
            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            Logger.error(f"Erreur majeure dans la commande /comparer : {e}")
            traceback.print_exc()
            await interaction.followup.send("❌ Oups, une erreur critique est survenue. Le staff a été notifié.", ephemeral=True)
    
    @app_commands.command(name="ma_commande", description="Affiche le statut de votre dernière commande.")
    async def ma_commande(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await log_user_action(interaction, "a demandé le statut de sa dernière commande.")

        api_url = f"{APP_URL}/api/get_last_order/{interaction.user.id}"
        
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, timeout=15) as response:
                    data = await response.json()
                    
                    if not response.ok:
                        # Gérer les erreurs de l'API (compte non lié, etc.)
                        await interaction.followup.send(f"❌ {data.get('error', 'Une erreur est survenue.')}", ephemeral=True)
                        return

                    # Si tout est OK, on crée un bel embed
                    order = data.get("order")
                    embed = create_styled_embed(
                        title=f"📦 Statut de votre commande #{order.get('name')}",
                        description=f"Voici les détails de votre dernière commande passée le {order.get('date')}.",
                        color=discord.Color.blue()
                    )
                    embed.add_field(name="Statut du Paiement", value=order.get('payment_status_fr'), inline=True)
                    embed.add_field(name="Statut de l'Expédition", value=order.get('fulfillment_status_fr'), inline=True)
                    embed.add_field(name="Montant Total", value=f"**{order.get('total_price')} €**", inline=True)

                    # Ajouter les produits
                    items_text = ""
                    for item in order.get('line_items', []):
                        items_text += f"• {item.get('quantity')}x {item.get('title')}\n"
                    
                    if items_text:
                        embed.add_field(name="📝 Contenu de la commande", value=items_text, inline=False)

                    if order.get('tracking_url'):
                        embed.add_field(name="🚚 Suivi du colis", value=f"**[Cliquez ici pour suivre votre colis]({order.get('tracking_url')})**", inline=False)

                    await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            Logger.error(f"Erreur dans /ma_commande : {e}")
            await interaction.followup.send("❌ Oups, une erreur critique est survenue.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(SlashCommands(bot))
    await bot.add_cog(ConfigCog(bot))