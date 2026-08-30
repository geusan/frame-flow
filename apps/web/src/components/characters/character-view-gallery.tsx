import type { CharacterRecord } from "@/lib/api";

export function characterRoleLabel(value: string): string {
  return value.replaceAll("_", " ");
}

export function CharacterViewGallery({ character }: { character: CharacterRecord }) {
  return <div className="node-detail-character-grid" data-count={character.images.length}>
    {character.images.map((image) => <figure key={image.artifact_id}>
      <div
        role="img"
        aria-label={`${character.name} ${characterRoleLabel(image.role)}`}
        style={{ backgroundImage: `url(${image.url})` }}
      />
      <figcaption>{characterRoleLabel(image.role)}</figcaption>
    </figure>)}
  </div>;
}
