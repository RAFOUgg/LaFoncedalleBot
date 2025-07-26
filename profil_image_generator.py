# Fichier : profil_image_generator.py (Version finale avec maquette et badge de rang)

from PIL import Image, ImageDraw, ImageFont, ImageOps
import requests
import io
import os
import asyncio
import traceback

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

# --- Palette de couleurs basée sur la maquette ---
COLORS = {
    "background": "#FFFFFF",
    "card": "#A445E8",
    "primary_text": "#FFFFFF",
    "secondary_text": (255, 255, 255, 180),
    "accent": "#FFFFFF",
    "inner_card": "#FFFFFF",
    "text_on_white": "#4A007B",
    "label_on_white": "#A37FC4",
    "gold": {"bg": "#FFC700", "text": "#4D3800"},
    "silver": {"bg": "#D1D1D1", "text": "#3D3D3D"},
    "bronze": {"bg": "#E29F6E", "text": "#502E15"},
}

async def create_profile_card(user_data: dict) -> io.BytesIO:
    def _generate():
        fonts = {}
        try:
            font_paths = { "bold": os.path.join(ASSETS_DIR, "Gobold Bold.otf"), "regular": os.path.join(ASSETS_DIR, "Gobold Regular.otf"), "light": os.path.join(ASSETS_DIR, "Gobold Light.otf"), "emoji": os.path.join(ASSETS_DIR, "NotoColorEmoji-Regular.ttf"), }
            fonts.update({ 'name': ImageFont.truetype(font_paths['bold'], 70), 'title': ImageFont.truetype(font_paths['bold'], 30), 'regular_l': ImageFont.truetype(font_paths['regular'], 32), 'regular_s': ImageFont.truetype(font_paths['regular'], 28), 'light': ImageFont.truetype(font_paths['light'], 22), 'emoji': ImageFont.truetype(font_paths['emoji'], 30), })
        except Exception as e:
            print(f"ERREUR [ImageGen]: Polices introuvables. {e}"); traceback.print_exc(); return None

        bg = Image.new("RGBA", (1200, 600), COLORS["background"])
        draw = ImageDraw.Draw(bg)
        draw.rounded_rectangle((40, 40, 1160, 560), fill=COLORS["card"], radius=30)
        draw.rounded_rectangle((60, 280, 580, 540), fill=COLORS["inner_card"], radius=20)
        draw.rounded_rectangle((620, 280, 1140, 540), fill=COLORS["inner_card"], radius=20)

        # --- Helper pour dessiner une stat sur fond blanc ---
        def draw_stat_line(y, icon, label, value, col_base_x):
            draw.text((col_base_x + 30, y), icon, font=fonts['emoji'], embedded_color=True, anchor="lm")
            draw.text((col_base_x + 80, y), label, font=fonts['regular_s'], fill=COLORS["label_on_white"], anchor="lm")
            draw.text((col_base_x + 500, y), str(value), font=fonts['regular_l'], fill=COLORS["text_on_white"], anchor="rm")

        # --- Avatar ---
        avatar_pos, avatar_size = (80, 70), (180, 180)
        try:
            draw.ellipse((avatar_pos[0]-6, avatar_pos[1]-6, avatar_pos[0]+avatar_size[0]+6, avatar_pos[1]+avatar_size[1]+6), fill=COLORS["accent"])
            avatar_image = Image.open(io.BytesIO(requests.get(user_data.get("avatar_url"), stream=True).content)).convert("RGBA")
            mask = Image.new("L", avatar_size, 0); ImageDraw.Draw(mask).ellipse((0, 0) + avatar_size, fill=255)
            avatar = ImageOps.fit(avatar_image, mask.size, centering=(0.5, 0.5))
            bg.paste(avatar, avatar_pos, mask)
        except Exception: draw.ellipse((avatar_pos[0], avatar_pos[1], avatar_pos[0]+avatar_size[0], avatar_pos[1]+avatar_size[1]), fill=COLORS["secondary_text"])

        # --- Nom, ligne de séparation et logo d'angle ---
        user_name = user_data.get("name", "Utilisateur").split("#")[0].upper()
        draw.text((300, 110), user_name, font=fonts['name'], fill=COLORS["primary_text"], anchor="lt")
        draw.line([(300, 190), (1120, 190)], fill=COLORS["accent"], width=3)
        try:
            corner_logo = Image.open(os.path.join(ASSETS_DIR, "logo_rond.png")).convert("RGBA"); corner_logo.thumbnail((120, 120), Image.Resampling.LANCZOS)
            bg.paste(corner_logo, (1010, 60), corner_logo)
        except FileNotFoundError: print("WARNING [ImageGen]: 'logo_rond.png' non trouvé.")

        # --- Badge de Rang Dynamique ---
        monthly_rank = user_data.get('monthly_rank')
        if monthly_rank:
            badge_info = { 1: ("🥇 Top Noteur OR", COLORS["gold"]), 2: ("🥈 Top Noteur ARGENT", COLORS["silver"]), 3: ("🥉 Top Noteur BRONZE", COLORS["bronze"]) }
            badge_text, colors = badge_info.get(monthly_rank)
            text_width = draw.textlength(badge_text, font=fonts['regular_s'])
            draw.rounded_rectangle((300, 205, 300 + text_width + 40, 245), fill=colors["bg"], radius=8)
            draw.text((300 + 20, 225), badge_text, font=fonts['regular_s'], fill=colors["text"], anchor="lm")

        # --- Bloc 1: Activité Boutique ---
        col1_x, col1_y = 60, 280
        draw.text((col1_x + 30, col1_y + 40), "Activité Boutique", font=fonts['title'], fill=COLORS["text_on_white"], anchor="lt")
        draw.line([(col1_x + 30, col1_y + 80), (col1_x + 500, col1_y + 80)], fill=COLORS["label_on_white"], width=2)
        if user_data.get("purchase_count", 0) > 0:
            draw_stat_line(col1_y + 130, "🛍️", "Commandes", user_data.get('purchase_count', 0), col1_x)
            draw_stat_line(col1_y + 190, "💶", "Total Dépensé", f"{user_data.get('total_spent', 0):.2f} €", col1_x)
        else:
            draw.text((col1_x + 260, col1_y + 180), "Aucune activité", font=fonts['regular_l'], fill=COLORS["label_on_white"], anchor="mm")

        # --- Bloc 2: Activité Discord ---
        col2_x, col2_y = 620, 280
        draw.text((col2_x + 30, col2_y + 40), "Activité Discord", font=fonts['title'], fill=COLORS["text_on_white"], anchor="lt")
        draw.line([(col2_x + 30, col2_y + 80), (col2_x + 500, col2_y + 80)], fill=COLORS["label_on_white"], width=2)
        if user_data.get('count', 0) > 0:
            avg_note, min_max_str = user_data.get('avg', 0), f"{user_data.get('min_note', 0):.2f} / {user_data.get('max_note', 0):.2f}"
            draw_stat_line(col2_y + 130, "📝", "Notes Données", user_data.get('count', 0), col2_x)
            draw_stat_line(col2_y + 190, "📊", "Moyenne", f"{avg_note:.2f} / 10", col2_x)
        else:
            draw.text((col2_x + 260, col2_y + 180), "Aucune note enregistrée", font=fonts['regular_l'], fill=COLORS["label_on_white"], anchor="mm")
        
        buffer = io.BytesIO()
        bg.save(buffer, format="PNG"); buffer.seek(0)
        return buffer

    return await asyncio.to_thread(_generate)