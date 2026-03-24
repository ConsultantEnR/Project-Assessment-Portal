"""
github_sync.py
==============
Fonctions utilitaires pour synchroniser les données de projet sur GitHub.

Utilisation :
    - Nécessite PyGithub (déjà dans requirements.txt)
    - Token GitHub dans les secrets Streamlit : GITHUB_TOKEN = "ghp_..."
"""

import json
import re
from datetime import datetime
from github import Github, Auth, GithubException

PROJECTS_BASE = "projects"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def sanitize(name: str) -> str:
    """Convertit un nom de projet en nom de dossier valide pour GitHub."""
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip()
    safe = re.sub(r'\s+', '_', safe)
    return safe[:80] or "projet"


def _get_repo(token: str, repo_name: str):
    return Github(auth=Auth.Token(token)).get_repo(repo_name)


def _get_contents_safe(repo, path: str):
    """Retourne le contenu d'un chemin ou None si inexistant."""
    try:
        return repo.get_contents(path)
    except GithubException:
        return None


def _create_or_update(repo, path: str, message: str, content) -> bool:
    """Crée ou met à jour un fichier sur GitHub. Accepte str ou bytes."""
    try:
        if isinstance(content, str):
            content = content.encode("utf-8")
        existing = _get_contents_safe(repo, path)
        if existing and not isinstance(existing, list):
            repo.update_file(path, message, content, existing.sha)
        else:
            repo.create_file(path, message, content)
        return True
    except GithubException:
        return False


# ─── Gestion des dossiers projet ──────────────────────────────────────────────

def create_project_folder(token: str, repo_name: str, project_name: str,
                          project_id: str = "") -> bool:
    """
    Crée la structure de dossiers d'un projet sur GitHub :
        projects/{slug}/
            .gitkeep
            financial_results/.gitkeep
            energy_flows/.gitkeep
            documents/.gitkeep
    """
    try:
        repo = _get_repo(token, repo_name)
        slug = sanitize(project_name)
        base = f"{PROJECTS_BASE}/{slug}"
        ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        subdirs = ["", "/financial_results", "/energy_flows", "/documents"]
        for sub in subdirs:
            path = f"{base}{sub}/.gitkeep"
            if not _get_contents_safe(repo, path):
                _create_or_update(
                    repo, path,
                    f"Init dossier projet : {project_name} ({ts})",
                    ""
                )
        return True
    except Exception:
        return False


def rename_project_folder(token: str, repo_name: str,
                          old_name: str, new_name: str) -> bool:
    """
    Renomme un dossier de projet en déplaçant tous les fichiers vers
    le nouveau chemin, puis en supprimant l'ancien.
    """
    try:
        repo = _get_repo(token, repo_name)
        old_slug = sanitize(old_name)
        new_slug = sanitize(new_name)

        if old_slug == new_slug:
            return True

        old_base = f"{PROJECTS_BASE}/{old_slug}"
        new_base = f"{PROJECTS_BASE}/{new_slug}"

        # Récupérer tous les fichiers récursivement
        def collect_files(path):
            items = _get_contents_safe(repo, path)
            if items is None:
                return []
            if not isinstance(items, list):
                items = [items]
            files = []
            for item in items:
                if item.type == "dir":
                    files.extend(collect_files(item.path))
                else:
                    files.append(item)
            return files

        all_files = collect_files(old_base)

        # Si l'ancien dossier n'existe pas, créer juste le nouveau
        if not all_files:
            return create_project_folder(token, repo_name, new_name)

        # Copier chaque fichier vers le nouveau chemin
        msg = f"Renommage projet : {old_name} → {new_name}"
        for f in all_files:
            new_path = f.path.replace(old_base, new_base, 1)
            try:
                _create_or_update(repo, new_path, msg, f.decoded_content)
            except Exception:
                pass

        # Supprimer l'ancien dossier (tous les fichiers)
        for f in all_files:
            try:
                repo.delete_file(f.path, msg, f.sha)
            except Exception:
                pass

        return True
    except Exception:
        return False


# ─── Sauvegarde des résultats ─────────────────────────────────────────────────

def save_financial_results(token: str, repo_name: str,
                           project_name: str, site_name: str,
                           results: dict) -> bool:
    """
    Sauvegarde les résultats du modèle financier dans :
        projects/{project_slug}/financial_results/{site_slug}.json
    """
    try:
        repo = _get_repo(token, repo_name)
        slug = sanitize(project_name)
        site_slug = sanitize(site_name)
        path = f"{PROJECTS_BASE}/{slug}/financial_results/{site_slug}.json"

        data = {
            "project":     project_name,
            "site":        site_name,
            "generatedAt": datetime.utcnow().isoformat() + "Z",
            "kpis":        results.get("kpis", {}),
            "annual":      results.get("annual", []),
            "params":      results.get("params", {}),
        }
        content = json.dumps(data, ensure_ascii=False, indent=2)
        return _create_or_update(
            repo, path,
            f"Résultats financiers : {site_name} ({project_name})",
            content
        )
    except Exception:
        return False


def save_energy_flows(token: str, repo_name: str,
                      project_name: str, site_name: str,
                      results: dict) -> bool:
    """
    Sauvegarde les résultats de simulation des flux énergétiques dans :
        projects/{project_slug}/energy_flows/{site_slug}.json
    """
    try:
        repo = _get_repo(token, repo_name)
        slug = sanitize(project_name)
        site_slug = sanitize(site_name)
        path = f"{PROJECTS_BASE}/{slug}/energy_flows/{site_slug}.json"

        data = {
            "project":     project_name,
            "site":        site_name,
            "generatedAt": datetime.utcnow().isoformat() + "Z",
            **results,
        }
        content = json.dumps(data, ensure_ascii=False, indent=2)
        return _create_or_update(
            repo, path,
            f"Flux énergétiques : {site_name} ({project_name})",
            content
        )
    except Exception:
        return False


# ─── Gestion des documents ────────────────────────────────────────────────────

def upload_document(token: str, repo_name: str,
                    project_name: str, filename: str,
                    file_bytes: bytes) -> tuple[bool, str]:
    """
    Upload un document dans :
        projects/{project_slug}/documents/{safe_filename}

    Retourne (succès, url_raw_github).
    """
    try:
        repo = _get_repo(token, repo_name)
        slug = sanitize(project_name)
        safe_name = re.sub(r'[^\w.\-]', '_', filename)
        path = f"{PROJECTS_BASE}/{slug}/documents/{safe_name}"

        ok = _create_or_update(
            repo, path,
            f"Upload document : {filename} ({project_name})",
            file_bytes
        )
        if ok:
            raw_url = (
                f"https://raw.githubusercontent.com/{repo_name}/main/{path}"
            )
            return True, raw_url
        return False, ""
    except Exception:
        return False, ""


def list_documents(token: str, repo_name: str,
                   project_name: str) -> list[dict]:
    """
    Liste les documents dans :
        projects/{project_slug}/documents/

    Retourne une liste de dicts {name, path, size, download_url}.
    """
    try:
        repo = _get_repo(token, repo_name)
        slug = sanitize(project_name)
        path = f"{PROJECTS_BASE}/{slug}/documents"

        items = _get_contents_safe(repo, path)
        if items is None:
            return []
        if not isinstance(items, list):
            items = [items]

        return [
            {
                "name":         f.name,
                "path":         f.path,
                "size":         f.size,
                "download_url": f.download_url,
            }
            for f in items
            if f.name != ".gitkeep"
        ]
    except Exception:
        return []
