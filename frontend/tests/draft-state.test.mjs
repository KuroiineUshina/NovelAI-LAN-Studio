import { test } from 'node:test';
import assert from 'node:assert/strict';
import { canAcceptRemoteDraft, outputSeed, removeDeletedPresetSelections } from '../src/draftState.ts';

test('unknown remote character is preserved; only a known deletion removes a selection', () => {
  assert.deepEqual(removeDeletedPresetSelections(['old', 'created-on-PC'], ['old'], ['old']), ['old', 'created-on-PC']);
  assert.deepEqual(removeDeletedPresetSelections(['deleted', 'created-on-PC'], ['deleted'], []), ['created-on-PC']);
});
test('a response cannot replace edits made while the poll or preset refresh was in flight', () => {
  assert.equal(canAcceptRemoteDraft(12, 10, true, false), false);
  assert.equal(canAcceptRemoteDraft(12, 10, false, true), false);
  assert.equal(canAcceptRemoteDraft(11, 12, false, false), false);
  assert.equal(canAcceptRemoteDraft(12, 12, false, false), false);
  assert.equal(canAcceptRemoteDraft(12, 10, false, false), true);
});
test('reuse actual output seed including zero, not the batch request seed', () => {
  assert.equal(outputSeed({ seed: 43, settings: { seed: 42 } }), 43);
  assert.equal(outputSeed({ seed: 0, settings: { seed: 42 } }), 0);
  assert.equal(outputSeed({ seed: 77, settings: { seed: null } }), 77);
  assert.equal(outputSeed({ seed: null, settings: { seed: 42 } }), 42);
  assert.equal(outputSeed({ seed: null, settings: { seed: null } }), null);
});
