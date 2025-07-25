# Fichier : profil_image_generator.py

from PIL import Image, ImageDraw, ImageFont, ImageOps
import requests
import io
import os
import asyncio
import traceback # <-- Importez traceback

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

async def create_profile_card(user_data: dict) -> io.BytesIO:
    """Génère une carte de profil visuellement riche avec une police personnalisée et des emojis."""

    def _generate():
        fonts = {}
        font_paths = {
            "name": os.path.join(ASSETS_DIR, "Gobold-Bold.ttf"),
            "title": os.path.join(ASSETS_DIR, "Gobold-Bold.ttf"),
            "regular": os.path.join(ASSETS_DIR, "Gobold-Regular.ttf"),
            "emoji": os.path.join(ASSETS_DIR, "NotoColorEmoji.ttf"),
        }

        try:
            # [AMÉLIORATION DU DEBUG]
            font_to_check = font_paths['name']
            print(f"INFO [ImageGen]: Tentative de chargement de la police depuis le chemin: {font_to_check}")
            if not os.path.exists(font_to_check):
                # Cette erreur sera maintenant visible dans les logs Render
                raise FileNotFoundError(f"Le fichier de police n'existe pas au chemin spécifié: {font_to_check}")

            fonts['name'] = ImageFont.truetype(font_to_check, 65)
            fonts['title'] = ImageFont.truetype(font_paths['title'], 42)
            fonts['regular'] = ImageFont.truetype(font_paths['regular'], 40)
            fonts['badge'] = ImageFont.truetype(font_paths['name'], 42)
            fonts['emoji'] = ImageFont.truetype(font_paths['emoji'], 40)
            print("SUCCESS [ImageGen]: Toutes les polices personnalisées ont été chargées avec succès.")

        except Exception as e:
            # [AMÉLIORATION DU DEBUG]
            print(f"ERREUR CRITIQUE [ImageGen]: Impossible de charger la police personnalisée. Erreur: {e}")
            print(traceback.format_exc()) # Imprime la trace complète de l'erreur
            print("INFO [ImageGen]: Utilisation des polices par défaut en secours.")
            fonts = {k: ImageFont.load_default() for k in ['name', 'title', 'regular', 'badge', 'emoji']}

        # ... Le reste du code de génération d'image ne change pas ...
        # --- Création du fond et de la zone de dessin ---
        bg = Image.new("RGBA", (1200, 600), (27, 27, 31))
        draw = ImageDraw.Draw(bg)

        def draw_text_with_emoji(x, y, emoji, text, text_fill):
            draw.text((x, y), emoji, font=fonts['emoji'], embedded_color=True)
            emoji_width = draw.textlength(emoji, font=fonts['emoji'])
            draw.text((x + emoji_width + 15, y + 5), text, font=fonts['regular'], fill=text_fill)

        # --- Avatar ---
        try:
            avatar_url = user_data.get("avatar_url")
            response = requests.get(avatar_url, stream=True)
            response.raise_for_status()
            avatar_image = Image.open(io.BytesIO(response.content)).convert("RGBA")
            size = (250, 250); mask = Image.new("L", size, 0); draw_mask = ImageDraw.Draw(mask)
            draw_mask.ellipse((0, 0) + size, fill=255); avatar = ImageOps.fit(avatar_image, mask.size, centering=(0.5, 0.5))
            avatar.putalpha(mask); bg.paste(avatar, (75, 75), avatar)
        except Exception:
            pass

        # --- Nom et ligne de séparation ---
        user_name = user_data.get("name", "Utilisateur").split("#")[0]
        draw.text((400, 90), user_name, font=fonts['name'], fill=(255, 255, 255))
        draw.line([(400, 175), (1100, 175)], fill=(60, 60, 65), width=4)

        # --- Colonne 1 : Activité Discord ---
        x_col1 = 400
        y_pos = 210
        draw.text((x_col1, y_pos), "Activité Discord", font=fonts['title'], fill=(255, 255, 255))
        y_pos += 70

        if user_data.get('is_top_3_monthly'):
            draw.text((x_col1 + 60, y_pos + 5), "Top Noteur du Mois", font=fonts['badge'], fill=(255, 215, 0))
            draw.text((x_col1, y_pos), "🏅", font=fonts['emoji'], embedded_color=True)
            y_pos += 60
            
        if user_data.get('count', 0) > 0:
            draw_text_with_emoji(x_col1, y_pos, "🏆", f"Classement : #{user_data.get('rank', 'N/C')}", (220, 220, 220))
            draw_text_with_emoji(x_col1, y_pos + 55, "📝", f"Notes : {user_data.get('count', 0)}", (220, 220, 220))
            draw_text_with_emoji(x_col1, y_pos + 110, "📊", f"Moyenne : {user_data.get('avg', 0):.2f}/10", (220, 220, 220))
            draw_text_with_emoji(x_col1, y_pos + 165, "↕️", f"Note Min/Max : {user_data.get('min_note', 0):.2f} / {user_data.get('max_note', 0):.2f}", (220, 220, 220))
        else:
            draw.text((x_col1, y_pos), "Aucune note enregistrée", font=fonts['regular'], fill=(150, 150, 150))
            
        # --- Colonne 2 : Activité Boutique ---
        x_col2 = 800
        y_pos = 210
        draw.text((x_col2, y_pos), "Activité Boutique", font=fonts['title'], fill=(255, 255, 255))
        y_pos += 70

        if user_data.get("purchase_count", 0) > 0:
            draw_text_with_emoji(x_col2, y_pos, "🛍️", f"Commandes : {user_data.get('purchase_count', 0)}", (220, 220, 220))
            draw_text_with_emoji(x_col2, y_pos + 55, "💳", f"Dépensé : {user_data.get('total_spent', 0):.2f} €", (220, 220, 220))
        else:
            draw.text((x_col2, y_pos), "Compte non lié", font=fonts['regular'], fill=(255, 180, 180))

        buffer = io.BytesIO()
        bg.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

    return await asyncio.to_thread(_generate)