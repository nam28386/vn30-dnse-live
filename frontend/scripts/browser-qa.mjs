import { chromium } from '@playwright/test';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import assert from 'node:assert/strict';
const artifactDir = new URL('../../artifacts/', import.meta.url).pathname;
mkdirSync(artifactDir, {recursive:true});
const executablePath = process.env.CHROMIUM_PATH || (existsSync('/usr/bin/chromium') ? '/usr/bin/chromium' : undefined);
const browser = await chromium.launch({executablePath, headless:true, args:['--no-sandbox']});
const page = await browser.newPage({viewport:{width:1440,height:1050},deviceScaleFactor:1});
const errors=[];
let interrupted=false;
const sockets=[];
await page.routeWebSocket('**/api/stream', ws=>{
 if(interrupted){ws.close({code:1012,reason:'QA network interruption'});return;}
 sockets.push(ws);
 ws.connectToServer();
});
page.on('pageerror', e=>errors.push(e.message));
try {
 await page.goto('http://127.0.0.1:5173/');
 await page.locator('.session').filter({hasText:'REPLAY CONNECTED'}).waitFor();
 await page.getByText('Price discovery',{exact:true}).waitFor();
 await page.waitForFunction(()=>document.querySelectorAll('canvas').length>=8);
 const initial = await page.locator('.market-time').textContent();
 await page.waitForFunction(t=>document.querySelector('.market-time')?.textContent !== t, initial);
 await page.screenshot({path:artifactDir+'/desktop.png', fullPage:true});
 await page.getByRole('button',{name:'Volume',exact:true}).click();
 await page.getByRole('button',{name:'Explore events ↗'}).click();
 await page.locator('.event-row').first().click();
 await page.locator('.event-detail').waitFor();
 await page.screenshot({path:artifactDir+'/events.png',fullPage:true});
 await page.getByRole('button',{name:'Data quality',exact:true}).first().click();
 await page.getByText('Feature quality & availability').waitFor();
 await page.getByRole('button',{name:'Market overview'}).click();
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:artifactDir+'/mobile.png',fullPage:true});
 const overflow = await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth);
 assert.equal(overflow,false,'mobile horizontal overflow');
 await page.setViewportSize({width:1440,height:1050});
 interrupted=true;
 await page.context().setOffline(true);
 for(const socket of sockets)socket.close({code:1012,reason:'QA network interruption'});
 await page.getByRole('alert').waitFor({timeout:20000});
 assert.match(await page.getByRole('alert').innerText(), /frozen/);
 interrupted=false;
 await page.context().setOffline(false);
 await page.locator('.session').filter({hasText:'REPLAY CONNECTED'}).waitFor({timeout:25000});
 assert.deepEqual(errors,[]);
 writeFileSync(artifactDir+'/browser-qa.json', JSON.stringify({
  status:'PASS',browser:'Chromium',desktop:'1440x1050',mobile:'390x844',
  checks:['HTTP load','WebSocket stream updates','Lightweight Charts canvas rendering',
   'CVD/volume switch','event details','feature quality navigation','no mobile overflow',
   'offline frozen-data warning','automatic reconnect','no uncaught browser errors'],errors
 },null,2));
 console.log('Browser QA PASS: desktop, mobile, charts, tabs, streaming, disconnect/reconnect.');
} finally {await browser.close();}
