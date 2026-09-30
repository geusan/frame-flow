# Studio character generation

## Mandatory body continuity — 2026-10-01

For all future wardrobe/pose transfers, the established White Pink Bob Character (art_f8f932740cf64e329c) is the anatomical source of truth. The user explicitly reported that the outfit transfer reduced the character's bust to the outfit model's body shape. Preserve the Character's bust volume and forward projection, shoulder/ribcage/waist/hip ratios and limb proportions across clothing changes. Use frontal, side and full-body Character views; fit and drape garments around that body. Never reshape the character to match the person wearing a reference outfit, flatten the chest to fit clothing, or exaggerate beyond the Character. Clothing/pose/environment references cannot override anatomy. Preserve approved facial relighting during body correction. Preserving anatomy does not mean tracing skin-level breast separation onto thick outer knitwear: allow hidden undergarment support, fabric thickness and ease to produce a gentle central bridge and a stable button placket without shrinking the character.

## Current active brief — White Pink Bob redesign (2026-09-30)

The user explicitly superseded the first-photo identity lock: the earlier results resembled source 1 too closely. Create a new adult identity informed by all three newly added photos, use original photo 2 only for its chin-length bob silhouette, and use pearl-white hair blended with pastel pink. Cheekbones/cheek apples must not appear round or inflated; retain natural volume, a softly tapered oval outline and smooth cheek-to-jaw transitions, without gaunt hollows or an extreme V-shaped chin. Keep the studio wardrobe and natural rose makeup. Original source 1 and the earlier generated characters must not be identity inputs for this redesign.

New references: art_976aef4273f34927a6, art_a2ebd13d73da42ccab, art_7dcdad56ec854778a7. Haircut reference: art_2bab21e4d772432fa5. The Canvas branch first creates an independent Image identity baseline (pink-bob-design), then uses it as the sole identity image for character.generate@2 (studio-character-pink-bob), producing a new 8-view Character. This avoids the old Character executor re-locking the original source-1 face. Existing characters remain historical results. Prompt/blueprint and run records: output/studio-character-pink-bob/.

The older requests below are historical and do not override this active brief.

`character.generate@2` adds an OpenAI studio shot plan to the existing Character capability. This is a new contract because the shot roles, default view count and default quality change. V1 definitions and its story-scene prompts remain unchanged.

V2 defaults to eight high-quality views: full-body front (`baseline`), front headshot, left/right three-quarter, left/right profile, full-body back and smiling portrait. The first supplied reference defines the person's face and hair. Three additional inputs are styling/posing references. The initial request uses all four inputs; subsequent requests include the generated baseline first, followed by all four originals. The provider supports these five images without dropping the fourth source.

The existing Registry capability and `NodeExecutionResult` produce one `Character` (`character.v1`) and eight `Image` (`character.view.v1`) artifacts. Original inputs have `reference_image` lineage; the bundle links generated views as `character_view`. The runtime snapshots `character-openai.v2`, the Definition digest, normalized config, provider and exact model. Studio provider errors are marked non-retryable so an explicit provider failure is not automatically billed again; a failure before the bundle is complete can leave provider-side work without a finished Character. Cost reporting retains the existing per-model estimate, not a provider invoice.

## Draft migration

There is no automatic migration. Replace a V1 node manually in a Draft with the Registry's Studio character node, reconnect the same typed ports in the original order, and copy the prompt and desired name. The UI uses Generic Inspector.

Review this diff before replacement:

| Setting | V1 | V2 default |
| --- | --- | --- |
| contract_version | 1 | 2 |
| model | Existing Google/OpenAI selection | OpenAI image alias |
| shot_count | 6, or saved value | 8 |
| quality | medium, or saved value | high |
| shot_style | Not available; story scenes | studio |
| reference inputs used | Up to 3 | Up to 4 + generated studio anchor |
| view roles | Baseline, cafe, work, action, night, etc. | Eight studio views |

Warnings: V2 generates new artifacts and incurs new API usage. It does not modify an existing Character or prior Run. Preserve existing settings intentionally, then publish a new WorkflowVersion to use this graph in a managed Workflow. Existing published Versions and their V1 execution remain unchanged.

## Canvas request: canvas_8fd18abfcd5f4c05aa

The user requested one reusable character built from the four existing Canvas images, eight photoreal studio images, NOTTALGGAK prompting and OpenAI API generation. The user explicitly selected: **keep the person in the first photograph; use the other three only for style**. This request must not be interpreted as face blending or four separate characters.

Source order:

1. `art_a734c3fe2b5d428aab`: identity and hair.
2. `art_2bab21e4d772432fa5`: style.
3. `art_fa932ce2915f4fe09f`: style.
4. `art_2c039d843a074b378e`: style.

The exact skill prompt, Korean translation and blueprint are saved in `output/studio-character-8/master-prompt.md` and the Canvas prompt/annotation. Local/Temporal contract, provider request, view count, source order, lineage and V1 compatibility are covered by `test_studio_character.py`.

## Completed result

- Character: `art_4c8b274d425943c2a9` — **Studio Character 01**.
- Canvas run: `canvasrun_866874f2faca4eebbb`, `SUCCEEDED`, one attempt.
- Experiment: `exp_856c1d22b87a4375a4`, `character-openai.v2`, exact model `gpt-image-2`.
- Eight PNG images verified at 1024 × 1536 and displayed in the Canvas node detail gallery. Copies: `output/studio-character-8/01-baseline.png` through `08-smile.png`.
- Original four reference artifacts retained in order; first reference identity, remaining references styling only. Canvas prompt and editable Sticky record the user's decision.
- The generated three-quarter views have similar orientation; the opposite profile views and rear view are present. These are a studio portrait set, not a calibrated 3D turnaround.
- Validation: 81 API/contract/provider/Local–Temporal tests passed; UI architecture and workflow contract checks passed. The live result and all eight images were visually inspected.

## Makeup revision request — 2026-09-30

The user added `art_1e0ef3b79f084995b9` (image.png) and explicitly confirmed: **preserve the first photograph's face and apply only the new photograph's makeup**. Do not blend in the new person's face or copy her tied-back hair, sweater, microphone or background.

The requested makeup is a natural satin complexion, diffused cool-pink cheek blush, understated brown/taupe eyes and muted rose satin lips. A new eight-image Character is being created, preserving the original eight-image Character. Inputs are ordered: original identity `art_a734c3fe2b5d428aab`, prior studio baseline `art_05f1dfcbba7f44b39b`, new makeup reference LAST. The prior baseline carries lineage to the original four inputs and preserves wardrobe/studio styling.

- New Canvas node: `studio-character-makeup` (`character.generate@2`).
- Run: `canvasrun_730028ddd0a8489b87`.
- Prompt, translation and blueprint: `output/studio-character-makeup/master-prompt.md`.
- Original pasted-image node was recovered from its already completed upload; no duplicate upload was made.

Completed makeup revision: Character `art_f8d6160eed97475aae` — **Studio Character 01 · Rosy Makeup**, eight PNG views generated with `gpt-image-2`; run `canvasrun_730028ddd0a8489b87` succeeded in one attempt. The original Character `art_4c8b274d425943c2a9` and its eight images remain unchanged. Canvas node detail gallery and saved output were verified; the frontal portraits show restrained pink blush, softer brown eye definition and muted rose lips while retaining the original identity, hairstyle, wardrobe and studio setting. Copies are in `output/studio-character-makeup/`.

## White Pink Bob execution records

- New identity baseline: `art_6e251204186748cd9e`, generated by `image.generate@1` with OpenAI `gpt-image-2` from original haircut photo 2 and all three newly added references; original photo 1 and previous Character outputs were excluded. Design run `canvasrun_fb8b1b5f05c84d309b` succeeded; experiment `exp_d7e833919a7e491596`.
- Baseline visually checked: visibly new face, smooth tapered cheek/jaw outline without protruding spherical cheek apples, chin-length blunt bob, pearl-white/pastel-pink blend. Baseline copy: `output/studio-character-pink-bob/design-baseline.png`.
- Eight-view run: `canvasrun_b6905d48140647cf9f`; experiment `exp_dbbe91de08444e8a9b`. The only direct identity input is the new baseline. Input lineage retains the four design references.

Completed White Pink Bob Character: `art_f8f932740cf64e329c` — **Studio Character · White Pink Bob**, eight views. Run `canvasrun_b6905d48140647cf9f` succeeded in one attempt (643943 ms) using OpenAI `gpt-image-2`. Canvas node `studio-character-pink-bob` is saved as SUCCEEDED with all eight images. The full gallery and frontal/angled portraits were visually checked: pearl-white and pastel-pink chin-length bob, airy bangs, a new face and a smoother cheek/jaw silhouette without the earlier round projecting cheek apples. Existing characters remain unchanged. Output copies: `output/studio-character-pink-bob/01-baseline.png` through `08-smile.png`.

## Outfit and pose image — 2026-10-01

The user requested the current White Pink Bob Character wearing the outfit and adopting the pose from Canvas node `upload-1790782239011-1` (`art_55b8c9977d3e44dfb2`). The character's face, white/pink bob and flatter cheek silhouette remain fixed. The reference supplies an open pale-blue oversized shirt, fitted white tank, gray striped drawstring shorts, black shoulder bag and an indoor mirror-selfie pose with the phone covering the lower face and the other hand making a V sign.

Completed one Image: `art_75d57681b7ba4599a3`, Canvas node `character-outfit-pose`. Run `canvasrun_2bdb1bfd3be84f2295` succeeded in one attempt using OpenAI `gpt-image-2`; experiment `exp_fa0b86ee527d4e088b`. Identity inputs: Character front `art_5257761348ca4de79d` and full-body baseline `art_1d90bd3d6e154053bd`, followed by the user-linked outfit/pose image. The generated result was visually verified in Canvas. Prompt, source reference, output and execution records are in `output/character-outfit-pose/`. Prior Character images remain unchanged.

## Facial shadow relighting — 2026-10-01

The user requested stronger facial shadows appropriate to the hallway lighting and explicitly required NOTTALGGAK prompt improvement. The current selfie itself, art_75d57681b7ba4599a3, became the primary edit input; art_55b8c9977d3e44dfb2 supplies ambient-light guidance only. Identity, white/pink bob, outfit, phone/V gesture, camera framing and room geometry remain locked.

The first prompt (high frontal overhead key, 2-stop weaker fill, 0.7-stop facial-midtones reduction) returned art_58814bc738554f019e but produced an insufficient change and was not retained as the final result. The revised prompt specifies high light slightly behind the head, 3-stop weaker frontal fill, a requested 1.3-stop facial-midtones reduction, and visibly feathered fringe/brow/upper-eye shadows with readable irises. Requested stop values are prompting targets, not measured exposure metadata.

Final result: art_a9e660a58cce4f96b9, same Canvas node character-outfit-pose; run canvasrun_61c22e3ee42141249d succeeded. The original and first attempt remain immutable in history. The current prompt node is outfit-lighting-prompt; the previous outfit-pose-prompt remains on Canvas as history. Final prompt, Korean translation and lighting blueprint: output/character-outfit-lighting/master-prompt.md. Original prompt iteration: master-prompt.v1.md. Final output copy: result.png.

Visual comparison confirmed stronger fringe/eye and side-face shadows while preserving pose, clothing and framing. Coarse same-position pixel-region checks supported the visible change: forehead/eye RGB average about 22% lower, one exposed side-face region about 31% lower, while a wall region changed about 2%. These are relative image-brightness checks, not calibrated photographic stop measurements.

## Canonical body restored under outfit — 2026-10-01

The user required the character's body to remain unchanged when clothing changes, specifically correcting reduced bust volume inherited from the outfit model. The latest relit selfie art_a9e660a58cce4f96b9 was edited using three explicit anatomical references from the White Pink Bob Character: front art_5257761348ca4de79d, side art_459c25dfa51240689e and full-body art_1d90bd3d6e154053bd. The external outfit-model image was excluded from this correction's direct inputs. The prompt makes anatomy the priority and fits the garments to the character, without enlarging beyond the character reference.

Completed output: art_5f14c2fb23634d07b4 at the same Canvas node character-outfit-pose. Run canvasrun_4a8ec98bc9974db78c and experiment exp_fa896ab312534466ae succeeded using OpenAI gpt-image-2. The result was visually checked against the frontal/side Character views: fuller canonical bust contour is restored through garment fit, while the selfie pose, white/pink bob, face shadows, shorts, bag and room remain consistent. Prompt/translation/blueprint and output are in output/character-outfit-body-lock/. The mandatory body-continuity rule is also at the top of the Canvas Sticky and this document.

## Two additional outfit/pose references — 2026-10-01

The user requested the same body-preserving transfer for two more source nodes. Both prompts use Character front art_5257761348ca4de79d, side art_459c25dfa51240689e and full-body art_1d90bd3d6e154053bd as inputs 1–3, with the respective outfit/pose photo as input 4. Garments are fitted to the established character; reference wearers' face, hair and body proportions are excluded.

1. Source upload-1790782249973-2 / art_17d586acaf9e47f09c: open white shirt, white inner top, denim mini skirt, white socks/sneakers, net tote, sideways stepping pose on a blue-railed seaside road. Output art_f93db6e0a2da4d3594; node character-outfit-coastal. Run canvasrun_dfa2f36731b34bfabe, experiment exp_4e65675add2f43d3bd, OpenAI gpt-image-2, SUCCEEDED. Visually checked for outfit/pose, character proportions and cool shaded subject against bright outdoor surroundings.
2. Source upload-1790782346299-1 / art_dea2a904b7a74abf89: ivory cable-knit button cardigan, small black furry microphone, gentle speaking pose, plain wall and right-of-center upper-body framing. Output art_9fd16daadf7648168b; node character-outfit-knit-mic. Run canvasrun_4b671df703bb46ee87, experiment exp_9044205dae3d4827ba, OpenAI gpt-image-2, SUCCEEDED. Visually checked for character identity/white-pink bob, body/garment fit, microphone hand pose and soft room lighting. The screenshot's teaching captions/UI were not copied.

Both outputs and the earlier corrected selfie remain saved in Canvas. Prompt translations/blueprints, references, output PNGs and execution records: output/character-two-outfits/.


## Knitwear front-drape correction — 2026-10-01

The user identified an implausibly deep center indentation in the ivory cardigan. The correction assumes a well-fitting everyday bra hidden beneath the opaque closed knit, preserves the established bust volume and outer torso silhouette, and changes only the garment surface: a gentle fabric bridge, shallow center transitions, a nearly straight button band, continuous cables and natural folds. This is a garment-support assumption for the generated scene, not a universal anatomical claim.

Final output: art_10fbe202c92243c78b, same node character-outfit-knit-mic. Run canvasrun_072746bac7e44c9b9f and experiment exp_8e7cb143469c487db7 succeeded using OpenAI gpt-image-2; sole edit input art_9fd16daadf7648168b. The result was visually compared with the previous portrait: the deep central trench was removed and the button placket is straighter, while the character, full chest silhouette, microphone pose, framing and soft light remain consistent. Prior result remains immutable. Prompt/translation/blueprint, source snapshot and output: output/character-knit-drape-fix/.
