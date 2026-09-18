import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { freshExpressions, parseExpressions, faceMask, expressionRect, EXPRESSION_SOURCE_SHA } from '../src/features/avatar-2d/expression-library.ts';

const library = freshExpressions();
assert.deepEqual(parseExpressions(library), library);
assert.equal(library.entries.length, 8);
assert.equal(new Set(library.entries.map(e => e.id)).size, 8);
assert.equal(createHash('sha256').update(readFileSync(new URL('../public/avatars/cat-2d-v1/base.png',import.meta.url))).digest('hex'), EXPRESSION_SOURCE_SHA, 'existing rig coordinates must remain bound to the original artwork');
for (const entry of library.entries) {
  const path = new URL(`../public${entry.image}`,import.meta.url);
  assert.ok(existsSync(path));
  const png=readFileSync(path);
  assert.equal(png.readUInt32BE(16),1024);assert.equal(png.readUInt32BE(20),1536);
}
assert.throws(() => parseExpressions({...library,source_sha256:'different-artwork'}),/캐릭터/);
assert.throws(() => parseExpressions({...library,entries:[library.entries[1]]}),/원본/);
assert.throws(() => parseExpressions({...library,selected:'missing'}),/선택/);
assert.throws(() => parseExpressions({...library,entries:[...library.entries,library.entries[1]]}),/중복/);
assert.throws(() => parseExpressions({...library,entries:library.entries.map((e,i) => i===0?{...e,scale:1.1}:e)}),/원본/);
for (const bad of ['https://example.org/avatar.png','javascript:alert(1)','data:image/svg+xml;base64,PHN2Zz4=']) assert.throws(() => parseExpressions({...library,entries:[...library.entries,{...library.entries[1],id:'custom',image:bad}]}),/이미지/);
assert.throws(() => parseExpressions({...library,entries:[...library.entries,{...library.entries[1],id:'custom',scale:Infinity}]}),/정렬/);
const custom={...library.entries[1],id:'custom',image:'data:image/png;base64,YWJjZA=='};
assert.equal(parseExpressions({...library,selected:'custom',entries:[...library.entries,custom]}).selected,'custom');
const parsed=parseExpressions(library);parsed.entries[1].name='changed';assert.equal(library.entries[1].name,'미소','editing a loaded document cannot mutate its source');
assert.deepEqual(expressionRect(library.entries[0]),[0,0,1024,1536]);
assert.deepEqual(expressionRect({...custom,layout:'face',offsetX:10,offsetY:-5}),[408,105,224,224]);
assert.equal(faceMask(508,219),1);
for(const [x,y] of [[400,10],[600,25],[512,320],[400,345],[512,420],[800,700],[512,1000]]) assert.equal(faceMask(x,y),0,'face color cannot affect ears, shoulders, torso or limbs');
for(let x=0;x<1024;x+=5) for(let y=290;y<1536;y+=5) assert.equal(faceMask(x,y),0);
assert.equal(faceMask(470,200),1);assert.equal(faceMask(547,200),1);assert.equal(faceMask(508,250),1);
console.log('2D expressions: bundled images, source identity, immutable original, portable document validation, alignment and face-only masking passed.');
