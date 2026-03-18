/**
 * auth.js — Portail Investissement
 * Gestion de l'authentification côté client (localStorage).
 * Exposé via window.Auth.
 */
(function (global) {
    'use strict';

    // ── Utilisateurs autorisés ─────────────────────────────
    const USERS = [
        { email: 'nicolas.lecoeur@8p2.fr', password: 'Dolfines@2026.' },
        { email: 'richard.musi@8p2.fr',    password: 'Claudine2026.'  },
    ];

    const SESSION_KEY = 'pi_auth_session';
    const LOGIN_PAGE  = 'index.html';

    // ── Helpers ────────────────────────────────────────────

    /** Extrait le prénom + nom depuis l'adresse email (partie locale avant @, split sur '.') */
    function nameFromEmail(email) {
        const local = (email || '').split('@')[0];
        return local.split('.')
            .map(p => p.charAt(0).toUpperCase() + p.slice(1).toLowerCase())
            .join(' ');
    }

    /** Initiales (2 max) depuis le nom complet */
    function initialsFromName(name) {
        return (name || '?')
            .split(' ')
            .map(p => p[0] || '')
            .join('')
            .substring(0, 2)
            .toUpperCase();
    }

    /** Lit la session depuis localStorage */
    function getSession() {
        try { return JSON.parse(localStorage.getItem(SESSION_KEY)) || null; }
        catch { return null; }
    }

    /** Met à jour les éléments #userAvatar et #userName dans la page courante */
    function renderUser(session) {
        const name     = session ? session.name : '—';
        const initials = session ? initialsFromName(name) : '?';
        const avatarEl = document.getElementById('userAvatar');
        const nameEl   = document.getElementById('userName');
        if (avatarEl) avatarEl.textContent = initials;
        if (nameEl)   nameEl.textContent   = name;
    }

    // ── API publique ───────────────────────────────────────

    /**
     * À appeler en haut du script de chaque page protégée.
     * Redirige vers index.html si la session est absente.
     * Met automatiquement à jour l'affichage du nom utilisateur.
     * @returns {object|null} session courante
     */
    function checkAuth() {
        const session = getSession();
        if (!session || !session.email) {
            window.location.replace(LOGIN_PAGE);
            return null;
        }
        // Injection du nom dans la sidebar dès que le DOM est prêt
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => renderUser(session));
        } else {
            renderUser(session);
        }
        return session;
    }

    /**
     * Tente de connecter un utilisateur.
     * @param {string} email
     * @param {string} password
     * @returns {boolean} succès
     */
    function login(email, password) {
        const user = USERS.find(u => u.email === email && u.password === password);
        if (!user) return false;
        const session = {
            email:    user.email,
            name:     nameFromEmail(user.email),
            loggedAt: Date.now(),
        };
        localStorage.setItem(SESSION_KEY, JSON.stringify(session));
        return true;
    }

    /** Déconnecte l'utilisateur et redirige vers la page de connexion */
    function logout() {
        localStorage.removeItem(SESSION_KEY);
        window.location.href = LOGIN_PAGE;
    }

    /** Retourne le nom affiché de l'utilisateur connecté */
    function getUserName() {
        const s = getSession();
        return s ? s.name : '—';
    }

    global.Auth = { checkAuth, login, logout, getUserName, getSession };

}(window));
