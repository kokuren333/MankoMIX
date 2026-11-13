/**
 * 16×16 pixel icons of the product family theme "Circuit White / Solder Mask" (D-067).
 * Files live in public/icons/ (provenance in public/icons/manifest.json; reused ones come
 * from CyberSprite, the MankoMIX-specific ones are drawn by tools/make_icons.py).
 * Meaning is carried by the shape; an icon next to visible text is decorative (alt=""),
 * an icon alone must get a `label`.
 */
export const ICONS = [
  "add",
  "agent",
  "chain",
  "download",
  "error",
  "export",
  "first",
  "folder",
  "grid",
  "headphones",
  "human",
  "info",
  "link",
  "lock",
  "meter",
  "model",
  "pause",
  "play",
  "remove",
  "report",
  "separate",
  "settings",
  "sources",
  "stem",
  "undo",
  "validate-ok",
  "warning",
  "waveform",
] as const;
export type IconName = (typeof ICONS)[number];

export function Icon({ name, label, scale = 1, className }: { name: IconName; label?: string; scale?: 1 | 2; className?: string }) {
  return (
    <img
      className={`ico ico-x${scale}` + (className ? " " + className : "")}
      src={`${import.meta.env.BASE_URL}icons/${name}.png`}
      width={16 * scale}
      height={16 * scale}
      alt={label ?? ""}
      aria-hidden={label ? undefined : true}
      title={label}
      draggable={false}
      data-icon={name}
    />
  );
}
