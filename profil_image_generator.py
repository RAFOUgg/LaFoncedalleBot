# Fichier : profil_image_generator.py

from PIL import Image, ImageDraw, ImageFont, ImageOps
import requests
import io
import os
import asyncio
import traceback

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

# --- Palette de couleurs "LaFoncedalle" ---
COLORS = {
    "background": "#FDF9FF",       # Rose très pâle, presque blanc
    "card": "#F5ECFE",             # Fond principal de la carte
    "primary_text": "#4A007B",      # Violet profond pour les infos clés
    "secondary_text": "#A37FC4",   # Violet doux pour les labels
    "accent": "#9D41E8",           # Violet vif pour les accents
    "gold": "#FFC700",             # Or pour le badge
    "inner_card": "#FAF5FF",        # Fond des blocs de stats
    "progress_bar_bg": "#EADBF9"
}

async def create_profile_card(user_data: dict) -> io.BytesIO:
    """Génère une carte de profil premium avec l'identité visuelle de LaFoncedalle."""

    def _generate():
        # --- Chargement des polices ---
        fonts = {}
        try:
            font_paths = {
                "bold": os.path.join(ASSETS_DIR, "Gobold Bold.otf"),
                "regular": os.path.join(ASSETS_DIR, "Gobold Regular.otf"),
                "light": os.path.join(ASSETS_DIR, "Gobold Light.otf"),
                "emoji": os.path.join(ASSETS_DIR, "NotoColorEmoji-Regular.ttf"),
            }
            fonts['name'] = ImageFont.truetype(font_paths['bold'], 70)
            fonts['title'] = ImageFont.truetype(font_paths['bold'], 38)
            fonts['regular_l'] = ImageFont.truetype(font_paths['regular'], 32)
            fonts['regular_s'] = ImageFont.truetype(font_paths['regular'], 28)
            fonts['light'] = ImageFont.truetype(font_paths['light'], 22)
            fonts['emoji'] = ImageFont.truetype(font_paths['emoji'], 30)
        except Exception as e:
            print(f"ERREUR CRITIQUE [ImageGen]: Polices introuvables. {e}")
            traceback.print_exc()
            return None

        # --- Création du fond avec watermark ---
        bg = Image.new("RGBA", (1200, 600), COLORS["background"])
        try:
            watermark_logo = Image.open(os.path.join(ASSETS_DIR, "logo_rond.png")).convert("RGBA")
            watermark_logo = watermark_logo.resize((800, 800), Image.Resampling.LANCZOS)
            alpha = watermark_logo.getchannel('A')
            alpha = Image.eval(alpha, lambda p: p // 12) # Opacité ~8%
            watermark_logo.putalpha(alpha)
            bg.paste(watermark_logo, (200, -100), watermark_logo)
        except FileNotFoundError:
            print("WARNING [ImageGen]: 'logo_rond.png' non trouvé pour le watermark.")

        draw = ImageDraw.Draw(bg)
        draw.rounded_rectangle((40, 40, 1160, 560), fill=COLORS["card"], radius=30)
        
        # --- Blocs internes pour les statistiques ---
        draw.rounded_rectangle((60, 260, 580, 540), fill=COLORS["inner_card"], radius=20)
        draw.rounded_rectangle((620, 260, 1140, 540), fill=COLORS["inner_card"], radius=20)

        # --- Helper pour dessiner une ligne de stat parfaitement alignée ---
        def draw_stat_line(y, icon, label, value, col_base_x, col_width):
            icon_x = col_base_x + 30
            label_x = icon_x + 50
            value_x = col_base_x + col_width - 30
            draw.text((icon_x, y), icon, font=fonts['emoji'], embedded_color=True, anchor="lm")
            draw.text((label_x, y), label, font=fonts['regular_s'], fill=COLORS["secondary_text"], anchor="lm")
            draw.text((value_x, y), str(value), font=fonts['regular_l'], fill=COLORS["primary_text"], anchor="rm")
        
        def draw_progress_bar(x, y, width, height, progress):
            draw.rounded_rectangle((x, y, x + width, y + height), fill=COLORS["progress_bar_bg"], radius=height//2)
            if progress > 0:
                fill_width = int(width * progress)
                draw.rounded_rectangle((x, y, x + fill_width, y + height), fill=COLORS["accent"], radius=height//2)

        # --- Avatar ---
        avatar_pos, avatar_size = (80, 70), (180, 180)
        try:
            draw.ellipse((avatar_pos[0]-6, avatar_pos[1]-6, avatar_pos[0]+avatar_size[0]+6, avatar_pos[1]+avatar_size[1]+6), fill=COLORS["accent"])
            avatar_url = user_data.get("avatar_url")
            response_content = requests.get(avatar_url, stream=True).content
            avatar_image = Image.open(io.BytesIO(response_content)).convert("RGBA")
            mask = Image.new("L", avatar_size, 0)
            ImageDraw.Draw(mask).ellipse((0, 0) + avatar_size, fill=255)
            avatar = ImageOps.fit(avatar_image, mask.size, centering=(0.5, 0.5))
            bg.paste(avatar, avatar_pos, mask)
        except Exception:
            draw.ellipse((avatar_pos[0], avatar_pos[1], avatar_pos[0]+avatar_size[0], avatar_pos[1]+avatar_size[1]), fill=COLORS["secondary_text"])

        # --- Nom, ligne de séparation et badge ---
        user_name = user_data.get("name", "Utilisateur").split("#")[0].upper()
        draw.text((300, 110), user_name, font=fonts['name'], fill=COLORS["primary_text"], anchor="lt")
        draw.line([(300, 190), (1120, 190)], fill=COLORS["accent"], width=3)
        if user_data.get('is_top_3_monthly'):
            badge_text = "Top Noteur du Mois"
            text_width = draw.textlength(badge_text, font=fonts['regular_s'])
            draw.rounded_rectangle((300, 205, 300 + text_width + 50, 245), fill=COLORS["gold"], radius=8)
            draw.text((300 + 20, 225), "🏅", font=fonts['emoji'], embedded_color=True, anchor="lm")
            draw.text((300 + 55, 225), badge_text, font=fonts['regular_s'], fill="#4A2B00", anchor="lm")

        # --- Bloc 1: Activité Boutique ---
        col1_x, col1_y, col1_width = 60, 260, 520
        draw.text((col1_x + 30, col1_y + 40), "Activité Boutique", font=fonts['title'], fill=COLORS["primary_text"], anchor="lt")
        draw.line([(col1_x + 30, col1_y + 80), (col1_x + col1_width - 30, col1_y + 80)], fill=COLORS["accent"], width=2)
        
        if user_data.get("purchase_count", 0) > 0:
            draw_stat_line(col1_y + 130, "🛍️", "Commandes", user_data.get('purchase_count', 0), col1_x, col1_width)
            draw_stat_line(col1_y + 190, "💶", "Total Dépensé", f"{user_data.get('total_spent', 0):.2f} €", col1_x, col1_width)
        else:
            draw.text((col1_x + col1_width/2, col1_y + 180), "Aucune activité sur la boutique", font=fonts['regular_l'], fill=COLORS["secondary_text"], anchor="mm")

        # --- Bloc 2: Activité Discord ---
        col2_x, col2_y, col2_width = 620, 260, 520
        draw.text((col2_x + 30, col2_y + 40), "Activité Discord", font=fonts['title'], fill=COLORS["primary_text"], anchor="lt")
        draw.line([(col2_x + 30, col2_y + 80), (col2_x + col2_width - 30, col2_y + 80)], fill=COLORS["accent"], width=2)

        if user_data.get('count', 0) > 0:
            avg_note = user_data.get('avg', 0)
            min_max_str = f"{user_data.get('min_note', 0):.2f} / {user_data.get('max_note', 0):.2f}"
            draw_stat_line(col2_y + 120, "📝", "Notes Données", user_data.get('count', 0), col2_x, col2_width)
            draw_stat_line(col2_y + 170, "📊", "Moyenne", f"{avg_note:.2f} / 10", col2_x, col2_width)
            draw_progress_bar(col2_x + 30, col2_y + 205, col2_width - 60, 15, avg_note / 10) # Ajout de la barre
            draw_stat_line(col2_y + 250, "↕️", "Note Min / Max", min_max_str, col2_x, col2_width)
        else:
            draw.text((col2_x + col2_width/2, col2_y + 180), "Aucune note enregistrée", font=fonts['regular_l'], fill=COLORS["secondary_text"], anchor="mm")

        # --- Footer ---
        try:
            footer_logo = Image.open(os.path.join(ASSETS_DIR, "logo_rect.png")).convert("RGBA")
            footer_logo.thumbnail((200, 50), Image.Resampling.LANCZOS)
            bg.paste(footer_logo, (920, 490), footer_logo)
        except FileNotFoundError:
            draw.text((1140, 540), "Généré par LaFoncedalleBot", font=fonts['light'], fill=COLORS['secondary_text'], anchor="rs")

        buffer = io.BytesIO()
        bg.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

    return await asyncio.to_thread(_generate)