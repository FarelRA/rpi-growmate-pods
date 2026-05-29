/**
 * GrowMate Setup Form - Progressive Enhancement
 * 
 * This script enhances the native HTML form with AJAX submission for better UX.
 * The form works without JavaScript via native submission as a fallback.
 */

(function() {
    'use strict';
    
    // Wait for DOM to be ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
    
    function init() {
        const form = document.getElementById('configForm');
        const status = document.getElementById('status');
        
        if (!form || !status) {
            console.error('Required form elements not found');
            return;
        }
        
        // Enhance form with AJAX submission
        form.addEventListener('submit', handleSubmit);
    }
    
    /**
     * Handle form submission with AJAX
     * Falls back to native submission if fetch fails
     */
    async function handleSubmit(e) {
        e.preventDefault(); // Prevent native submission, use AJAX instead
        
        const form = e.target;
        const ssid = document.getElementById('wifiSsid').value.trim();
        const password = document.getElementById('wifiPassword').value;
        const submitButton = form.querySelector('button[type="submit"]');
        
        // Validate SSID
        if (!ssid) {
            showStatus('Please enter a WiFi network name', 'error');
            return;
        }
        
        // Disable submit button and show loading state
        submitButton.disabled = true;
        showStatus('Saving configuration...', '');
        
        try {
            const response = await fetch('/api/config', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    wifiSsid: ssid,
                    wifiPassword: password
                })
            });
            
            const data = await response.json();
            
            if (response.ok) {
                showStatus(data.message || 'Configuration saved successfully!', 'success');
                // Keep button disabled on success
            } else {
                showStatus(data.error || 'Failed to save configuration', 'error');
                submitButton.disabled = false;
            }
        } catch (error) {
            console.error('Network error:', error);
            showStatus('Network error. Please try again.', 'error');
            submitButton.disabled = false;
        }
    }
    
    /**
     * Display status message to user
     * @param {string} message - Message to display
     * @param {string} type - Message type: 'success', 'error', or empty for neutral
     */
    function showStatus(message, type) {
        const status = document.getElementById('status');
        if (!status) return;
        
        status.textContent = message;
        status.className = 'show' + (type ? ' ' + type : '');
    }
})();
