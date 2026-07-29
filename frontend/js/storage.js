/**
 * Persistent Storage Utility
 * 
 * Uses localStorage for persistent login (survives browser close/restart).
 * Falls back to sessionStorage if localStorage is unavailable.
 * 
 * Add this script BEFORE auth.js and api.js in HTML files.
 */

const Storage = {
    /**
     * Get the storage type based on config.
     */
    _getStorage() {
        try {
            if (CONFIG.TOKEN.STORAGE === 'localStorage') {
                // Test if localStorage is available
                const testKey = '__storage_test__';
                localStorage.setItem(testKey, '1');
                localStorage.removeItem(testKey);
                return localStorage;
            }
        } catch (e) {
            // localStorage not available (private browsing, etc.), fallback to sessionStorage
        }
        return sessionStorage;
    },

    /**
     * Get an item from storage.
     */
    get(key) {
        try {
            return this._getStorage().getItem(key);
        } catch (e) {
            return null;
        }
    },

    /**
     * Set an item in storage.
     */
    set(key, value) {
        try {
            this._getStorage().setItem(key, value);
        } catch (e) {
            // Storage full or unavailable
        }
    },

    /**
     * Remove an item from storage.
     */
    remove(key) {
        try {
            this._getStorage().removeItem(key);
        } catch (e) {
            // Ignore
        }
    },

    /**
     * Clear all auth-related items.
     */
    clearAuth() {
        this.remove(CONFIG.TOKEN.ACCESS_TOKEN_KEY);
        this.remove(CONFIG.TOKEN.REFRESH_TOKEN_KEY);
    }
};