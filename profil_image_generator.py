# Fichier : profil_image_generator.py

from PIL import Image, ImageDraw, ImageFont, ImageOps
import requests
import io
import os
import asyncio
import traceback

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

# --- Nouvelle palette de couleurs "LaFoncedalle" inspirée du logo ---
COLORS = {
    "background": "#FDF9FF",  # Un rose très très pâle, presque blanc
    "card": "#F5ECFE",        # Le fond de la carte, rose/lilas pâle
    "primary_text": "#4A007B", # Un violet profond pour les titres et textes importants
    "secondary_text": "#A37FC4", # Un violet plus doux pour les textes secondaires
    "accent": "#9D41E8",      # Le violet vif du logo pour les accents (barre, etc.)
    "gold": "#FFD700",        # L'or pour le badge Top Noteur
    "progress_bar_bg": "#EADBF9", # Fond de la barre de progression
}

async def create_profile_card(user_data: dict) -> io.BytesIO:
    """Génère une carte de profil visuellement riche avec une nouvelle identité visuelle."""

    def _generate():
        print("Génération de la nouvelle carte de profil... c'est parti !")
        fonts = {}
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
        except Exception as e:
            print(f"ERREUR CRITIQUE [ImageGen]: Impossible de charger la police personnalisée. Erreur: {e}")
            print(traceback.format_exc())
            return None # On arrête la génération si les polices manquent

        # --- Création du fond et de la carte principale ---
        bg = Image.new("RGBA", (1200, 600), COLORS["background"])
        
        # --- AJOUT DU WATERMARK ---
        try:
            watermark_logo = Image.open(os.path.join(ASSETS_DIR, "logo_rond.png")).convert("RGBA")
            watermark_logo = watermark_logo.resize((800, 800), Image.LANCZOS)
            
            # Réduire l'opacité
            alpha = watermark_logo.getchannel('A')
            alpha = Image.eval(alpha, lambda p: p // 10) # Opacité à ~10%
            watermark_logo.putalpha(alpha)

            bg.paste(watermark_logo, (200, -100), watermark_logo)
        except FileNotFoundError:
            print("WARNING [ImageGen]: Logo 'logo_rond.png' pour le watermark non trouvé.")


        draw = ImageDraw.Draw(bg)
        draw.rounded_rectangle((40, 40, 1160, 560), fill=COLORS["card"], radius=30)

        # --- Fonctions Helper ---
        def draw_text_with_emoji(x, y, emoji, text, font_key='regular_l', color_key='secondary_text'):
            draw.text((x, y - 2), emoji, font=fonts['emoji'], embedded_color=True, anchor="lm")
            emoji_width = draw.textlength(emoji, font=fonts['emoji'])
            draw.text((x + emoji_width + 15, y), text, font=fonts[font_key], fill=COLORS[color_key], anchor="lm")
        
        def draw_progress_bar(x, y, width, height, progress):
            draw.rounded_rectangle((x, y, x + width, y + height), fill=COLORS["progress_bar_bg"], radius=height//2)
            if progress > 0:
                fill_width = int(width * progress)
                draw.rounded_rectangle((x, y, x + fill_width, y + height), fill=COLORS["accent"], radius=height//2)

        # --- Avatar avec bordure ---
        avatar_pos = (80, 70)
        avatar_size = (200, 200)
        try:
            # Cercle de fond pour la bordure
            draw.ellipse((avatar_pos[0]-5, avatar_pos[1]-5, avatar_pos[0]+avatar_size[0]+5, avatar_pos[1]+avatar_size[1]+5), fill=COLORS["accent"])

            avatar_url = user_data.get("avatar_url")
            response = requests.get(avatar_url, stream=True)
            response.raise_for_status()
            avatar_image = Image.open(io.BytesIO(response.content)).convert("RGBA")
            
            mask = Image.new("L", avatar_size, 0)
            draw_mask = ImageDraw.Draw(mask)
            draw_mask.ellipse((0, 0) + avatar_size, fill=255)
            
            avatar = ImageOps.fit(avatar_image, mask.size, centering=(0.5, 0.5))
            avatar.putalpha(mask)
            bg.paste(avatar, avatar_pos, avatar)
        except Exception:
            draw.ellipse((avatar_pos, (avatar_pos[0]+avatar_size[0], avatar_pos[1]+avatar_size[1])), fill=COLORS["secondary_text"])

        # --- Nom, ligne de séparation et badge ---
        user_name = user_data.get("name", "Utilisateur").split("#")[0]
        draw.text((320, 90), user_name, font=fonts['name'], fill=COLORS["primary_text"], anchor="lt")
        draw.line([(320, 180), (1100, 180)], fill=COLORS["accent"], width=3)
        
        if user_data.get('is_top_3_monthly'):
            badge_x, badge_y = 320, 200
            badge_text = "🏅 Top Noteur du Mois"
            text_width = draw.textlength(badge_text, font=fonts['regular_s'])
            draw.rounded_rectangle((badge_x, badge_y, badge_x + text_width + 30, badge_y + 40), fill=COLORS["gold"], radius=8)
            draw.text((badge_x + 15, badge_y + 20), badge_text, font=fonts['regular_s'], fill=COLORS["primary_text"], anchor="lm")
        
        y_pos_start = 280
        
        # --- COLONNE 1 : Activité Boutique ---
        x_col1 = 80
        draw.text((x_col1, y_pos_start), "🛒 Activité Boutique", font=fonts['title'], fill=COLORS["primary_text"])
        y_pos_col1 = y_pos_start + 60
        
        if user_data.get("purchase_count", 0) > 0:
            draw_text_with_emoji(x_col1, y_pos_col1, "🛍️", f"Commandes : {user_data.get('purchase_count', 0)}", color_key='primary_text')
            draw_text_with_emoji(x_col1, y_pos_col1 + 55, "💳", f"Dépensé : {user_data.get('total_spent', 0):.2f} €", color_key='primary_text')
        else:
            draw.text((x_col1, y_pos_col1), "Aucune commande trouvée.", font=fonts['regular_l'], fill=COLORS["secondary_text"])

        # --- COLONNE 2 : Activité Discord ---
        x_col2 = 650
        draw.text((x_col2, y_pos_start), "🤖 Activité Discord", font=fonts['title'], fill=COLORS["primary_text"])
        y_pos_col2 = y_pos_start + 60

        if user_data.get('count', 0) > 0:
            avg_note = user_data.get('avg', 0)
            draw_text_with_emoji(x_col2, y_pos_col2, "📝", f"{user_data.get('count', 0)} Notes | Moyenne : {avg_note:.2f}/10", color_key='primary_text')
            bar_y = y_pos_col2 + 45
            draw_progress_bar(x_col2, bar_y, 450, 20, avg_note / 10)
            note_min_max = f"Note Min/Max : {user_data.get('min_note', 0):.2f} / {user_data.get('max_note', 0):.2f}"
            draw_text_with_emoji(x_col2, y_pos_col2 + 80, "↕️", note_min_max, color_key='primary_text')
            draw_text_with_emoji(x_col2, y_pos_col2 + 135, "🏆", f"Classement Général : #{user_data.get('rank', 'N/C')}", color_key='primary_text')
        else:
            draw.text((x_col2, y_pos_col2), "Aucune note enregistrée.", font=fonts['regular_l'], fill=COLORS["secondary_text"])
            
        # --- Footer avec logo rectangulaire ---
        try:
            footer_logo = Image.open(os.path.join(ASSETS_DIR, "logo_rect.png")).convert("RGBA")
            footer_logo.thumbnail((150, 40), Image.LANCZOS)
            bg.paste(footer_logo, (990, 500), footer_logo)
        except FileNotFoundError:
            print("WARNING [ImageGen]: Logo 'logo_rect.png' pour le footer non trouvé.")
            draw.text((1140, 540), "Généré par LaFoncedalleBot", font=fonts['light'], fill=COLORS['secondary_text'], anchor="rs")

        # --- Conversion en buffer pour l'envoi ---
        buffer = io.BytesIO()
        bg.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

    # On exécute la fonction de génération dans un thread pour ne pas bloquer le bot
    return await asyncio.to_thread(_generate)