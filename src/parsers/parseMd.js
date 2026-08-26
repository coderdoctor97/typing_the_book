import {marked} from 'marked';import {sanitize} from '../sanitize.js';
export function parseMd(input){if(typeof input!=='string')return {html:'',text:''};const html=sanitize(marked.parse(input,{gfm:true,breaks:true}));const box=document.createElement('div');box.innerHTML=html;return {html,text:box.textContent||''}}
