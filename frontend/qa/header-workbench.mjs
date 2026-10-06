// Run against the browser owned by agent-browser, on the isolated QA fixture.
// No request in this fixture can reach NovelAI or the user's database.
import assert from 'node:assert/strict';
const ws = new WebSocket(process.argv[2]);
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
let sequence = 0;
const pending = new Map();
ws.onmessage = ({ data }) => {
  const message = JSON.parse(data);
  const request = pending.get(message.id);
  if (request) {
    pending.delete(message.id);
    message.error ? request.reject(message.error) : request.resolve(message.result);
  }
};
const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
  const id = ++sequence;
  pending.set(id, { resolve, reject });
  ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
});
try {
  const { targetInfos } = await send('Target.getTargets');
  const target = targetInfos.find(t => t.type === 'page' && t.url.startsWith('http://127.0.0.1:5179/qa/design.html'));
  assert(target, 'Open the isolated QA fixture with agent-browser first');
  const { sessionId } = await send('Target.attachToTarget', { targetId: target.targetId, flatten: true });
  const evaluate = async expression => {
    const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true }, sessionId);
    assert(!result.exceptionDetails, JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  const settle = () => evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 120))))');
  const click = async selector => {
    const point = await evaluate(`(() => {const e=document.querySelector(${JSON.stringify(selector)}); if(!e) throw Error('Missing click target'); const r=e.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2};})()`);
    for (const type of ['mousePressed', 'mouseReleased']) await send('Input.dispatchMouseEvent', { type, button: 'left', clickCount: 1, ...point }, sessionId);
    await settle();
  };
  const viewport = async (width, height) => {
    await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false }, sessionId);
    await settle();
  };
  const measure = () => evaluate(`(() => {
    const rect = e => {const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom};};
    return {width:innerWidth,height:innerHeight,overflow:document.documentElement.scrollWidth-innerWidth,
      removed:document.querySelectorAll('.sidebar,.bottom-nav,.workbench-results,.workbench-mobile-switch').length,
      headers:document.querySelectorAll('.studio-header').length,navigations:document.querySelectorAll('nav[aria-label="주 메뉴"]').length,
      header:rect(document.querySelector('.studio-header')),footer:rect(document.querySelector('.generation-action-bar')),
      nav:[...document.querySelectorAll('.header-nav button')].map(e=>({name:e.textContent,...rect(e)})),errors:window.__qaErrors};
  })()`);
  // The supplied mock images must not appear or be fetched as a preview.
  assert.equal(await evaluate('window.__qaRequests.filter(r=>r.path==="/api/images").length'), 0);
  const layouts = [];
  for (const [width, height] of [[320,740],[390,844],[600,900],[820,1180],[1024,768],[1100,800],[1101,800],[1180,820],[1440,900],[1920,1080]]) {
    await viewport(width, height);
    await evaluate('scrollTo(0,0);document.activeElement?.blur()');
    await settle();
    const state = await measure();
    assert.equal(state.overflow, 0, `No horizontal overflow at ${width}`);
    assert.equal(state.removed, 0);
    assert.equal(state.headers, 1);
    assert.equal(state.navigations, 1);
    assert.deepEqual(state.errors, []);
    assert.equal(state.nav.length, 6);
    assert(state.footer.bottom <= height && state.footer.y >= state.header.bottom, `Footer must remain usable at ${width}`);
    for (const button of state.nav) {
      assert(button.width >= 44 && button.height >= 44, `44px target: ${button.name} at ${width}`);
      assert(button.x >= 0 && button.right <= width && button.y >= 0 && button.bottom <= state.header.bottom, `Menu must be inside header: ${button.name}`);
    }
    layouts.push(state);
  }
  await viewport(390,844);
  await click('.header-connection > summary');
  assert.equal(await evaluate('document.querySelector(".header-connection").open'), true);
  const popup = await evaluate('(()=>{const r=document.querySelector(".header-connection-panel").getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,viewport:innerHeight};})()');
  assert(popup.left >= 0 && popup.right <= 390 && popup.bottom <= popup.viewport);
  assert.equal(await evaluate('document.querySelector(".header-connection-panel").textContent.includes("LAN 연결 가능")'), true);
  await send('Input.dispatchKeyEvent', { type:'keyDown', key:'Escape', code:'Escape', windowsVirtualKeyCode:27 }, sessionId);
  await settle();
  assert.equal(await evaluate('document.querySelector(".header-connection").open'), false);
  assert.equal(await evaluate('document.activeElement===document.querySelector(".header-connection > summary")'), true);
  await click('.header-connection > summary');
  assert.equal(await evaluate('window.NovelAIStudioBack()'), true);
  assert.equal(await evaluate('document.querySelector(".header-connection").open'), false);
  await click('.header-connection > summary');
  await click('.prompt-panel textarea');
  assert.equal(await evaluate('document.querySelector(".header-connection").open'), false);

  const routes = [];
  for (const [index, name] of ['생성','갤러리','인물','통계','설정'].entries()) {
    await click(`.header-nav button:nth-child(${index+1})`);
    const route = await evaluate('({active:document.querySelector(".header-nav [aria-current=page]")?.textContent,heading:document.querySelector("main h1")?.textContent,errors:window.__qaErrors,overflow:document.documentElement.scrollWidth-innerWidth})');
    assert.equal(route.active, name);
    assert(route.heading, `The ${name} screen must render a heading`);
    assert.deepEqual(route.errors, []);
    assert.equal(route.overflow, 0);
    if (name === '갤러리') assert.equal(await evaluate('document.querySelectorAll(".image-card").length'), 2);
    routes.push(route);
  }
  // The Android hardware-back hook must still go to the previous page.
  assert.equal(await evaluate('window.NovelAIStudioBack()'), true);
  await settle();
  assert.equal(await evaluate('document.querySelector(".header-nav [aria-current=page]").textContent'), '통계');
  await click('.header-nav button:first-child');
  const previousTheme = await evaluate('document.documentElement.dataset.theme');
  await click('.theme-toggle');
  assert.notEqual(await evaluate('document.documentElement.dataset.theme'), previousTheme);
  // Verify input state and one batched request; no live API or paid generation.
  await evaluate(`(() => {const el=document.querySelector('.repeat-count-control input');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,'3');el.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await settle();
  await click('.floating-submit-button');
  const requests = await evaluate('window.__qaRequests.filter(r=>r.path==="/api/jobs"&&r.method==="POST").map(r=>JSON.parse(r.body))');
  assert.equal(requests.length,1);
  assert.equal(requests[0].repeat_count,3);
  assert.equal(requests[0].description_prompt,'햇살이 비치는 창가, 편안한 오후의 한 장면');
  await viewport(1440,900);
  // Validation opens a closed disclosure and focuses the invalid field.
  await evaluate(`document.querySelector('.settings-panel').open=true`);
  await settle();
  await evaluate(`(() => {const el=[...document.querySelectorAll('.settings-grid label')].find(e=>e.textContent==='가로').querySelector('input');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,'65');el.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await settle();
  await evaluate('document.querySelector(".settings-panel").open=false;document.querySelector(".creator-layout").requestSubmit()');
  await settle();
  assert.equal(await evaluate('document.querySelector(".settings-panel").open'), true);
  assert.equal(await evaluate('document.activeElement.type'), 'number');
  assert.equal(await evaluate('window.__qaRequests.filter(r=>r.path==="/api/jobs"&&r.method==="POST").length'),1);
  assert.deepEqual(await evaluate('window.__qaErrors'), []);
  console.log(JSON.stringify({passed:true,layouts,routes,popup,repeatCount:requests[0].repeat_count,validation:true,hardwareBack:true,errors:[]},null,2));
} finally { ws.close(); }
