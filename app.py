import os
import sqlite3
import random
import time
from flask import Flask, request, jsonify
import shopify
from dotenv import load_dotenv
import threading
import asyncio
import smtplib, ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from config import SHOP_URL, SHOPIFY_API_VERSION, FLASK_SECRET_KEY
import catalogue_final

load_dotenv()

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY

SENDER_EMAIL = os.getenv('SENDER_EMAIL')
INFOMANIAK_APP_PASSWORD = os.getenv('INFOMANIAK_APP_PASSWORD')
SHOPIFY_ADMIN_ACCESS_TOKEN = os.getenv('SHOPIFY_ADMIN_ACCESS_TOKEN')

def run_bot():
    asyncio.set_event_loop(asyncio.new_event_loop())
    asyncio.run(catalogue_final.main())

if not os.environ.get("WERKZEUG_RUN_MAIN"):
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()

def initialize_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS user_links (discord_id TEXT PRIMARY KEY, user_email TEXT NOT NULL UNIQUE);")
    cursor.execute("CREATE TABLE IF NOT EXISTS verification_codes (discord_id TEXT PRIMARY KEY, user_email TEXT NOT NULL, code TEXT NOT NULL, expires_at INTEGER NOT NULL);")
    conn.commit()
    conn.close()

initialize_db()

@app.route('/')
def health_check():
    return "L'application pont Shopify-Discord est en ligne.", 200

@app.route('/api/start-verification', methods=['POST'])
def start_verification():
    data = request.json
    discord_id, email = data.get('discord_id'), data.get('email')
    if not all([discord_id, email]): return jsonify({"error": "Données manquantes."}), 400

    conn = sqlite3.connect('database.db'); cursor = conn.cursor()
    cursor.execute("SELECT user_email FROM user_links WHERE discord_id = ?", (discord_id,))
    if cursor.fetchone(): conn.close(); return jsonify({"error": "Ce compte Discord est déjà lié."}), 409
    cursor.execute("SELECT discord_id FROM user_links WHERE user_email = ?", (email,))
    if cursor.fetchone(): conn.close(); return jsonify({"error": "Cet e-mail est déjà utilisé."}), 409
    
    code = str(random.randint(100000, 999999))
    expires_at = int(time.time()) + 600

    message = MIMEMultipart("alternative")
    
    # --- CORRECTION 1 : Gérer l'encodage du sujet ---
    sujet = "Votre code de vérification LaFoncedalle"
    message["Subject"] = Header(sujet, 'utf-8')
    
    message["From"] = SENDER_EMAIL
    message["To"] = email

    # --- CORRECTION 2 : Gérer l'encodage du corps du message ---
    html_body = f'Bonjour !<br>Voici votre code de vérification : <strong>{code}</strong><br>Ce code expire dans 10 minutes.'
    part = MIMEText(html_body, "html", "utf-8") # <--- AJOUTEZ "utf-8" ICI
    message.attach(part)
    
    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL("mail.infomaniak.com", 465, context=context) as server:
            server.login(SENDER_EMAIL, INFOMANIAK_APP_PASSWORD)
            server.sendmail(SENDER_EMAIL, email, message.as_string())
        print(f"E-mail de vérification envoyé avec succès à {email}")
    except Exception as e:
        # Amélioration du log pour voir l'erreur exacte
        import traceback
        print(f"Erreur SMTP: {e}")
        traceback.print_exc() # <--- Affiche plus de détails dans vos logs Render
        return jsonify({"error": "Impossible d'envoyer l'e-mail de vérification."}), 500

    cursor.execute("INSERT OR REPLACE INTO verification_codes VALUES (?, ?, ?, ?)", (discord_id, email, code, expires_at))
    conn.commit(); conn.close()
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