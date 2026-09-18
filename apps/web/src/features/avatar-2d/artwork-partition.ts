/** Split the original pixels by ownership, without synthesizing or discarding any
 * of them. The mask identifies the original head contour; below the jaw its skin
 * and clothing belong to the complementary body layer. */
export function partitionArtwork(source: Uint8ClampedArray, region: Uint8ClampedArray, width: number, height: number) {
  if (source.length !== width * height * 4 || region.length !== source.length) throw new Error("Artwork dimensions do not match the head mask");
  const head = new Uint8ClampedArray(source), body = new Uint8ClampedArray(source);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const k = (y * width + x) * 4;
    const belongs = region[k + 3] >= 128 && (y <= 281 || (source[k] <= 160 && source[k + 1] <= 150));
    if (belongs) body[k + 3] = 0; else head[k + 3] = 0;
  }
  return { head, body };
}
