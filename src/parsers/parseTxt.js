import {textToHtml} from '../sanitize.js';
const re=/[\p{L}\p{N}']+(?:-[\p{L}\p{N}']+)*/gu;
export function parseTxt(input){if(typeof input!=='string')return {html:'',text:'',wordCount:0,charCount:0,paragraphCount:0};const text=input.replace(/\r\n?/g,'\n');return {html:textToHtml(text),text,wordCount:(text.match(re)||[]).length,charCount:text.length,paragraphCount:text.trim()?text.split(/\n\s*\n/).filter(x=>x.trim()).length:0}}
export {textToHtml};
