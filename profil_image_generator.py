# --- START OF FILE image_generator.py ---

from PIL import Image, ImageDraw, ImageFont, ImageOps
import requests
import io
import asyncio

async def create_profile_card(user_data: dict) -> io.BytesIO:
    """Génère une carte de profil visuellement améliorée."""

    def _generate():
        # --- Configuration (Polices plus grandes) ---
        try:
            # Assurez-vous d'avoir ces fichiers de police dans votre dossier de projet
            font_name = ImageFont.truetype("GROBOLD.ttf", 60)
            font_title = ImageFont.truetype("GROBOLD.ttf", 45)
            font_regular = ImageFont.truetype("GROBOLD.ttf", 38)
            font_badge = ImageFont.truetype("GROBOLD.ttf", 35)
        except IOError:
            # Polices de secours si les fichiers ne sont pas trouvés
            font_name = ImageFont.load_default()
            font_title = ImageFont.load_default()
            font_regular = ImageFont.load_default()
            font_badge = ImageFont.load_default()

        # --- Création du fond ---
        bg = Image.new("RGBA", (1200, 600), (27, 27, 31)) # Toile plus grande
        draw = ImageDraw.Draw(bg)

        # --- Avatar ---
        try:
            avatar_url = user_data.get("avatar_url")
            response = requests.get(avatar_url, stream=True)
            response.raise_for_status()
            avatar_image = Image.open(io.BytesIO(response.content)).convert("RGBA")
            
            size = (250, 250) # Avatar plus grand
            mask = Image.new("L", size, 0)
            draw_mask = ImageDraw.Draw(mask)
            draw_mask.ellipse((0, 0) + size, fill=255)
            
            avatar = ImageOps.fit(avatar_image, mask.size, centering=(0.5, 0.5))
            avatar.putalpha(mask)
            bg.paste(avatar, (75, 75), avatar)
        except Exception:
            pass

        # --- Nom de l'utilisateur ---
        user_name = user_data.get("name", "Utilisateur Inconnu")
        draw.text((400, 100), user_name, font=font_name, fill=(255, 255, 255))
        
        # --- Ligne de séparation ---
        draw.line([(400, 180), (1100, 180)], fill=(60, 60, 65), width=3)

        y_pos = 220 # Position de départ pour les stats

        # --- Badge Spécial ---
        if user_data.get('is_top_3_monthly'):
            draw.text((400, y_pos), "🏅 Top Noteur du Mois", font=font_badge, fill=(255, 215, 0)) # Couleur Or
            y_pos += 70 # On décale le reste vers le bas

        # --- Statistiques ---
        if user_data.get('count', 0) > 0:
            # Stats Discord
            rank_text = f"🏆 Classement : #{user_data.get('rank', 'N/C')}"
            notes_text = f"📝 Notes : {user_data.get('count', 0)}"
            avg_text = f"📊 Moyenne : {user_data.get('avg', 0):.2f}/10"
            min_max_text = f"📉 Note Min/Max : {user_data.get('min_note', 0):.2f} / {user_data.get('max_note', 0):.2f}"
            
            draw.text((400, y_pos), rank_text, font=font_regular, fill=(220, 220, 220))
            draw.text((400, y_pos + 55), notes_text, font=font_regular, fill=(220, 220, 220))
            draw.text((400, y_pos + 110), avg_text, font=font_regular, fill=(220, 220, 220))
            draw.text((400, y_pos + 165), min_max_text, font=font_regular, fill=(220, 220, 220))
        else:
            draw.text((400, y_pos), "📝 Aucune note enregistrée", font=font_regular, fill=(150, 150, 150))
            
        # Stats Boutique
        if user_data.get("purchase_count") is not None and user_data.get("purchase_count") > 0:
            orders_text = f"🛍️ Commandes : {user_data.get('purchase_count', 0)}"
            spent_text = f"💳 Dépensé : {user_data.get('total_spent', 0):.2f} €"
            draw.text((400, y_pos + 250), orders_text, font=font_regular, fill=(220, 220, 220))
            draw.text((400, y_pos + 305), spent_text, font=font_regular, fill=(220, 220, 220))
        else:
            draw.text((400, y_pos + 250), "🛍️ Compte boutique non lié", font=font_regular, fill=(255, 180, 180))

        # --- Sauvegarde en mémoire ---
        buffer = io.BytesIO()
        bg.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

    return await asyncio.to_thread(_generate)