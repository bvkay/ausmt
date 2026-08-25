"use strict";
// HTML-escaping helpers. ALL survey/station metadata is escaped through these before it
// reaches innerHTML. esc -> text nodes; escAttr -> quoted attribute values; escUrl -> hrefs.
function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function escAttr(s){return esc(s);}
// The "/" branch is a SAME-ORIGIN path and nothing else. A second slash starts an off-site authority
// (//host), and a backslash is folded to a slash while an http(s) URL is parsed, so /\host reaches the
// same authority; both collapse to "#" like every other off-allowlist form. Third-party field values
// arrive here raw (a related identifier of type URL), so this branch is an allowlist, not a shorthand.
function escUrl(u){u=String(u==null?"":u);return /^(https?:|mailto:|#|\/(?![\/\\]))/i.test(u)?esc(u):"#";}
