/**
 * github_sync_client.js — Portail Investissement
 * Synchronise projets, sites et documents vers le dépôt GitHub via l'API REST.
 *
 * Utilisation :
 *   GHSync.isConfigured()                      → bool (token présent)
 *   GHSync.setToken(t) / GHSync.getToken()
 *   GHSync.syncProject(projectObj)             → Promise (crée/MàJ dossier + project.json)
 *   GHSync.syncSite(projectObj, siteObj)       → Promise (crée/MàJ dossier + site.json)
 *   GHSync.syncIndex()                         → Promise (MàJ data/projects.json)
 *   GHSync.uploadProjDocB64(proj, name, b64)   → Promise<url|null>
 *   GHSync.uploadSiteDocB64(proj, site, name, b64) → Promise<url|null>
 *   GHSync.loadFromGitHub()                    → Promise<projects[]|null>
 */
(function (global) {
    'use strict';

    const TOKEN_KEY   = 'pi_github_token';
    const REPO_KEY    = 'pi_github_repo';
    const API         = 'https://api.github.com';
    const DATA_ROOT   = 'data';
    const DEFAULT_REPO = 'ConsultantEnR/Project-Assessment-Portal';

    // ── Config ────────────────────────────────────────────────────────────────

    function getToken() { return localStorage.getItem(TOKEN_KEY) || ''; }
    function getRepo()  { return localStorage.getItem(REPO_KEY)  || DEFAULT_REPO; }
    function setToken(t){ if (t) localStorage.setItem(TOKEN_KEY, t.trim()); else localStorage.removeItem(TOKEN_KEY); }
    function setRepo(r) { localStorage.setItem(REPO_KEY, (r || DEFAULT_REPO).trim()); }
    function isConfigured() { return !!getToken(); }

    // ── Helpers ───────────────────────────────────────────────────────────────

    function sanitize(name) {
        return String(name || 'unnamed')
            .replace(/[<>:"/\\|?*\x00-\x1f]/g, '_')
            .replace(/\s+/g, '_')
            .replace(/_{2,}/g, '_')
            .slice(0, 60);
    }

    /** UTF-8-safe base64 encoding for text content */
    function toB64Text(str) {
        return btoa(unescape(encodeURIComponent(str)));
    }

    /** Decode base64 content from GitHub API response */
    function fromB64Text(b64) {
        return decodeURIComponent(escape(atob(b64.replace(/\n/g, ''))));
    }

    function apiHeaders() {
        return {
            'Authorization':  `Bearer ${getToken()}`,
            'Accept':         'application/vnd.github.v3+json',
            'Content-Type':   'application/json',
        };
    }

    // ── Paths ─────────────────────────────────────────────────────────────────

    function projFolder(proj) {
        return `${DATA_ROOT}/projects/${proj.id}_${sanitize(proj.name)}`;
    }

    function siteFolder(proj, site) {
        return `${projFolder(proj)}/sites/${site.id}_${sanitize(site.name)}`;
    }

    // ── GitHub REST API wrappers ───────────────────────────────────────────────

    async function ghGet(path) {
        if (!isConfigured()) return null;
        try {
            const res = await fetch(
                `${API}/repos/${getRepo()}/contents/${encodeURI(path)}`,
                { headers: apiHeaders() }
            );
            if (!res.ok) return null;
            return res.json();
        } catch { return null; }
    }

    async function ghPut(path, b64content, message, sha = null) {
        if (!isConfigured()) return false;
        try {
            const body = { message, content: b64content };
            if (sha) body.sha = sha;
            const res = await fetch(
                `${API}/repos/${getRepo()}/contents/${encodeURI(path)}`,
                { method: 'PUT', headers: apiHeaders(), body: JSON.stringify(body) }
            );
            return res.ok;
        } catch { return false; }
    }

    async function currentSha(path) {
        const data = await ghGet(path);
        return (data && !Array.isArray(data)) ? data.sha : null;
    }

    async function putText(path, text, message) {
        const sha = await currentSha(path);
        return ghPut(path, toB64Text(text), message, sha);
    }

    async function putB64(path, b64, message) {
        const sha = await currentSha(path);
        return ghPut(path, b64, message, sha);
    }

    async function ensureGitkeep(path) {
        const sha = await currentSha(path);
        if (!sha) await ghPut(path, '', 'Init dossier', null);
    }

    // ── Public : project / site sync ──────────────────────────────────────────

    async function syncProject(proj) {
        if (!isConfigured()) return;
        try {
            const base = projFolder(proj);
            await putText(
                `${base}/project.json`,
                JSON.stringify(proj, null, 2),
                `Sync projet : ${proj.name}`
            );
            // Ensure subfolder placeholders exist (parallel)
            await Promise.all([
                ensureGitkeep(`${base}/documents/.gitkeep`),
                ensureGitkeep(`${base}/sites/.gitkeep`),
            ]);
            syncIndex(); // fire-and-forget
        } catch (e) { console.warn('[GHSync] syncProject:', e); }
    }

    async function syncSite(proj, site) {
        if (!isConfigured()) return;
        try {
            const base = siteFolder(proj, site);
            await putText(
                `${base}/site.json`,
                JSON.stringify(site, null, 2),
                `Sync site : ${site.name} (${proj.name})`
            );
            await ensureGitkeep(`${base}/documents/.gitkeep`);
        } catch (e) { console.warn('[GHSync] syncSite:', e); }
    }

    async function syncIndex() {
        if (!isConfigured()) return;
        try {
            const raw = localStorage.getItem('pi_projects') || '[]';
            const projects = JSON.parse(raw);
            const index = { projects, lastSync: new Date().toISOString() };
            await putText(
                `${DATA_ROOT}/projects.json`,
                JSON.stringify(index, null, 2),
                'Sync index projets'
            );
        } catch (e) { console.warn('[GHSync] syncIndex:', e); }
    }

    // ── Public : document upload ───────────────────────────────────────────────

    /**
     * Upload un document projet depuis une base64 (extraite d'un dataUrl).
     * @param {object} proj   - projet
     * @param {string} name   - nom du fichier
     * @param {string} b64    - contenu base64 (sans le préfixe data:...)
     * @returns {Promise<string|null>} URL raw.githubusercontent.com ou null
     */
    async function uploadProjDocB64(proj, name, b64) {
        if (!isConfigured()) return null;
        try {
            const safeName = name.replace(/[^\w.\-]/g, '_');
            const path = `${projFolder(proj)}/documents/${safeName}`;
            const ok = await putB64(path, b64, `Document projet : ${name} (${proj.name})`);
            if (ok) return `https://raw.githubusercontent.com/${getRepo()}/main/${path}`;
        } catch (e) { console.warn('[GHSync] uploadProjDoc:', e); }
        return null;
    }

    /**
     * Upload un document site depuis une base64 (extraite d'un dataUrl).
     */
    async function uploadSiteDocB64(proj, site, name, b64) {
        if (!isConfigured()) return null;
        try {
            const safeName = name.replace(/[^\w.\-]/g, '_');
            const path = `${siteFolder(proj, site)}/documents/${safeName}`;
            const ok = await putB64(path, b64, `Document site : ${name} (${site.name})`);
            if (ok) return `https://raw.githubusercontent.com/${getRepo()}/main/${path}`;
        } catch (e) { console.warn('[GHSync] uploadSiteDoc:', e); }
        return null;
    }

    // ── Public : load from GitHub ──────────────────────────────────────────────

    /**
     * Charge les projets depuis data/projects.json sur GitHub.
     * @returns {Promise<object[]|null>} tableau de projets ou null
     */
    async function loadFromGitHub() {
        if (!isConfigured()) return null;
        try {
            const data = await ghGet(`${DATA_ROOT}/projects.json`);
            if (!data || !data.content) return null;
            const text   = fromB64Text(data.content);
            const parsed = JSON.parse(text);
            const arr    = Array.isArray(parsed) ? parsed : (parsed.projects || null);
            return (Array.isArray(arr) && arr.length > 0) ? arr : null;
        } catch (e) { console.warn('[GHSync] loadFromGitHub:', e); return null; }
    }

    // ── Expose ────────────────────────────────────────────────────────────────

    global.GHSync = {
        isConfigured,
        getToken, setToken,
        getRepo,  setRepo,
        syncProject,
        syncSite,
        syncIndex,
        uploadProjDocB64,
        uploadSiteDocB64,
        loadFromGitHub,
    };

})(window);
