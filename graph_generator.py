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
    if not os.path.exists(FONT_PATH):
        Logger.error(f"CRITIQUE: Fichier de police introuvable à '{FONT_PATH}'.")
        return None
    font_props = FontProperties(fname=FONT_PATH, size=12)
    font_props_legend = FontProperties(fname=FONT_PATH, size=11)
    font_props_title = FontProperties(fname=FONT_PATH, size=16)
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Requête pour obtenir les moyennes des deux produits
        query = "SELECT product_name, AVG(visual_score), AVG(smell_score), AVG(touch_score), AVG(taste_score), AVG(effects_score) FROM ratings WHERE product_name LIKE ? OR product_name LIKE ? GROUP BY product_name"
        cursor.execute(query, (f'%{product1_name}%', f'%{product2_name}%'))
        results = cursor.fetchall()
        
        # [AMÉLIORATION] Vérification robuste des résultats
        if len(results) < 2:
            Logger.warning(f"Données insuffisantes pour comparer '{product1_name}' et '{product2_name}'. Trouvé : {len(results)} produit(s).")
            return None

        # [AMÉLIORATION] Extraction simple et fiable des données
        db_name1, scores1 = results[0][0], np.array(results[0][1:], dtype=float)
        db_name2, scores2 = results[1][0], np.array(results[1][1:], dtype=float)
        
        # S'assurer que les scores ne sont pas NaN (au cas où il n'y aurait que des NULLs)
        scores1 = np.nan_to_num(scores1)
        scores2 = np.nan_to_num(scores2)

        categories = ['Visuel', 'Odeur', 'Toucher', 'Goût', 'Effets']
        angles = np.linspace(0, 2 * np.pi, len(categories), endpoint=False).tolist()
        angles += angles[:1]
        fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
        fig.patch.set_facecolor('#2f3136')
        ax.set_facecolor('#2f3136')
        
        # Tracé pour le produit 1
        scores_for_plot1 = np.concatenate((scores1, [scores1[0]]))
        ax.plot(angles, scores_for_plot1, color='#5865F2', linewidth=2, label=remove_emojis(db_name1))
        ax.fill(angles, scores_for_plot1, color='#5865F2', alpha=0.2)
        
        # Tracé pour le produit 2
        scores_for_plot2 = np.concatenate((scores2, [scores2[0]]))
        ax.plot(angles, scores_for_plot2, color='#57F287', linewidth=2, label=remove_emojis(db_name2))
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
        # On utilise time.time() pour s'assurer que le nom de fichier est unique
        filename = f"{output_dir}/comparison_chart_{int(time.time())}.png"
        plt.savefig(filename, bbox_inches='tight', dpi=120, transparent=True)
        plt.close(fig)
        return filename
        
    except Exception as e:
        Logger.error(f"Erreur inattendue dans create_comparison_radar_chart : {e}")
        traceback.print_exc()
        return None
    finally:
        if conn:
            conn.close()