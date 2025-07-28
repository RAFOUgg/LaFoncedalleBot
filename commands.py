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
import dotenv
import shopify

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
        embed.add_field(name="Note de la Communauté", value=community_score_str, inline=True)
        embed.add_field(name="Votre Note Globale", value=f"**{user_avg:.2f} / 10**", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=False)
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
            conn = sqlite3.connect(DB_FILE)
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

class DebugView(discord.ui.View):
    def __init__(self, bot, author):
        super().__init__(timeout=300)
        self.bot = bot
        self.author = author

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # S'assure que seul l'auteur de la commande peut utiliser les boutons
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Vous n'êtes pas autorisé à utiliser ces boutons.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🔄 Synchroniser les Commandes", style=discord.ButtonStyle.primary, row=0)
    async def sync_commands(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            synced = await self.bot.tree.sync()
            await interaction.followup.send(f"✅ **Succès !** {len(synced)} commandes synchronisées avec Discord.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ **Échec de la synchronisation :**\n```py\n{e}\n```", ephemeral=True)

    @discord.ui.button(label="📢 Forcer la Publication du Menu", style=discord.ButtonStyle.success, row=0)
    async def force_publish(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            await self.bot.check_for_updates(self.bot, force_publish=True)
            await interaction.followup.send("✅ **Succès !** La tâche de publication forcée du menu a été lancée.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ **Échec de la publication :**\n```py\n{e}\n```", ephemeral=True)
    
    @discord.ui.button(label="📤 Forcer la Sélection Semaine", style=discord.ButtonStyle.primary, row=0)
    async def force_selection(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True, ephemeral=True)
        if not interaction.guild:
            await interaction.followup.send("❌ Cette action ne peut être effectuée qu'au sein d'un serveur.", ephemeral=True)
            return
        try:
            await self.bot.post_weekly_selection(self.bot, interaction.guild.id)
            await interaction.followup.send("✅ **Succès !** La publication de la sélection de la semaine a été lancée.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ **Échec de la publication de la sélection :**\n```py\n{e}\n```", ephemeral=True)
    
    @discord.ui.button(label="📁 Exporter la base de donnée", style=discord.ButtonStyle.primary, row=0)
    async def export_db(self, interaction: discord.Interaction, button: discord.ui.Button):
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

    @discord.ui.button(label="🗑️ Vider le Cache Produits", style=discord.ButtonStyle.secondary, row=1)
    async def clear_cache(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.bot.product_cache = {}
        await interaction.response.send_message("✅ Cache de produits en mémoire vidé. Il sera rechargé au prochain `/check` ou à la prochaine tâche.", ephemeral=True)

    @discord.ui.button(label="📨 Tester l'Envoi d'E-mail", style=discord.ButtonStyle.danger, row=1)
    async def test_email(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Ouvre la fenêtre modale pour demander l'adresse e-mail
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


class ProductView(discord.ui.View):
    def __init__(self, products: List[dict], category: str = None):
        super().__init__(timeout=300)
        self.products = products
        self.current_index = 0
        self.category = category
        
        # On pré-charge le nombre d'avis
        self.review_counts = self._get_review_counts()
        
        # On ajoute les boutons fixes
        self.add_item(self.PrevButton())
        self.add_item(self.NextButton())
        self.add_item(self.ShowReviewsButton())
        
        # On met à jour l'état de tous les boutons
        self.update_ui_elements()

    def _get_review_counts(self) -> dict:
        product_names = [p['name'] for p in self.products]
        if not product_names: return {}
        
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        placeholders = ','.join('?' for _ in product_names)
        cursor.execute(f"SELECT product_name, COUNT(id) FROM ratings WHERE product_name IN ({placeholders}) AND comment IS NOT NULL AND TRIM(comment) != '' GROUP BY product_name", product_names)
        counts = {name: count for name, count in cursor.fetchall()}
        conn.close()
        return counts
    
    def update_ui_elements(self):
        product = self.products[self.current_index]

        # Navigation
        prev_button = discord.utils.get(self.children, custom_id="prev_product")
        next_button = discord.utils.get(self.children, custom_id="next_product")
        if prev_button: prev_button.disabled = self.current_index == 0
        if next_button: next_button.disabled = self.current_index >= len(self.products) - 1

        # Téléchargements
        for item in [c for c in self.children if hasattr(c, "is_download_button")]: self.remove_item(item)
        stats = product.get('stats', {})
        for key, value in stats.items():
            if isinstance(value, str) and ("lab" in key.lower() or "terpen" in key.lower()) and value.startswith("http"):
                label = "Télécharger Lab Test" if "lab" in key.lower() else "Télécharger Terpènes"
                emoji = "🧪" if "lab" in key.lower() else "🌿"
                self.add_item(self.DownloadButton(label, value, emoji))

        # Avis
        reviews_button = discord.utils.get(self.children, custom_id="show_reviews_button")
        if reviews_button:
            review_count = self.review_counts.get(product.get('name'), 0)
            reviews_button.label = f"💬 Avis Clients ({review_count})"
            reviews_button.disabled = (review_count == 0)

    def get_category_emoji(self):
        if self.category == "weed": return "🍃"
        if self.category == "hash": return "🍫"
        if self.category == "box": return "📦"
        if self.category == "accessoire": return "🛠️"
        return ""

    def create_embed(self) -> discord.Embed:
        # ... (cette fonction est correcte et reste inchangée) ...
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
        embed.add_field(name="Prix", value=price_text, inline=True)
        if not product.get('is_sold_out') and product.get('stats', {}).get('Stock'):
            embed.add_field(name="Stock", value=f"{product['stats']['Stock']}", inline=True)
        stats = product.get('stats', {})
        char_lines = []
        ignore_keys = ["pdf", "lab", "terpen", "stock", "description"]
        ignore_values = ["livraison", "offert", "derniers", "grammes", "lots"]
        for k, v in stats.items():
            k_lower, v_str = k.lower(), str(v)
            v_lower = v_str.lower()
            if (any(key in k_lower for key in ignore_keys) or v_str.startswith(("http", "gid://")) or any(val in v_lower for val in ignore_values)):
                continue
            if "effet" in k_lower: char_lines.append(f"**Effet :** {v_str}")
            elif "gout" in k_lower: char_lines.append(f"**Goût :** {v_str}")
            elif "cbd" in k_lower: char_lines.append(f"**CBD :** {v_str}")
            elif "thc" in k_lower: char_lines.append(f"**THC :** {v_str}")
            else: char_lines.append(f"**{k.strip().capitalize()} :** {v_str}")
        if char_lines:
            embed.add_field(name="Caractéristiques", value="\n".join(char_lines), inline=False)
        embed.add_field(name="\u200b", value=f"**[Voir la fiche produit sur le site]({product.get('product_url', CATALOG_URL)})**", inline=False)
        embed.set_footer(text=f"Produit {self.current_index + 1} sur {len(self.products)}")
        return embed
        
    async def update_message(self, interaction: discord.Interaction):
        self.update_ui_elements()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

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
                conn = sqlite3.connect(DB_FILE)
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
            import requests
            response = await asyncio.to_thread(requests.post, api_url, json=payload, timeout=10)
            response.raise_for_status()
            avg_score = sum(scores.values()) / len(scores)

            def _get_count(user_id):
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("SELECT COUNT(id) FROM ratings WHERE user_id = ?", (user_id,))
                count = c.fetchone()[0]
                conn.close()
                return count
            
            new_rating_count = await asyncio.to_thread(_get_count, interaction.user.id)
            await self.cog_instance.update_loyalty_roles(interaction.guild, interaction.user, new_rating_count)


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
                    conn = sqlite3.connect(DB_FILE)
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
            embed = discord.Embed(title=f"Graphique Radar pour {product_name}", description="Moyenne des notes de la communauté.", color=discord.Color.green()).set_image(url="attachment://radar_chart.png")
            await interaction.followup.send(embed=embed, file=file, ephemeral=True)
            os.remove(chart_path)
        else:
            await interaction.followup.send("Impossible de générer le graphique (pas assez de données ?).", ephemeral=True)

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
            conn = sqlite3.connect(DB_FILE); c=conn.cursor(); c.execute("DELETE FROM ratings WHERE user_id=?",(uid,)); conn.commit(); conn.close()
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
class ConfigCog(commands.GroupCog, name="config", description="Gère la configuration du bot LaFoncedalle."):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()

    # --- On définit un SOUS-GROUPE pour les commandes "set" ---
    set_group = app_commands.Group(name="set", description="Définit un paramètre de configuration.")

    # --- COMMANDE D'AFFICHAGE (/config view) ---
    @app_commands.command(name="view", description="[STAFF] Affiche la configuration actuelle du bot pour ce serveur.")
    @app_commands.check(is_staff_or_owner)
    async def view_config(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        staff_role_id = await config_manager.get_state(guild.id, 'staff_role_id')
        mention_role_id = await config_manager.get_state(guild.id, 'mention_role_id')
        menu_channel_id = await config_manager.get_state(guild.id, 'menu_channel_id')
        selection_channel_id = await config_manager.get_state(guild.id, 'selection_channel_id')

        def format_setting(item_id, item_type, is_critical=False):
            if not item_id: return f"{'❌' if is_critical else '⚠️'} `Non défini`"
            item = guild.get_role(item_id) if item_type == 'role' else guild.get_channel(item_id)
            if item: return f"✅ {item.mention}"
            return f"{'❌' if is_critical else '⚠️'} `Introuvable (ID: {item_id})`"

        staff_role_text = format_setting(staff_role_id, 'role')
        mention_role_text = format_setting(mention_role_id, 'role')
        menu_channel_text = format_setting(menu_channel_id, 'channel', is_critical=True)
        selection_channel_text = format_setting(selection_channel_id, 'channel')

        embed = discord.Embed(
            title=f"Configuration de {self.bot.user.name}",
            description=f"Voici les paramètres actuels pour le serveur **{guild.name}**.",
            color=discord.Color.blue(), timestamp=datetime.now(paris_tz)
        )
        embed.add_field(name="📌 Rôles", value=f"**Staff :** {staff_role_text}\n**Mention Nouveautés :** {mention_role_text}", inline=False)
        embed.add_field(name="📺 Salons", value=f"**Menu Principal :** {menu_channel_text}\n**Sélection de la Semaine :** {selection_channel_text}", inline=False)
        embed.set_footer(text="Utilisez /config set <role|salon> ou /config loyalty pour gérer les rôles.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # --- COMMANDE /config set role ---
    @set_group.command(name="role", description="[STAFF] Configure un rôle spécifique (staff, mentions).")
    @app_commands.check(is_staff_or_owner)
    @app_commands.describe(parametre="Le type de rôle à configurer.", valeur="Le rôle à assigner.")
    @app_commands.choices(parametre=[
        Choice(name="Staff", value="staff_role_id"),
        Choice(name="Mention Nouveautés", value="mention_role_id"),
    ])
    async def set_role(self, interaction: discord.Interaction, parametre: Choice[str], valeur: discord.Role):
        await config_manager.update_state(interaction.guild.id, parametre.value, valeur.id)
        await log_user_action(interaction, f"a configuré le paramètre '{parametre.name}' sur {valeur.name}")
        await interaction.response.send_message(f"✅ Le paramètre **{parametre.name}** est maintenant assigné à {valeur.mention}.", ephemeral=True)

    # --- COMMANDE /config set salon ---
    @set_group.command(name="salon", description="[STAFF] Configure un salon spécifique (menu, sélection).")
    @app_commands.check(is_staff_or_owner)
    @app_commands.describe(parametre="Le type de salon à configurer.", valeur="Le salon à assigner.")
    @app_commands.choices(parametre=[
        Choice(name="Menu Principal", value="menu_channel_id"),
        Choice(name="Sélection de la Semaine", value="selection_channel_id"),
    ])
    async def set_salon(self, interaction: discord.Interaction, parametre: Choice[str], valeur: discord.TextChannel):
        await config_manager.update_state(interaction.guild.id, parametre.value, valeur.id)
        await log_user_action(interaction, f"a configuré le paramètre '{parametre.name}' sur {valeur.name}")
        await interaction.response.send_message(f"✅ Le paramètre **{parametre.name}** est maintenant assigné à {valeur.mention}.", ephemeral=True)

    
    loyalty_group = app_commands.Group(name="loyalty", description="Gère les rôles de fidélité.")
    
    @loyalty_group.command(name="view", description="[STAFF] Affiche la configuration des rôles de fidélité.")
    @app_commands.check(is_staff_or_owner)
    async def view_loyalty(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        loyalty_config = config_manager.get_config("loyalty_roles", {})
        
        embed = create_styled_embed("Configuration des Rôles de Fidélité", "Voici les paliers actuellement configurés.", color=discord.Color.gold())
        
        if not loyalty_config:
            embed.description = "Aucun rôle de fidélité n'est configuré.\nUtilisez `/config loyalty set` pour en ajouter un."
        else:
            sorted_roles = sorted(loyalty_config.items(), key=lambda item: item[1].get('threshold', 0))
            for name, data in sorted_roles:
                role_id = data.get('id')
                role = interaction.guild.get_role(int(role_id)) if role_id else None
                role_mention = role.mention if role else f"⚠️ Rôle introuvable (ID: {role_id})"
                threshold = data.get('threshold', 'N/A')
                emoji = data.get('emoji', '')
                embed.add_field(
                    name=f"{emoji} {data.get('name', name.capitalize())}",
                    value=f"**Rôle :** {role_mention}\n**Seuil :** `{threshold} notes`",
                    inline=False
                )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @loyalty_group.command(name="set", description="[STAFF] Ajoute ou modifie un palier de rôle de fidélité.")
    @app_commands.check(is_staff_or_owner)
    @app_commands.describe(
        tier_name="Le nom du palier (ex: 'Fidèle', 'Adepte').",
        role="Le rôle Discord à assigner pour ce palier.",
        threshold="Le nombre de notes requis pour atteindre ce palier.",
        emoji="L'émoji à afficher pour ce badge (ex: 💚)."
    )
    async def set_loyalty(self, interaction: discord.Interaction, tier_name: str, role: discord.Role, threshold: app_commands.Range[int, 1, 1000], emoji: str):
        await interaction.response.defer(ephemeral=True)
        
        tier_key = tier_name.lower().strip().replace(" ", "_")
        
        loyalty_config = config_manager.get_config("loyalty_roles", {})
        loyalty_config[tier_key] = {
            "id": str(role.id),
            "threshold": threshold,
            "name": tier_name,
            "emoji": emoji
        }
        
        await config_manager.update_config("loyalty_roles", loyalty_config)
        await interaction.followup.send(f"✅ Le palier de fidélité **{tier_name}** a été configuré avec le rôle {role.mention} à partir de **{threshold}** notes.", ephemeral=True)

# -- COMMANDES --
class SlashCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    async def update_loyalty_roles(self, guild: discord.Guild, member: discord.Member, rating_count: int):
        """Met à jour les rôles de fidélité d'un membre."""
        if not guild or not member: return

        loyalty_config = config_manager.get_config("loyalty_roles", {})
        if not loyalty_config: return

        sorted_roles = sorted(loyalty_config.values(), key=lambda r: r.get('threshold', 0), reverse=True)
        
        target_role_id_str = None
        for role_data in sorted_roles:
            if rating_count >= role_data.get('threshold', 0):
                target_role_id_str = role_data.get('id')
                break
        
        target_role_id = int(target_role_id_str) if target_role_id_str else None
        all_loyalty_role_ids = {int(r['id']) for r in loyalty_config.values() if r.get('id')}
        
        roles_to_add, roles_to_remove = [], []

        if target_role_id:
            target_role = guild.get_role(target_role_id)
            if target_role and target_role not in member.roles:
                roles_to_add.append(target_role)

        for role_id in all_loyalty_role_ids:
            if role_id != target_role_id:
                role_to_check = guild.get_role(role_id)
                if role_to_check and role_to_check in member.roles:
                    roles_to_remove.append(role_to_check)
        
        try:
            if roles_to_add:
                await member.add_roles(*roles_to_add, reason="Mise à jour automatique du rôle de fidélité")
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove, reason="Mise à jour automatique du rôle de fidélité")
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
                message = "🤔 **Aucun produit à noter pour le moment.**\nIl se peut que tu n'aies pas encore de commande enregistrée ou que tu aies déjà noté tous tes produits achetés."
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
            conn = sqlite3.connect(DB_FILE)
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
                conn = sqlite3.connect(DB_FILE)
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

        try:
            import requests
            res = await asyncio.to_thread(requests.get, f"{APP_URL}/", timeout=5)
            res.raise_for_status()
            status_text += f"✅ **API Flask :** `En ligne ({res.status_code})`\n"
        except Exception:
            status_text += f"❌ **API Flask :** `Injoignable ou erreur`\n"
        
        embed.add_field(name="🌐 Connectivité", value=status_text, inline=False)
        
        # --- 2. Tâches Programmées (NOUVELLE SECTION) ---
        tasks_text = ""
        # Accéder aux tâches enregistrées dans le fichier principal du bot
        from catalogue_final import scheduled_check, post_weekly_ranking, scheduled_selection, daily_role_sync

        tasks_to_check = {
            "Vérification Menu": scheduled_check,
            "Classement Hebdo": post_weekly_ranking,
            "Sélection Semaine": scheduled_selection,
            "Synchro Rôles": daily_role_sync
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
            item = get_method(int(item_id))
            if item: return f"✅ {item.mention}"
            return f"{'❌' if is_critical else '⚠️'} `Introuvable (ID: {item_id})`"

        staff_role_id = await config_manager.get_state(guild.id, 'staff_role_id')
        config_text += f"**Rôle Staff :** {format_setting(staff_role_id, guild.get_role)}\n"
        
        mention_role_id = await config_manager.get_state(guild.id, 'mention_role_id')
        config_text += f"**Rôle Mention :** {format_setting(mention_role_id, guild.get_role)}\n"

        menu_channel_id = await config_manager.get_state(guild.id, 'menu_channel_id')
        config_text += f"**Salon Menu :** {format_setting(menu_channel_id, guild.get_channel, is_critical=True)}\n"

        selection_channel_id = await config_manager.get_state(guild.id, 'selection_channel_id')
        config_text += f"**Salon Sélection :** {format_setting(selection_channel_id, guild.get_channel)}\n"
        
        embed.add_field(name="🔧 Configuration Locale", value=config_text, inline=False)
        
        # --- 4. & 5. Cache et Base de Données ---
        if self.bot.product_cache:
            products_count = len(self.bot.product_cache.get('products', []))
            cache_age_ts = self.bot.product_cache.get('timestamp', 0)
            embed.add_field(name="🗃️ Cache de Produits", value=f"✅ `Chargé`\n**Produits :** `{products_count}`\n**MàJ :** <t:{int(cache_age_ts)}:R>", inline=True)
        else:
            embed.add_field(name="🗃️ Cache de Produits", value="❌ `Vide`", inline=True)
            
        try:
            conn = sqlite3.connect(DB_FILE)
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

    @app_commands.command(name="graph", description="[STAFF] Voir un graphique radar pour un produit")
    @app_commands.check(is_staff_or_owner)
    async def graph(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await log_user_action(interaction, "a demandé un graphique.")
        def fetch_products():
            conn = sqlite3.connect(DB_FILE); c = conn.cursor()
            c.execute("SELECT DISTINCT product_name FROM ratings")
            products = [row[0] for row in c.fetchall()]
            conn.close()
            return products
        products = await asyncio.to_thread(fetch_products)
        if not products:
            await interaction.followup.send("Aucun produit n'a encore été noté.", ephemeral=True)
            return
        view = ProductSelectViewForGraph(products, self.bot)
        await interaction.followup.send("Sélectionnez un produit :", view=view, ephemeral=True)

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
            conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row; c = conn.cursor()
            
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

async def setup(bot: commands.Bot):
    await bot.add_cog(SlashCommands(bot))
    await bot.add_cog(ConfigCog(bot))