# graph_generator.py
import matplotlib.pyplot as plt
import numpy as np
import os
import sqlite3
from typing import Dict, Any, List

# Assurez-vous que DB_FILE et Logger sont accessibles,
# ici on les importe directement si ce fichier est standalone,
# sinon, on les passerait en paramètre ou on les importerait depuis shared_utils.
# Pour l'instant, faisons comme s'il avait besoin d'importer de shared_utils
from shared_utils import Logger, DB_FILE

def create_radar_chart(product_name: str) -> str | None:
    """
    Génère un graphique en toile d'araignée pour un produit donné et le sauvegarde.
    Retourne le chemin vers le fichier image généré ou None en cas d'échec.
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Récupérer toutes les notes pour le produit donné
        cursor.execute("""
            SELECT visual_score, smell_score, touch_score, taste_score, effects_score
            FROM ratings
            WHERE product_name = ?
        """, (product_name,))
        all_ratings = cursor.fetchall()

        if not all_ratings:
            Logger.info(f"Aucune note trouvée pour '{product_name}'. Impossible de générer le graphique.")
            return None

        # Calculer la moyenne de chaque critère
        # Utiliser numpy pour faciliter la manipulation des moyennes
        all_ratings_np = np.array(all_ratings)
        mean_scores = np.mean(all_ratings_np, axis=0) # Moyenne pour chaque colonne (critère)

        # Critères et leurs scores
        categories = ['Visuel', 'Odeur', 'Touché', 'Goût', 'Effets']
        num_categories = len(categories)

        # Ajouter le premier score à la fin pour fermer la toile d'araignée
        scores_for_plot = np.concatenate((mean_scores, [mean_scores[0]]))
        angles = np.linspace(0, 2 * np.pi, num_categories, endpoint=False)
        angles = np.concatenate((angles, [angles[0]]))

        # Création du graphique
        fig, ax = plt.subplots(figsize=(6, 6), subplot_kw=dict(polar=True))
        ax.plot(angles, scores_for_plot, linewidth=2, linestyle='solid', label=f'Moyenne pour {product_name}')
        ax.fill(angles, scores_for_plot, 'blue', alpha=0.25)

        # Configuration de l'axe
        ax.set_theta_offset(np.pi / 2)
        ax.set_theta_direction(-1)
        ax.set_rlabel_position(0)
        
        # Limites de l'axe radial (notes de 0 à 10)
        ax.set_ylim(0, 10)
        ax.set_yticks(np.arange(0, 11, 2)) # Étiquettes de 0 à 10 par pas de 2
        
        # Étiquettes des catégories
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(categories)

        ax.set_title(f'Notes Moyennes pour {product_name}', va='bottom')
        ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.1))

        # Sauvegarde du graphique
        output_dir = "charts"
        os.makedirs(output_dir, exist_ok=True)
        filename = f"{output_dir}/{product_name.replace(' ', '_').replace('/', '')}_radar_chart.png"
        plt.savefig(filename, bbox_inches='tight', dpi=100)
        plt.close(fig) # Fermer la figure pour libérer la mémoire

        Logger.success(f"Graphique en toile d'araignée généré pour '{product_name}' : {filename}")
        return filename

    except sqlite3.Error as e:
        Logger.error(f"Erreur SQL lors de la génération du graphique pour '{product_name}': {e}")
        return None
    except Exception as e:
        Logger.error(f"Erreur inattendue lors de la génération du graphique pour '{product_name}': {e}")
        return None
    finally:
        if conn:
            conn.close()

# Exemple d'utilisation (pour tester séparément)
if __name__ == '__main__':
    # Initialisation minimale pour le test si nécessaire
    class MockLogger:
        @staticmethod
        def info(msg): print(f"INFO: {msg}")
        @staticmethod
        def success(msg): print(f"SUCCESS: {msg}")
        @staticmethod
        def error(msg): print(f"ERROR: {msg}")
    
    # Assurez-vous que DB_FILE est défini ou initialisé si vous testez ce fichier seul
    # from shared_utils import DB_FILE, Logger est préférable
    
    # Créer un faux DB pour le test si vous n'avez pas de ratings.db
    if not os.path.exists('ratings.db'):
        conn = sqlite3.connect('ratings.db')
        cursor = conn.cursor()
        cursor.execute(''' CREATE TABLE IF NOT EXISTS ratings (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, user_name TEXT NOT NULL, product_name TEXT NOT NULL, visual_score REAL, smell_score REAL, touch_score REAL, taste_score REAL, effects_score REAL, rating_timestamp TEXT NOT NULL, UNIQUE(user_id, product_name)) ''')
        cursor.execute("INSERT OR IGNORE INTO ratings VALUES (1, 101, 'User1', 'Product A', 7, 8, 7.5, 9, 8.5, '2023-01-01')")
        cursor.execute("INSERT OR IGNORE INTO ratings VALUES (2, 102, 'User2', 'Product A', 6, 7.5, 8, 7, 7.5, '2023-01-02')")
        cursor.execute("INSERT OR IGNORE INTO ratings VALUES (3, 103, 'User3', 'Product A', 8, 8.5, 7, 8, 9, '2023-01-03')")
        cursor.execute("INSERT OR IGNORE INTO ratings VALUES (4, 104, 'User4', 'Product B', 9, 6, 7, 8, 7.5, '2023-01-04')")
        conn.commit()
        conn.close()

    Logger.info("Test de génération de graphique...")
    chart_path = create_radar_chart("Product A")
    if chart_path:
        Logger.success(f"Graphique généré : {chart_path}")
    else:
        Logger.warning("Échec de la génération du graphique.")

    chart_path_b = create_radar_chart("Product B")
    if chart_path_b:
        Logger.success(f"Graphique généré : {chart_path_b}")
    else:
        Logger.warning("Échec de la génération du graphique pour Product B.")