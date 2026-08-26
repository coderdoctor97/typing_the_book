import mammoth from 'mammoth';import {sanitize} from '../sanitize.js';
export async function parseDocx(buffer){try{const r=await mammoth.convertToHtml({arrayBuffer:buffer});const html=sanitize(r.value||'');const box=document.createElement('div');box.innerHTML=html;return {html,text:box.textContent||''}}catch{return {html:'',text:''}}}
