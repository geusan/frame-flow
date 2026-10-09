import assert from 'node:assert/strict';
import { BodyTrackingSession } from '../../../packages/studio/src/features/avatar-2d/tracking-session.ts';
const workers=[],tracks=[];
class WorkerMock {
  terminated=false;
  constructor(){workers.push(this);}
  postMessage(m){if(m.type==='init')queueMicrotask(()=>{if(!this.terminated)this.onmessage?.({data:{type:'ready'}});});}
  terminate(){this.terminated=true;}
}
const stream=()=>{const track={stopped:false,stop(){this.stopped=true;},addEventListener(){}};tracks.push(track);return {getTracks:()=>[track]};};
const video={srcObject:null,src:'',paused:true,videoWidth:640,videoHeight:480,async play(){this.paused=false;},pause(){this.paused=true;},removeAttribute(){this.src='';},load(){}};
Object.defineProperty(globalThis,'navigator',{configurable:true,value:{mediaDevices:{getUserMedia:async()=>stream()}}});
globalThis.Worker=WorkerMock;globalThis.window=globalThis;globalThis.requestAnimationFrame=()=>1;globalThis.cancelAnimationFrame=()=>{};
const statuses=[];const session=new BodyTrackingSession(video,()=>{},(text,running)=>statuses.push({text,running}));
await session.start();assert.equal(statuses.at(-1).running,true);assert.ok(video.srcObject);
session.stop();assert.equal(tracks.at(-1).stopped,true);assert.equal(workers.at(-1).terminated,true);assert.equal(video.srcObject,null);
let grant;navigator.mediaDevices.getUserMedia=()=>new Promise(resolve=>{grant=resolve;});
const pending=session.start();await new Promise(resolve=>setTimeout(resolve,0));session.stop();grant(stream());await pending;
assert.equal(tracks.at(-1).stopped,true,'late camera permissions are released');assert.equal(video.srcObject,null);
const initializing=session.start();session.stop();await initializing;assert.equal(workers.at(-1).terminated,true);
navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('denied','NotAllowedError');};await session.start();assert.match(statuses.at(-1).text,/권한/);assert.equal(statuses.at(-1).running,false);
navigator.mediaDevices.getUserMedia=async()=>stream();video.play=async()=>{throw new Error('decode failed');};await session.start();assert.equal(tracks.at(-1).stopped,true);assert.equal(workers.at(-1).terminated,true);
video.play=async()=>{};await session.start('http://localhost/example.mp4');assert.equal(video.src,'http://localhost/example.mp4');const oldWorker=workers.at(-1);session.stop();await session.start('http://localhost/second.mp4');oldWorker.onerror?.();assert.equal(workers.at(-1).terminated,false,'stale worker errors cannot stop the new session');session.stop();
console.log('2D tracking: camera teardown, denial, late grants, initialization cancellation, video errors and stale sessions passed.');
