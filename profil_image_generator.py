# --- START OF FILE image_generator.py ---

from PIL import Image, ImageDraw, ImageFont, ImageOps
import requests
import io
import asyncio

async def create_profile_card(user_data: dict) -> io.BytesIO:
    """Génère une carte de profil sobre, professionnelle et lisible."""

    def _generate():
        # --- Configuration des polices (Taille et graisse variées pour la hiérarchie) ---
        try:
            # Assurez-vous que les fichiers de police sont dans le même dossier que vos scripts
            font_name = ImageFont.truetype("Roboto-Bold.ttf", 65)
            font_title = ImageFont.truetype("Roboto-Bold.ttf", 42)
            font_regular = ImageFont.truetype("Roboto-Regular.ttf", 40)
            font_badge = ImageFont.truetype("Roboto-Bold.ttf", 42)
        except IOError:
            # Polices de secours si les fichiers ne sont pas trouvés
            font_name = ImageFont.load_default()
            font_title = ImageFont.load_default()
            font_regular = ImageFont.load_default()
            font_badge = ImageFont.load_default()

        # --- Création du fond ---
        bg = Image.new("RGBA", (1200, 600), (27, 27, 31))
        draw = ImageDraw.Draw(bg)

        # --- Avatar ---
        try:
            avatar_url = user_data.get("avatar_url")
            response = requests.get(avatar_url, stream=True)
            response.raise_for_status()
            avatar_image = Image.open(io.BytesIO(response.content)).convert("RGBA")
            
            size = (250, 250)
            mask = Image.new("L", size, 0)
            draw_mask = ImageDraw.Draw(mask)
            draw_mask.ellipse((0, 0) + size, fill=255)
            
            avatar = ImageOps.fit(avatar_image, mask.size, centering=(0.5, 0.5))
            avatar.putalpha(mask)
            bg.paste(avatar, (75, 75), avatar)
        except Exception:
            pass

        # --- Nom de l'utilisateur ---
        user_name = user_data.get("name", "Utilisateur Inconnu").split("#")[0] # On enlève le #XXXX
        draw.text((400, 90), user_name, font=font_name, fill=(255, 255, 255))
        
        # --- Ligne de séparation ---
        draw.line([(400, 175), (1100, 175)], fill=(60, 60, 65), width=4)

        # --- Colonne de gauche (Activité Discord) ---
        x_col1 = 400
        y_pos = 210
        
        # Titre de la section
        draw.text((x_col1, y_pos), "Activité Discord", font=font_title, fill=(255, 255, 255))
        y_pos += 70

        # Badge Spécial (sans emoji)
        if user_data.get('is_top_3_monthly'):
            draw.text((x_col1, y_pos), "Top Noteur du Mois", font=font_badge, fill=(255, 215, 0)) # Or
            y_pos += 60
            
        # Stats Discord
        if user_data.get('count', 0) > 0:
            rank_text = f"Classement : #{user_data.get('rank', 'N/C')}"
            notes_text = f"Notes : {user_data.get('count', 0)}"
            avg_text = f"Moyenne : {user_data.get('avg', 0):.2f}/10"
            min_max_text = f"Note Min/Max : {user_data.get('min_note', 0):.2f} / {user_data.get('max_note', 0):.2f}"
            
            draw.text((x_col1, y_pos), rank_text, font=font_regular, fill=(220, 220, 220))
            draw.text((x_col1, y_pos + 55), notes_text, font=font_regular, fill=(220, 220, 220))
            draw.text((x_col1, y_pos + 110), avg_text, font=font_regular, fill=(220, 220, 220))
            draw.text((x_col1, y_pos + 165), min_max_text, font=font_regular, fill=(220, 220, 220))
        else:
            draw.text((x_col1, y_pos), "Aucune note enregistrée", font=font_regular, fill=(150, 150, 150))
            
        # --- Colonne de droite (Activité Boutique) ---
        x_col2 = 800
        y_pos = 210

        # Titre de la section
        draw.text((x_col2, y_pos), "Activité Boutique", font=font_title, fill=(255, 255, 255))
        y_pos += 70

        # Stats Boutique
        if user_data.get("purchase_count") is not None and user_data.get("purchase_count") > 0:
            orders_text = f"Commandes : {user_data.get('purchase_count', 0)}"
            spent_text = f"Dépensé : {user_data.get('total_spent', 0):.2f} €"
            draw.text((x_col2, y_pos), orders_text, font=font_regular, fill=(220, 220, 220))
            draw.text((x_col2, y_pos + 55), spent_text, font=font_regular, fill=(220, 220, 220))
        else:
            draw.text((x_col2, y_pos), "Compte non lié", font=font_regular, fill=(255, 180, 180))

        # --- Sauvegarde en mémoire ---
        buffer = io.BytesIO()
        bg.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

    return await asyncio.to_thread(_generate)