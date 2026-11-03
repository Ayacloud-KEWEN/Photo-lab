import { useTranslation } from "react-i18next";

const COLORS = ["#ff5a5a", "#5ad65a", "#5a8cff"];

/** RGB histogram of the rendered image (counts per bin, from the backend). */
export function Histogram({ data }: { data: number[][] | null }) {
  const { t } = useTranslation();
  const bins = data?.[0]?.length ?? 0;
  // Ignore the end bins when scaling, so clipped shadows/highlights do not flatten the rest.
  const peak = data
    ? Math.max(1, ...data.flatMap((channel) => channel.slice(1, -1)))
    : 1;

  return (
    <svg
      role="img"
      aria-label={t("develop.histogram")}
      viewBox={`0 0 ${Math.max(bins, 1)} 100`}
      preserveAspectRatio="none"
      className="h-20 w-full rounded bg-black/40"
    >
      {data?.map((channel, index) => (
        <path
          key={index}
          d={`M0,100 ${channel
            .map((count, bin) => `L${bin},${100 - Math.min(100, (count / peak) * 100)} L${bin + 1},${100 - Math.min(100, (count / peak) * 100)}`)
            .join(" ")} L${bins},100 Z`}
          fill={COLORS[index]}
          fillOpacity={0.45}
          style={{ mixBlendMode: "screen" }}
        />
      ))}
    </svg>
  );
}
