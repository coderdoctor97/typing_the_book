import {marked} from 'marked'; import {sanitize} from '../sanitize.js';
const re=/[\p{L}\p{N}']+(?:-[\p{L}\p{N}']+)*/gu;
export function parseMd(input){if(typeof input!=='string')return {html:'',text:'',wordCount:0,charCount:0};const html=sanitize(marked.parse(input,{gfm:true,breaks:true}));const box=typeof document!=='undefined'?document.createElement('div'):null;if(box){box.innerHTML=html;const text=box.textContent||'';return {html,text,wordCount:(text.match(re)||[]).length,charCount:text.length}}return {html,text:input,wordCount:(input.match(re)||[]).length,charCount:input.length}}
