"""
sharepoint_sync.py
==================
Fonctions utilitaires pour synchroniser les données du portail investissement
vers SharePoint via Microsoft Graph API (MSAL pour l'authentification).

Cible :
    https://dietswell.sharepoint.com/sites/COMMERCIAL
    → Documents partages/C-8.2 ADVISORY/05 - Investments/Projets portail investissement/

Prérequis :
    pip install msal requests

Configuration (variables d'environnement ou Streamlit secrets) :
    SP_TENANT_ID     — ID du tenant Azure AD  (ex: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
    SP_CLIENT_ID     — App ID de l'app Azure AD enregistrée
    SP_CLIENT_SECRET — Secret client (si mode app-only) OU laisser vide pour device-code flow

Modes d'authentification supportés :
    1. Device-code flow   (interactif, aucun secret requis) → usage CLI / local
    2. Client credentials (silencieux, nécessite un secret)  → usage Streamlit / serveur

Utilisation :
    sp = SharePointSync(tenant_id, client_id, client_secret_or_none)
    sp.create_project_folder(project_name)
    sp.upload_document(project_name, filename, file_bytes)
    sp.save_financial_results(project_name, site_name, results_dict)
    sp.save_energy_flows(project_name, site_name, results_dict)
    sp.sync_index(projects_list)
    sp.load_index()  → list[dict] | None
    sp.upload_project_page(project_name, html_str)
    sp.upload_site_page(project_name, site_name, html_str)
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from typing import Optional

import msal
import requests

# ─── Constantes SharePoint ────────────────────────────────────────────────────

SHAREPOINT_HOST    = "dietswell.sharepoint.com"
SITE_PATH          = "/sites/COMMERCIAL"
# Chemin relatif à la racine de la bibliothèque "Documents partages"
DRIVE_ROOT_PATH    = "C-8.2 ADVISORY/05 - Investments/Projets portail investissement"
PROJECTS_FOLDER    = DRIVE_ROOT_PATH          # dossier racine des projets

GRAPH_API          = "https://graph.microsoft.com/v1.0"
SCOPES_DELEGATED   = ["https://graph.microsoft.com/Files.ReadWrite.All",
                      "https://graph.microsoft.com/Sites.ReadWrite.All"]
SCOPES_APP         = ["https://graph.microsoft.com/.default"]

# Cache token en mémoire pour la session courante
_TOKEN_CACHE: dict = {}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def sanitize(name: str) -> str:
    """Convertit un nom en nom de dossier valide pour SharePoint."""
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f#%{}^[\]`~]', '_', str(name or "")).strip()
    safe = re.sub(r'\s+', '_', safe)
    safe = re.sub(r'_+', '_', safe).strip('_')
    return safe[:80] or "projet"


def _graph_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


# ─── Classe principale ────────────────────────────────────────────────────────

class SharePointSync:
    """
    Interface unifiée pour pousser les données du portail vers SharePoint.

    Paramètres
    ----------
    tenant_id     : ID du tenant Azure AD
    client_id     : ID de l'application Azure AD
    client_secret : Secret client (app-only) — laisser None pour device-code flow
    drive_id      : (optionnel) ID de la drive SharePoint (détecté automatiquement)
    """

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: Optional[str] = None,
    ):
        self.tenant_id     = tenant_id
        self.client_id     = client_id
        self.client_secret = client_secret
        self._token: Optional[str] = None
        self._token_exp: float = 0.0
        self._site_id: Optional[str] = None
        self._drive_id: Optional[str] = None

    # ── Authentification ──────────────────────────────────────────────────────

    def _get_token_app(self) -> Optional[str]:
        """Client credentials flow (silencieux — nécessite secret + admin consent)."""
        authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        app = msal.ConfidentialClientApplication(
            self.client_id,
            authority=authority,
            client_credential=self.client_secret,
        )
        result = app.acquire_token_for_client(scopes=SCOPES_APP)
        if "access_token" in result:
            return result["access_token"]
        print(f"[SPSync] Erreur token app : {result.get('error_description')}")
        return None

    def _get_token_device_code(self) -> Optional[str]:
        """
        Device-code flow interactif.
        Affiche un code à saisir sur https://microsoft.com/devicelogin
        Utilisé en local ou en CLI.
        """
        authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        app = msal.PublicClientApplication(self.client_id, authority=authority)

        # Vérifier le cache d'abord
        accounts = app.get_accounts()
        if accounts:
            result = app.acquire_token_silent(SCOPES_DELEGATED, account=accounts[0])
            if result and "access_token" in result:
                return result["access_token"]

        flow = app.initiate_device_flow(scopes=SCOPES_DELEGATED)
        if "user_code" not in flow:
            print(f"[SPSync] Impossible d'initier le device flow : {flow}")
            return None

        print("\n" + "="*60)
        print(flow["message"])
        print("="*60 + "\n")

        result = app.acquire_token_by_device_flow(flow)
        if "access_token" in result:
            return result["access_token"]
        print(f"[SPSync] Erreur device flow : {result.get('error_description')}")
        return None

    def get_token(self) -> Optional[str]:
        """Retourne un token valide (depuis le cache ou en ré-authentifiant)."""
        if self._token and time.time() < self._token_exp - 60:
            return self._token

        if self.client_secret:
            token = self._get_token_app()
        else:
            token = self._get_token_device_code()

        if token:
            self._token = token
            self._token_exp = time.time() + 3600  # 1h par défaut
        return self._token

    # ── Résolution des IDs SharePoint ─────────────────────────────────────────

    def _get_site_id(self) -> Optional[str]:
        if self._site_id:
            return self._site_id
        token = self.get_token()
        if not token:
            return None
        url = f"{GRAPH_API}/sites/{SHAREPOINT_HOST}:{SITE_PATH}"
        r = requests.get(url, headers=_graph_headers(token))
        if r.ok:
            self._site_id = r.json().get("id")
        else:
            print(f"[SPSync] Impossible de résoudre le site ID : {r.status_code} {r.text[:200]}")
        return self._site_id

    def _get_drive_id(self) -> Optional[str]:
        """Retourne l'ID de la drive "Documents partages" du site."""
        if self._drive_id:
            return self._drive_id
        site_id = self._get_site_id()
        if not site_id:
            return None
        token = self.get_token()
        url = f"{GRAPH_API}/sites/{site_id}/drives"
        r = requests.get(url, headers=_graph_headers(token))
        if not r.ok:
            print(f"[SPSync] Impossible de lister les drives : {r.status_code} {r.text[:200]}")
            return None
        drives = r.json().get("value", [])
        # La bibliothèque principale s'appelle généralement "Documents" ou "Documents partages"
        for d in drives:
            name = d.get("name", "").lower()
            if "document" in name:
                self._drive_id = d["id"]
                break
        if not self._drive_id and drives:
            self._drive_id = drives[0]["id"]  # fallback : première drive
        return self._drive_id

    # ── Opérations fichiers Graph API ─────────────────────────────────────────

    def _upload_bytes(self, sp_path: str, content: bytes, overwrite: bool = True) -> bool:
        """
        Upload un fichier vers SharePoint via l'API Graph.
        sp_path : chemin relatif à la racine de la drive (ex: "C-8.2 ADVISORY/.../file.json")
        """
        token = self.get_token()
        drive_id = self._get_drive_id()
        if not token or not drive_id:
            return False

        encoded = requests.utils.quote(sp_path, safe="/")
        url = f"{GRAPH_API}/drives/{drive_id}/root:/{encoded}:/content"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream",
        }
        r = requests.put(url, headers=headers, data=content)
        if r.ok:
            return True
        print(f"[SPSync] Erreur upload '{sp_path}' : {r.status_code} {r.text[:300]}")
        return False

    def _upload_text(self, sp_path: str, text: str) -> bool:
        return self._upload_bytes(sp_path, text.encode("utf-8"))

    def _ensure_folder(self, folder_path: str) -> bool:
        """
        Crée un dossier (et ses parents) dans SharePoint si inexistant.
        Utilise l'API Graph "mkdir" (PATCH sur l'item avec conflictBehavior=replace).
        """
        token = self.get_token()
        drive_id = self._get_drive_id()
        if not token or not drive_id:
            return False

        # Décompose le chemin pour créer chaque niveau
        parts = folder_path.strip("/").split("/")
        # Parent = tout sauf dernier segment
        if len(parts) == 1:
            parent_ref = "root"
            folder_name = parts[0]
        else:
            parent_path = "/".join(parts[:-1])
            encoded_parent = requests.utils.quote(parent_path, safe="/")
            parent_ref = f"root:/{encoded_parent}:"
            folder_name = parts[-1]

        url = f"{GRAPH_API}/drives/{drive_id}/{parent_ref}/children"
        body = {
            "name": folder_name,
            "folder": {},
            "@microsoft.graph.conflictBehavior": "replace",
        }
        r = requests.post(url, headers=_graph_headers(token), json=body)
        return r.ok or r.status_code == 409  # 409 = déjà existant

    def _read_text(self, sp_path: str) -> Optional[str]:
        """Lit le contenu d'un fichier texte depuis SharePoint."""
        token = self.get_token()
        drive_id = self._get_drive_id()
        if not token or not drive_id:
            return None
        encoded = requests.utils.quote(sp_path, safe="/")
        url = f"{GRAPH_API}/drives/{drive_id}/root:/{encoded}:/content"
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.get(url, headers=headers)
        if r.ok:
            return r.text
        return None

    # ── Chemins ───────────────────────────────────────────────────────────────

    def _proj_path(self, project_name: str) -> str:
        return f"{PROJECTS_FOLDER}/{sanitize(project_name)}"

    def _site_path(self, project_name: str, site_name: str) -> str:
        return f"{self._proj_path(project_name)}/{sanitize(site_name)}"

    # ── API publique ──────────────────────────────────────────────────────────

    def create_project_folder(self, project_name: str) -> bool:
        """
        Crée la structure de dossiers d'un projet dans SharePoint :
            Projets portail investissement/{slug}/
                documents/
                financial_results/
                energy_flows/
        """
        try:
            base = self._proj_path(project_name)
            for sub in ["", "/documents", "/financial_results", "/energy_flows"]:
                self._ensure_folder(f"{base}{sub}")
            return True
        except Exception as e:
            print(f"[SPSync] create_project_folder: {e}")
            return False

    def create_site_folder(self, project_name: str, site_name: str) -> bool:
        """Crée la structure de dossiers d'un site."""
        try:
            base = self._site_path(project_name, site_name)
            for sub in ["", "/documents"]:
                self._ensure_folder(f"{base}{sub}")
            return True
        except Exception as e:
            print(f"[SPSync] create_site_folder: {e}")
            return False

    def sync_project(self, project: dict) -> bool:
        """Sauvegarde project.json dans le dossier du projet."""
        try:
            path = f"{self._proj_path(project['name'])}/project.json"
            return self._upload_text(path, json.dumps(project, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"[SPSync] sync_project: {e}")
            return False

    def sync_site(self, project: dict, site: dict) -> bool:
        """Sauvegarde site.json dans le dossier du site."""
        try:
            path = f"{self._site_path(project['name'], site['name'])}/site.json"
            return self._upload_text(path, json.dumps(site, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"[SPSync] sync_site: {e}")
            return False

    def sync_index(self, projects: list) -> bool:
        """Met à jour _index.json à la racine des projets."""
        try:
            index = {"projects": projects, "lastSync": datetime.utcnow().isoformat() + "Z"}
            path = f"{PROJECTS_FOLDER}/_index.json"
            return self._upload_text(path, json.dumps(index, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"[SPSync] sync_index: {e}")
            return False

    def load_index(self) -> Optional[list]:
        """Charge la liste des projets depuis _index.json sur SharePoint."""
        try:
            path = f"{PROJECTS_FOLDER}/_index.json"
            text = self._read_text(path)
            if not text:
                return None
            parsed = json.loads(text)
            arr = parsed if isinstance(parsed, list) else parsed.get("projects")
            return arr if arr else None
        except Exception as e:
            print(f"[SPSync] load_index: {e}")
            return None

    def save_financial_results(
        self, project_name: str, site_name: str, results: dict
    ) -> bool:
        """
        Sauvegarde les résultats financiers dans :
            {projet}/financial_results/{site_slug}.json
        """
        try:
            site_slug = sanitize(site_name)
            path = f"{self._proj_path(project_name)}/financial_results/{site_slug}.json"
            data = {
                "project":     project_name,
                "site":        site_name,
                "generatedAt": datetime.utcnow().isoformat() + "Z",
                "kpis":        results.get("kpis", {}),
                "annual":      results.get("annual", []),
                "params":      results.get("params", {}),
            }
            return self._upload_text(path, json.dumps(data, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"[SPSync] save_financial_results: {e}")
            return False

    def save_energy_flows(
        self, project_name: str, site_name: str, results: dict
    ) -> bool:
        """
        Sauvegarde les flux énergétiques dans :
            {projet}/energy_flows/{site_slug}.json
        """
        try:
            site_slug = sanitize(site_name)
            path = f"{self._proj_path(project_name)}/energy_flows/{site_slug}.json"
            data = {
                "project":     project_name,
                "site":        site_name,
                "generatedAt": datetime.utcnow().isoformat() + "Z",
                **results,
            }
            return self._upload_text(path, json.dumps(data, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"[SPSync] save_energy_flows: {e}")
            return False

    def upload_document(
        self, project_name: str, filename: str, file_bytes: bytes,
        site_name: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        Upload un document dans :
            {projet}/documents/{safe_name}                   (si site_name is None)
            {projet}/{site}/documents/{safe_name}            (si site_name fourni)

        Retourne (succès, url_sharepoint).
        """
        try:
            safe_name = re.sub(r'[^\w.\-]', '_', filename)
            if site_name:
                folder = f"{self._site_path(project_name, site_name)}/documents"
            else:
                folder = f"{self._proj_path(project_name)}/documents"
            path = f"{folder}/{safe_name}"
            ok = self._upload_bytes(path, file_bytes)
            if ok:
                drive_id = self._get_drive_id()
                # URL d'accès direct (nécessite auth SharePoint)
                url = (
                    f"https://{SHAREPOINT_HOST}/sites/COMMERCIAL"
                    f"/_layouts/15/download.aspx?SourceUrl={requests.utils.quote(path)}"
                )
                return True, url
            return False, ""
        except Exception as e:
            print(f"[SPSync] upload_document: {e}")
            return False, ""

    def upload_project_page(self, project_name: str, html_content: str) -> bool:
        """
        Upload une page HTML dédiée au projet :
            {projet}/projet_dashboard.html
        """
        try:
            path = f"{self._proj_path(project_name)}/projet_dashboard.html"
            return self._upload_text(path, html_content)
        except Exception as e:
            print(f"[SPSync] upload_project_page: {e}")
            return False

    def upload_site_page(
        self, project_name: str, site_name: str, html_content: str
    ) -> bool:
        """
        Upload une page HTML dédiée au site :
            {projet}/{site}/site_dashboard.html
        """
        try:
            path = f"{self._site_path(project_name, site_name)}/site_dashboard.html"
            return self._upload_text(path, html_content)
        except Exception as e:
            print(f"[SPSync] upload_site_page: {e}")
            return False


# ─── Helpers hors-classe (compatibilité avec github_sync.py) ──────────────────

def _build_sync(token_id: str, client_id: str, client_secret: Optional[str] = None) -> SharePointSync:
    return SharePointSync(token_id, client_id, client_secret)


# ─── Entrée CLI (test rapide) ─────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv()

    tenant_id     = os.environ.get("SP_TENANT_ID", "")
    client_id     = os.environ.get("SP_CLIENT_ID", "")
    client_secret = os.environ.get("SP_CLIENT_SECRET") or None  # None → device code

    if not tenant_id or not client_id:
        print(
            "Variables manquantes. Définissez SP_TENANT_ID et SP_CLIENT_ID\n"
            "dans votre .env ou dans les secrets Streamlit."
        )
        exit(1)

    sp = SharePointSync(tenant_id, client_id, client_secret)

    print("Test de connexion…")
    site_id = sp._get_site_id()
    if site_id:
        print(f"✓ Site résolu : {site_id}")
    else:
        print("✗ Impossible de résoudre le site SharePoint.")
        exit(1)

    print("Création du dossier de test…")
    ok = sp.create_project_folder("Projet_Test_CLI")
    print("✓ Dossier créé" if ok else "✗ Échec création dossier")

    print("Upload d'un fichier test…")
    ok2, url = sp.upload_document("Projet_Test_CLI", "test.txt", b"Hello SharePoint!")
    print(f"✓ Fichier uploadé : {url}" if ok2 else "✗ Échec upload")
