import os
import sqlite3
import random
import time
import threading
import asyncio
import traceback # Ajouté pour un meilleur logging d'erreur
import base64

# Imports pour l'e-mail
import smtplib, ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header # [CORRECTION] Importé pour gérer l'encodage du sujet
import csv
import io
from email.mime.application import MIMEApplication
# Imports Flask et Shopify
from flask import Flask, request, jsonify
import shopify
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import json
from shared_utils import Logger, DB_FILE, anonymize_email
# [CORRECTION] Import des variables depuis config.py et catalogue_final pour le bot



# --- Initialisation : Charger les clés secrètes depuis les variables d'environnement ---
load_dotenv()
app = Flask(__name__)
FLASK_SECRET_KEY = os.getenv('FLASK_SECRET_KEY') # On lit la variable
app.secret_key = FLASK_SECRET_KEY # On l'assigne à l'application
SHOP_URL = os.getenv('SHOPIFY_SHOP_URL')
SHOPIFY_API_VERSION = os.getenv('SHOPIFY_API_VERSION')

# Récupération des secrets depuis les variables d'environnement SMTP
SENDER_EMAIL = os.getenv('SENDER_EMAIL')
INFOMANIAK_APP_PASSWORD = os.getenv('INFOMANIAK_APP_PASSWORD')
SHOPIFY_ADMIN_ACCESS_TOKEN = os.getenv('SHOPIFY_ADMIN_ACCESS_TOKEN')

# On utilise le même chemin que le bot pour avoir une seule DB
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
paris_tz = timezone(timedelta(hours=2))

CLAIMED_WELCOME_CODES_FILE = os.path.join(BASE_DIR, "claimed_welcome_codes.json")
WELCOME_CODES_FILE = os.path.join(BASE_DIR, "welcome_codes.txt")

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

@app.route('/api/export-customers', methods=['POST'])
def export_customers():
    # --- SÉCURITÉ MAXIMUM ---
    auth_header = request.headers.get('Authorization')
    expected_header = f"Bearer {FLASK_SECRET_KEY}"
    if not auth_header or auth_header != expected_header:
        return jsonify({"error": "Accès non autorisé."}), 403

    admin_email = os.getenv('ADMIN_EMAIL')
    if not admin_email:
        Logger.error("ADMIN_EMAIL n'est pas configuré dans les variables d'environnement.")
        return jsonify({"error": "L'adresse e-mail de l'administrateur n'est pas configurée."}), 500

    try:
        # --- CONNEXION À SHOPIFY ---
        session = shopify.Session(SHOP_URL, SHOPIFY_API_VERSION, SHOPIFY_ADMIN_ACCESS_TOKEN)
        shopify.ShopifyResource.activate_session(session)
        
        customers = shopify.Customer.find(limit=250)
        # Note : Pour plus de 250 clients, il faudrait implémenter une pagination.
        
        if not customers:
            return jsonify({"success": True, "message": "Aucun client trouvé à exporter."}), 200

        # --- GÉNÉRATION DU FICHIER CSV EN MÉMOIRE ---
        output = io.StringIO()
        writer = csv.writer(output)
        
        # En-têtes du CSV
        writer.writerow(['ID Client', 'Prénom', 'Nom', 'Email', 'Nombre de Commandes', 'Total Dépensé', 'Date de Création'])

        for customer in customers:
            writer.writerow([
                customer.id,
                customer.first_name,
                customer.last_name,
                customer.email,
                customer.orders_count,
                customer.total_spent,
                customer.created_at
            ])
        
        csv_data = output.getvalue()
        output.close()
        
        # --- ENVOI DE L'E-MAIL AVEC LE CSV EN PIÈCE JOINTE ---
        message = MIMEMultipart()
        sujet = f"Export des clients Shopify - {datetime.now(paris_tz).strftime('%Y-%m-%d %H:%M')}"
        message["Subject"] = Header(sujet, 'utf-8')
        message["From"] = f"LaFoncedalleBot <{SENDER_EMAIL}>"
        message["To"] = admin_email
        
        message.attach(MIMEText("Veuillez trouver ci-joint l'export de la base de données clients Shopify.", "plain", "utf-8"))
        
        attachment = MIMEApplication(csv_data.encode('utf-8'), _subtype='csv')
        attachment.add_header('Content-Disposition', 'attachment', filename="export_clients_shopify.csv")
        message.attach(attachment)

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("mail.infomaniak.com", 465, context=context) as server:
            server.login(SENDER_EMAIL, INFOMANIAK_APP_PASSWORD)
            server.sendmail(SENDER_EMAIL, admin_email, message.as_string())

        Logger.success(f"Export clients envoyé avec succès à {admin_email}.")
        return jsonify({"success": True, "customer_count": len(customers)}), 200

    except Exception as e:
        Logger.error(f"Erreur critique lors de l'export des clients : {e}")
        traceback.print_exc()
        return jsonify({"error": "Une erreur est survenue lors de la génération de l'export."}), 500
    finally:
        if 'shopify' in locals() and shopify.ShopifyResource.get_session():
            shopify.ShopifyResource.clear_session()
            
@app.route('/api/start-verification', methods=['POST'])
def start_verification():
    force = request.args.get('force', 'false').lower() == 'true'
    data = request.json
    discord_id, email = data.get('discord_id'), data.get('email')

    if not all([discord_id, email]): return jsonify({"error": "Données manquantes."}), 400

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    if not force:
        cursor.execute("SELECT user_email FROM user_links WHERE discord_id = ?", (discord_id,))
        result = cursor.fetchone()
        if result:
            anonymized_email = anonymize_email(result[0])
            conn.close()
            return jsonify({"status": "conflict", "existing_email": anonymized_email}), 409

    # ... (Le reste de la fonction pour envoyer l'email est inchangé)
    cursor.execute("SELECT discord_id FROM user_links WHERE user_email = ?", (email,))
    if cursor.fetchone(): conn.close(); return jsonify({"error": "Cet e-mail est déjà utilisé par un autre compte."}), 409
    
    code = str(random.randint(100000, 999999))
    expires_at = int(time.time()) + 600
    message = MIMEMultipart("alternative")
    sujet = "Votre code de vérification LaFoncedalle"
    expediteur_formate = f"LaFoncedalle <{SENDER_EMAIL}>" 
    message["Subject"] = Header(sujet, 'utf-8')
    message["From"] = expediteur_formate
    message["To"] = email
    html_body = f'Bonjour !<br>Voici votre code de vérification : <strong>{code}</strong><br>Ce code expire dans 10 minutes.'
    message.attach(MIMEText(html_body, "html", "utf-8"))
    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL("mail.infomaniak.com", 465, context=context) as server:
            auth_string = f"\0{SENDER_EMAIL}\0{INFOMANIAK_APP_PASSWORD}"
            auth_bytes_utf8 = auth_string.encode('utf-8')
            auth_bytes_b64 = base64.b64encode(auth_bytes_utf8)
            server.docmd("AUTH", f"PLAIN {auth_bytes_b64.decode('ascii')}")
            
            server.sendmail(SENDER_EMAIL, email, message.as_string())
    except Exception as e:
        print(f"ERREUR SMTP CRITIQUE: {e}"); traceback.print_exc()
        return jsonify({"error": "Impossible d'envoyer l'e-mail de vérification."}), 500

    cursor.execute("INSERT OR REPLACE INTO verification_codes VALUES (?, ?, ?, ?)", (discord_id, email, code, expires_at))
    conn.commit(); conn.close()
    return jsonify({"success": True}), 200

@app.route('/api/test-email', methods=['POST'])
def test_email():
    # --- LOG DE DIAGNOSTIC ---
    data = request.json
    recipient_email = data.get('recipient_email')
    Logger.info(f"Appel de /api/test-email reçu pour le destinataire : {recipient_email}")

    auth_header = request.headers.get('Authorization')
    expected_header = f"Bearer {FLASK_SECRET_KEY}"
    if not auth_header or auth_header != expected_header:
        return jsonify({"error": "Accès non autorisé."}), 403

    if not recipient_email:
        return jsonify({"error": "E-mail destinataire manquant."}), 400

    message = MIMEMultipart("alternative")
    sujet = "Email de Test - LaFoncedalleBot"
    message["Subject"] = Header(sujet, 'utf-8')
    message["From"] = f"LaFoncedalle <{SENDER_EMAIL}>"
    message["To"] = recipient_email
    html_body = f"""
    <html><body><h3>Ceci est un e-mail de test.</h3>
    <p>Si vous recevez cet e-mail, la configuration SMTP est <strong>correcte</strong>.</p>
    <p><b>Heure du test:</b> {datetime.now(paris_tz).strftime('%Y-%m-%d %H:%M:%S')}</p>
    </body></html>"""
    message.attach(MIMEText(html_body, "html", "utf-8"))
    
    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL("mail.infomaniak.com", 465, context=context) as server:
            auth_string = f"\0{SENDER_EMAIL}\0{INFOMANIAK_APP_PASSWORD}"
            auth_bytes_utf8 = auth_string.encode('utf-8')
            auth_bytes_b64 = base64.b64encode(auth_bytes_utf8)
            server.docmd("AUTH", f"PLAIN {auth_bytes_b64.decode('ascii')}")
            server.sendmail(SENDER_EMAIL, recipient_email, message.as_string())
        
        Logger.success(f"E-mail de test envoyé avec succès à {recipient_email}.")
        return jsonify({"success": True, "message": f"E-mail de test envoyé à {recipient_email}."}), 200

    except Exception as e:
        Logger.error(f"ERREUR SMTP CRITIQUE lors du test: {e}"); traceback.print_exc()
        return jsonify({"error": "Impossible d'envoyer l'e-mail de test.", "details": str(e)}), 500
    
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

    conn = sqlite3.connect(DB_FILE)
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

    # --- Logique d'envoi de code de bienvenue ---
    try:
        claimed_users = {}
        try:
            with open(CLAIMED_WELCOME_CODES_FILE, 'r') as f:
                claimed_users = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        if str(discord_id) in claimed_users:
            print(f"INFO: L'utilisateur {discord_id} a déjà réclamé un code de bienvenue.")
            # --- MODIFICATION N°1 : On informe le bot que le cadeau n'a pas été envoyé ---
            return jsonify({"success": True, "gift_sent": False, "reason": "already_claimed"}), 200

        with open(WELCOME_CODES_FILE, 'r+') as f:
            codes = [line.strip() for line in f if line.strip()]
            if not codes:
                print("ERREUR CRITIQUE: Plus de codes de bienvenue disponibles !")
                # On informe le bot que le cadeau n'a pas été envoyé
                return jsonify({"success": True, "gift_sent": False, "reason": "no_codes_available"}), 200

            gift_code = codes.pop(0)
            f.seek(0); f.truncate(); f.write('\n'.join(codes))

        # ... (le code d'envoi d'email reste exactement le même) ...
        message = MIMEMultipart("alternative")
        message["Subject"] = Header("🎉 Bienvenue chez LaFoncedalle ! Voici votre cadeau.", 'utf-8')
        message["From"] = f"LaFoncedalle <{SENDER_EMAIL}>"
        message["To"] = user_email
        html_body = f"""
        <html><body><h3>Merci d'avoir lié votre compte !</h3><p>Pour vous remercier, voici un code de réduction de <strong>5€</strong> :</p><h2 style="text-align: center; background-color: #f0f0f0; padding: 10px; border-radius: 5px;">{gift_code}</h2><p>À bientôt sur notre boutique !</p></body></html>
        """
        message.attach(MIMEText(html_body, "html", "utf-8"))
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("mail.infomaniak.com", 465, context=context) as server:
            auth_string = f"\0{SENDER_EMAIL}\0{INFOMANIAK_APP_PASSWORD}"
            auth_bytes_utf8 = auth_string.encode('utf-8')
            auth_bytes_b64 = base64.b64encode(auth_bytes_utf8)
            server.docmd("AUTH", f"PLAIN {auth_bytes_b64.decode('ascii')}")
            
            server.sendmail(SENDER_EMAIL, user_email, message.as_string())

        claimed_users[str(discord_id)] = {"code": gift_code, "date": datetime.utcnow().isoformat()}
        with open(CLAIMED_WELCOME_CODES_FILE, 'w') as f:
            json.dump(claimed_users, f, indent=4)
        
        print(f"INFO: Code de bienvenue '{gift_code}' envoyé à {user_email} pour l'utilisateur {discord_id}.")

    except Exception as e:
        print(f"ERREUR CRITIQUE lors de l'envoi du code de bienvenue : {e}")
        traceback.print_exc()
    
    # --- MODIFICATION N°2 : On informe le bot que le cadeau a bien été envoyé ---
    return jsonify({"success": True, "gift_sent": True}), 200

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
    force = request.args.get('force', 'false').lower() == 'true'
    auth_header = request.headers.get('Authorization')
    expected_header = f"Bearer {FLASK_SECRET_KEY}"
    if not auth_header or auth_header != expected_header:
        return jsonify({"error": "Accès non autorisé."}), 403

    data = request.json
    discord_id, email = data.get('discord_id'), data.get('email')
    if not all([discord_id, email]): return jsonify({"error": "ID Discord ou e-mail manquant."}), 400

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    if not force:
        cursor.execute("SELECT user_email FROM user_links WHERE discord_id = ?", (discord_id,))
        result = cursor.fetchone()
        if result:
            anonymized_email = anonymize_email(result[0])
            conn.close()
            return jsonify({"status": "conflict", "existing_email": anonymized_email}), 409

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
    app.run(host='0.0.0.0', port=5000, debug=True)