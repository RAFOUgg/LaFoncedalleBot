import os
import sqlite3
import random
import time
import threading
import asyncio
import traceback # Ajouté pour un meilleur logging d'erreur

# Imports pour l'e-mail
import smtplib, ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header # [CORRECTION] Importé pour gérer l'encodage du sujet

# Imports Flask et Shopify
from flask import Flask, request, jsonify
import shopify
from dotenv import load_dotenv
from datetime import datetime, timedelta

# [CORRECTION] Import des variables depuis config.py et catalogue_final pour le bot



# --- Initialisation : Charger les clés secrètes depuis les variables d'environnement ---
load_dotenv()
app = Flask(__name__)
FLASK_SECRET_KEY = os.getenv('FLASK_SECRET_KEY') # On lit la variable
app.secret_key = FLASK_SECRET_KEY # On l'assigne à l'application
SHOP_URL = os.getenv('SHOPIFY_SHOP_URL')
SHOPIFY_API_VERSION = os.getenv('SHOPIFY_API_VERSION')

# Récupération des secrets depuis les variables d'environnement SMTP
DB_FILE = "/app/ratings.db"
SENDER_EMAIL = os.getenv('SENDER_EMAIL')
INFOMANIAK_APP_PASSWORD = os.getenv('INFOMANIAK_APP_PASSWORD')
SHOPIFY_ADMIN_ACCESS_TOKEN = os.getenv('SHOPIFY_ADMIN_ACCESS_TOKEN')

# On utilise le même chemin que le bot pour avoir une seule DB
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# --- Initialisation de la Base de Données ---
def initialize_db():
    """Initialise les tables pour la liaison de comptes dans la DB partagée."""
    print(f"INFO: Initialisation des tables de liaison dans la base de données: {DB_FILE}")
    conn = sqlite3.connect(DB_FILE) # [CORRECTION] Utilise la DB partagée
    cursor = conn.cursor()
    # Ces tables seront ajoutées à ratings.db si elles n'existent pas
    cursor.execute("CREATE TABLE IF NOT EXISTS user_links (discord_id TEXT PRIMARY KEY, user_email TEXT NOT NULL UNIQUE);")
    cursor.execute("CREATE TABLE IF NOT EXISTS verification_codes (discord_id TEXT PRIMARY KEY, user_email TEXT NOT NULL, code TEXT NOT NULL, expires_at INTEGER NOT NULL);")
    conn.commit()
    conn.close()

initialize_db()


# --- Routes de l'API ---

@app.route('/')
def health_check():
    return "L'application pont Shopify-Discord est en ligne.", 200


@app.route('/debug-filesystem')
def debug_filesystem():
    """
    Endpoint temporaire pour diagnostiquer l'état du système de fichiers
    à l'intérieur du conteneur Render.
    """
    base_path = '/app'
    assets_path = os.path.join(base_path, 'assets')
    font_path = os.path.join(assets_path, 'Gobold-Bold.ttf') # On teste avec une police

    results = {
        "1_current_working_directory": os.getcwd(),
        "2_base_path_contents": [],
        "3_assets_dir_exists": os.path.exists(assets_path),
        "4_assets_dir_contents": [],
        "5_font_file_exists": os.path.exists(font_path),
        "6_font_file_readable": False,
        "7_error_log": None
    }

    try:
        results["2_base_path_contents"] = os.listdir(base_path)
        if results["3_assets_dir_exists"]:
            results["4_assets_dir_contents"] = os.listdir(assets_path)
        if results["5_font_file_exists"]:
            with open(font_path, 'rb') as f:
                results["6_font_file_readable"] = True # Si on arrive ici, le fichier est lisible
    except Exception as e:
        results["7_error_log"] = traceback.format_exc()

    return jsonify(results)


@app.route('/api/start-verification', methods=['POST'])
def start_verification():
    data = request.json
    discord_id, email = data.get('discord_id'), data.get('email')
    if not all([discord_id, email]): return jsonify({"error": "Données manquantes."}), 400

    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor() # [CORRECTION] Utilise la DB partagée
    cursor.execute("SELECT user_email FROM user_links WHERE discord_id = ?", (discord_id,))
    if cursor.fetchone(): conn.close(); return jsonify({"error": "Ce compte Discord est déjà lié."}), 409
    cursor.execute("SELECT discord_id FROM user_links WHERE user_email = ?", (email,))
    if cursor.fetchone(): conn.close(); return jsonify({"error": "Cet e-mail est déjà utilisé."}), 409
    
    code = str(random.randint(100000, 999999))
    expires_at = int(time.time()) + 600

    message = MIMEMultipart("alternative")

    sujet = "Votre code de vérification LaFoncedalle"
    # Format "Nom <email@adresse.com>" recommandé
    expediteur_formate = f"LaFoncedalle <{SENDER_EMAIL}>" 
    
    message["Subject"] = Header(sujet, 'utf-8')
    message["From"] = expediteur_formate # Utiliser la version formatée
    message["To"] = email
    html_body = f'Bonjour !<br>Voici votre code de vérification : <strong>{code}</strong><br>Ce code expire dans 10 minutes.'
    message.attach(MIMEText(html_body, "html", "utf-8"))
    
    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL("mail.infomaniak.com", 465, context=context) as server:
            # L'erreur se produit FORCÉMENT sur l'une de ces deux lignes
            server.login(SENDER_EMAIL, INFOMANIAK_APP_PASSWORD) 
            server.sendmail(SENDER_EMAIL, email, message.as_string())
        print(f"E-mail de vérification envoyé avec succès à {email}")
    except Exception as e:
        # CE BLOC EST EXÉCUTÉ
        print(f"ERREUR SMTP CRITIQUE: {e}") 
        traceback.print_exc() 
        return jsonify({"error": "Impossible d'envoyer l'e-mail de vérification."}), 500

    cursor.execute("INSERT OR REPLACE INTO verification_codes VALUES (?, ?, ?, ?)", (discord_id, email, code, expires_at))
    conn.commit(); conn.close()
    return jsonify({"success": True}), 200

@app.route('/api/add-comment', methods=['POST'])
def add_comment():
    data = request.json
    user_id = data.get('user_id')
    product_name = data.get('product_name')
    comment_text = data.get('comment')

    if not all([user_id, product_name, comment_text]):
        return jsonify({"error": "Données manquantes pour ajouter le commentaire."}), 400

    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("""
            UPDATE ratings 
            SET comment = ? 
            WHERE user_id = ? AND product_name = ?
        """, (comment_text, user_id, product_name))
        conn.commit()
        
        # On vérifie si une ligne a bien été modifiée
        if conn.total_changes == 0:
            conn.close()
            return jsonify({"error": "Aucune note correspondante à mettre à jour."}), 404
            
        conn.close()
        print(f"INFO: Commentaire ajouté pour {user_id} sur le produit {product_name}")
        return jsonify({"success": True}), 200
    except Exception as e:
        print(f"Erreur SQL lors de l'ajout du commentaire : {e}")
        traceback.print_exc()
        return jsonify({"error": "Erreur lors de la sauvegarde du commentaire."}), 500
    
@app.route('/api/confirm-verification', methods=['POST'])
def confirm_verification():
    data = request.json
    discord_id = data.get('discord_id')
    code = data.get('code')

    conn = sqlite3.connect(DB_FILE) # [CORRECTION] Utilise la DB partagée
    cursor = conn.cursor()
    cursor.execute("SELECT user_email, expires_at FROM verification_codes WHERE discord_id = ? AND code = ?", (discord_id, code))
    result = cursor.fetchone()

    if not result:
        conn.close()
        return jsonify({"error": "Code invalide ou expiré."}), 400
    
    user_email, expires_at = result
    if time.time() > expires_at:
        conn.close()
        return jsonify({"error": "Le code de vérification a expiré."}), 400
        
    cursor.execute("INSERT OR REPLACE INTO user_links (discord_id, user_email) VALUES (?, ?)", (discord_id, user_email))
    cursor.execute("DELETE FROM verification_codes WHERE discord_id = ?", (discord_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True}), 200

@app.route('/api/unlink', methods=['POST'])
def unlink_account():
    data = request.json
    discord_id = data.get('discord_id')
    if not discord_id: return jsonify({"error": "ID Discord manquant."}), 400

    conn = sqlite3.connect(DB_FILE) # [CORRECTION] Utilise la DB partagée
    cursor = conn.cursor()
    cursor.execute("SELECT user_email FROM user_links WHERE discord_id = ?", (discord_id,))
    result = cursor.fetchone()

    if not result:
        conn.close()
        return jsonify({"error": "Aucun compte n'est lié à cet ID Discord."}), 404

    cursor.execute("DELETE FROM user_links WHERE discord_id = ?", (discord_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "unlinked_email": result[0]}), 200

@app.route('/api/force-link', methods=['POST'])
def force_link():
    # [CORRECTION] Ajout d'une protection par clé secrète sur cet endpoint sensible
    auth_header = request.headers.get('Authorization')
    expected_header = f"Bearer {FLASK_SECRET_KEY}"

    if not auth_header or auth_header != expected_header:
        return jsonify({"error": "Accès non autorisé."}), 403

    data = request.json
    discord_id = data.get('discord_id')
    email = data.get('email')

    if not all([discord_id, email]):
        return jsonify({"error": "ID Discord ou e-mail manquant."}), 400

    conn = sqlite3.connect(DB_FILE) # [CORRECTION] Utilise la DB partagée
    cursor = conn.cursor()
    
    cursor.execute("INSERT OR REPLACE INTO user_links (discord_id, user_email) VALUES (?, ?)", (discord_id, email))
    cursor.execute("DELETE FROM verification_codes WHERE discord_id = ?", (discord_id,))
    
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "message": f"Compte {discord_id} forcé à être lié à {email}."}), 200

@app.route('/api/get_purchased_products/<discord_id>')
def get_purchased_products(discord_id):
    conn = sqlite3.connect(DB_FILE) # [CORRECTION] Utilise la DB partagée
    cursor = conn.cursor()
    cursor.execute("SELECT user_email FROM user_links WHERE discord_id = ?", (discord_id,))
    result = cursor.fetchone()
    conn.close()

    if not result:
        return jsonify({"error": "user_not_linked"}), 404

    user_email = result[0]
    session = shopify.Session(SHOP_URL, SHOPIFY_API_VERSION, SHOPIFY_ADMIN_ACCESS_TOKEN)
    shopify.ShopifyResource.activate_session(session)
    
    try:
        orders = shopify.Order.find(email=user_email, status='any', limit=250)
        purchased_products = {item.title for order in orders for item in order.line_items}
        purchase_count = len(orders)
        total_spent = sum(float(order.total_price) for order in orders)
    except Exception as e:
        print(f"Erreur API Shopify: {e}")
        return jsonify({"error": "Erreur lors de la récupération des commandes."}), 500
    finally:
        shopify.ShopifyResource.clear_session()

    return jsonify({
        "products": list(purchased_products),
        "purchase_count": purchase_count,
        "total_spent": total_spent
    })
@app.route('/api/submit-rating', methods=['POST'])
def submit_rating():
    data = request.json
    required_keys = ['user_id', 'user_name', 'product_name', 'scores']
    if not all(key in data for key in required_keys):
        return jsonify({"error": "Données manquantes."}), 400

    # On récupère toutes les données du payload
    user_id = data['user_id']
    user_name = data['user_name']
    product_name = data['product_name']
    scores = data['scores']
    comment_text = data.get('comment')  # .get() pour gérer le cas où le commentaire est optionnel

    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("""
            INSERT OR REPLACE INTO ratings 
            (user_id, user_name, product_name, visual_score, smell_score, touch_score, taste_score, effects_score, rating_timestamp, comment) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, user_name, product_name, 
            scores.get('visual'), scores.get('smell'), scores.get('touch'), 
            scores.get('taste'), scores.get('effects'), 
            datetime.utcnow().isoformat(), comment_text
        ))
        conn.commit()
        conn.close()
        print(f"INFO: Note enregistrée pour {user_name} sur le produit {product_name}")
        return jsonify({"success": True}), 200
    except Exception as e:
        print(f"Erreur SQL lors de l'enregistrement de la note : {e}")
        traceback.print_exc()
        return jsonify({"error": "Erreur lors de la sauvegarde de la note."}), 500

# --- AJOUTER CET ENDPOINT ÉGALEMENT ---
@app.route('/api/get_user_stats/<discord_id>')
def get_user_stats(discord_id):
    try:
        user_id_int = int(discord_id)
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Récupérer les notes de l'utilisateur
        c.execute("SELECT * FROM ratings WHERE user_id = ? ORDER BY rating_timestamp DESC", (user_id_int,))
        user_ratings = [dict(row) for row in c.fetchall()]

        # Calculer les statistiques
        c.execute("""
            WITH UserAverageNotes AS (
                SELECT user_id, 
                       (COALESCE(visual_score, 0) + COALESCE(smell_score, 0) + COALESCE(touch_score, 0) + COALESCE(taste_score, 0) + COALESCE(effects_score, 0)) / 5.0 AS avg_note
                FROM ratings
            ), AllRanks AS (
                SELECT user_id, 
                       COUNT(user_id) as rating_count, 
                       AVG(avg_note) as global_avg, 
                       MIN(avg_note) as min_note, 
                       MAX(avg_note) as max_note,
                       RANK() OVER (ORDER BY COUNT(user_id) DESC, AVG(avg_note) DESC) as user_rank
                FROM UserAverageNotes 
                GROUP BY user_id
            )
            SELECT user_rank, rating_count, global_avg, min_note, max_note
            FROM AllRanks 
            WHERE user_id = ?
        """, (user_id_int,))
        stats_row = c.fetchone()
        
        user_stats = {'rank': 'N/C', 'count': 0, 'avg': 0, 'min_note': 0, 'max_note': 0}
        if stats_row:
            user_stats.update(dict(zip(stats_row.keys(), stats_row)))

        # Badge Top 3 du mois
        one_month_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
        c.execute("SELECT user_id FROM ratings WHERE rating_timestamp >= ? GROUP BY user_id ORDER BY COUNT(id) DESC LIMIT 3", (one_month_ago,))
        top_3_monthly_ids = [row['user_id'] for row in c.fetchall()]
        user_stats['is_top_3_monthly'] = user_id_int in top_3_monthly_ids

        conn.close()
        
        return jsonify({
            "user_stats": user_stats,
            "user_ratings": user_ratings
        })
    except Exception as e:
        print(f"Erreur lors de la récupération des stats pour {discord_id}: {e}")
        return jsonify({"error": "Erreur interne du serveur."}), 500


if __name__ == '__main__':
    app.run(port=5000, debug=True)