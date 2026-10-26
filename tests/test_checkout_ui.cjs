'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ui = require('../static/checkout.js');
const html = fs.readFileSync(path.join(__dirname, '../templates/checkout.html'), 'utf8');

function element(id, i18n = null) {
  return { id, hidden:false, disabled:false, value:'', textContent:'', className:'', type:'', name:'', checked:false, dataset:{}, attributes:i18n?{'data-i18n':i18n}:{}, listeners:{}, focused:false, children:[],
    setAttribute(key,value){this.attributes[key]=value;}, getAttribute(key){return this.attributes[key];},
    addEventListener(type,fn){this.listeners[type]=fn;}, focus(){this.focused=true;},
    appendChild(child){this.children.push(child);}, replaceChildren(...children){this.children=children;} };
}
function harness(responses=[], language='it-CH') {
  const nodes=Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(match=>[match[1],element(match[1])]));
  const translated=[...html.matchAll(/data-i18n="([^"]+)"/g)].map((match,index)=>element('translated-'+index,match[1]));
  const cycles=[element('cycle-monthly'),element('cycle-annual')]; Object.assign(cycles[0],{name:'billing-cycle',value:'monthly',checked:true}); Object.assign(cycles[1],{name:'billing-cycle',value:'annual'});
  const saved=new Map(), requests=[];
  const document={title:'',documentElement:{lang:'it'},getElementById:id=>{assert.ok(nodes[id],'Known element '+id);return nodes[id];},querySelectorAll:selector=>selector==='[data-i18n]'?translated:selector==='input[name="billing-cycle"]'?cycles:[],createElement:tag=>element(tag)};
  const window={navigator:{language},localStorage:{getItem:key=>saved.get(key)||null,setItem:(key,value)=>saved.set(key,value)},crypto:{getRandomValues(array){array[0]=11;array[1]=22;array[2]=33;return array;}}};
  async function fetcher(url,options){requests.push({url,options});const response=responses.shift();if(response instanceof Error)throw response;assert.ok(response,'fixture for '+url);if(typeof response==='function')return response(url,options);return{ok:(response.status||200)<400,status:response.status||200,json:async()=>response.data};}
  const controller=ui.createController(document,window,fetcher);
  return{controller,nodes,translated,cycles,requests,responses,document,saved};
}
const account={id:'user-1',email_verified:true,membership_verified:true,eligible_for_analysis:true,company:{id:'company-1',verified:true}};
const session={authenticated:true,csrf:'csrf-token',billing_sandbox_available:true,account};
const plans={simulation:true,charged:false,subscription_active:false,status:'draft_unapproved',plans:[
  {plan_code:'trial_company_v1',selectable:false},{plan_code:'tier_essential_v1',selectable:true},{plan_code:'tier_team_v1',selectable:true},{plan_code:'tier_partner_v1',selectable:true}
]};
function checkout(status='draft'){return{checkout_id:'intent-1',status,selection:{plan_code:'tier_team_v1',billing_cycle:'annual'},simulation:true,charged:false,subscription_active:false};}

test('checkout copy is complete in four languages and the page has explicit non-charge semantics',()=>{
  assert.deepEqual(ui.locales.sort(),['de','en','fr','it']);const keys=Object.keys(ui.dictionaries.it).sort();
  for(const language of ui.locales){assert.deepEqual(Object.keys(ui.dictionaries[language]).sort(),keys);for(const key of keys)assert.ok(ui.dictionaries[language][key].trim(),language+':'+key);}
  for(const match of html.matchAll(/data-i18n="([^"]+)"/g))assert.ok(keys.includes(match[1]),match[1]);
  assert.match(html,/Simulazione · nessun addebito/);assert.match(html,/role="radiogroup"/);assert.match(html,/aria-live="polite" aria-atomic="true" tabindex="-1"/);
  assert.doesNotMatch(html,/<input[^>]+type="(?:text|number|password)"|CVV|IBAN/i);
});

test('verified owner sees three draft cards and no internal code or invented price',async()=>{
  const h=harness([{data:session},{data:plans}]);await h.controller.start();
  assert.equal(h.nodes['checkout-chooser'].hidden,false);assert.equal(h.nodes['checkout-unavailable'].hidden,true);
  assert.equal(h.nodes['checkout-plans'].children.length,3);
  function visibleText(node){return [node.textContent,...node.children.flatMap(child=>visibleText(child))].join(' ');}
  const rendered=h.nodes['checkout-plans'].children.map(visibleText).join(' ');
  assert.doesNotMatch(rendered,/tier_|draft_unapproved|null|TBD|CHF|popular|beliebt|populaire/i);
  assert.match(rendered,/Proposta 1/);assert.match(rendered,/Da definire/);
});

test('selection creates one CSRF and idempotency protected simulation then confirms without charge',async()=>{
  const created=checkout('draft'),confirmed=checkout('confirmed_simulation');
  const h=harness([{data:session},{data:plans},{status:201,data:{checkout:created}},{data:{checkout:confirmed}}]);await h.controller.start();
  h.controller.selectPlan('tier_team_v1');assert.equal(h.nodes['checkout-plans'].children[1].children[0].focused,true);h.controller.setCycle('annual');await h.controller.createCheckout();
  const request=h.requests[2];assert.equal(request.url,'/api/sandbox/billing/checkout-simulations');assert.equal(request.options.headers['X-CSRF-Token'],'csrf-token');assert.equal(request.options.headers['Idempotency-Key'],'checkout-11-22-33');
  assert.deepEqual(JSON.parse(request.options.body),{plan_code:'tier_team_v1',billing_cycle:'annual'});assert.equal(h.nodes['checkout-summary'].hidden,false);assert.equal(h.nodes['summary-title'].focused,true);assert.equal(h.nodes['summary-plan'].textContent,'Proposta 2');
  await h.controller.transition('confirm');assert.match(h.nodes['checkout-state'].textContent,/Nessun addebito/);assert.equal(h.nodes['checkout-state'].dataset.status,'confirmed_simulation');assert.equal(h.nodes['checkout-state'].focused,true);assert.equal(h.nodes['checkout-confirm'].hidden,true);assert.equal(h.nodes['checkout-cancel'].hidden,true);
});

test('uncertain create response reuses exactly the same intent key',async()=>{
  const h=harness([{data:session},{data:plans},new Error('offline'),{status:201,data:{checkout:checkout('draft')}}]);await h.controller.start();h.controller.selectPlan('tier_essential_v1');
  await h.controller.createCheckout();const first=h.requests[2].options.headers['Idempotency-Key'];assert.match(h.nodes['checkout-notice'].textContent,/stessa richiesta/);assert.equal(h.controller.state.pendingCreateKey,first);
  await h.controller.createCheckout();assert.equal(h.requests[3].options.headers['Idempotency-Key'],first);assert.equal(h.controller.state.pendingCreateKey,null);
});

test('flag-off session reveals no chooser and makes no billing request',async()=>{
  const h=harness([{data:{...session,billing_sandbox_available:false}}]);await h.controller.start();assert.equal(h.nodes['checkout-unavailable'].hidden,false);assert.equal(h.nodes['checkout-chooser'].hidden,true);assert.equal(h.requests.length,1);
});

test('expired and cancelled states are textual and do not rely on colour',async()=>{
  const h=harness([{data:session},{data:plans},{status:201,data:{checkout:checkout('draft')}},{data:{checkout:checkout('cancelled')}}]);await h.controller.start();h.controller.selectPlan('tier_partner_v1');await h.controller.createCheckout();await h.controller.transition('cancel');
  assert.match(h.nodes['checkout-state'].textContent,/annullata/i);assert.equal(h.nodes['checkout-state'].dataset.status,'cancelled');
  h.controller.state.checkout=checkout('expired');h.controller.setLanguage('de');assert.match(h.nodes['checkout-state'].textContent,/abgelaufen/i);assert.ok(ui.dictionaries.de.draftNote.length>70);
});

test('responsive CSS covers phone, desktop cards, large text and reduced motion',()=>{
  const css=fs.readFileSync(path.join(__dirname,'../static/checkout.css'),'utf8');assert.match(css,/grid-template-columns:repeat\(3/);assert.match(css,/@media\(max-width:520px\)/);assert.match(css,/min-height:44px/);assert.match(css,/prefers-reduced-motion/);assert.match(css,/font-size:clamp/);
});
