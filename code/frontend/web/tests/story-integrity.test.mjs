import assert from 'node:assert/strict';
import test from 'node:test';
import {initialNarrativeState,narrativeReducer} from '../app/lib/narrative-model.ts';

const entry=(id,day,phase)=>({id,contentInstanceId:id,cursor:Number(id),storyDay:day,text:`完整正文${id}`,kind:phase==='night'?'night':'narration',presentationPhase:phase});

test('end-day reads night on its story day and archives it when morning advances the date',()=>{
  const old=entry('1',46,'consequence'), night=entry('2',46,'night'), morning=entry('3',47,'morning');
  let state=narrativeReducer(initialNarrativeState,{type:'SESSION_REBUILD',sessionId:'s',items:[old],cursor:1});
  state=narrativeReducer(state,{type:'FEED_MERGE',sessionId:'s',items:[night],storyDay:46,cursor:2});
  assert.deepEqual(state.items.map(i=>i.id),['1','2']);
  assert.equal(state.items[state.currentIndex].id,'2');
  state=narrativeReducer(state,{type:'FEED_MERGE',sessionId:'s',items:[night,morning],storyDay:47,cursor:3});
  assert.deepEqual(state.items.map(i=>i.id),['3']);
  const restored=narrativeReducer(initialNarrativeState,{type:'SESSION_REBUILD',sessionId:'s',items:[old,night,morning],storyDay:47,position:0,cursor:3});
  assert.equal(restored.items[restored.currentIndex].id,'3');
  assert.deepEqual(restored.historyItems.map(i=>i.id),['1','2']);
});
