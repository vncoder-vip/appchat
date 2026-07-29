/**
 * Authentication State Management.
 * 
 * Manages login/logout state, token lifecycle, and user info.
 * Uses localStorage for persistent session (survives browser restart).
 */
const Auth = {
    _user: null,
    _listeners: [],

    /**
     * Initialize auth from stored session.
     * Auto-refreshes expired tokens.
     * Does NOT clear token on transient errors (e.g. Vercel cold start).
     */
    async init() {
        const token = AppStorage.get(CONFIG.TOKEN.ACCESS_TOKEN_KEY);
        if (!token) return false;

        ApiClient.init(token);

        // Retry up to 3 times for cold start on Vercel
        var maxRetries = 3;
        for (var attempt = 1; attempt <= maxRetries; attempt++) {
            try {
                const data = await ApiClient.getMe();
                if (data.success) {
                    this._user = data.user;
                    this._notify();
                    return true;
                }
                // API returned success=false, token might be invalid
                if (attempt >= maxRetries) {
                    // Try refresh before giving up
                    try {
                        const refreshed = await ApiClient._tryRefresh();
                        if (refreshed) {
                            const data2 = await ApiClient.getMe();
                            if (data2.success) {
                                this._user = data2.user;
                                this._notify();
                                return true;
                            }
                        }
                    } catch (e) {
                        // Refresh failed
                    }
                    // Only clear token if we're sure it's invalid
                    // Check if we got a 401 response
                    if (data.code === 'TOKEN_EXPIRED_OR_INVALID' || data.code === 'UNAUTHORIZED') {
                        AppStorage.clearAuth();
                    }
                    return false;
                }
            } catch (err) {
                // Network error or server error (cold start) - retry
                if (attempt >= maxRetries) {
                    // Last attempt - try refresh
                    try {
                        const refreshed = await ApiClient._tryRefresh();
                        if (refreshed) {
                            const data2 = await ApiClient.getMe();
                            if (data2.success) {
                                this._user = data2.user;
                                this._notify();
                                return true;
                            }
                        }
                    } catch (e) {
                        // Refresh failed
                    }
                    // Don't clear token on network/server errors - token is still valid
                    return false;
                }
                // Wait before retry (exponential backoff)
                await new Promise(function(r) { setTimeout(r, attempt * 1000); });
            }
        }
        return false;
    },

    /**
     * Check if current user is admin.
     */
    isAdmin() {
        return this._user && this._user.role === 'admin';
    },

    /**
     * Login with username/email + password.
     */
    async login(usernameOrEmail, password) {
        const data = await ApiClient.login(usernameOrEmail, password);
        if (data.success) {
            ApiClient.setAccessToken(data.accessToken);
            AppStorage.set(CONFIG.TOKEN.ACCESS_TOKEN_KEY, data.accessToken);
            this._user = data.user;
            this._notify();
        }
        return data;
    },

    /**
     * Register new account.
     */
    async register(username, email, password) {
        const data = await ApiClient.register(username, email, password);
        if (data.success) {
            ApiClient.setAccessToken(data.accessToken);
            AppStorage.set(CONFIG.TOKEN.ACCESS_TOKEN_KEY, data.accessToken);
            this._user = data.user;
            this._notify();
        }
        return data;
    },

    /**
     * Logout current session.
     */
    async logout() {
        try {
            await ApiClient.logout();
        } catch (err) {
            // Ignore errors during logout
        }
        this._cleanup();
    },

    /**
     * Logout from all devices.
     */
    async logoutAll() {
        try {
            await ApiClient.logoutAll();
        } catch (err) {
            // Ignore errors
        }
        this._cleanup();
    },

    /**
     * Clean up auth state.
     */
    _cleanup() {
        ApiClient.clearAccessToken();
        AppStorage.clearAuth();
        this._user = null;
        this._notify();
        window.location.href = 'login.html';
    },

    /**
     * Check if user is authenticated.
     */
    isAuthenticated() {
        return !!this._user;
    },

    /**
     * Get current user.
     */
    getUser() {
        return this._user;
    },

    /**
     * Refresh user data from API.
     */
    async refreshUser() {
        try {
            const data = await ApiClient.getMe();
            if (data.success) {
                this._user = data.user;
                this._notify();
            }
            return data;
        } catch (err) {
            return null;
        }
    },

    /**
     * Subscribe to auth state changes.
     */
    subscribe(listener) {
        this._listeners.push(listener);
        return () => {
            this._listeners = this._listeners.filter(l => l !== listener);
        };
    },

    /**
     * Notify all listeners of state change.
     */
    _notify() {
        this._listeners.forEach(listener => {
            try {
                listener(this._user);
            } catch (err) {
                console.error('Auth listener error:', err);
            }
        });
    },

    /**
     * Update user profile (username, display_name, avatar_url).
     */
    async updateProfile(username, display_name, avatar_url) {
        const data = await ApiClient.put(CONFIG.ENDPOINTS.UPDATE_PROFILE, { username, display_name, avatar_url });
        if (data.success) {
            this._user = data.user;
            this._notify();
        }
        return data;
    },

    /**
     * Change password.
     */
    async changePassword(currentPassword, newPassword) {
        return ApiClient.post(CONFIG.ENDPOINTS.CHANGE_PASSWORD, { currentPassword, newPassword });
    },

    /**
     * Redirect to login if not authenticated.
     */
    requireAuth() {
        if (!this.isAuthenticated()) {
            window.location.href = 'login.html?redirect=' + encodeURIComponent(window.location.pathname);
            return false;
        }
        return true;
    },
};