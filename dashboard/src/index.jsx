/**
 * Hermes Chat — Dashboard Plugin Entry Point.
 *
 * Registers the React component with the Hermes Dashboard SDK.
 * The SDK provides React, hooks, and UI components via window.__HERMES_PLUGIN_SDK__.
 */
import React from 'react';
import App from './App';
import './Chat.css';

// ── Plugin Registration ────────────────────────────────────────────────────
// Dashboard plugins do NOT need ReactDOM — the Dashboard handles mounting.
// We return a React component and register it; Dashboard calls render().

const SDK = window.__HERMES_PLUGIN_SDK__;
if (!SDK) {
  console.error('[hermes-chat] SDK not found — is the Dashboard loaded?');
}

/**
 * Plugin root component that wraps App in SDK's React context if needed.
 */
function HermesChatPlugin() {
  return React.createElement(App);
}

// Register with the Dashboard
if (window.__HERMES_PLUGINS__) {
  window.__HERMES_PLUGINS__.register('hermes-chat', HermesChatPlugin);
}

export default HermesChatPlugin;
