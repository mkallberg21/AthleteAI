// Ask the live Android WebView a question, over Chrome's debugging protocol.
// Playwright cannot attach to a WebView; the raw protocol can.
//   node scripts/ui/webview-eval.mjs "<javascript expression>"
const expr = process.argv[2];
const list = await (await fetch('http://127.0.0.1:9222/json')).json();
const target = list.find((t) => t.type === 'page') || list[0];
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
const answer = await new Promise((resolve) => {
  ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id === 1) resolve(d); };
  ws.send(JSON.stringify({ id: 1, method: 'Runtime.evaluate',
    params: { expression: expr, returnByValue: true, awaitPromise: true } }));
});
console.log(JSON.stringify(answer.result?.result?.value ?? answer.result ?? answer, null, 1));
ws.close();
