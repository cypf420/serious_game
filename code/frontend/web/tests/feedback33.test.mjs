import assert from 'node:assert/strict';
import test from 'node:test';
import { dialogueSegments } from '../app/lib/dialogue-segments.ts';

test('named dialogue preserves every character, cursor and block identity',()=>{
  const text='他开了门。\n\n刘三：「李县长，我不能待太久。」\n\n石文斌：“材料在这里。”\n\n他们离开了。';
  const source={id:'one',blockId:'d20_arrival',contentInstanceId:'block:d20_arrival',cursor:23,kind:'narration',text};
  const result=dialogueSegments(source);
  assert.equal(result.map(s=>s.text).join(''),text);
  assert.deepEqual(result.filter(s=>s.speaker).map(s=>s.speaker),['刘三','石文斌']);
  for(const segment of result){
    assert.equal(segment.cursor,23);assert.equal(segment.blockId,source.blockId);
    assert.equal(segment.contentInstanceId,source.contentInstanceId);
    assert.equal(segment.text,text.slice(segment.sourceStart,segment.sourceEnd));
    assert.ok(segment.text.trim());
  }
  assert.equal(source.text,text);
});
test('mentions, unknown speakers and unmatched quotes do not invent identities',()=>{
  for(const text of ['你想起刘三：“他会来吗？”','陌生人：「你好。」','刘三：「未闭合'])
    assert.equal(dialogueSegments({id:'x',kind:'narration',text}).length,1);
});
test('decision gate is never split',()=>{
  assert.equal(dialogueSegments({id:'gate',text:'刘三：「怎么办？」',kind:'decision',presentationPhase:'decision'}).length,1);
});
test('verified day32 scene switch is exact and text remains intact',()=>{
  const text='罗健：「李县长。」\n\n赵建国：「小罗。」\n\n下午三点，巡察组的查账人员坐进会议室。桌上放着台账。';
  const result=dialogueSegments({id:'d32',blockId:'d32_ledger',kind:'narration',text});
  assert.equal(result.map(s=>s.text).join(''),text);
  assert.equal(result[0].displaySceneId,'C03_S02');
  assert.equal(result.at(-1).displaySceneId,'C01_S06');
});
