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
import io

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
    font_props = FontProperties(family="Gobold", weight='bold', size=12)
    font_props_title = FontProperties(family="Gobold", weight='bold', size=16)
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
            label.set_fontproperties(FontProperties(family="Gobold", weight='regular', size=10))
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

DEBUG_LOG_FILE = os.path.join(os.path.dirname(__file__), 'graph_debug.log')

def _log_debug(step_message):
    """Fonction helper pour écrire dans notre fichier de log de manière fiable."""
    try:
        with open(DEBUG_LOG_FILE, 'a') as f:
            f.write(f"[{datetime.now().isoformat()}] {step_message}\n")
    except Exception:
        # Si même ça échoue, on ne peut rien faire, mais c'est très improbable.
        pass

def create_comparison_radar_chart(db_name1: str, scores1: np.ndarray, db_name2: str, scores2: np.ndarray) -> bytes | None:
    _log_debug("--- NEW GRAPH GENERATION ---")
    _log_debug(f"START: Génération pour '{db_name1}' vs '{db_name2}'.")
    
    try:
        # Étape 1 : Vérification des prérequis
        _log_debug("STEP 1.1: Checking for font file...")
        if not os.path.exists(FONT_PATH):
            _log_debug(f"CRITICAL: Font file not found at '{FONT_PATH}'. Aborting.")
            return None
        _log_debug("STEP 1.2: Font file found. Initializing Matplotlib properties...")
        
        # ... (le code de préparation reste identique)
        labels = ['Visuel', 'Odeur', 'Toucher', 'Goût', 'Effets']
        angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
        angles += angles[:1]
        scores1_closed = np.concatenate((scores1, [scores1[0]]))
        scores2_closed = np.concatenate((scores2, [scores2[0]]))

        # Étape 2 : Création de la figure Matplotlib
        _log_debug("STEP 2.1: Calling plt.subplots()...")
        fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
        _log_debug("STEP 2.2: plt.subplots() successful. Applying styles...")
        fig.patch.set_facecolor('#2f3136')
        ax.set_facecolor('#2f3136')

        # Étape 3 : Tracé des données
        _log_debug("STEP 3.1: Plotting data for product 1...")
        ax.plot(angles, scores1_closed, color='#5865F2', linewidth=2, label=remove_emojis(db_name1))
        ax.fill(angles, scores1_closed, color='#5865F2', alpha=0.25)
        _log_debug("STEP 3.2: Plotting data for product 2...")
        ax.plot(angles, scores2_closed, color='#57F287', linewidth=2, label=remove_emojis(db_name2))
        ax.fill(angles, scores2_closed, color='#57F287', alpha=0.25)

        # Étape 4 : Personnalisation
        _log_debug("STEP 4.1: Customizing axes, labels, and legend...")
        ax.set_ylim(0, 10)
        ax.set_thetagrids(np.degrees(angles[:-1]), labels)
        # ... (le reste de la personnalisation est identique)
        ax.set_yticklabels([])
        ax.spines['polar'].set_color('gray')
        ax.set_title('Comparaison des Profils', size=20, pad=25)
        ax.legend(loc='upper right', bbox_to_anchor=(1.4, 1.1))

        # Étape 5 : Sauvegarde en mémoire
        buf = io.BytesIO()
        _log_debug("STEP 5.1: Preparing to save figure to buffer with plt.savefig()...")
        plt.savefig(buf, format='png', bbox_inches='tight', transparent=True, dpi=120)
        _log_debug("STEP 5.2: plt.savefig() successful.")
        buf.seek(0)
        
        # Étape 6 : Nettoyage
        _log_debug("STEP 6.1: Closing figure with plt.close()...")
        plt.close(fig)
        _log_debug("STEP 6.2: Figure closed.")

        _log_debug("SUCCESS: Graph generated. Returning bytes.")
        return buf.getvalue()

    except Exception as e:
        _log_debug(f"ERROR: An exception occurred: {e}")
        traceback.print_exc() # Cela ne s'affichera peut-être pas, mais on le garde au cas où
        with open(DEBUG_LOG_FILE, 'a') as f:
            traceback.print_exc(file=f) # Écrire le traceback dans le fichier
        plt.close('all')
        return None