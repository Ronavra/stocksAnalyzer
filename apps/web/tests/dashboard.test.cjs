const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const Module=require('node:module');
const ts=require('typescript');
const React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
require.extensions['.css']=()=>{};
function load(file){
 const name=path.resolve(__dirname,'..',file);
 const output=ts.transpileModule(fs.readFileSync(name,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}});
 const m=new Module(name,module);m.filename=name;m.paths=Module._nodeModulePaths(path.dirname(name));m._compile(output.outputText,name);return m.exports;
}
const Portfolio=load('app/PortfolioComparison.tsx').default;
const replay={status:'ok',summary:{},curve:[],issues:[],pending_cohorts:0};
function data(){return {active_version:'current',by_policy:{old:{5:{total_return:{base:replay}}},current:{5:{total_return:{base:replay}}}}};}
test('only one current selection policy is offered, with controls explained',()=>{
 const html=renderToStaticMarkup(React.createElement(Portfolio,{data:data()}));
 assert.doesNotMatch(html,/Selection policy<select|>old<|>current</);
 assert.match(html,/One current weekly selection policy/);
 assert.equal((html.match(/<select/g)||[]).length,3);
 assert.match(html,/reinvested dividends/);
 assert.match(html,/0\.10% per buy and per sell/);
 assert.match(html,/simulation assumptions/);
});
test('missing current policy never silently substitutes old decisions',()=>{
 const d=data();delete d.by_policy.current;
 const html=renderToStaticMarkup(React.createElement(Portfolio,{data:d}));
 assert.match(html,/older versions are never substituted/);
 assert.doesNotMatch(html,/<select/);
});
test('performance details show current results only',()=>{
 const Performance=load('app/PolicyPerformance.tsx').default;
 const policy={cohorts:0,no_pick_cohorts:0,by_horizon:{}};
 const html=renderToStaticMarkup(React.createElement(Performance,{metrics:{active_version:'current',by_policy:{old:{...policy,cohorts:7},current:policy}}}));
 assert.match(html,/Current weekly selection/);
 assert.doesNotMatch(html,/7 published groups|>old</);
});
test('API timeout is distinguished from a service that cannot be reached',async()=>{
 const api=load('lib/api.ts');const previous=global.fetch;
 try{
  global.fetch=async()=>{throw new DOMException('timeout','TimeoutError');};
  await assert.rejects(api.getSystemHealth(),/took too long/);
  global.fetch=async()=>{throw new TypeError('network');};
  await assert.rejects(api.getSystemHealth(),/Cannot reach/);
 }finally{global.fetch=previous;}
});

test('archive deferral and short history are visible without claiming validation',()=>{
 const Model=load('app/ModelReadiness.tsx').default;
 const html=renderToStaticMarkup(React.createElement(Model,{data:{history_requires_local_archive:true,
 financial_observation_days:7,estimate_observation_days:7,fiscal_estimate_companies:501,minimum_observed_sample_dates:26,
 latest_execution:{metadata:{outcome:'deferred_archive_required'}},latest_training:{status:'interrupted'}}}));
 assert.match(html,/Training awaits the local archive/);
 assert.match(html,/501 companies/);
 assert.match(html,/Deferred/);
 assert.match(html,/interrupted/);
 assert.doesNotMatch(html,/model promoted|Validation passed/);
});
