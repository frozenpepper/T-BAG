import assert from "node:assert/strict"
import fs from "node:fs"
import path from "node:path"
import { pathToFileURL } from "node:url"

const source=path.resolve(process.argv[2])
const scratchRoot=path.join(process.cwd(),"TBag","scratch"); fs.mkdirSync(scratchRoot,{recursive:true})
const tmp=fs.mkdtempSync(path.join(scratchRoot,"opencode-transport-"))
fs.writeFileSync(path.join(tmp,"package.json"),JSON.stringify({type:"module"}))
const pkg=path.join(tmp,"node_modules","@opencode-ai","plugin")
fs.mkdirSync(pkg,{recursive:true})
fs.writeFileSync(path.join(pkg,"package.json"),JSON.stringify({type:"module",exports:"./index.js"}))
fs.writeFileSync(path.join(pkg,"index.js"),`
const scalar=()=>({describe(){return this},optional(){return this}})
export const tool=Object.assign((definition)=>definition,{schema:{string:scalar,number:scalar,boolean:scalar,array:()=>scalar()}})
`)
const pluginDir=path.join(tmp,"plugins"); fs.mkdirSync(pluginDir,{recursive:true})
const pluginCopy=path.join(pluginDir,"tbag.js"); fs.copyFileSync(source,pluginCopy)
fs.copyFileSync(path.resolve(path.dirname(source),"..","tbag-opencode-transport-core.js"),path.join(tmp,"tbag-opencode-transport-core.js"))
const run=path.join(tmp,"run"); fs.mkdirSync(run,{recursive:true}); fs.writeFileSync(path.join(run,"run.json"),JSON.stringify({status:"active"}))

const encoder=new TextEncoder(); let observerResolve
const observer={pid:424242,exitCode:null,get exited(){return new Promise((resolve)=>{observerResolve=()=>{this.exitCode=0;resolve(0)}})}}
globalThis.Bun={
  spawnSync(argv){
    if(argv[2]==="inspect") return {exitCode:0,stdout:encoder.encode('{"state":"running"}'),stderr:encoder.encode("")}
    throw new Error(`unexpected spawnSync ${argv.join(" ")}`)
  },
  spawn(){return observer},
}
const prompts=[]
const client={session:{prompt:async(req)=>{prompts.push(req);return{}}},app:{log:async()=>({})}}
const module=await import(pathToFileURL(pluginCopy).href)
const plugin=await module.default({client,directory:tmp,worktree:tmp})
const args={run_root:run,phase_id:"P",task_id:"T",event_dir:path.join(run,"event")}
const result=JSON.parse(await plugin.tool.tbag_follow.execute(args,{sessionID:"parent-session",directory:tmp,worktree:tmp}))
assert.equal(result.armed,true)
const registryPath=path.join(run,".transport","opencode.json")
assert.ok(fs.existsSync(registryPath),"tbag_follow should mirror disposable observer state")
let registry=JSON.parse(fs.readFileSync(registryPath,"utf8"))
assert.equal(registry.format,"tbag-opencode-transport-v1")
assert.equal(registry.parent_sessions[0].session_id,"parent-session")
assert.equal(registry.observers[0].task_id,"T")
assert.equal(registry.observers[0].observer_pid,424242)
observerResolve(); await new Promise((resolve)=>setTimeout(resolve,0)); await new Promise((resolve)=>setTimeout(resolve,0))
registry=JSON.parse(fs.readFileSync(registryPath,"utf8"))
assert.equal(registry.observers.length,0,"completed observer should disappear from transport registry")
fs.rmSync(tmp,{recursive:true,force:true})
console.log("OPENCODE_TRANSPORT_REGISTRY_PASS")
