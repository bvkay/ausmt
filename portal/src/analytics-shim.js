// Analytics no-op shim - EXTERNAL file so no page needs an inline <script> for it (inline script On
// index.html was the only thing forcing CSP 'unsafe-inline' there. See docs: portal internals,
// analytics-shim.js.
window.plausible = window.plausible || function(){ (window.plausible.q = window.plausible.q || []).push(arguments); };
// AusMT event helper — fires a named, property-only event (no identifiers). Used for downloads,
// citation exports and package generation so an operator can see *what* is used, never *who*.
window.track = function(name, props){ try{ window.plausible(name, props ? {props:props} : undefined); }catch(e){} };
