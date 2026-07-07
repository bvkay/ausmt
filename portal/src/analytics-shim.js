// Analytics no-op shim — EXTERNAL file so no page needs an inline <script> for it (inline script
// on index.html was the only thing forcing CSP 'unsafe-inline' there; extracted 2026-07-05 so the
// deployed Caddy policy can be strict script-src 'self' everywhere except add-survey.html, whose
// application code is still one intentional inline block).
// Safe no-op queue so track() calls never error when analytics is disabled (the default).
window.plausible = window.plausible || function(){ (window.plausible.q = window.plausible.q || []).push(arguments); };
// AusMT event helper — fires a named, property-only event (no identifiers). Used for downloads,
// citation exports and package generation so an operator can see *what* is used, never *who*.
window.track = function(name, props){ try{ window.plausible(name, props ? {props:props} : undefined); }catch(e){} };
