"use client";

import { useEffect, useMemo, useState } from "react";
import { CircleCheck, ContactRound, Images, Maximize2, PanelRightClose, RefreshCw, Sparkles } from "lucide-react";
import Image from "next/image";

import { CharacterViewGallery, characterRoleLabel } from "@/components/characters/character-view-gallery";
import { SearchField } from "@/components/shared/search-field";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { frameflowApi, type CharacterRecord } from "@/lib/api";

function CharacterDetail({ character, onClose }: { character: CharacterRecord; onClose: () => void }) {
  return <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
    <DialogContent className="node-detail-dialog has-media has-output character-library-detail-dialog" overlayClassName="node-detail-backdrop">
      <DialogDescription className="sr-only">View every generated identity image and the saved metadata for {character.name}.</DialogDescription>
      <section className="node-detail-media character-output">
        <header>
          <span><small>character output</small><DialogTitle asChild><strong title={character.name}>{character.name}</strong></DialogTitle></span>
          <b>{character.image_count} views</b>
        </header>
        <div className="node-detail-character-stage">
          {character.images.length
            ? <CharacterViewGallery character={character} />
            : <div className="node-detail-character-fallback"><span>Character view manifest is unavailable.</span></div>}
        </div>
      </section>

      <aside className="node-inspector character-detail-inspector">
        <div className="inspector-heading">
          <div><span className="subtle-label">Character inspector</span><strong title={character.name}>{character.name}</strong></div>
          <DialogClose asChild><Button variant="ghost" size="icon-sm" className="size-[25px] min-h-[25px]" type="button" aria-label="Close character details"><PanelRightClose size={16} /></Button></DialogClose>
        </div>
        <div className="inspector-status"><span className="character-detail-ready"><CircleCheck size={14} /> Ready</span><span>Character</span></div>
        <div className="inspector-tabs"><span className="active">Details</span></div>
        <div className="inspector-content character-detail-content">
          <section className="character-detail-summary">
            <span><Sparkles size={13} /> Reusable identity bundle</span>
            <p>{character.synopsis || "No synopsis recorded for this character."}</p>
          </section>
          <div className="character-detail-meta">
            <span><small>Generated views</small><strong>{character.image_count}</strong></span>
            <span><small>Created</small><strong>{new Date(character.created_at).toLocaleString("ko-KR")}</strong></span>
            <span><small>Model alias</small><strong>{character.model_alias || "Generated"}</strong></span>
            <span><small>Exact model</small><strong title={character.exact_model_id}>{character.exact_model_id || "—"}</strong></span>
          </div>
          <div className="inspector-section-title"><span>Identity views</span><Images size={14} /></div>
          <div className="character-detail-view-list">
            {character.images.map((image, index) => <div key={image.artifact_id}>
              <Image src={image.url} alt="" width={72} height={72} unoptimized />
              <span><strong>{characterRoleLabel(image.role)}</strong><small>View {index + 1} · {image.artifact_id}</small></span>
            </div>)}
          </div>
          <label className="field-label character-detail-id"><span>Character ID</span><input value={character.id} readOnly /></label>
        </div>
      </aside>
    </DialogContent>
  </Dialog>;
}

export function CharacterLibrary({ selectedCharacterId, onOpenCharacter, onCloseCharacter }: { selectedCharacterId?: string; onOpenCharacter: (characterId: string) => void; onCloseCharacter: () => void }) {
  const [characters, setCharacters] = useState<CharacterRecord[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    frameflowApi.listCharacters()
      .then((items) => { if (active) setCharacters(items); })
      .catch((loadError) => { if (active) setError(loadError instanceof Error ? loadError.message : "Characters loading failed"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const visible = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return characters;
    return characters.filter((character) => `${character.name} ${character.synopsis}`.toLowerCase().includes(normalized));
  }, [characters, query]);
  const selectedCharacter = selectedCharacterId ? characters.find((character) => character.id === selectedCharacterId) : undefined;

  return <div className="view-page character-library">
    <div className="character-toolbar">
      <div><span><ContactRound size={16} /> Character bundles</span><small>Character Generator가 만든 단일 이미지 묶음입니다. 콜라주는 미리보기로만 사용됩니다.</small></div>
      <SearchField className="character-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search characters…" />
    </div>

    {loading && <div className="character-library-state"><RefreshCw className="spin" size={20} /><strong>Loading characters…</strong></div>}
    {error && <div className="character-library-state error"><strong>{error}</strong></div>}
    {!loading && !error && !visible.length && <div className="character-library-state"><span><ContactRound size={22} /></span><strong>{characters.length ? "No matching characters" : "No characters yet"}</strong><small>Canvas에서 Prompt를 Character Generator에 연결해 첫 캐릭터를 만드세요.</small></div>}

    {!!visible.length && <div className="character-grid">
      {visible.map((character) => <article className="character-card" key={character.id} role="button" tabIndex={0} aria-haspopup="dialog" aria-label={`Open ${character.name} details`} onClick={() => onOpenCharacter(character.id)} onKeyDown={(event) => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); onOpenCharacter(character.id); } }}>
        <div className="character-card-cover">
          {character.cover_url ? <Image src={character.cover_url} alt={`${character.name} cover`} width={640} height={960} unoptimized /> : <ContactRound size={34} />}
          <span><Images size={12} /> {character.image_count} views</span>
          <i><Maximize2 size={12} /> View details</i>
        </div>
        <div className="character-card-body">
          <div><span><Sparkles size={12} /> {character.model_alias || "Generated"}</span><time>{new Date(character.created_at).toLocaleDateString("ko-KR")}</time></div>
          <h2>{character.name}</h2>
          <p>{character.synopsis || "No synopsis recorded."}</p>
          <div className="character-view-strip">
            {character.images.slice(0, 6).map((image) => <span title={characterRoleLabel(image.role)} key={image.artifact_id}><Image src={image.url} alt={`${character.name} ${characterRoleLabel(image.role)}`} width={160} height={160} unoptimized /></span>)}
          </div>
          <footer><code>{character.id}</code><span>{character.images.slice(0, 4).map((image) => characterRoleLabel(image.role)).join(" · ")}</span></footer>
        </div>
      </article>)}
    </div>}
    {selectedCharacter && <CharacterDetail character={selectedCharacter} onClose={onCloseCharacter} key={selectedCharacter.id} />}
  </div>;
}
