# Fichier : profil_image_generator.py

from PIL import Image, ImageDraw, ImageFont, ImageOps
import requests
import io
import os
import asyncio
import traceback

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

# --- NOUVELLES COULEURS & CONFIGURATION ---
COLORS = {
    "background": "#1E1F22",  # Fond Discord plus doux
    "card": "#2B2D31",        # Fond de la carte
    "white": "#FFFFFF",
    "grey": "#B0B3B8",
    "gold": "#FFD700",
    "progress_bar_bg": "#4E5058",
    "progress_bar_fill": "#5865F2", # Bleu Discord
}

async def create_profile_card(user_data: dict) -> io.BytesIO:
    """Génère une carte de profil visuellement riche avec une police personnalisée et des emojis."""

    def _generate():
        fonts = {}
        # --- NOUVEAUX CHEMINS DE POLICE ---
        # Assurez-vous que ces noms de fichiers correspondent EXACTEMENT à ceux dans votre dossier 'assets'
        font_paths = {
            "bold": os.path.join(ASSETS_DIR, "Gobold Bold.otf"),
            "regular": os.path.join(ASSETS_DIR, "Gobold Regular.otf"),
            "light": os.path.join(ASSETS_DIR, "Gobold Light.otf"),
            "emoji": os.path.join(ASSETS_DIR, "NotoColorEmoji-Regular.ttf"),
        }

        try:
            fonts['name'] = ImageFont.truetype(font_paths['bold'], 65)
            fonts['title'] = ImageFont.truetype(font_paths['bold'], 38)
            fonts['regular_l'] = ImageFont.truetype(font_paths['regular'], 32)
            fonts['regular_s'] = ImageFont.truetype(font_paths['regular'], 28)
            fonts['light'] = ImageFont.truetype(font_paths['light'], 24)
            fonts['emoji'] = ImageFont.truetype(font_paths['emoji'], 30)
            print("SUCCESS [ImageGen]: Toutes les polices personnalisées ont été chargées avec succès.")
        except Exception as e:
            print(f"ERREUR CRITIQUE [ImageGen]: Impossible de charger la police personnalisée. Erreur: {e}")
            print(traceback.format_exc())
            print("INFO [ImageGen]: Utilisation des polices par défaut en secours.")
            # Utiliser des tailles différentes pour la police par défaut pour garder une hiérarchie
            default_font = ImageFont.load_default()
            fonts = {
                'name': ImageFont.load_default(size=50),
                'title': ImageFont.load_default(size=30),
                'regular_l': ImageFont.load_default(size=25),
                'regular_s': ImageFont.load_default(size=22),
                'light': ImageFont.load_default(size=20),
                'emoji': ImageFont.load_default(size=25)
            }

        # --- Création du fond et de la zone de dessin ---
        bg = Image.new("RGBA", (1200, 600), COLORS["background"])
        draw = ImageDraw.Draw(bg)
        
        # Dessiner la carte principale
        draw.rounded_rectangle((40, 40, 1160, 560), fill=COLORS["card"], radius=20)

        # --- FONCTIONS HELPER POUR UN CODE PLUS PROPRE ---
        def draw_text_with_emoji(x, y, emoji, text, font_key='regular_l', color_key='grey'):
            # Dessine l'emoji
            draw.text((x, y), emoji, font=fonts['emoji'], embedded_color=True, anchor="lm")
            emoji_width = draw.textlength(emoji, font=fonts['emoji'])
            # Dessine le texte à côté
            draw.text((x + emoji_width + 15, y), text, font=fonts[font_key], fill=COLORS[color_key], anchor="lm")

        def draw_progress_bar(x, y, width, height, progress, bg_color, fill_color):
            # Fond de la barre
            draw.rounded_rectangle((x, y, x + width, y + height), fill=bg_color, radius=height//2)
            # Progression
            if progress > 0:
                fill_width = int(width * progress)
                draw.rounded_rectangle((x, y, x + fill_width, y + height), fill=fill_color, radius=height//2)
        
        # --- Avatar ---
        try:
            avatar_url = user_data.get("avatar_url")
            response = requests.get(avatar_url, stream=True)
            response.raise_for_status()
            avatar_image = Image.open(io.BytesIO(response.content)).convert("RGBA")
            size = (200, 200)
            mask = Image.new("L", size, 0)
            draw_mask = ImageDraw.Draw(mask)
            draw_mask.ellipse((0, 0) + size, fill=255)
            avatar = ImageOps.fit(avatar_image, mask.size, centering=(0.5, 0.5))
            avatar.putalpha(mask)
            bg.paste(avatar, (100, 90), avatar)
        except Exception:
            # En cas d'échec, dessiner un cercle vide
            draw.ellipse((100, 90, 300, 290), outline=COLORS["grey"], width=4)

        # --- Nom et ligne de séparation ---
        user_name = user_data.get("name", "Utilisateur").split("#")[0]
        draw.text((340, 110), user_name, font=fonts['name'], fill=COLORS["white"], anchor="lt")
        draw.line([(340, 195), (1100, 195)], fill=COLORS["progress_bar_bg"], width=2)
        
        # --> AMÉLIORATION : Vrai badge visuel pour le Top Noteur
        if user_data.get('is_top_3_monthly'):
            badge_x, badge_y = 340, 215
            badge_text = "🏅 Top Noteur du Mois"
            text_width = draw.textlength(badge_text, font=fonts['regular_s'])
            # Dessiner le fond du badge
            draw.rounded_rectangle((badge_x, badge_y, badge_x + text_width + 30, badge_y + 40), fill=COLORS["gold"], radius=8)
            # Dessiner le texte du badge
            draw.text((badge_x + 15, badge_y + 20), badge_text, font=fonts['regular_s'], fill=COLORS["card"], anchor="lm")
        
        # --- COLONNE 1 : Activité Discord (décalée vers le bas si badge présent) ---
        y_pos_start = 290 if user_data.get('is_top_3_monthly') else 230
        x_col1 = 100
        
        draw.text((x_col1, y_pos_start), "Activité Discord", font=fonts['title'], fill=COLORS["white"])
        y_pos = y_pos_start + 60
        
        if user_data.get('count', 0) > 0:
            draw_text_with_emoji(x_col1, y_pos, "🏆", f"Classement : #{user_data.get('rank', 'N/C')}", 'regular_l', 'white')
            draw_text_with_emoji(x_col1, y_pos + 55, "📝", f"Notes : {user_data.get('count', 0)}", 'regular_l', 'white')

            # --> AMÉLIORATION : Barre de progression pour la moyenne
            avg_note = user_data.get('avg', 0)
            draw_text_with_emoji(x_col1, y_pos + 110, "📊", f"Moyenne : {avg_note:.2f}/10", 'regular_l', 'white')
            bar_y = y_pos + 150
            draw_progress_bar(x_col1, bar_y, 450, 20, avg_note / 10, COLORS["progress_bar_bg"], COLORS["progress_bar_fill"])
            
            note_min_max = f"Note Min/Max : {user_data.get('min_note', 0):.2f} / {user_data.get('max_note', 0):.2f}"
            draw_text_with_emoji(x_col1, y_pos + 185, "↕️", note_min_max, 'regular_l', 'white')
        else:
            draw.text((x_col1, y_pos), "Aucune note enregistrée", font=fonts['regular_l'], fill=COLORS["grey"])
            
        # --- COLONNE 2 : Activité Boutique ---
        x_col2 = 700
        y_pos = y_pos_start + 60 # S'aligne sur la colonne 1

        draw.text((x_col2, y_pos_start), "Activité Boutique", font=fonts['title'], fill=COLORS["white"])
        
        if user_data.get("purchase_count", 0) > 0:
            draw_text_with_emoji(x_col2, y_pos, "🛍️", f"Commandes : {user_data.get('purchase_count', 0)}", 'regular_l', 'white')
            draw_text_with_emoji(x_col2, y_pos + 55, "💳", f"Dépensé : {user_data.get('total_spent', 0):.2f} €", 'regular_l', 'white')
        else:
            draw.text((x_col2, y_pos), "Compte non lié ou aucune commande", font=fonts['regular_l'], fill=COLORS["grey"])

        # --- Footer ---
        draw.text((1140, 540), "Généré par LaFoncedalleBot", font=fonts['light'], fill=COLORS['grey'], anchor="rs")

        buffer = io.BytesIO()
        bg.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

    return await asyncio.to_thread(_generate)