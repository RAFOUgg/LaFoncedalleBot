# bot_runner.py
import asyncio
import catalogue_final
import os
import shared_utils  # <--- AJOUTEZ CET IMPORT
from concurrent.futures import ProcessPoolExecutor  # <--- AJOUTEZ CET IMPORT

print(f"INFO [BotRunner]: Démarrage du processus du bot (PID: {os.getpid()}).")
if __name__ == "__main__":
    # On initialise l'exécuteur de processus ICI et SEULEMENT ICI.
    shared_utils.process_executor = ProcessPoolExecutor(max_workers=2)
    
    try:
        asyncio.run(catalogue_final.main())
    except KeyboardInterrupt:
        print("INFO [BotRunner]: Arrêt du bot demandé.")
    finally:
        # On ajoute la logique pour fermer l'exécuteur proprement
        if shared_utils.process_executor:
            print("INFO [BotRunner]: Fermeture de l'exécuteur de processus...")
            shared_utils.process_executor.shutdown(wait=True)
            print("INFO [BotRunner]: Exécuteur de processus fermé.")
            
print(f"INFO [BotRunner]: Démarrage du processus du bot (PID: {os.getpid()}).")
if __name__ == "__main__":
    try:
        asyncio.run(catalogue_final.main())
    except KeyboardInterrupt:
        print("INFO [BotRunner]: Arrêt du bot demandé.")