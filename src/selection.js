export const WORD_RE=/[\p{L}\p{N}']+(?:-[\p{L}\p{N}']+)*/gu;
const block=new Set(['p','h1','h2','h3','h4','h5','h6','li','blockquote','pre','tr']);
function cleanupSelection(raw){if(typeof raw!=='string')return '';return raw.split('\n').map(x=>x.replace(/\s+/g,' ').trim()).join('\n').replace(/\n{3,}/g,'\n\n').trim()}
export function selectionToText(win,selection){if(!selection||selection.isCollapsed)return '';const f=selection.getRangeAt(0).cloneContents(),parts=[];const walk=win.document.createTreeWalker(f,win.NodeFilter.SHOW_ALL);let n;while(n=walk.nextNode()){if(n.nodeType===3)parts.push(n.nodeValue);else if(n.nodeType===1&&block.has(n.tagName.toLowerCase()))parts.push('\n')}return cleanupSelection(parts.join(''))}
export function analyzeSelection(text){const t=cleanupSelection(text);const words=t.match(WORD_RE)||[];return {valid:Boolean(words.length),reason:words.length?'':'Selection is empty or contains no readable words.',words:words.length,chars:t.length}}
