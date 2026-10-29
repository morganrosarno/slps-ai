/* Real-browser journeys against a disposable, outbound-blocked Flask server.
 * Requires locally installed Playwright and Chromium; never installs packages.
 * Run: node tests/acceptance_browser.cjs
 */
'use strict';
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const path = require('node:path');
const fs = require('node:fs/promises');
const os = require('node:os');
const {chromium} = require('playwright');

async function main() {
  const root = path.resolve(__dirname, '..');
  const output = process.env.SLPS_BROWSER_EVIDENCE_DIR || await fs.mkdtemp(path.join(os.tmpdir(), 'slps-browser-evidence-'));
  await fs.mkdir(output, {recursive: true});
  const server = spawn(process.env.PYTHON || 'python', [path.join(root, 'scripts/acceptance_server.py')], {cwd:root, stdio:['ignore','pipe','pipe']});
  let browser;
  const logs=[];
  server.stderr.on('data',chunk=>logs.push(chunk.toString()));
  const results=[];
  try {
    const config = await new Promise((resolve,reject)=>{
      let text=''; const timer=setTimeout(()=>reject(new Error('Synthetic server startup timeout')),15000);
      server.once('error',reject);
      server.once('exit',code=>{clearTimeout(timer);reject(new Error(`Synthetic server exited ${code}: ${logs.join('')}`));});
      server.stdout.on('data',chunk=>{text+=chunk;if(text.includes('\n')){clearTimeout(timer);try{resolve(JSON.parse(text.split('\n')[0]));}catch(e){reject(e);}}});
    });
    browser=await chromium.launch({headless:true,executablePath:process.env.SLPS_BROWSER_EXECUTABLE || chromium.executablePath()});
    for(const width of [1440,390]) for(const locale of ['it','de','fr','en']) {
      const context=await browser.newContext({viewport:{width,height:1000},locale});
      context.setDefaultTimeout(10000);
      const page=await context.newPage(); const errors=[]; const blocked=[];
      page.on('pageerror',e=>errors.push(e.message));
      await context.route('**/*',route=>{
        const url=route.request().url();
        if(url.startsWith(config.url+'/')) return route.continue();
        blocked.push(url); return route.abort();
      });
      await page.addInitScript(value=>localStorage.setItem('slps.locale',value),locale);
      async function visible(id){await page.locator(id).waitFor({state:'visible'});}
      async function layout(label){
        assert.equal(await page.locator('html').getAttribute('lang'),locale,`${label}: language`);
        const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+1);
        assert.equal(overflow,false,`${locale}/${width}/${label}: horizontal overflow`);
      }
      await page.goto(config.url); await visible('#site-language');
      await page.waitForFunction(value=>document.documentElement.lang===value,locale);
      await layout('landing');
      await page.locator('a[href="/app"]').first().click();
      await visible('#show-login'); await page.locator('#show-login').click();
      await page.locator('#login-email').fill(`${locale}${width}@example.test`);
      await page.locator('#login-password').fill(config.password);
      await page.locator('#login-submit').click(); await visible('#account-workspace');
      await layout('account'); await page.locator('#account-workspace').click();
      await visible('#workspace'); await layout('input');
      await page.locator('#photo').setInputFiles(config.photo);
      await page.locator('#context').fill('Synthetic browser acceptance. No real workplace data.');
      await page.locator('#analyse-button').click(); await visible('#report');
      assert.match(await page.locator('#summary').innerText(),/SYNTHETIC SOFTWARE TEST/);
      assert.equal(await page.locator('#print-report').isVisible(),false);
      assert.equal(await page.locator('#export-json').isVisible(),false);
      assert.equal(await page.locator('#findings canvas').count(),1,'The crop uses the submitted image');
      await layout('result');
      await page.screenshot({path:path.join(output,`${locale}-${width}-result.png`),fullPage:true});
      await page.locator('#nav-history').click(); await visible('.history-item');
      assert.equal(await page.locator('.history-item').count(),1); await layout('history');
      await page.locator('.history-actions button').first().click(); await visible('#report');
      assert.match(await page.locator('#summary').innerText(),/SYNTHETIC/);
      await page.locator('#new-analysis').click();
      await page.locator('#photo').setInputFiles(config.video);
      await page.locator('#analyse-button').click(); await visible('#video-evidence');
      assert.equal(await page.locator('#video-frames img').count()>0,true,'Technical video has sampled frames');
      assert.notEqual(await page.locator('#audio-summary').innerText(),'');
      await layout('technical-video');
      await page.locator('#account-link').click(); await visible('#consultation-load');
      await page.locator('#consultation-load').click(); await visible('#consultation-form');
      await page.locator('#consultation-submit').click(); await visible('#consultation-result');
      assert.equal(await page.locator('#consultation-reserved').innerText(),'1');
      await layout('consultation');
      await page.locator('#billing-checkout-link').click(); await visible('#checkout-chooser');
      await page.locator('#checkout-plans input[type="radio"]').first().check();
      await page.locator('#checkout-create').click(); await visible('#checkout-summary');
      await page.locator('#checkout-confirm').click();
      await page.locator('#checkout-state[data-status="confirmed_simulation"]').waitFor();
      await layout('checkout');
      await page.screenshot({path:path.join(output,`${locale}-${width}-checkout.png`),fullPage:true});
      assert.deepEqual(errors,[],`JavaScript errors: ${errors}`);
      assert.deepEqual(blocked,[],`Unexpected external requests: ${blocked}`);
      results.push({locale,width,journey:'landing/login/photo/result/crop/history/reopen/technical-video-audio/consultation/checkout',passed:true});
      await context.close();
    }
    await fs.writeFile(path.join(output,'results.json'),JSON.stringify({synthetic:true,real_ai:false,real_payments:false,results},null,2)+'\n');
    console.log(JSON.stringify({passed:results.length,evidence:output,synthetic:true,real_ai:false}));
  } catch(error) {
    console.error(error.stack); if(logs.length) console.error(logs.slice(-8).join('')); process.exitCode=1;
  } finally {
    if(browser) await browser.close();
    if(server.exitCode===null){const stopped=once(server,'exit');server.kill('SIGTERM');await stopped;}
  }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
