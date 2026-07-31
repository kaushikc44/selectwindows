import React, { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";

import { addressAutocomplete, getPlaceDetails, PlaceSuggestion } from "../api/places";
import { ApiError } from "../api/client";
import { colors, shared } from "../theme";

interface Props {
  value: string;
  onChange: (address: string) => void;
  label?: string;
}

// Replaces the paper form's hand-written address line: as the Sales rep
// (or Owner editing a quote) types, this pings the backend Google Places
// proxy (api/places.ts → app/api/places.py) for suggestions and shows them
// in a list below the input; tapping one resolves its formatted address
// (and caches the lat/lng server-side for Anthony's job map). Styled to
// match the adjacent shared.input fields so it reads as one form.
export default function AddressAutocomplete({ value, onChange, label = "Site address" }: Props) {
  const [query, setQuery] = useState(value);
  const [suggestions, setSuggestions] = useState<PlaceSuggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [fetchingDetails, setFetchingDetails] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Sync from the parent (e.g. OwnerEditQuoteScreen hydrating the form
  // from the server after mount). During typing the parent never changes
  // `value`, so this never disrupts an in-progress edit.
  useEffect(() => {
    setQuery(value);
  }, [value]);

  const fetchSuggestions = (input: string) => {
    if (input.trim().length < 3) {
      setSuggestions([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    addressAutocomplete(input.trim())
      .then(setSuggestions)
      .catch(() => setSuggestions([]))
      .finally(() => setLoading(false));
  };

  const onChangeText = (text: string) => {
    setQuery(text);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => fetchSuggestions(text), 300);
  };

  const selectSuggestion = (suggestion: PlaceSuggestion) => {
    setSuggestions([]);
    setQuery(suggestion.description);
    setFetchingDetails(true);
    getPlaceDetails(suggestion.place_id)
      .then((details) => {
        const address = details.formatted_address || suggestion.description;
        setQuery(address);
        onChange(address);
      })
      .catch((err) => {
        // Fall back to the suggestion text so the rep isn't blocked; the
        // map just won't have a cached pin for it.
        onChange(suggestion.description);
        if (!(err instanceof ApiError && err.status === 503)) {
          setQuery(suggestion.description);
        }
      })
      .finally(() => setFetchingDetails(false));
  };

  // Delayed dismiss so the suggestion tap (which fires after blur) still
  // registers — the standard RN autocomplete-onBlur workaround.
  const onBlur = () => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    setTimeout(() => setSuggestions([]), 150);
  };

  return (
    <View>
      <Text style={shared.label}>{label}</Text>
      <View style={styles.inputRow}>
        <TextInput
          style={[shared.input, { flex: 1 }]}
          value={query}
          onChangeText={onChangeText}
          onBlur={onBlur}
          autoCapitalize="words"
          autoComplete="street-address"
          placeholder="Start typing the site address"
        />
        {(loading || fetchingDetails) && (
          <ActivityIndicator style={styles.spinner} color={colors.accent} />
        )}
      </View>

      {suggestions.length > 0 && (
        <View style={styles.dropdown}>
          <FlatList
            data={suggestions}
            keyboardShouldPersistTaps="handled"
            keyExtractor={(s) => s.place_id}
            renderItem={({ item }) => (
              <TouchableOpacity style={styles.row} onPress={() => selectSuggestion(item)}>
                <Text style={styles.rowText} numberOfLines={2}>
                  {item.description}
                </Text>
              </TouchableOpacity>
            )}
            ItemSeparatorComponent={() => <View style={styles.separator} />}
          />
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  inputRow: { flexDirection: "row", alignItems: "center" },
  spinner: { position: "absolute", right: 12, alignSelf: "center" },
  dropdown: {
    marginTop: 4,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: 8,
    backgroundColor: colors.card,
    maxHeight: 220,
    overflow: "hidden",
  },
  row: { paddingVertical: 12, paddingHorizontal: 12 },
  rowText: { fontSize: 15, color: colors.ink },
  separator: { height: 1, backgroundColor: colors.line },
});