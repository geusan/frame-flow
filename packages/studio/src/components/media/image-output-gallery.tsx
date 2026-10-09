import Image from "next/image";
import type { CanvasOutput } from "../../lib/canvas-model";
import styles from "./image-output-gallery.module.css";

export function ImageOutputGallery({ images, compact = false }: { images: NonNullable<CanvasOutput["images"]>; compact?: boolean }) {
  return <div className={`${styles.gallery} ${compact ? styles.compact : ""}`} aria-label="Generated image views">
    {images.map((image) => <figure key={image.artifactId}>
      <Image src={image.url} alt={image.title} width={512} height={512} unoptimized />
      <figcaption>{image.title}</figcaption>
    </figure>)}
  </div>;
}
