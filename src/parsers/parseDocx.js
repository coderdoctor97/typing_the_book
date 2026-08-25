import mammoth from 'mammoth'; import {sanitize} from '../sanitize.js';
const re=/[\p{L}\p{N}']+(?:-[\p{L}\p{N}']+)*/gu;
export async function parseDocx(buffer){try{const r=await mammoth.convertToHtml({arrayBuffer:buffer});const html=sanitize(r.value||'');const box=document.createElement('div');box.innerHTML=html;const text=box.textContent||'';return {html,text,wordCount:(text.match(re)||[]).length,charCount:text.length,messages:r.messages.map(x=>x.message)}}catch(e){return {html:'',text:'',wordCount:0,charCount:0,messages:[`Could not parse this .docx file: ${e.message}`]}}}
