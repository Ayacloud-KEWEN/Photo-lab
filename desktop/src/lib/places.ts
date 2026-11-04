import type { PlaceName, TripSuggestion } from "@/api/types";

/** A place name in the interface language (the international name otherwise). */
export function placeName(name: PlaceName, language: string): string {
  if (language.startsWith("zh")) return name.zh;
  if (language.startsWith("fr")) return name.fr;
  return name.name;
}

/** "Town, Region, Country" without repeats (e.g. Kuala Lumpur, Kuala Lumpur). */
export function placeLine(parts: (PlaceName | null | undefined)[], language: string): string {
  const names = parts.filter((part): part is PlaceName => !!part).map((p) => placeName(p, language));
  return names.filter((name, index) => names.indexOf(name) === index).join(" · ");
}

/** What a trip is named after: its (up to 3) main towns, or its countries if several. */
export function tripPlace(trip: Pick<TripSuggestion, "cities" | "countries">, language: string) {
  const separator = language.startsWith("zh") ? "、" : ", ";
  if (trip.countries.length > 1) {
    return trip.countries
      .slice(0, 3)
      .map((name) => placeName(name, language))
      .join(separator);
  }
  return trip.cities.map((name) => placeName(name, language)).join(separator);
}
