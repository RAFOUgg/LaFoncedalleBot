# dev_stats_cog.py

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import aiohttp
import traceback
import subprocess
from datetime import datetime, timedelta, timezone

from shared_utils import (
    Logger, 
    create_styled_embed,
    GITHUB_TOKEN, 
    GITHUB_REPO_OWNER, 
    GITHUB_REPO_NAME
)
from commands import is_staff_or_owner # On importe le check de permission

# --- Fonctions de Calcul ---

async def get_commit_stats() -> dict:
    """
    Interroge l'API GitHub pour récupérer les statistiques des commits.
    """
    if not all([GITHUB_TOKEN, GITHUB_REPO_OWNER, GITHUB_REPO_NAME]):
        return {"error": "Configuration GitHub manquante."}

    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    api_url = f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/commits"
    
    all_commits = []
    page = 1
    
    try:
        async with aiohttp.ClientSession() as session:
            while True:
                params = {"per_page": 100, "page": page}
                async with session.get(api_url, headers=headers, params=params) as response:
                    response.raise_for_status()
                    data = await response.json()
                    if not data:
                        break
                    all_commits.extend(data)
                    page += 1
    except Exception as e:
        Logger.error(f"Erreur API GitHub : {e}")
        return {"error": str(e)}

    # Calcul de l'estimation du temps
    daily_sessions = {}
    for commit in all_commits:
        commit_date_str = commit['commit']['author']['date']
        commit_date = datetime.fromisoformat(commit_date_str.replace('Z', '+00:00'))
        day = commit_date.date()
        
        if day not in daily_sessions:
            daily_sessions[day] = []
        daily_sessions[day].append(commit_date)

    total_duration = timedelta(0)
    for day, commits_in_day in daily_sessions.items():
        if len(commits_in_day) > 1:
            first_commit = min(commits_in_day)
            last_commit = max(commits_in_day)
            session_duration = last_commit - first_commit
            total_duration += session_duration

    return {
        "total_commits": len(all_commits),
        "estimated_duration": total_duration,
        "first_commit_date": datetime.fromisoformat(all_commits[-1]['commit']['author']['date'].replace('Z', '+00:00')),
        "last_commit_date": datetime.fromisoformat(all_commits[0]['commit']['author']['date'].replace('Z', '+00:00'))
    }


def get_loc_stats() -> dict:
    """
    Utilise des commandes git locales pour compter les lignes et les caractères
    UNIQUEMENT pour les fichiers Python (.py).
    """
    try:
        # --- MODIFICATION 1 : On spécifie de ne chercher que les fichiers .py ---
        pathspec = '*.py'

        # Compte le nombre de fichiers Python
        files_process = subprocess.run(
            ['git', 'ls-files', pathspec], 
            capture_output=True, text=True, check=True
        )
        file_list = files_process.stdout.strip().split('\n')
        # Gère le cas où aucun fichier .py n'est trouvé pour éviter une erreur
        total_files = len(file_list) if file_list and file_list[0] else 0

        # Si aucun fichier .py n'est trouvé, on retourne des zéros
        if total_files == 0:
            return {"total_lines": 0, "total_chars": 0, "total_files": 0}

        # Utilise xargs et wc sur la liste filtrée de fichiers Python
        p1 = subprocess.Popen(['git', 'ls-files', pathspec], stdout=subprocess.PIPE)
        p2 = subprocess.Popen(['xargs', 'wc'], stdin=p1.stdout, stdout=subprocess.PIPE, text=True)
        p1.stdout.close()
        output = p2.communicate()[0]
        
        total_line = output.strip().split('\n')[-1]
        parts = total_line.split()
        
        total_lines = int(parts[0])
        total_chars = int(parts[2])

        return {
            "total_lines": total_lines,
            "total_chars": total_chars,
            "total_files": total_files
        }

    except (subprocess.CalledProcessError, FileNotFoundError, IndexError) as e:
        Logger.error(f"Erreur lors de l'exécution de git/wc : {e}")
        return {"error": "Impossible d'exécuter les commandes git locales."}


# --- Le Cog ---

class DevStatsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="project_stats", description="[STAFF] Affiche les statistiques de développement du projet.")
    @app_commands.check(is_staff_or_owner)
    async def project_stats(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)

        try:
            commit_task = asyncio.create_task(get_commit_stats())
            loc_task = asyncio.to_thread(get_loc_stats)

            commit_data, loc_data = await asyncio.gather(commit_task, loc_task)
            
            if "error" in commit_data:
                await interaction.followup.send(f"❌ Erreur GitHub : {commit_data['error']}", ephemeral=True)
                return
            if "error" in loc_data:
                await interaction.followup.send(f"❌ Erreur Locale : {loc_data['error']}", ephemeral=True)
                return

            embed = create_styled_embed(
                title=f"📊 Statistiques du Projet - {GITHUB_REPO_NAME}",
                description="Un aperçu de l'activité de développement du projet.",
                color=discord.Color.dark_green()
            )

            first_commit_ts = int(commit_data['first_commit_date'].timestamp())
            last_commit_ts = int(commit_data['last_commit_date'].timestamp())
            
            commit_text = (
                f"**Nombre total de commits :** `{commit_data['total_commits']}`\n"
                f"**Premier commit :** <t:{first_commit_ts}:D>\n"
                f"**Dernier commit :** <t:{last_commit_ts}:R>"
            )
            embed.add_field(name="⚙️ Activité des Commits", value=commit_text, inline=False)
            
            # --- MODIFICATION 1 (Label) : On précise qu'on compte les fichiers Python ---
            loc_text = (
                f"**Lignes de code :** `{loc_data['total_lines']:,}`\n"
                f"**Caractères :** `{loc_data['total_chars']:,}`\n"
                f"**Fichiers Python :** `{loc_data['total_files']}`"
            )
            embed.add_field(name="💻 Code Source (.py)", value=loc_text, inline=True)

            # --- MODIFICATION 2 : On calcule et affiche le nombre total d'heures ---
            total_seconds = commit_data['estimated_duration'].total_seconds()
            total_hours = total_seconds / 3600
            time_text = f"**Estimation :**\n`{total_hours:.2f} heures`"
            embed.add_field(name="⏱️ Amplitude de Développement", value=time_text, inline=True)

            embed.set_footer(text="Données via API GitHub & commandes git locales.")

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            Logger.error(f"Erreur dans /project_stats : {e}")
            traceback.print_exc()
            await interaction.followup.send("❌ Une erreur critique est survenue.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(DevStatsCog(bot))