"use strict";
// The terminal-command composers for the time-series hand-off, with no DOM and no SPA state, so
// index.html and every generated survey page load the same file. See docs: portal internals, fetchcmd.js.

// The output path for one fetched level, <survey slug>/<level>/<archive basename>.
function tsOutPath(r,l){return (r.slug||"survey")+"/"+l.level+"/"+String(l.filename||"download");}
// POSIX single-quote a token, so a register-derived path segment is literal in bash and zsh.
function shq(s){return "'"+String(s==null?"":s).replace(/'/g,"'\\''")+"'";}
// PowerShell and cmd quote incompatibly, so the Windows local name is held to a metacharacter-free charset.
function winSafePath(s){return String(s==null?"":s).replace(/[^A-Za-z0-9._\/-]/g,"_");}
// The unix form, one wget per file into -P <slug>/<level>, so names never collide and a re-run resumes.
function tsWgetCommand(rows){
  const lines=[];(rows||[]).forEach(r=>r.levels.forEach(l=>{
    if(l.url)lines.push("wget -c -q --show-progress --content-disposition -P "+shq((r.slug||"survey")+"/"+l.level)+" "+shq(l.url));}));
  return lines.join("\n");}
// The curl form for macOS and Windows, where curl is preinstalled, with -o paths namespaced by slug and level.
function tsCurlCommand(rows,exe){
  const win=(exe==="curl.exe");
  const parts=[exe+" -L -C - --create-dirs"];
  (rows||[]).forEach(r=>r.levels.forEach(l=>{
    if(!l.url)return;
    const p=tsOutPath(r,l),o=win?('"'+winSafePath(p)+'"'):shq(p);
    parts.push("-o "+o+' "'+l.url+'"');}));
  return parts.join(" ");}
var WGET_OS_NOTES={
  linux:"wget is preinstalled on most Linux distributions.",
  mac:"curl is preinstalled on macOS.",
  win:"curl.exe is preinstalled on Windows 10 and later. Run it in PowerShell or Command Prompt, naming curl.exe in full.",
};
function detectOs(){
  const p=String((navigator.userAgentData&&navigator.userAgentData.platform)||navigator.platform||navigator.userAgent||"");
  // "windows", never bare /win/: Darwin (the macOS kernel some UA strings report) contains "win".
  if(/windows/i.test(p)||/^win(32|64)?$/i.test(p))return "win";
  if(/mac|darwin|iphone|ipad/i.test(p))return "mac";
  return "linux";}
