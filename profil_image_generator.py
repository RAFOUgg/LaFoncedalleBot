# Dans un nouveau fichier image_generator.py ou dans un fichier utilitaire

from PIL import Image, ImageDraw, ImageFont, ImageOps
import requests
import io

async def create_profile_card(user_data: dict) -> io.BytesIO:
    """Génère une carte de profil en image et la retourne sous forme de bytes."""

    # --- Configuration ---
    # Vous pouvez télécharger une police comme "Montserrat" ou "Roboto" sur Google Fonts
    # et la mettre dans le même dossier que votre script.
    try:
        font_bold = ImageFont.truetype("your-font-bold.ttf", 40)
        font_regular = ImageFont.truetype("your-font-regular.ttf", 30)
        font_small = ImageFont.truetype("your-font-regular.ttf", 24)
    except IOError: # Police non trouvée, on utilise la police par défaut
        font_bold = ImageFont.load_default()
        font_regular = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Créer une image de fond. Vous pouvez utiliser une image de fond personnalisée.
    # bg = Image.open("background.png").convert("RGBA")
    # Pour l'exemple, on crée un fond uni.
    bg = Image.new("RGBA", (1000, 400), (27, 27, 31))
    draw = ImageDraw.Draw(bg)

    # --- Avatar ---
    try:
        # Télécharger l'avatar de l'utilisateur
        avatar_url = user_data.get("avatar_url")
        response = requests.get(avatar_url, stream=True)
        response.raise_for_status()
        avatar_image = Image.open(io.BytesIO(response.content)).convert("RGBA")
        
        # Créer un masque rond pour l'avatar
        size = (180, 180)
        mask = Image.new("L", size, 0)
        draw_mask = ImageDraw.Draw(mask)
        draw_mask.ellipse((0, 0) + size, fill=255)
        
        # Appliquer le masque
        avatar = ImageOps.fit(avatar_image, mask.size, centering=(0.5, 0.5))
        avatar.putalpha(mask)
        
        bg.paste(avatar, (50, 50), avatar)
    except Exception as e:
        print(f"Erreur chargement avatar: {e}")


    # --- Textes ---
    draw.text((270, 70), user_data.get("name"), font=font_bold, fill=(255, 255, 255))

    # Stats Discord
    draw.text((270, 150), "Activité Discord", font=font_regular, fill=(180, 180, 180))
    rank_text = f"Classement : #{user_data.get('rank', 'N/C')}"
    notes_text = f"Notes : {user_data.get('count', 0)}"
    avg_text = f"Moyenne : {user_data.get('avg', 0):.2f}/10"
    draw.text((270, 200), rank_text, font=font_small, fill=(255, 255, 255))
    draw.text((270, 240), notes_text, font=font_small, fill=(255, 255, 255))
    draw.text((270, 280), avg_text, font=font_small, fill=(255, 255, 255))

    # Stats Boutique
    draw.text((600, 150), "Activité Boutique", font=font_regular, fill=(180, 180, 180))
    if user_data.get("purchase_count") is not None:
        orders_text = f"Commandes : {user_data.get('purchase_count', 0)}"
        spent_text = f"Dépensé : {user_data.get('total_spent', 0):.2f} €"
        draw.text((600, 200), orders_text, font=font_small, fill=(255, 255, 255))
        draw.text((600, 240), spent_text, font=font_small, fill=(255, 255, 255))
    else:
        draw.text((600, 200), "Compte non lié", font=font_small, fill=(255, 180, 180))


    # --- Sauvegarde en mémoire ---
    buffer = io.BytesIO()
    bg.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer