export const computeWpm=(correct,ms)=>ms>0?Math.round((correct/5)/(Math.max(ms,1000)/60000)*10)/10:0;
export const computeAccuracy=(correct,total)=>total?Math.round(correct/total*1000)/10:100;
export const computeProgress=(done,total)=>total?Math.round(done/total*1000)/10:0;
export const elapsedMs=(start,now,paused=0)=>Math.max(0,now-start-paused);
export function sessionSummary({correctChars,totalChars,correctKeystrokes,totalKeystrokes,elapsedMs,mistakeCount}){return {wpm:computeWpm(correctChars,elapsedMs),accuracy:computeAccuracy(correctKeystrokes,totalKeystrokes),elapsedSeconds:Math.round(elapsedMs/1000),errorCount:mistakeCount,correctChars,totalChars}}
