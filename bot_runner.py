# bot_runner.py
import asyncio
import catalogue_final
import os


print(f"INFO [BotRunner]: Démarrage du processus du bot (PID: {os.getpid()}).")
if __name__ == "__main__":
    try:
        asyncio.run(catalogue_final.main())
    except KeyboardInterrupt:
        print("INFO [BotRunner]: Arrêt du bot demandé.")

print(f"INFO [BotRunner]: Démarrage du processus du bot (PID: {os.getpid()}).")
if __name__ == "__main__":
    try:
        asyncio.run(catalogue_final.main())
    except KeyboardInterrupt:
        print("INFO [BotRunner]: Arrêt du bot demandé.")