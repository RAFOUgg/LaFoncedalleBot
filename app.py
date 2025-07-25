import os
import sqlite3
import random
import time
from flask import Flask, request, jsonify
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import shopify
from dotenv import load_dotenv
import threading
import asyncio

# Importer la configuration simple et le point d'entrée du bot
from config import SHOP_URL, SHOPIFY_API_VERSION, FLASK_SECRET_KEY
import catalogue_final # On importe le module du bot

# Charger les variables d'environnement
load_dotenv()

# --- Configuration ---
app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY

# Clés secrètes depuis l'environnement
SENDGRID_API_KEY = os.getenv('SENDGRID_API_KEY')
SENDER_EMAIL = os.getenv('SENDER_EMAIL')
SHOPIFY_ADMIN_ACCESS_TOKEN = os.getenv('SHOPIFY_ADMIN_ACCESS_TOKEN')

# --- Lancement du Bot Discord en arrière-plan ---
def run_bot():
    # Crée une nouvelle boucle d'événements pour le thread du bot
    asyncio.set_event_loop(asyncio.new_event_loop())
    # Utilise la fonction main() de catalogue_final.py pour démarrer le bot
    asyncio.run(catalogue_final.main())

# On s'assure que le bot ne se lance qu'une seule fois
if not os.environ.get("WERKZEUG_RUN_MAIN"):
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()

# --- Base de données ---
def initialize_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS user_links (discord_id TEXT PRIMARY KEY, user_email TEXT NOT NULL UNIQUE);")
    cursor.execute("CREATE TABLE IF NOT EXISTS verification_codes (discord_id TEXT PRIMARY KEY, user_email TEXT NOT NULL, code TEXT NOT NULL, expires_at INTEGER NOT NULL);")
    conn.commit()
    conn.close()

initialize_db()

# --- Routes API ---

@app.route('/')
def health_check():
    return "L'application pont Shopify-Discord est en ligne et prête pour la vérification par e-mail.", 200

# --- CETTE FONCTION MANQUAIT ---
@app.route('/api/start-verification', methods=['POST'])
def start_verification():
    data = request.json
    discord_id = data.get('discord_id')
    email = data.get('email')

    if not all([discord_id, email]):
        return jsonify({"error": "ID Discord ou e-mail manquant."}), 400

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    # Vérification complète de l'existence
    cursor.execute("SELECT user_email FROM user_links WHERE discord_id = ?", (discord_id,))
    existing_link = cursor.fetchone()
    if existing_link:
        conn.close()
        return jsonify({"error": f"votre compte Discord est déjà lié à l'e-mail `{existing_link[0]}`."}), 409

    cursor.execute("SELECT discord_id FROM user_links WHERE user_email = ?", (email,))
    email_taken = cursor.fetchone()
    if email_taken:
        conn.close()
        return jsonify({"error": "cette adresse e-mail est déjà utilisée par un autre compte Discord."}), 409
    
    code = str(random.randint(100000, 999999))
    expires_at = int(time.time()) + 600

    message = Mail(
        from_email=SENDER_EMAIL,
        to_emails=email,
        subject='Votre code de vérification LaFoncedalle',
        html_content=f'Bonjour !<br>Voici votre code de vérification pour lier votre compte Discord : <strong>{code}</strong><br>Ce code expire dans 10 minutes.'
    )
    
    # --- CORRECTION DE LA GESTION D'ERREUR SENDGRID ---
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        # On vérifie explicitement si l'API a renvoyé une erreur
        if response.status_code >= 300:
             raise Exception(f"SendGrid a retourné une erreur: {response.status_code} {response.body}")
    except Exception as e:
        print(f"Erreur SendGrid: {e}") # Pour vos logs
        conn.close()
        # On renvoie une erreur 500 que notre bot pourra intercepter
        return jsonify({"error": "Impossible d'envoyer l'e-mail de vérification."}), 500

    cursor.execute("INSERT OR REPLACE INTO verification_codes (discord_id, user_email, code, expires_at) VALUES (?, ?, ?, ?)",(discord_id, email, code, expires_at))
    conn.commit()
    conn.close()

    return jsonify({"success": True}), 200

@app.route('/api/confirm-verification', methods=['POST'])
def confirm_verification():
    data = request.json
    discord_id = data.get('discord_id')
    code = data.get('code')

    conn = sqlite3.connect('database.db')
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

    if not discord_id:
        return jsonify({"error": "ID Discord manquant."}), 400

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    # Vérifier si un lien existe avant de le supprimer
    cursor.execute("SELECT user_email FROM user_links WHERE discord_id = ?", (discord_id,))
    result = cursor.fetchone()

    if not result:
        conn.close()
        return jsonify({"error": "Aucun compte n'est lié à cet ID Discord."}), 404

    # Supprimer la liaison
    cursor.execute("DELETE FROM user_links WHERE discord_id = ?", (discord_id,))
    conn.commit()
    conn.close()

    # Renvoyer l'e-mail qui a été délié pour le message de confirmation
    return jsonify({"success": True, "unlinked_email": result[0]}), 200

@app.route('/api/force-link', methods=['POST'])
def force_link():
    data = request.json
    discord_id = data.get('discord_id')
    email = data.get('email')

    if not all([discord_id, email]):
        return jsonify({"error": "ID Discord ou e-mail manquant."}), 400

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    
    # On insère ou on remplace la liaison existante.
    # C'est parfait pour les tests, car on peut changer l'e-mail lié à la volée.
    cursor.execute("INSERT OR REPLACE INTO user_links (discord_id, user_email) VALUES (?, ?)", (discord_id, email))
    
    # On supprime tout code de vérification en attente pour cet utilisateur, pour rester propre.
    cursor.execute("DELETE FROM verification_codes WHERE discord_id = ?", (discord_id,))
    
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "message": f"Compte {discord_id} forcé à être lié à {email}."}), 200

@app.route('/api/get_purchased_products/<discord_id>')
def get_purchased_products(discord_id):
    conn = sqlite3.connect('database.db')
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

if __name__ == '__main__':
    app.run(port=5000, debug=True)