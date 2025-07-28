# Fichier : profil_image_generator.py (Version Finale avec Correction de Mesure)

import PIL
from PIL import Image, ImageDraw, ImageFont, ImageOps, features
import requests
import io
import os
import asyncio
import traceback

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

print(f"--- [ImageGen DEBUG] Pillow version: {PIL.__version__} ---")
print(f"--- [ImageGen DEBUG] Raqm support: {features.check('raqm')} ---")
print(f"--- [ImageGen DEBUG] Freetype support: {features.check('freetype2')} ---")

async def create_profile_card(user_data: dict) -> io.BytesIO:
    print(f"DEBUG [ImageGen]: Données utilisateur reçues -> {user_data}")
    def _generate():
        # ... (Palette de couleurs et chargement des polices inchangés) ...
        COLORS = {
                "background": "#330D4C",
                "card": "#A744E8",
                "primary_text": "#FFFFFF",
                "accent": "#FFC700",
                "inner_card": "#7A1CB8",
                "value_text": "#FFFFFF",
                "label_text": "#D6B3ED",
                "separator_line": "#A744E8",
                "badge_text_color": "#3A2B01",
        }
        fonts = {}
        try:
            font_paths = {
                "bold": os.path.join(ASSETS_DIR, "Gobold Bold.otf"),
                "regular": os.path.join(ASSETS_DIR, "Gobold Regular.otf"),
                "emoji": os.path.join(ASSETS_DIR, "NotoColorEmoji-Regular.ttf"),
            }
            fonts.update({
                'name': ImageFont.truetype(font_paths['bold'], 70),
                'title': ImageFont.truetype(font_paths['bold'], 30),
                'label': ImageFont.truetype(font_paths['regular'], 28),
                'value': ImageFont.truetype(font_paths['bold'], 32),
                'badge': ImageFont.truetype(font_paths['bold'], 22),
                'emoji': ImageFont.truetype(font_paths['emoji'], 22),
            })
        except Exception as e:
            print(f"ERREUR [ImageGen]: Polices introuvables. {e}"); traceback.print_exc(); return None

        bg = Image.new("RGBA", (1200, 600), COLORS["background"])
        draw = ImageDraw.Draw(bg)
        
        # ... (Dessin de la carte, avatar, nom, etc. inchangé) ...
        draw.rounded_rectangle((20, 20, 1180, 580), fill=COLORS["card"], radius=30)
        draw.rounded_rectangle((40, 280, 590, 560), fill=COLORS["inner_card"], radius=20)
        draw.rounded_rectangle((610, 280, 1160, 560), fill=COLORS["inner_card"], radius=20)

        def draw_stat_line(y, label, value, col_base_x):
            draw.text((col_base_x + 40, y), label.upper(), font=fonts['label'], fill=COLORS["label_text"], anchor="lm")
            draw.text((col_base_x + 510, y), str(value), font=fonts['value'], fill=COLORS["value_text"], anchor="rm")

        avatar_pos, avatar_size = (60, 60), (180, 180)
        try:
            draw.ellipse((avatar_pos[0]-5, avatar_pos[1]-5, avatar_pos[0]+avatar_size[0]+5, avatar_pos[1]+avatar_size[1]+5), fill="#FFFFFF")
            avatar_image = Image.open(io.BytesIO(requests.get(user_data.get("avatar_url"), stream=True).content)).convert("RGBA")
            mask = Image.new("L", avatar_size, 0); ImageDraw.Draw(mask).ellipse((0, 0) + avatar_size, fill=255)
            avatar = ImageOps.fit(avatar_image, mask.size, centering=(0.5, 0.5)); bg.paste(avatar, avatar_pos, mask)
        except Exception: 
            draw.ellipse((avatar_pos[0], avatar_pos[1], avatar_pos[0]+avatar_size[0], avatar_pos[1]+avatar_size[1]), fill="#CCCCCC")

        user_name = user_data.get("name", "Utilisateur").split("#")[0].upper()
        draw.text((280, 100), user_name, font=fonts['name'], fill=COLORS["primary_text"], anchor="lt")
        
        draw.line([(280, 180), (1140, 180)], fill=COLORS["primary_text"], width=2)
        
        try:
            corner_logo = Image.open(os.path.join(ASSETS_DIR, "logo_rond.png")).convert("RGBA")
            corner_logo.thumbnail((100, 100), Image.Resampling.LANCZOS)
            bg.paste(corner_logo, (1060, 60), corner_logo)
        except FileNotFoundError: print("WARNING [ImageGen]: 'logo_rond.png' non trouvé.")
        
        badge_data = user_data.get('loyalty_badge')

        if badge_data:
            badge_text = badge_data.get('name', 'Badge').upper()
            
            # [NOUVEAU] Dictionnaire qui mappe un caractère émoji à un nom de fichier image.
            # Ajoutez simplement de nouvelles lignes ici pour de nouveaux badges.
            EMOJI_TO_IMAGE_MAP = {
                '💚': 'emoji-coeur-vert.png',
                '🧘': 'emoji-yoga.png',
                '🙋': 'emoji-leve-main.png',
                # '⭐': 'etoile.png',  <-- Exemple si vous ajoutiez une étoile
            }

            # On récupère le caractère émoji depuis les données utilisateur
            emoji_char = badge_data.get('emoji') 
            
            icon_img = None
            icon_width = 0
            
            # On cherche si cet émoji a une image correspondante dans notre map
            icon_filename = EMOJI_TO_IMAGE_MAP.get(emoji_char)

            if icon_filename:
                try:
                    # On charge l'image si elle est trouvée
                    icon_path = os.path.join(ASSETS_DIR, icon_filename)
                    icon_img = Image.open(icon_path).convert("RGBA")
                    # On redimensionne l'icône pour qu'elle s'adapte à la hauteur du badge
                    icon_img.thumbnail((32, 32), Image.Resampling.LANCZOS)
                    icon_width = icon_img.width
                except FileNotFoundError:
                    print(f"AVERTISSEMENT [ImageGen]: Le fichier icône '{icon_filename}' configuré pour l'émoji '{emoji_char}' est introuvable.")
                    pass # On continue sans icône si le fichier n'existe pas
            
            # Mesure du texte
            text_bbox = draw.textbbox((0, 0), badge_text, font=fonts['badge'])
            text_width = text_bbox[2] - text_bbox[0]
            
            # Calcul de la largeur totale du badge
            padding, spacing = 20, 10
            badge_width = (icon_width + spacing if icon_img else 0) + text_width + (padding * 2)
            badge_x, badge_y, badge_h = 280, 195, 40
            badge_y_center = badge_y + (badge_h / 2)
            
            # Dessin du fond du badge
            draw.rounded_rectangle((badge_x, badge_y, badge_x + badge_width, badge_y + badge_h), fill=COLORS["accent"], radius=8)
            
            current_x = badge_x + padding
            
            # [MODIFIÉ] On colle l'image de l'icône si elle a été chargée
            if icon_img:
                # On calcule la position Y pour centrer l'icône verticalement dans le badge
                paste_y = int(badge_y_center - (icon_img.height / 2))
                bg.paste(icon_img, (current_x, paste_y), icon_img)
                current_x += icon_width + spacing

            # On dessine le texte à côté de l'icône (ou au début si pas d'icône)
            draw.text((current_x, badge_y_center), badge_text, font=fonts['badge'], fill=COLORS["badge_text_color"], anchor="lm")

        # ... (Blocs Boutique et Discord inchangés) ...
        col1_x, col1_y = 40, 280
        draw.text((col1_x + 40, col1_y + 40), "ACTIVITÉ BOUTIQUE", font=fonts['title'], fill=COLORS["primary_text"], anchor="lt")
        draw.line([(col1_x + 40, col1_y + 85), (col1_x + 510, col1_y + 85)], fill=COLORS["separator_line"], width=2)
        if user_data.get("purchase_count", 0) > 0:
            draw_stat_line(col1_y + 125, "Commandes", user_data.get('purchase_count', 0), col1_x)
            draw_stat_line(col1_y + 175, "Total Dépensé", f"{user_data.get('total_spent', 0):.2f} €", col1_x)
        else:
            draw.text((col1_x + 295, col1_y + 160), "AUCUNE ACTIVITÉ", font=fonts['label'], fill=COLORS["label_text"], anchor="mm")

        col2_x, col2_y = 610, 280
        draw.text((col2_x + 40, col2_y + 40), "ACTIVITÉ DISCORD", font=fonts['title'], fill=COLORS["primary_text"], anchor="lt")
        draw.line([(col2_x + 40, col2_y + 85), (col2_x + 510, col2_y + 85)], fill=COLORS["separator_line"], width=2)
        if user_data.get('count', 0) > 0:
            avg_note = user_data.get('avg', 0)
            min_max_str = f"{user_data.get('min_note', 0):.2f} / {user_data.get('max_note', 0):.2f}"
            draw_stat_line(col2_y + 110, "Notes Données", user_data.get('count', 0), col2_x)
            draw_stat_line(col2_y + 155, "Moyenne", f"{avg_note:.2f} / 10", col2_x)
            draw_stat_line(col2_y + 200, "Note Min / Max", min_max_str, col2_x)
            draw_stat_line(col2_y + 245, "Classement Général", f"#{user_data.get('rank', 'N/C')}", col2_x)
        else:
            draw.text((col2_x + 275, col2_y + 160), "AUCUNE NOTE ENREGISTRÉE", font=fonts['label'], fill=COLORS["label_text"], anchor="mm")
        
        buffer = io.BytesIO()
        bg.save(buffer, format="PNG"); buffer.seek(0)
        return buffer

    return await asyncio.to_thread(_generate)