# --- START OF FILE image_generator.py ---

from PIL import Image, ImageDraw, ImageFont, ImageOps
import requests
import io
import asyncio

async def create_profile_card(user_data: dict) -> io.BytesIO:
    """Génère une carte de profil visuellement riche avec une police personnalisée et des emojis."""

    def _generate():
        # --- Configuration des Polices ---
        # On charge la police de texte (Gobold) et la police pour les emojis.
        try:
            # Assurez-vous que les noms de fichiers correspondent à ceux que vous avez téléchargés
            font_name = ImageFont.truetype("Gobold-Bold.ttf", 65)
            font_title = ImageFont.truetype("Gobold-Bold.ttf", 42)
            font_regular = ImageFont.truetype("Gobold-Regular.ttf", 40)
            font_badge = ImageFont.truetype("Gobold-Bold.ttf", 42)
            # Charge la police emoji
            font_emoji = ImageFont.truetype("NotoColorEmoji.ttf", 40)
        except IOError:
            # Polices de secours si les fichiers ne sont pas trouvés
            font_name = ImageFont.load_default()
            font_title = ImageFont.load_default()
            font_regular = ImageFont.load_default()
            font_badge = ImageFont.load_default()
            try:
                font_emoji = ImageFont.truetype("NotoColorEmoji.ttf", 40)
            except IOError:
                font_emoji = font_regular # Au pire, on se passe d'emojis

        # --- Création du fond et de la zone de dessin ---
        bg = Image.new("RGBA", (1200, 600), (27, 27, 31))
        draw = ImageDraw.Draw(bg)

        # --- Fonction utilitaire pour dessiner texte avec emoji ---
        def draw_text_with_emoji(x, y, emoji, text, emoji_font, text_font, text_fill):
            # Dessine l'emoji en couleur
            draw.text((x, y), emoji, font=emoji_font, embedded_color=True)
            # Calcule la largeur de l'emoji pour placer le texte juste après
            emoji_width = draw.textlength(emoji, font=emoji_font)
            # Dessine le texte à côté de l'emoji avec un petit espace
            draw.text((x + emoji_width + 15, y + 5), text, font=text_font, fill=text_fill)


        # --- Avatar (inchangé) ---
        try:
            # ... (le code pour l'avatar reste le même)
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
        user_name = user_data.get("name", "Utilisateur Inconnu").split("#")[0]
        draw.text((400, 90), user_name, font=font_name, fill=(255, 255, 255))
        draw.line([(400, 175), (1100, 175)], fill=(60, 60, 65), width=4)

        # --- Colonne 1 : Activité Discord ---
        x_col1 = 400
        y_pos = 210
        draw.text((x_col1, y_pos), "Activité Discord", font=font_title, fill=(255, 255, 255))
        y_pos += 70

        if user_data.get('is_top_3_monthly'):
            draw_text_with_emoji(x_col1, y_pos, "🏅", "Top Noteur du Mois", font_emoji, font_badge, (255, 215, 0))
            y_pos += 60
            
        if user_data.get('count', 0) > 0:
            draw_text_with_emoji(x_col1, y_pos, "🏆", f"Classement : #{user_data.get('rank', 'N/C')}", font_emoji, font_regular, (220, 220, 220))
            draw_text_with_emoji(x_col1, y_pos + 55, "📝", f"Notes : {user_data.get('count', 0)}", font_emoji, font_regular, (220, 220, 220))
            draw_text_with_emoji(x_col1, y_pos + 110, "📊", f"Moyenne : {user_data.get('avg', 0):.2f}/10", font_emoji, font_regular, (220, 220, 220))
            draw_text_with_emoji(x_col1, y_pos + 165, "↕️", f"Note Min/Max : {user_data.get('min_note', 0):.2f} / {user_data.get('max_note', 0):.2f}", font_emoji, font_regular, (220, 220, 220))
        else:
            draw.text((x_col1, y_pos), "Aucune note enregistrée", font=font_regular, fill=(150, 150, 150))
            
        # --- Colonne 2 : Activité Boutique ---
        x_col2 = 800
        y_pos = 210
        draw.text((x_col2, y_pos), "Activité Boutique", font=font_title, fill=(255, 255, 255))
        y_pos += 70

        if user_data.get("purchase_count") is not None and user_data.get("purchase_count") > 0:
            draw_text_with_emoji(x_col2, y_pos, "🛍️", f"Commandes : {user_data.get('purchase_count', 0)}", font_emoji, font_regular, (220, 220, 220))
            draw_text_with_emoji(x_col2, y_pos + 55, "💳", f"Dépensé : {user_data.get('total_spent', 0):.2f} €", font_emoji, font_regular, (220, 220, 220))
        else:
            draw.text((x_col2, y_pos), "Compte non lié", font=font_regular, fill=(255, 180, 180))

        # --- Sauvegarde en mémoire ---
        buffer = io.BytesIO()
        bg.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

    # On exécute la fonction de dessin (synchrone) dans un thread pour ne pas bloquer le bot
    return await asyncio.to_thread(_generate)