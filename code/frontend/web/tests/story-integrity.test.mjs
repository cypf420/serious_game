import assert from 'node:assert/strict';
import test from 'node:test';
import {initialNarrativeState,narrativeReducer} from '../app/lib/narrative-model.ts';

const entry=(id,day,phase)=>({id,contentInstanceId:id,cursor:Number(id),storyDay:day,text:`完整正文${id}`,kind:phase==='night'?'night':'narration',presentationPhase:phase});

test('end-day shows newly emitted night text before the next morning, including rebuild',()=>{
  const old=entry('1',46,'consequence'), night=entry('2',46,'night'), morning=entry('3',47,'morning');
  let state=narrativeReducer(initialNarrativeState,{type:'SESSION_REBUILD',sessionId:'s',items:[old],cursor:1});
  state=narrativeReducer(state,{type:'FEED_MERGE',sessionId:'s',items:[night,morning],cursor:3});
  assert.deepEqual(state.items.map(i=>i.id),['2','3']);
  assert.equal(state.items[state.currentIndex].id,'2');
  state=narrativeReducer(state,{type:'FEED_MERGE',sessionId:'s',items:[night,morning],cursor:3});
  assert.deepEqual(state.items.map(i=>i.id),['2','3']);
  const restored=narrativeReducer(initialNarrativeState,{type:'SESSION_REBUILD',sessionId:'s',items:[old,night,morning],position:0,cursor:3});
  assert.equal(restored.items[restored.currentIndex].id,'2');
  assert.deepEqual(restored.historyItems.map(i=>i.id),['1']);
});
