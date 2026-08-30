"use client";

import { useParams, useRouter } from "next/navigation";

import { CharacterLibrary } from "@/components/views/character-library";

export default function CharactersPage() {
  const params = useParams<{ id?: string }>();
  const router = useRouter();

  return <CharacterLibrary
    selectedCharacterId={params.id}
    onOpenCharacter={(characterId) => router.push(`/characters/${encodeURIComponent(characterId)}`, { scroll: false })}
    onCloseCharacter={() => router.replace("/characters", { scroll: false })}
  />;
}
