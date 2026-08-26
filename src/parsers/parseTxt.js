import {textToHtml} from '../sanitize.js';
export function parseTxt(input){if(typeof input!=='string')return {html:'',text:''};const text=input.replace(/\r\n?/g,'\n');return {html:textToHtml(text),text}}
