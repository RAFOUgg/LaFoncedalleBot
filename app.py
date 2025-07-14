# app.py
from flask import Flask, request, redirect, session, url_for
import shopify
import requests
import sqlite3

# Importer la configuration
from config import *

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY

# Configuration de l'API Shopify
shopify.Session.setup(api_key=SHOPIFY_API_KEY, secret=SHOPIFY_API_SECRET)

def initialize_db():
    # Crée la DB pour lier les comptes
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_links (
            discord_id TEXT PRIMARY KEY,
            shopify_customer_id TEXT,
            shopify_access_token TEXT
        );
    """)
    conn.commit()
    conn.close()

# 1. Point d'entrée depuis Discord
@app.route('/connect/<discord_id>')
def connect_user(discord_id):
    session['discord_id'] = discord_id
    
    # Création de la permission URL pour Shopify
    permission_url = shopify.Session(SHOP_URL, SHOPIFY_API_VERSION).create_permission_url(
        scope=['read_customers', 'read_orders'], # On demande la permission de lire les clients et les commandes
        redirect_uri=f"{APP_URL}/callback/shopify"
    )
    return redirect(permission_url)

# 2. Shopify redirige l'utilisateur ici après autorisation
@app.route('/callback/shopify')
def shopify_callback():
    if 'discord_id' not in session:
        return "Erreur: ID Discord non trouvé. Veuillez recommencer depuis Discord.", 400

    # On échange le code temporaire contre un vrai token d'accès
    shop_session = shopify.Session(SHOP_URL, SHOPIFY_API_VERSION)
    access_token = shop_session.request_token(request.args.to_dict())

    # On stocke le token et on active la session
    shopify.ShopifyResource.activate_session(shop_session)

    # On récupère les infos du client Shopify
    customer = shopify.Customer.current()
    shopify_customer_id = customer.id
    discord_id = session['discord_id']

    # On enregistre le lien dans notre DB
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO user_links (discord_id, shopify_customer_id, shopify_access_token) VALUES (?, ?, ?)",
        (discord_id, str(shopify_customer_id), access_token)
    )
    conn.commit()
    conn.close()
    
    # On désactive la session Shopify pour être propre
    shopify.ShopifyResource.clear_session()

    return "<h1>✅ Compte Shopify lié !</h1><p>Vous pouvez maintenant fermer cette fenêtre et retourner sur Discord.</p>"

# 3. API sécurisée que le bot Discord va appeler
@app.route('/api/get_purchased_products/<discord_id>')
def get_purchased_products(discord_id):
    # (Dans une vraie app, ajoutez une clé d'API pour sécuriser cet endpoint)
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT shopify_access_token FROM user_links WHERE discord_id = ?", (discord_id,))
    result = cursor.fetchone()
    conn.close()

    if not result:
        return {"error": "user_not_linked"}, 404

    access_token = result[0]
    
    # On active une session Shopify avec le token de l'utilisateur
    shop_session = shopify.Session(SHOP_URL, SHOPIFY_API_VERSION, token=access_token)
    shopify.ShopifyResource.activate_session(shop_session)
    
    # On récupère les commandes
    orders = shopify.Order.find()
    
    # On extrait tous les noms de produits uniques
    purchased_products = set()
    for order in orders:
        for item in order.line_items:
            purchased_products.add(item.title)
    
    shopify.ShopifyResource.clear_session()

    return {"products": list(purchased_products)}

@app.route('/')
def health_check():
    return "L'application pont Shopify-Discord est en ligne.", 200

if __name__ == '__main__':
    initialize_db()
    app.run(port=5000, debug=True) # Pour le test en local