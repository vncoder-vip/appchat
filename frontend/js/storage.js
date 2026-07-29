/**
 * Persistent Storage Utility
 * 
 * Uses localStorage for persistent login (survives browser close/restart).
 * Falls back to sessionStorage if localStorage is unavailable.
 * 
 * NOTE: Uses 'AppStorage' instead of 'Storage' to avoid conflict with
 * the browser's built-in window.Storage interface.
 * 
 * Provides both short methods (get/set/remove) and full methods (getItem/setItem/removeItem)
 * for compatibility with code that may call either style.
 */

const AppStorage = {
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
        // Fallback to sessionStorage (works in all browsers)
        return window.sessionStorage;
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
     * Alias for get() - compatibility with sessionStorage API style.
     */
    getItem(key) {
        return this.get(key);
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
     * Alias for set() - compatibility with sessionStorage API style.
     */
    setItem(key, value) {
        this.set(key, value);
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
     * Alias for remove() - compatibility with sessionStorage API style.
     */
    removeItem(key) {
        this.remove(key);
    },

    /**
     * Clear all auth-related items.
     */
    clearAuth() {
        this.remove(CONFIG.TOKEN.ACCESS_TOKEN_KEY);
        this.remove(CONFIG.TOKEN.REFRESH_TOKEN_KEY);
    }
};