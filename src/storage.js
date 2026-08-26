const KEY='typing_the_book.error_history',VERSION=1;const empty=()=>({version:VERSION,words:[]});const norm=x=>typeof x==='string'?x.normalize('NFKC').trim().toLowerCase():'';
function valid(d){return d&&d.version===VERSION&&Array.isArray(d.words)&&d.words.every(w=>w&&typeof w.word==='string'&&typeof w.displayForm==='string'&&Number.isFinite(w.mistakeCount)&&Number.isFinite(w.sessionCount)&&Number.isFinite(w.lastPracticed))}
export function readHistory(){try{const d=JSON.parse(globalThis.localStorage?.getItem(KEY)||'null');return valid(d)?d:empty()}catch{return empty()}}
export function writeHistory(d){if(!valid(d))throw Error('Invalid history');globalThis.localStorage?.setItem(KEY,JSON.stringify(d))}
export function addMistake(d,displayForm){const key=norm(displayForm);if(!key)return d;let w=d.words.find(x=>norm(x.word)===key);if(w){w.mistakeCount++;w.sessionCount++;w.lastPracticed=Date.now()}else d.words.push({word:key,displayForm,mistakeCount:1,sessionCount:1,lastPracticed:Date.now()});return d}
export const removeWord=(d,w)=>({...d,words:d.words.filter(x=>norm(x.word)!==norm(w))});export const clearHistory=empty;
