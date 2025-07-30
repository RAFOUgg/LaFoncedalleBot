# graph_generator.py
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import numpy as np
import os
import sqlite3
import traceback
import re # <-- Importé pour les regex
from typing import Dict, Any, List
from shared_utils import Logger, DB_FILE
import time

FONT_PATH = os.path.join(os.path.dirname(__file__), 'assets', 'Gobold-Bold.otf')

def remove_emojis(text: str) -> str:
    """Supprime les caractères emoji et certains symboles d'une chaîne."""
    if not text:
        return ""
    emoji_pattern = re.compile(
        "["
        u"\U0001F600-\U0001F64F"  # emoticons
        u"\U0001F300-\U0001F5FF"  # symbols & pictographs
        u"\U0001F680-\U0001F6FF"  # transport & map symbols
        u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
        u"\U00002702-\U000027B0"
        u"\U000024C2-\U0001F251"
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub(r'', text).strip()

def create_radar_chart(product_name: str) -> str | None:
    if not os.path.exists(FONT_PATH):
        Logger.error(f"CRITIQUE: Fichier de police introuvable à '{FONT_PATH}'.")
        return None
    font_props = FontProperties(fname=FONT_PATH, size=12)
    font_props_title = FontProperties(fname=FONT_PATH, size=16)
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT visual_score, smell_score, touch_score, taste_score, effects_score FROM ratings WHERE product_name = ?", (product_name,))
        all_ratings = cursor.fetchall()
        if not all_ratings:
            return None
        all_ratings_np = np.array(all_ratings, dtype=float)
        mean_scores = np.nanmean(np.where(all_ratings_np == None, np.nan, all_ratings_np), axis=0)
        categories = ['Visuel', 'Odeur', 'Toucher', 'Goût', 'Effets']
        scores_for_plot = np.concatenate((mean_scores, [mean_scores[0]]))
        angles = np.linspace(0, 2 * np.pi, len(categories), endpoint=False).tolist()
        angles += angles[:1]
        fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
        fig.patch.set_facecolor('#2f3136')
        ax.set_facecolor('#2f3136')
        ax.plot(angles, scores_for_plot, color='#5865F2', linewidth=2)
        ax.fill(angles, scores_for_plot, color='#5865F2', alpha=0.25)
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
        product_name_clean = remove_emojis(product_name)
        ax.set_title(f'Profil de saveur : {product_name_clean}\n', fontproperties=font_props_title, color='white')
        output_dir = "charts"
        os.makedirs(output_dir, exist_ok=True)
        filename = f"{output_dir}/{product_name_clean.replace(' ', '_').replace('/', '')}_radar_chart.png"
        plt.savefig(filename, bbox_inches='tight', dpi=120, transparent=True)
        plt.close(fig)
        return filename
    except Exception as e:
        Logger.error(f"Erreur inattendue dans create_radar_chart pour '{product_name}': {e}")
        traceback.print_exc()
        return None
    finally:
        if conn:
            conn.close()

def create_comparison_radar_chart(product1_name: str, product2_name: str) -> str | None:
    # --- LOG DE DÉBUT ---
    Logger.info(f"[GraphCompare] Début de la génération pour '{product1_name}' vs '{product2_name}'.")

    if not os.path.exists(FONT_PATH):
        Logger.error(f"[GraphCompare] CRITIQUE: Fichier de police introuvable à '{FONT_PATH}'.")
        return None
        
    font_props = FontProperties(fname=FONT_PATH, size=12)
    font_props_legend = FontProperties(fname=FONT_PATH, size=11)
    font_props_title = FontProperties(fname=FONT_PATH, size=16)
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # [AMÉLIORATION] On passe les noms en minuscule et on retire les espaces pour la comparaison SQL
        # Cela rend la recherche plus robuste face à des variations mineures.
        p1_clean = product1_name.strip().lower()
        p2_clean = product2_name.strip().lower()

        query = """
            SELECT product_name, 
                   AVG(visual_score), AVG(smell_score), AVG(touch_score), 
                   AVG(taste_score), AVG(effects_score) 
            FROM ratings 
            WHERE LOWER(TRIM(product_name)) = ? OR LOWER(TRIM(product_name)) = ? 
            GROUP BY LOWER(TRIM(product_name))
        """
        cursor.execute(query, (p1_clean, p2_clean))
        results = cursor.fetchall()
        
        # --- LOG CRUCIAL ---
        Logger.info(f"[GraphCompare] Résultats de la DB: {results}")

        if not results or len(results) < 2:
            Logger.warning(f"[GraphCompare] Données insuffisantes. Trouvé {len(results)} produit(s).")
            return None

        # [CORRECTION MAJEURE] On normalise les clés du dictionnaire (lower, trim)
        scores_map = {
            row[0].strip().lower(): np.nan_to_num(np.array(row[1:], dtype=float)) 
            for row in results
        }
        
        # --- LOG CRUCIAL ---
        Logger.info(f"[GraphCompare] Dictionnaire de scores créé: {scores_map.keys()}")

        scores1 = scores_map.get(p1_clean)
        scores2 = scores_map.get(p2_clean)
        
        # --- LOG CRUCIAL ---
        Logger.info(f"[GraphCompare] Score pour '{p1_clean}': {'TROUVÉ' if scores1 is not None else 'MANQUANT'}")
        Logger.info(f"[GraphCompare] Score pour '{p2_clean}': {'TROUVÉ' if scores2 is not None else 'MANQUANT'}")
        
        if scores1 is None or scores2 is None:
            Logger.error(f"[GraphCompare] Echec de la récupération des scores depuis le dictionnaire.")
            return None

        # --- Le reste du code est identique mais on le garde pour être complet ---
        categories = ['Visuel', 'Odeur', 'Toucher', 'Goût', 'Effets']
        angles = np.linspace(0, 2 * np.pi, len(categories), endpoint=False).tolist()
        angles += angles[:1]
        fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
        fig.patch.set_facecolor('#2f3136')
        ax.set_facecolor('#2f3136')
        
        scores_for_plot1 = np.concatenate((scores1, [scores1[0]]))
        ax.plot(angles, scores_for_plot1, color='#5865F2', linewidth=2, label=remove_emojis(product1_name))
        ax.fill(angles, scores_for_plot1, color='#5865F2', alpha=0.2)
        
        scores_for_plot2 = np.concatenate((scores2, [scores2[0]]))
        ax.plot(angles, scores_for_plot2, color='#57F287', linewidth=2, label=remove_emojis(product2_name))
        ax.fill(angles, scores_for_plot2, color='#57F287', alpha=0.2)
        
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
        ax.set_title('Comparaison des Profils de Saveur\n', fontproperties=font_props_title, color='white')
        legend = ax.legend(loc='upper right', bbox_to_anchor=(1.4, 1.1))
        for text in legend.get_texts():
            text.set_fontproperties(font_props_legend)
            text.set_color('white')
        output_dir = "charts"
        os.makedirs(output_dir, exist_ok=True)
        filename = f"{output_dir}/comparison_chart_{int(time.time())}.png"
        plt.savefig(filename, bbox_inches='tight', dpi=120, transparent=True)
        plt.close(fig)

        Logger.success(f"[GraphCompare] Graphique généré avec succès: {filename}")
        return filename
        
    except Exception as e:
        Logger.error(f"[GraphCompare] Erreur inattendue: {e}")
        traceback.print_exc()
        return None
    finally:
        if conn:
            conn.close()