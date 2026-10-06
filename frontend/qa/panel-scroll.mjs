// Real wheel input against the isolated fixture only. No production API calls.
// Usage: node qa/panel-scroll.mjs <owned test browser CDP websocket URL>
import assert from 'node:assert/strict';
const ws = new WebSocket(process.argv[2]);
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
let seq = 0;
const pending = new Map();
ws.onmessage = ({data}) => {
  const message = JSON.parse(data);
  const task = pending.get(message.id);
  if (task) { pending.delete(message.id); message.error ? task.reject(message.error) : task.resolve(message.result); }
};
function send(method, params = {}, sessionId) {
  return new Promise((resolve, reject) => {
    const id = ++seq;
    pending.set(id, {resolve, reject});
    ws.send(JSON.stringify({id, method, params, ...(sessionId ? {sessionId} : {})}));
  });
}
try {
  const {targetInfos} = await send('Target.getTargets');
  const target = targetInfos.find(t => t.type === 'page' && t.url.startsWith('http://127.0.0.1:5179/qa/design.html'));
  assert(target, 'The isolated test fixture must be open');
  const {sessionId} = await send('Target.attachToTarget', {targetId:target.targetId, flatten:true});
  const evaluate = async expression => {
    const result = await send('Runtime.evaluate', {expression, returnByValue:true, awaitPromise:true}, sessionId);
    assert(!result.exceptionDetails, JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  const settle = () => evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 120))))');
  await evaluate(`document.querySelector('.settings-panel').open = true;
    document.querySelector('.negative-disclosure').open = true;
    document.querySelector('.creator-main').scrollTop = 0;`);
  await settle();
  const measure = () => evaluate(`(() => {
    const p=document.querySelector('.creator-main'), r=p.getBoundingClientRect();
    return {body:scrollY, docHeight:document.documentElement.scrollHeight, viewport:innerHeight,
      panel:p.scrollTop, panelMax:p.scrollHeight-p.clientHeight,
      header:document.querySelector('.topbar').getBoundingClientRect().top,
      footer:document.querySelector('.generation-action-bar').getBoundingClientRect().top,
      x:r.left+5, y:r.top+80};
  })()`);
  const before = await measure();
  const wheel = async (deltaY, x=before.x, y=before.y) => {
    await send('Input.dispatchMouseEvent', {type:'mouseWheel',x,y,deltaX:0,deltaY}, sessionId);
    await settle();
  };
  await wheel(500);
  const middle = await measure();
  assert(middle.panel > before.panel, 'Wheel must move the right panel');
  await wheel(100000);
  await wheel(800);
  const end = await measure();
  assert.equal(end.panel, end.panelMax, 'All settings must be reachable');
  await wheel(800, 40, 36);
  const outside = await measure();
  for (const sample of [before, middle, end, outside]) {
    assert.equal(sample.body, 0, 'The document must not scroll');
    assert.equal(sample.docHeight, sample.viewport, 'Document height must fit viewport');
    for (const anchor of ['header','footer']) assert.equal(sample[anchor], before[anchor], `${anchor} must stay fixed`);
  }
  assert.equal(outside.panel, end.panel, 'Wheel over header must not move settings');
  await evaluate("document.querySelector('.creator-main').scrollTop=0;document.querySelector('.creator-main').focus()");
  await send('Input.dispatchKeyEvent', {type:'keyDown',key:'PageDown',code:'PageDown',windowsVirtualKeyCode:34}, sessionId);
  await send('Input.dispatchKeyEvent', {type:'keyUp',key:'PageDown',code:'PageDown',windowsVirtualKeyCode:34}, sessionId);
  await settle();
  const keyboard = await measure();
  assert(keyboard.panel > 0, 'Keyboard must scroll the focused settings panel');
  assert.equal(keyboard.body, 0);
  console.log(JSON.stringify({passed:true,before,middle,end,outside,keyboard},null,2));
} finally { ws.close(); }
