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

def create_comparison_radar_chart(db_name1: str, scores1: np.ndarray, db_name2: str, scores2: np.ndarray) -> io.BytesIO | None:
    """Génère un graphique araignée de comparaison et le retourne comme un buffer en mémoire."""
    Logger.info(f"[GraphCompare] Génération pour '{db_name1}' vs '{db_name2}'.")
    
    try:
        # 1. DÉFINIR LES DONNÉES ET LES LABELS
        labels = ['Visuel', 'Odeur', 'Toucher', 'Goût', 'Effets']
        num_vars = len(labels)

        # Charger les polices personnalisées
        font_props_axes = FontProperties(family="Gobold", weight='bold', size=12)
        font_props_legend = FontProperties(family="Gobold", weight='bold', size=11)
        font_props_title = FontProperties(family="Gobold", weight='bold', size=16)

        # 2. PRÉPARER LES ANGLES POUR LE GRAPHIQUE POLAIRE
        angles = np.linspace(0, 2 * np.pi, num_vars, endpoint=False).tolist()
        # Répéter le premier angle à la fin pour fermer le polygone
        angles += angles[:1]

        # Répéter la première valeur de chaque set de données pour fermer les polygones
        scores1_closed = np.concatenate((scores1, [scores1[0]]))
        scores2_closed = np.concatenate((scores2, [scores2[0]]))

        # 3. CRÉER LE GRAPHIQUE AVEC MATPLOTLIB
        fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
        
        # Appliquer le style "dark mode" du bot
        fig.patch.set_facecolor('#2f3136')
        ax.set_facecolor('#2f3136')

        # TRACÉ 1 : Premier produit (bleu Discord)
        ax.plot(angles, scores1_closed, color='#5865F2', linewidth=2, linestyle='solid', label=remove_emojis(db_name1))
        ax.fill(angles, scores1_closed, color='#5865F2', alpha=0.25)

        # TRACÉ 2 : Second produit (vert Discord)
        ax.plot(angles, scores2_closed, color='#57F287', linewidth=2, linestyle='solid', label=remove_emojis(db_name2))
        ax.fill(angles, scores2_closed, color='#57F287', alpha=0.25)

        # 4. PERSONNALISER L'APPARENCE DU GRAPHIQUE
        ax.set_ylim(0, 10) # Forcer l'échelle de 0 à 10
        
        # Configurer les grilles et les axes
        ax.set_rgrids([2, 4, 6, 8], angle=90, color="gray", linestyle='--', linewidth=0.5)
        ax.set_thetagrids(np.degrees(angles[:-1]), labels)
        
        # Style des étiquettes des axes (Visuel, Odeur...)
        for label in ax.get_xticklabels():
            label.set_fontproperties(font_props_axes)
            label.set_color('white')
            label.set_y(label.get_position()[1] * 1.12) # Ajustement pour éviter le chevauchement

        # Masquer les étiquettes des valeurs (2, 4, 6, 8)
        ax.set_yticklabels([])
        ax.spines['polar'].set_color('gray')

        ax.set_title('Comparaison des Profils', size=20, fontproperties=font_props_title, color='white', pad=25)
        
        # Configurer la légende
        legend = ax.legend(loc='upper right', bbox_to_anchor=(1.4, 1.1))
        for text in legend.get_texts():
            text.set_fontproperties(font_props_legend)
            text.set_color('white')
        legend.get_frame().set_facecolor('#40444B')
        legend.get_frame().set_edgecolor('#2f3136')

        # 5. SAUVEGARDER LE GRAPHIQUE DANS UN BUFFER EN MÉMOIRE
        buf = io.BytesIO()
        # bbox_inches='tight' est crucial pour que la légende ne soit pas coupée
        plt.savefig(buf, format='png', bbox_inches='tight', transparent=True, dpi=120)
        buf.seek(0)
        
        plt.close(fig) # Très important pour libérer la mémoire !

        Logger.success("[GraphCompare] Graphique généré avec succès en mémoire.")
        return buf.getvalue()

    except Exception as e:
        Logger.error(f"Erreur inattendue dans create_comparison_radar_chart : {e}")
        traceback.print_exc()
        plt.close('all') # S'assurer de tout fermer en cas d'erreur
        return None