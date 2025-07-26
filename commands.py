import discord
from discord.ext import commands
from discord import app_commands
import json, time, sqlite3, traceback, asyncio, os
from typing import List, Optional
from datetime import datetime, timedelta
from profil_image_generator import create_profile_card
from shared_utils import *

# --- Logique des permissions ---
async def is_staff_or_owner(interaction: discord.Interaction) -> bool:
    if await interaction.client.is_owner(interaction.user): return True
    staff_role_id = await config_manager.get_state('staff_role_id', STAFF_ROLE_ID)
    if not staff_role_id: return False
    try: staff_role_id_int = int(staff_role_id)
    except (ValueError, TypeError): return False
    return any(role.id == staff_role_id_int for role in interaction.user.roles)

# --- VUES ET MODALES ---

# VUE POUR PAGINER LES NOTES (VERSION AMÉLIORÉE ++)
class RatingsPaginatorView(discord.ui.View):
    def __init__(self, target_user, user_ratings, items_per_page=1):
        super().__init__(timeout=180)
        self.target_user, self.user_ratings, self.items_per_page, self.current_page = target_user, user_ratings, items_per_page, 0
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
        p_name, p_details = rating['product_name'], self.product_map.get(rating['product_name'].strip().lower(), {})
        date = datetime.fromisoformat(rating['rating_timestamp']).strftime('%d/%m/%Y')
        embed = discord.Embed(title=f"Avis sur : {p_name}", url=p_details.get('product_url'), color=discord.Color.green())
        if p_details.get('image'): embed.set_thumbnail(url=p_details['image'])
        embed.add_field(name="Description du Produit", value=p_details.get('detailed_description', 'N/A')[:1024], inline=False)
        embed.add_field(name="Prix", value=p_details.get('price', 'N/A'), inline=True)
        avg = sum(rating.get(s, 0) for s in ['visual_score', 'smell_score', 'touch_score', 'taste_score', 'effects_score']) / 5
        embed.add_field(name="Note Globale Donnée", value=f"**{avg:.2f} / 10**", inline=True)
        notes = (f"👀 Visuel: `{rating.get('visual_score', 'N/A')}`\n👃 Odeur: `{rating.get('smell_score', 'N/A')}`\n"
                 f"🤏 Toucher: `{rating.get('touch_score', 'N/A')}`\n👅 Goût: `{rating.get('taste_score', 'N/A')}`\n"
                 f"🧠 Effets: `{rating.get('effects_score', 'N/A')}`")
        embed.add_field(name=f"Notes Détaillées de {self.target_user.display_name}", value=notes, inline=False)
        if rating.get('comment'): embed.add_field(name="💬 Commentaire", value=f"```{rating['comment']}```", inline=False)
        if self.total_pages >= 0: embed.set_footer(text=f"Note {self.current_page + 1} sur {len(self.user_ratings)}")
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
        paginator = RatingsPaginatorView(self.target_user, self.user_ratings)
        await i.response.send_message(embed=paginator.create_embed(), view=paginator, ephemeral=True)

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
        
            
class ProductView(discord.ui.View):
    def __init__(self, products: List[dict], category: str = None):
        super().__init__(timeout=300)
        self.products = products
        self.current_index = 0
        self.category = category
        self.update_buttons()
        self.update_download_buttons()

    def update_buttons(self):
        nav_buttons = [item for item in self.children if isinstance(item, discord.ui.Button) and not hasattr(item, "is_download_button")]
        if len(nav_buttons) >= 2:
            nav_buttons[0].disabled = self.current_index == 0
            nav_buttons[1].disabled = self.current_index >= len(self.products) - 1

    def update_download_buttons(self):
        items_to_remove = [item for item in self.children if hasattr(item, "is_download_button")]
        for item in items_to_remove:
            self.remove_item(item)
            
        product = self.products[self.current_index]
        stats = product.get('stats', {})

        for key, value in stats.items():
            if not value or not isinstance(value, str): continue
            key_lower = key.lower()
            
            if ("lab" in key_lower or "terpen" in key_lower) and value.startswith("http"):
                label = "Télécharger Lab Test" if "lab" in key_lower else "Télécharger Terpènes"
                emoji = "🧪" if "lab" in key_lower else "🌿"
                self.add_item(self.DownloadButton(label, value, emoji))

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
            
            if (any(key in k_lower for key in ignore_keys) or 
                v_str.startswith(("http", "gid://")) or 
                any(val in v_lower for val in ignore_values)):
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
        self.update_buttons()
        self.update_download_buttons()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="⬅️ Précédent", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_index > 0: self.current_index -= 1
        await self.update_message(interaction)

    @discord.ui.button(label="Suivant ➡️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_index < len(self.products) - 1: self.current_index += 1
        await self.update_message(interaction)

    class DownloadButton(discord.ui.Button):
        def __init__(self, label, url, emoji=None):
            super().__init__(label=label, style=discord.ButtonStyle.link, url=url, emoji=emoji)
            self.is_download_button = True

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

class RatingModal(discord.ui.Modal, title="Noter un produit"):
    def __init__(self, product_name: str, user: discord.User):
        super().__init__(timeout=None)
        self.product_name, self.user = product_name, user
        self.visual_score = discord.ui.TextInput(label="👀 Note Visuel /10", placeholder="Ex: 8.5", required=True)
        self.smell_score = discord.ui.TextInput(label="👃🏼 Note Odeur /10", placeholder="Ex: 9", required=True)
        self.touch_score = discord.ui.TextInput(label="🤏🏼 Note Toucher /10", placeholder="Ex: 7", required=True)
        self.taste_score = discord.ui.TextInput(label="👅 Note Goût /10", placeholder="Ex: 8", required=True)
        self.effects_score = discord.ui.TextInput(label="🧠 Note Effets /10", placeholder="Ex: 9.5", required=True)
        self.comment = discord.ui.TextInput(label="💬 Ton commentaire (optionnel)", style=discord.TextStyle.paragraph, placeholder="Un goût incroyable...", required=False, max_length=500)
        for item in [self.visual_score, self.smell_score, self.touch_score, self.taste_score, self.effects_score, self.comment]:
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        scores, comment_text = {}, self.comment.value or None
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
        payload = {
            "user_id": self.user.id,
            "user_name": str(self.user),
            "product_name": self.product_name,
            "scores": scores,
            "comment": comment_text
        }
        
        try:
            import requests
            response = await asyncio.to_thread(requests.post, api_url, json=payload, timeout=10)
            response.raise_for_status()  # Lève une exception si l'API renvoie une erreur (4xx ou 5xx)

            avg_score = sum(scores.values()) / len(scores)
            await interaction.followup.send(f"✅ Merci ! Votre note de **{avg_score:.2f}/10** pour **{self.product_name}** a été enregistrée.", ephemeral=True)

        except Exception as e:
            Logger.error(f"Erreur API lors de la soumission de la note : {e}")
            await interaction.followup.send("❌ Une erreur est survenue lors de l'enregistrement de votre note. Le staff a été notifié.", ephemeral=True)


# D'abord, la vue
class NotationProductSelectView(discord.ui.View):
    def __init__(self, products: list, user: discord.User):
        super().__init__(timeout=180)
        # On stocke la liste complète des produits pour plus tard
        self.products = products 
        if products:
            # On passe la liste complète au Select
            self.add_item(self.ProductSelect(products, user))

    # Ensuite, le menu déroulant (Select) à l'intérieur de la vue
    class ProductSelect(discord.ui.Select):
        def __init__(self, products: list, user: discord.User):
            self.user = user
            
            # [CORRECTION] On tronque à la fois le label ET la value à 100 caractères
            options = [
                discord.SelectOption(label=p[:100], value=p[:100]) 
                for p in products[:25] # On ne peut afficher que 25 options max
            ]
            
            if not options:
                options = [discord.SelectOption(label="Aucun produit à noter", value="disabled", default=True)]
            
            super().__init__(placeholder="Choisissez un produit à noter...", options=options)
        
        async def callback(self, interaction: discord.Interaction):
            if not self.values or self.values[0] == "disabled":
                await interaction.response.edit_message(content="Aucun produit sélectionné.", view=None)
                return
            
            # On récupère la valeur tronquée qui a été sélectionnée
            selected_value = self.values[0]
            
            # On retrouve le nom complet du produit en comparant le début des noms
            # de la liste originale (stockée dans la vue) avec la valeur tronquée.
            full_product_name = next(
                (p for p in self.view.products if p.startswith(selected_value)),
                selected_value
            )
            
            # On envoie le nom complet au Modal pour l'enregistrement
            await interaction.response.send_modal(RatingModal(full_product_name, self.user))

class TopRatersPaginatorView(discord.ui.View):
    def __init__(self, top_raters, guild, items_per_page=5): # On met un peu moins de noteurs par page pour la lisibilité
        super().__init__(timeout=180)
        self.top_raters = top_raters
        self.guild = guild
        self.items_per_page = items_per_page
        self.current_page = 0
        self.total_pages = (len(self.top_raters) - 1) // self.items_per_page
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
        page_raters = self.top_raters[start_index:end_index]
        
        embed = discord.Embed(title="🏆 Top des Noteurs", description="Classement basé sur le nombre de notes uniques.", color=discord.Color.gold())
        
        for i, rater_data in enumerate(page_raters):
            user_id = rater_data.get('user_id')
            last_user_name = rater_data.get('last_user_name')
            rating_count = rater_data.get('rating_count')
            global_average = rater_data.get('global_avg', 0)
            best_product = rater_data.get('best_rated_product', 'N/A') # On récupère le produit préféré
            
            rank = start_index + i + 1
            member = self.guild.get_member(user_id)
            name = member.mention if member else f"{last_user_name} (parti)"
            
            # --- NOUVEL AFFICHAGE ---
            value_text = (
                f"> **Notes :** `{rating_count}` | **Moyenne :** `{global_average:.2f}/10`\n"
                f"> **Produit Préféré :** ⭐ *{best_product}*"
            )
            
            embed.add_field(name=f"#{rank} - {name}", value=value_text, inline=False)
            
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.total_pages + 1}")
        return embed
            
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
        embed = discord.Embed(title="📈 Classement Général des Produits", description="Moyenne de tous les produits notés par la communauté.", color=discord.Color.blue())
        for i, (name, avg_score, count) in enumerate(page_ratings):
            rank = start_index + i + 1
            product_info = self.product_map.get(name.strip().lower())
            value_str = f"**Note : {avg_score:.2f}/10** ({count} avis)"
            if product_info and product_info.get('product_url'):
                value_str += f" - [Voir la fiche]({product_info['product_url']})"
            embed.add_field(name=f"#{rank} - {name}", value=value_str, inline=False)
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
    def __init__(self, contact_info):
        super().__init__(timeout=120)
        if contact_info.get("site"): self.add_item(discord.ui.Button(label="Boutique", style=discord.ButtonStyle.link, url=contact_info["site"], emoji=LFONCEDALLE_EMOJI))
        if contact_info.get("instagram"): self.add_item(discord.ui.Button(label="Instagram", style=discord.ButtonStyle.link, url=contact_info["instagram"], emoji=INSTAGRAM_EMOJI))
        if contact_info.get("telegram"): self.add_item(discord.ui.Button(label="Telegram", style=discord.ButtonStyle.link, url=contact_info["telegram"], emoji=TELEGRAM_EMOJI))
        if contact_info.get("tiktok"): self.add_item(discord.ui.Button(label="TikTok", style=discord.ButtonStyle.link, url=contact_info["tiktok"], emoji=TIKTOK_EMOJI))

# --- COMMANDES ---

class SlashCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    config_group = app_commands.Group(name="config", description="Commandes de configuration du bot (Staff uniquement)")

    @config_group.command(name="salon_menu", description="Définit le salon où le menu automatique sera publié.")
    @app_commands.check(is_staff_or_owner)
    @app_commands.describe(salon="Le salon textuel à utiliser pour le menu.")
    async def set_menu_channel(self, interaction: discord.Interaction, salon: discord.TextChannel):
        await config_manager.update_state('menu_channel_id', salon.id)
        await interaction.response.send_message(f"✅ Le salon pour le menu a été défini sur {salon.mention}.", ephemeral=True)

    @config_group.command(name="salon_selection", description="Définit le salon pour la sélection de la semaine.")
    @app_commands.check(is_staff_or_owner)
    @app_commands.describe(salon="Le salon textuel à utiliser.")
    async def set_selection_channel(self, interaction: discord.Interaction, salon: discord.TextChannel):
        await config_manager.update_state('selection_channel_id', salon.id)
        await interaction.response.send_message(f"✅ Le salon pour la sélection de la semaine a été défini sur {salon.mention}.", ephemeral=True)

    @config_group.command(name="role_staff", description="Définit le rôle qui peut utiliser les commandes staff.")
    @app_commands.check(is_staff_or_owner)
    @app_commands.describe(role="Le rôle à définir comme staff.")
    async def set_staff_role(self, interaction: discord.Interaction, role: discord.Role):
        await config_manager.update_state('staff_role_id', role.id)
        await interaction.response.send_message(f"✅ Le rôle staff a été défini sur {role.mention}.", ephemeral=True)
    
    @config_group.command(name="role_mention", description="Définit le rôle à mentionner lors des mises à jour du menu.")
    @app_commands.check(is_staff_or_owner)
    @app_commands.describe(role="Le rôle à mentionner.")
    async def set_mention_role(self, interaction: discord.Interaction, role: discord.Role):
        await config_manager.update_state('mention_role_id', role.id)
        await interaction.response.send_message(f"✅ Le rôle à mentionner a été défini sur {role.mention}.", ephemeral=True)

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
        # [CORRECTION] Cette ligne DOIT être la toute première pour éviter le timeout de 3 secondes.
        await interaction.response.defer(ephemeral=True, thinking=True)
        await log_user_action(interaction, "a initié la commande /noter")
        try:
            def fetch_purchased_products():
                import requests
                try:
                    res = requests.get(f"{APP_URL}/api/get_purchased_products/{interaction.user.id}", timeout=10)
                    if res.status_code == 404: return None
                    res.raise_for_status()
                    return res.json().get("products", [])
                except Exception as e:
                    Logger.error(f"Erreur API get_purchased_products: {e}"); return []
            
            purchased_products = await asyncio.to_thread(fetch_purchased_products)
            Logger.info(f"Produits achetés trouvés pour {interaction.user}: {purchased_products}")

            if purchased_products is None:
                await interaction.followup.send("Ton compte Discord n'est pas lié. Utilise `/lier_compte`.", ephemeral=True); return
            if not purchased_products:
                await interaction.followup.send("Aucun produit trouvé dans ton historique d'achats pouvant être noté.", ephemeral=True); return
            
            view = NotationProductSelectView(purchased_products, interaction.user)
            await interaction.followup.send("Veuillez choisir un produit à noter :", view=view, ephemeral=True)
        except Exception as e:
            Logger.error(f"Erreur majeure dans la commande /noter : {e}"); traceback.print_exc()
            await interaction.followup.send("❌ Oups, une erreur est survenue lors de la préparation du menu de notation.", ephemeral=True)

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

    @app_commands.command(name="classement_general", description="Affiche la moyenne de tous les produits notés.")
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

    # --- Reste des commandes (inchangé) ---
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

    @app_commands.command(name="contacts", description="Afficher les informations de contact de LaFoncedalle")
    async def contacts(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await log_user_action(interaction, "a demandé les contacts.")
        contact_info = config_manager.get_config("contact_info", {})
        embed = create_styled_embed(f"{SUCETTE_EMOJI} LaFoncedalle - Contacts", 
            contact_info.get("description", "Contactez-nous !"), 
            color=discord.Color.blue()
        )
        view = ContactButtonsView(contact_info)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    # Dans commands.py, à l'intérieur de la classe SlashCommands

    @app_commands.command(name="debug", description="[STAFF] Force la republication du menu et synchronise les commandes.")
    @app_commands.check(is_staff_or_owner)
    async def debug(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        Logger.info(f"Débogage forcé demandé par {interaction.user}...")

        # --- NOUVELLE ÉTAPE : SYNCHRONISATION DES COMMANDES ---
        try:
            synced = await self.bot.tree.sync()
            Logger.success(f"{len(synced)} commandes synchronisées avec Discord.")
            await interaction.followup.send(f"✅ {len(synced)} commandes synchronisées.", ephemeral=True)
        except Exception as e:
            Logger.error(f"Échec de la synchronisation des commandes : {e}")
            await interaction.followup.send("⚠️ Échec de la synchronisation des commandes.", ephemeral=True)

        # --- ANCIENNE LOGIQUE : REPUBLICATION DU MENU ---
        Logger.info("Publication forcée du menu...")
        try:
            updates_found = await self.bot.check_for_updates(self.bot, force_publish=True)
            if updates_found:
                await interaction.followup.send("✅ Menu mis à jour et republié avec mention.", ephemeral=True)
            else:
                await interaction.followup.send("✅ Tentative de republication effectuée (le menu était déjà à jour).", ephemeral=True)
        except Exception as e:
            Logger.error(f"Erreur critique lors de /debug : {e}")
            traceback.print_exc()
            await interaction.followup.send("❌ Une erreur est survenue lors de la republication du menu.", ephemeral=True)

    @app_commands.command(name="check", description="Vérifie si de nouveaux produits sont disponibles (cooldown 12h).")
    async def check(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        cooldown_period = timedelta(hours=12)
        last_check_iso = await config_manager.get_state('last_check_command_timestamp')
        if last_check_iso:
            time_since = datetime.utcnow() - datetime.fromisoformat(last_check_iso)
            if time_since < cooldown_period:
                next_time = datetime.fromisoformat(last_check_iso) + cooldown_period
                await interaction.followup.send(f"⏳ Prochaine vérification possible <t:{int(next_time.timestamp())}:R>.", ephemeral=True)
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
            await interaction.followup.send("❌ Oups, une erreur est survenue.", ephemeral=True)

    @app_commands.command(name="graph", description="Voir un graphique radar pour un produit")
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
            import requests
            conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row; c = conn.cursor()
            c.execute("SELECT * FROM ratings WHERE user_id = ? ORDER BY rating_timestamp DESC", (user_id,))
            user_ratings = [dict(row) for row in c.fetchall()]
            c.execute("""
                WITH UserAverageNotes AS (
                    SELECT user_id, (COALESCE(visual_score, 0) + COALESCE(smell_score, 0) + COALESCE(touch_score, 0) + COALESCE(taste_score, 0) + COALESCE(effects_score, 0)) / 5.0 AS avg_note
                    FROM ratings
                ),
                AllRanks AS (
                    SELECT user_id, COUNT(user_id) as rating_count, AVG(avg_note) as global_avg, MIN(avg_note) as min_note, MAX(avg_note) as max_note,
                           RANK() OVER (ORDER BY COUNT(user_id) DESC, AVG(avg_note) DESC) as user_rank
                    FROM UserAverageNotes GROUP BY user_id
                )
                SELECT user_rank, rating_count, global_avg, min_note, max_note
                FROM AllRanks WHERE user_id = ?
            """, (user_id,))
            stats_row = c.fetchone()
            user_stats = {'rank': 'N/C', 'count': 0, 'avg': 0, 'min_note': 0, 'max_note': 0}
            if stats_row:
                user_stats.update(dict(zip(stats_row.keys(), stats_row)))

            one_month_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
            c.execute("SELECT user_id FROM ratings WHERE rating_timestamp >= ? GROUP BY user_id ORDER BY COUNT(id) DESC LIMIT 3", (one_month_ago,))
            top_3_monthly_ids = [row['user_id'] for row in c.fetchall()]
            user_stats['is_top_3_monthly'] = user_id in top_3_monthly_ids
            conn.close()
            
            shopify_data = {}
            api_url = f"{APP_URL}/api/get_purchased_products/{user_id}"
            try:
                res = requests.get(api_url, timeout=10)
                if res.ok:
                    try: shopify_data = res.json()
                    except requests.exceptions.JSONDecodeError:
                        Logger.error(f"L'API Flask a renvoyé une réponse non-JSON pour {user_id}. Contenu: {res.text[:200]}")
                else: Logger.warning(f"L'API Flask a retourné un statut {res.status_code} pour {user_id}.")
            except requests.exceptions.RequestException as e: Logger.error(f"API Flask inaccessible pour {user_id}: {e}")
            
            return user_stats, user_ratings, shopify_data

        try:
            user_stats, user_ratings, shopify_data = await asyncio.to_thread(_fetch_user_data_sync, target_user.id)

            if user_stats['count'] == 0 and not shopify_data.get('purchase_count', 0) > 0:
                await interaction.followup.send("Cet utilisateur n'a aucune activité enregistrée.", ephemeral=True); return

            embed = discord.Embed(title=f"Profil de {target_user.display_name}", color=target_user.color)
            embed.set_thumbnail(url=target_user.display_avatar.url)

            shop_activity_text = "Compte non lié. Utilisez `/lier_compte`."
            if shopify_data.get('purchase_count', 0) > 0:
                shop_activity_text = (
                    f"**Commandes :** `{shopify_data['purchase_count']}`\n"
                    f"**Total dépensé :** `{shopify_data['total_spent']:.2f} €`"
                )
            embed.add_field(name="🛍️ Activité sur la Boutique", value=shop_activity_text, inline=False)

            discord_activity_text = "Aucune note enregistrée."
            if user_stats.get('count', 0) > 0:
                discord_activity_text = (
                    f"**Classement :** `#{user_stats['rank']}`\n"
                    f"**Nombre de notes :** `{user_stats['count']}`\n"
                    f"**Moyenne des notes :** `{user_stats['avg']:.2f}/10`\n"
                    f"**Note Min/Max :** `{user_stats['min_note']:.2f}` / `{user_stats['max_note']:.2f}`"
                )
                if user_stats.get('is_top_3_monthly'):
                    discord_activity_text += "\n**Badge :** `🏅 Top Noteur du Mois`"
            embed.add_field(name="📝 Activité sur le Discord", value=discord_activity_text, inline=False)
            
            can_reset = membre and membre.id != interaction.user.id and await is_staff_or_owner(interaction)
            view = ProfileView(target_user, user_stats, user_ratings, shopify_data, can_reset, self.bot)

            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            Logger.error(f"Erreur /profil pour {target_user.display_name}: {e}"); traceback.print_exc()
            await interaction.followup.send("❌ Erreur lors de la récupération du profil.", ephemeral=True)
    @app_commands.command(name="lier_force", description="[STAFF] Lie un compte à un e-mail sans vérification.")
    @app_commands.check(is_staff_or_owner)
    @app_commands.describe(membre="...", email="...")
    async def lier_force(self, interaction: discord.Interaction, email: str, membre: Optional[discord.Member] = None):
        await interaction.response.defer(ephemeral=True)
        
        target_user = membre or interaction.user
        
        api_url = f"{APP_URL}/api/force-link"
        payload = {"discord_id": str(target_user.id), "email": email}
        
        try:
            import requests
            response = await asyncio.to_thread(requests.post, api_url, json=payload, timeout=15)
            
            if response.ok:
                await interaction.followup.send(
                    f"✅ **Succès !** Le compte de {target_user.mention} est maintenant lié à l'e-mail `{email}`.",
                    ephemeral=True
                )
            else:
                error_message = response.json().get("error", "Une erreur inconnue est survenue.")
                await interaction.followup.send(f"❌ **Échec :** {error_message}", ephemeral=True)
                
        except Exception as e:
            Logger.error(f"Erreur API /force-link : {e}")
            await interaction.followup.send("❌ Impossible de contacter le service de liaison. Réessayez plus tard.", ephemeral=True)

    @app_commands.command(name="lier_compte", description="Démarre la liaison de ton compte via ton e-mail.")
    @app_commands.describe(email="L'adresse e-mail de tes commandes.")
    async def lier_compte(self, interaction: discord.Interaction, email: str):
        # Le defer est LA PREMIÈRE CHOSE à faire. Toujours.
        await interaction.response.defer(ephemeral=True)
        
        api_url = f"{APP_URL}/api/start-verification"
        payload = {"discord_id": str(interaction.user.id), "email": email}
        
        try:
            import requests # L'import local est parfait
            response = await asyncio.to_thread(requests.post, api_url, json=payload, timeout=15)

            if response.status_code == 200:
                await interaction.followup.send(f"✅ E-mail de vérification envoyé à **{email}**. Utilise `/verifier` avec le code.", ephemeral=True)
            elif response.status_code == 409:
                await interaction.followup.send(f"⚠️ **Déjà lié !** {response.json().get('error', 'Erreur inconnue.')}", ephemeral=True)
            else:
                error_details = response.json().get("error", "une erreur est survenue.")
                await interaction.followup.send(f"❌ **Échec.** Raison : {error_details}", ephemeral=True)
        except Exception as e:
            Logger.error(f"Erreur API /start-verification : {e}")
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
                await interaction.followup.send("🎉 **Félicitations !** Ton compte est maintenant lié. Tu peux utiliser la commande `/noter`.", ephemeral=True)
            else:
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

    @app_commands.command(name="selection", description="Publier la sélection de la semaine (staff uniquement)")
    @app_commands.check(is_staff_or_owner)
    async def selection(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.bot.post_weekly_selection(self.bot)
        await interaction.followup.send("La sélection de la semaine a été publiée.", ephemeral=True)
    
    @app_commands.command(name="promos", description="Affiche toutes les promotions en cours.")
    async def promos(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await log_user_action(interaction, "a demandé les promotions.")
        try:
            def _read_cache_sync():
                try:
                    with open(CACHE_FILE, 'r', encoding='utf-8') as f: return json.load(f)
                except (FileNotFoundError, json.JSONDecodeError): return {}

            site_data = await asyncio.to_thread(_read_cache_sync)
            if not site_data:
                await interaction.followup.send("Les informations sur les promotions ne sont pas disponibles pour le moment.", ephemeral=True); return
            
            promo_products = [p for p in site_data.get('products', []) if p.get('is_promo')]
            # On lit la liste des promotions dynamiques directement depuis le cache
            general_promos = site_data.get('general_promos', [])
            
            paginator = PromoPaginatorView(promo_products, general_promos)
            embed = paginator.create_embed()
            await interaction.followup.send(embed=embed, view=paginator, ephemeral=True)
        except Exception as e:
            Logger.error(f"Erreur dans /promos : {e}"); traceback.print_exc()
            await interaction.followup.send("❌ Erreur lors de la récupération des promotions.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(SlashCommands(bot))