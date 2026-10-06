import test from 'node:test';
import assert from 'node:assert/strict';
import { imageDownloadUrl } from '../src/imageDownload.ts';

test('download modes are explicit and preserve existing URL parameters', () => {
  assert.equal(imageDownloadUrl('/api/images/id/download','preserve'), '/api/images/id/download?metadata=preserve');
  assert.equal(imageDownloadUrl('/api/images/id/download?x=1&metadata=preserve#file','remove'), '/api/images/id/download?x=1&metadata=remove#file');
  assert.equal(imageDownloadUrl('https://studio.test/api/images/id/download','remove'), 'https://studio.test/api/images/id/download?metadata=remove');
});
