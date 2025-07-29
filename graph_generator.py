import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import numpy as np
import os
import sqlite3
import traceback
from typing import Dict, Any, List
from shared_utils import Logger, DB_FILE

# [NOUVEAU] Définir le chemin vers la police personnalisée
FONT_PATH = os.path.join(os.path.dirname(__file__), 'assets', 'Gobold-Bold.otf')

def create_radar_chart(product_name: str) -> str | None:
    """
    [CORRIGÉ] Génère un graphique en toile d'araignée en utilisant une police personnalisée
    et un style adapté à Discord.
    Retourne le chemin vers le fichier image généré ou None en cas d'échec.
    """
    if not os.path.exists(FONT_PATH):
        Logger.error(f"CRITIQUE: Fichier de police introuvable à l'emplacement '{FONT_PATH}'. Impossible de générer des graphiques.")
        return None
        
    font_props = FontProperties(fname=FONT_PATH, size=12)
    font_props_title = FontProperties(fname=FONT_PATH, size=16)

    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT visual_score, smell_score, touch_score, taste_score, effects_score
            FROM ratings
            WHERE product_name = ?
        """, (product_name,))
        all_ratings = cursor.fetchall()

        if not all_ratings:
            Logger.info(f"Aucune note trouvée pour '{product_name}'. Impossible de générer le graphique.")
            return None

        all_ratings_np = np.array(all_ratings, dtype=float)
        mean_scores = np.nanmean(np.where(all_ratings_np == None, np.nan, all_ratings_np), axis=0)

        categories = ['Visuel', 'Odeur', 'Toucher', 'Goût', 'Effets']
        num_categories = len(categories)

        scores_for_plot = np.concatenate((mean_scores, [mean_scores[0]]))
        angles = np.linspace(0, 2 * np.pi, num_categories, endpoint=False).tolist()
        angles += angles[:1]

        fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
        fig.patch.set_facecolor('#2f3136')
        ax.set_facecolor('#2f3136')

        ax.plot(angles, scores_for_plot, color='#5865F2', linewidth=2)
        ax.fill(angles, scores_for_plot, color='#5865F2', alpha=0.25)

        # Grille et étiquettes
        ax.set_ylim(0, 10)
        
        # [CORRECTION FINALE] On sépare la définition des positions de la grille et son style.
        # 1. On définit où placer les cercles de la grille et leurs étiquettes.
        ax.set_rgrids([2, 4, 6, 8], angle=90)
        # 2. On stylise les lignes de la grille (radiales ET angulaires) avec ax.grid()
        ax.grid(color="gray", linestyle='--', linewidth=0.5)

        ax.set_thetagrids(np.degrees(angles[:-1]), categories)

        # Style des étiquettes texte de la grille
        for label in ax.get_xticklabels():
            label.set_fontproperties(font_props)
            label.set_color('white')
            label.set_y(label.get_position()[1] * 1.1)

        for label in ax.get_yticklabels():
            label.set_fontproperties(FontProperties(fname=FONT_PATH, size=10))
            label.set_color('darkgrey')
        
        ax.spines['polar'].set_color('gray')
        
        ax.set_title(f'Profil de saveur : {product_name}\n', fontproperties=font_props_title, color='white')

        output_dir = "charts"
        os.makedirs(output_dir, exist_ok=True)
        filename = f"{output_dir}/{product_name.replace(' ', '_').replace('/', '')}_radar_chart.png"
        
        plt.savefig(filename, bbox_inches='tight', dpi=120, transparent=True)
        plt.close(fig)

        Logger.success(f"Graphique généré pour '{product_name}' : {filename}")
        return filename

    except Exception as e:
        Logger.error(f"Erreur inattendue lors de la génération du graphique pour '{product_name}': {e}")
        traceback.print_exc()
        return None
    finally:
        if conn:
            conn.close()

# Ajoutez cette nouvelle fonction à la fin de graph_generator.py

def create_comparison_radar_chart(product1_name: str, product2_name: str) -> str | None:
    """
    [CORRIGÉ] Génère un seul graphique radar superposant les données de deux produits.
    """
    if not os.path.exists(FONT_PATH):
        Logger.error(f"CRITIQUE: Fichier de police introuvable à l'emplacement '{FONT_PATH}'. Impossible de générer des graphiques.")
        return None
        
    font_props = FontProperties(fname=FONT_PATH, size=12)
    font_props_legend = FontProperties(fname=FONT_PATH, size=11)
    font_props_title = FontProperties(fname=FONT_PATH, size=16)

    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Récupérer les notes pour les deux produits en une seule requête
        cursor.execute("""
            SELECT product_name, 
                   AVG(visual_score), AVG(smell_score), AVG(touch_score), 
                   AVG(taste_score), AVG(effects_score)
            FROM ratings
            WHERE product_name IN (?, ?)
            GROUP BY product_name
        """, (product1_name, product2_name))
        results = cursor.fetchall()

        if len(results) < 2:
            Logger.warning(f"Données insuffisantes pour comparer '{product1_name}' et '{product2_name}'. Un des produits n'a pas de notes.")
            return None
        
        # Organiser les données dans un dictionnaire pour un accès facile
        scores_map = {row[0]: np.array(row[1:], dtype=float) for row in results}

        categories = ['Visuel', 'Odeur', 'Toucher', 'Goût', 'Effets']
        num_categories = len(categories)

        angles = np.linspace(0, 2 * np.pi, num_categories, endpoint=False).tolist()
        angles += angles[:1] # Fermer le cercle

        fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
        fig.patch.set_facecolor('#2f3136')
        ax.set_facecolor('#2f3136')

        # --- Dessiner le Produit 1 ---
        scores1 = scores_map[product1_name]
        scores_for_plot1 = np.concatenate((scores1, [scores1[0]]))
        ax.plot(angles, scores_for_plot1, color='#5865F2', linewidth=2, label=product1_name) # Bleu Discord
        ax.fill(angles, scores_for_plot1, color='#5865F2', alpha=0.2)

        # --- Dessiner le Produit 2 ---
        scores2 = scores_map[product2_name]
        scores_for_plot2 = np.concatenate((scores2, [scores2[0]]))
        ax.plot(angles, scores_for_plot2, color='#57F287', linewidth=2, label=product2_name) # Vert Discord
        ax.fill(angles, scores_for_plot2, color='#57F287', alpha=0.2)
        
        # Configuration de l'axe et de la grille
        ax.set_ylim(0, 10)
        ax.set_rgrids([2, 4, 6, 8], angle=90)
        ax.grid(color="gray", linestyle='--', linewidth=0.5)
        ax.set_thetagrids(np.degrees(angles[:-1]), categories)

        for label in ax.get_xticklabels():
            label.set_fontproperties(font_props)
            label.set_color('white')
            label.set_y(label.get_position()[1] * 1.1)

        for label in ax.get_yticklabels():
            label.set_fontproperties(FontProperties(fname=FONT_PATH, size=10))
            label.set_color('darkgrey')
        
        ax.spines['polar'].set_color('gray')
        
        # Titre et Légende
        ax.set_title('Comparaison des Profils de Saveur\n', fontproperties=font_props_title, color='white')
        legend = ax.legend(loc='upper right', bbox_to_anchor=(1.4, 1.1))
        for text in legend.get_texts():
            text.set_fontproperties(font_props_legend)
            text.set_color('white')

        # Sauvegarde
        output_dir = "charts"
        os.makedirs(output_dir, exist_ok=True)
        filename = f"{output_dir}/comparison_chart_{int(time.time())}.png"
        
        plt.savefig(filename, bbox_inches='tight', dpi=120, transparent=True)
        plt.close(fig)

        Logger.success(f"Graphique de comparaison généré : {filename}")
        return filename

    except Exception as e:
        Logger.error(f"Erreur inattendue lors de la génération du graphique de comparaison : {e}")
        traceback.print_exc()
        return None
    finally:
        if conn:
            conn.close()