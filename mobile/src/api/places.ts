import { apiGet } from "./client";

// Thin wrappers over the backend Google Places proxy (app/api/places.py).
// The Google API key stays server-side — the app never sees it; these just
// hit our own /places/* endpoints with the bearer token auto-attached by
// apiGet (see api/client.ts::request).

export interface PlaceSuggestion {
  place_id: string;
  description: string;
}

export interface PlaceDetails {
  formatted_address: string;
  lat: number | null;
  lng: number | null;
}

// GET /places/autocomplete?input=… — typed-address → place suggestions.
export function addressAutocomplete(input: string): Promise<PlaceSuggestion[]> {
  return apiGet<PlaceSuggestion[]>(`/places/autocomplete?input=${encodeURIComponent(input)}`);
}

// GET /places/details?place_id=… — selected place → formatted address + coords.
// The backend also caches the lat/lng into GeocodeCache so Anthony's job map
// pins it with no extra geocoding (see app/api/places.py::details).
export function getPlaceDetails(placeId: string): Promise<PlaceDetails> {
  return apiGet<PlaceDetails>(`/places/details?place_id=${encodeURIComponent(placeId)}`);
}