# Fichier : profil_image_generator.py (Version Restylisée Ultime)

from PIL import Image, ImageDraw, ImageFont, ImageOps
import requests
import io
import os
import asyncio
import traceback

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

# --- NOUVELLE Palette de couleurs pour le nouveau style ---
COLORS = {
    "background": "#FFFFFF",
    "card": "#A744E8",  # Le violet principal
    "primary_text": "#FFFFFF",  # Texte blanc sur le violet
    "accent": "#FFC700",  # Le jaune pour le badge
    "inner_card": "#FFFFFF",  # Le fond blanc des boîtes de stats
    "text_on_white": "#4A007B",  # Texte violet foncé sur fond blanc
    "label_on_white": "#A37FC4",  # Texte violet clair pour les labels
    "gold": {"bg": "#FFC700", "text": "#4D3800"},
}

async def create_profile_card(user_data: dict) -> io.BytesIO:
    def _generate():
        fonts = {}
        try:
            # Charger plusieurs graisses de police pour plus de contrôle
            font_paths = {
                "bold": os.path.join(ASSETS_DIR, "Gobold Bold.otf"),
                "regular": os.path.join(ASSETS_DIR, "Gobold Regular.otf"),
                "emoji": os.path.join(ASSETS_DIR, "NotoColorEmoji-Regular.ttf"),
            }
            fonts.update({
                'name': ImageFont.truetype(font_paths['bold'], 70),
                'title': ImageFont.truetype(font_paths['bold'], 30),
                'label': ImageFont.truetype(font_paths['regular'], 28), # Police pour les labels
                'value': ImageFont.truetype(font_paths['bold'], 32), # Police pour les valeurs
                'badge': ImageFont.truetype(font_paths['bold'], 22), # Police pour le badge
                'emoji': ImageFont.truetype(font_paths['emoji'], 22),
            })
        except Exception as e:
            print(f"ERREUR [ImageGen]: Polices introuvables. {e}"); traceback.print_exc(); return None

        bg = Image.new("RGBA", (1200, 600), COLORS["background"])
        draw = ImageDraw.Draw(bg)
        
        # --- Dessin des formes de base ---
        draw.rounded_rectangle((20, 20, 1180, 580), fill=COLORS["card"], radius=30)
        draw.rounded_rectangle((40, 280, 590, 560), fill=COLORS["inner_card"], radius=20) # Carte gauche
        draw.rounded_rectangle((610, 280, 1160, 560), fill=COLORS["inner_card"], radius=20) # Carte droite

        # --- NOUVELLE fonction pour dessiner les stats en colonnes ---
        def draw_stat_line(y, label, value, col_base_x):
            draw.text((col_base_x + 30, y), label.upper(), font=fonts['label'], fill=COLORS["label_on_white"], anchor="lm")
            draw.text((col_base_x + 520, y), str(value), font=fonts['value'], fill=COLORS["text_on_white"], anchor="rm")

        # --- Dessin de l'en-tête (Avatar, Nom, Badge) ---
        avatar_pos, avatar_size = (60, 60), (180, 180)
        try:
            # Cercle blanc derrière l'avatar
            draw.ellipse((avatar_pos[0]-5, avatar_pos[1]-5, avatar_pos[0]+avatar_size[0]+5, avatar_pos[1]+avatar_size[1]+5), fill="#FFFFFF")
            avatar_image = Image.open(io.BytesIO(requests.get(user_data.get("avatar_url"), stream=True).content)).convert("RGBA")
            mask = Image.new("L", avatar_size, 0); ImageDraw.Draw(mask).ellipse((0, 0) + avatar_size, fill=255)
            avatar = ImageOps.fit(avatar_image, mask.size, centering=(0.5, 0.5)); bg.paste(avatar, avatar_pos, mask)
        except Exception: 
            draw.ellipse((avatar_pos[0], avatar_pos[1], avatar_pos[0]+avatar_size[0], avatar_pos[1]+avatar_size[1]), fill="#CCCCCC")

        user_name = user_data.get("name", "Utilisateur").split("#")[0].upper()
        draw.text((280, 100), user_name, font=fonts['name'], fill=COLORS["primary_text"], anchor="lt")
        
        # Ligne de séparation sous le nom
        draw.line([(280, 180), (1140, 180)], fill=COLORS["primary_text"], width=2)
        
        try:
            corner_logo = Image.open(os.path.join(ASSETS_DIR, "logo_rond.png")).convert("RGBA")
            corner_logo.thumbnail((100, 100), Image.Resampling.LANCZOS)
            bg.paste(corner_logo, (1060, 60), corner_logo)
        except FileNotFoundError: print("WARNING [ImageGen]: 'logo_rond.png' non trouvé.")

        # Badge "Top Noteur"
        monthly_rank = user_data.get('monthly_rank')
        if monthly_rank == 1: # On affiche le badge OR uniquement pour le #1
            badge_text = "TOP NOTEUR OR"
            text_width = draw.textlength(badge_text, font=fonts['badge'])
            badge_width = text_width + 40
            draw.rounded_rectangle((280, 195, 280 + badge_width, 235), fill=COLORS["accent"], radius=8)
            draw.text((280 + badge_width / 2, 215), badge_text, font=fonts['badge'], fill=COLORS["gold"]["text"], anchor="mm")

        # --- Bloc 1: Activité Boutique ---
        col1_x, col1_y = 40, 280
        draw.text((col1_x + 30, col1_y + 35), "ACTIVITÉ BOUTIQUE", font=fonts['title'], fill=COLORS["text_on_white"], anchor="lt")
        draw.line([(col1_x + 30, col1_y + 80), (col1_x + 520, col1_y + 80)], fill="#E0E0E0", width=2)
        if user_data.get("purchase_count", 0) > 0:
            draw_stat_line(col1_y + 130, "Commandes", user_data.get('purchase_count', 0), col1_x)
            draw_stat_line(col1_y + 190, "Total Dépensé", f"{user_data.get('total_spent', 0):.2f} €", col1_x)
        else:
            draw.text((col1_x + 295, col1_y + 170), "AUCUNE ACTIVITÉ", font=fonts['label'], fill=COLORS["label_on_white"], anchor="mm")

        # --- Bloc 2: Activité Discord ---
        col2_x, col2_y = 610, 280
        draw.text((col2_x + 30, col2_y + 35), "ACTIVITÉ DISCORD", font=fonts['title'], fill=COLORS["text_on_white"], anchor="lt")
        draw.line([(col2_x + 30, col2_y + 80), (col2_x + 520, col2_y + 80)], fill="#E0E0E0", width=2)
        if user_data.get('count', 0) > 0:
            avg_note = user_data.get('avg', 0)
            min_max_str = f"{user_data.get('min_note', 0):.2f} / {user_data.get('max_note', 0):.2f}"
            draw_stat_line(col2_y + 115, "Notes Données", user_data.get('count', 0), col2_x)
            draw_stat_line(col2_y + 165, "Moyenne", f"{avg_note:.2f} / 10", col2_x)
            draw_stat_line(col2_y + 215, "Note Min / Max", min_max_str, col2_x)
            draw_stat_line(col2_y + 265, "Classement Général", f"#{user_data.get('rank', 'N/C')}", col2_x)
        else:
            draw.text((col2_x + 275, col2_y + 170), "AUCUNE NOTE ENREGISTRÉE", font=fonts['label'], fill=COLORS["label_on_white"], anchor="mm")
        
        buffer = io.BytesIO()
        bg.save(buffer, format="PNG"); buffer.seek(0)
        return buffer

    return await asyncio.to_thread(_generate)